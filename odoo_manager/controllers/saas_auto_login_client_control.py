# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.service import security
from odoo.exceptions import AccessDenied
import logging
import werkzeug
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

# Rate Limiting Storage
RATE_LIMIT_STORAGE = {}


class SaasAutoLoginController(http.Controller):

    def _check_rate_limit(self, key, max_attempts=5, window_minutes=5):
        """
        Check Rate Limiting

        Args:
            key: Identifier (IP or user_id)
            max_attempts: Maximum allowed attempts
            window_minutes: Time window in minutes

        Returns:
            (allowed: bool, remaining: int)
        """
        now = datetime.now()

        # Clean old records
        if key in RATE_LIMIT_STORAGE:
            RATE_LIMIT_STORAGE[key] = [
                timestamp for timestamp in RATE_LIMIT_STORAGE[key]
                if now - timestamp < timedelta(minutes=window_minutes)
            ]

        # Check attempts
        attempts = len(RATE_LIMIT_STORAGE.get(key, []))

        if attempts >= max_attempts:
            return False, 0

        # Register new attempt
        if key not in RATE_LIMIT_STORAGE:
            RATE_LIMIT_STORAGE[key] = []
        RATE_LIMIT_STORAGE[key].append(now)

        return True, max_attempts - attempts - 1

    def _verify_admin_password(self, db_name, admin_password):
        """
        Verify admin password using Odoo registry and environment
        Compatible with Odoo 19
        """
        try:
            import odoo
            from odoo.exceptions import AccessDenied

            # الدخول مباشرة إلى قاعدة البيانات للتحقق
            registry = odoo.registry(db_name)
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})

                # التحقق من بيانات الأدمن باستخدام الدالة القياسية authenticate
                uid = env['res.users'].authenticate(db_name, 'admin', admin_password, {'interactive': False})

            if uid:
                _logger.info("Admin password verified directly for database: %s", db_name)
                return True
            else:
                _logger.warning("Invalid admin password for database: %s", db_name)
                return False

        except odoo.exceptions.AccessDenied:
            _logger.warning("Authentication failed: Access Denied")
            return False
        except Exception as e:
            _logger.error("Error verifying admin password: %s", str(e))
            return False

    def _is_ip_allowed(self, ip):
        """
        Check if IP is allowed
        """
        allowed_ips = [
            '127.0.0.1',
            '::1',
            'localhost',
        ]

        try:
            allowed_param = request.env['ir.config_parameter'].sudo().get_param(
                'saas.autologin.allowed_ips', ''
            )
            if allowed_param:
                allowed_ips.extend([ip.strip() for ip in allowed_param.split(',')])
        except:
            pass

        if ip.startswith(('192.168.', '10.', '172.16.', '172.17.')):
            return True

        return ip in allowed_ips

    @http.route('/saas/generate_auth_link', type='http', auth='none', methods=['POST'], csrf=False)
    def generate_auth_link(self, **kwargs):
        """Generate auto login link"""
        try:
            client_ip = self._get_client_ip()
            _logger.info("Auth link request from IP: %s", client_ip)

            # 1. Check IP
            if not self._is_ip_allowed(client_ip):
                _logger.warning("Blocked request from unauthorized IP: %s", client_ip)
                return request.make_json_response({
                    'success': False,
                    'error': 'Unauthorized IP address'
                }, status=403)

            # 2. Rate Limiting
            allowed, remaining = self._check_rate_limit(client_ip, max_attempts=10, window_minutes=5)
            if not allowed:
                _logger.warning("Rate limit exceeded for IP: %s", client_ip)
                return request.make_json_response({
                    'success': False,
                    'error': 'Too many requests. Please try again later.'
                }, status=429)

            # Read data
            user_id = None
            admin_password = None

            if request.httprequest.data:
                try:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                    user_id = data.get('user_id')
                    admin_password = data.get('admin_password')
                    _logger.info("Data from JSON body: user_id=%s", user_id)
                except:
                    pass

            if not user_id:
                user_id = kwargs.get('user_id')
                admin_password = kwargs.get('admin_password')
                _logger.info("Data from kwargs: user_id=%s", user_id)

            if not user_id or not admin_password:
                _logger.error("Missing user_id or admin_password")
                return request.make_json_response({
                    'success': False,
                    'error': 'Missing user_id or admin_password'
                })

            user_id = int(user_id)
            current_db = request.env.cr.dbname

            # 3. Verify admin password
            if not self._verify_admin_password(admin_password, current_db):
                _logger.error("Invalid admin password from IP: %s", client_ip)
                return request.make_json_response({
                    'success': False,
                    'error': 'Invalid admin credentials'
                }, status=401)

            # Check User
            user = request.env['res.users'].sudo().browse(user_id)
            if not user.exists():
                _logger.error("User ID %d not found", user_id)
                return request.make_json_response({
                    'success': False,
                    'error': f'User ID {user_id} not found'
                })

            if not user.active:
                _logger.error("User ID %d is inactive", user_id)
                return request.make_json_response({
                    'success': False,
                    'error': 'User is inactive'
                })

            # 4. Generate token with a short expiration (2 minutes)
            auth_token = request.env['saas.auth.token'].sudo().generate_token(
                user_id=user_id,
                user_login=user.login,
                db_name=current_db,
                expires_minutes=2
            )

            base = request.httprequest.host_url.rstrip('/')
            auth_url = f"{base}/saas/autologin?token={auth_token.token}"

            _logger.info("Auth token generated for user %s (ID: %d) from IP: %s",
                         user.login, user_id, client_ip)

            return request.make_json_response({
                'success': True,
                'auth_url': auth_url,
                'token': auth_token.token,
                'expires_at': auth_token.expires_at.isoformat()
            })

        except Exception as e:
            _logger.error("Generate link failed: %s", str(e), exc_info=True)
            return request.make_json_response({
                'success': False,
                'error': 'Internal server error'
            }, status=500)

    @http.route('/saas/autologin', type='http', auth='public', methods=['GET'], csrf=False)
    def autologin(self, token, **kwargs):
        """Auto login"""
        try:
            client_ip = self._get_client_ip()
            _logger.info("Autologin attempt from IP: %s with token: %s...", client_ip, str(token)[:10])

            # Rate Limiting for autologin
            allowed, remaining = self._check_rate_limit(f"autologin_{client_ip}", max_attempts=20, window_minutes=5)
            if not allowed:
                _logger.warning("Autologin rate limit exceeded for IP: %s", client_ip)
                return request.render('web.login', {
                    'error': 'Too many attempts. Please try again later.'
                })

            # Verify token
            token_data = request.env['saas.auth.token'].sudo().validate_and_consume_token(token)

            if not token_data:
                _logger.warning("Invalid/expired token from IP: %s", client_ip)
                return request.render('web.login', {
                    'error': 'Invalid or expired login token'
                })

            user_id = token_data['user_id']
            user_login = token_data['user_login']
            db_name = token_data['db_name']

            # Check User again
            user = request.env['res.users'].sudo().browse(user_id)
            if not user.exists() or not user.active:
                _logger.error("User not found or inactive")
                return request.render('web.login', {
                    'error': 'User not found or inactive'
                })

            # Perform login
            request.session.logout(keep_db=True)

            request.session.uid = user_id
            request.session.login = user_login
            request.session.db = db_name

            # Odoo 19 compliant session setup
            request.update_env(user=user_id)
            request.session.session_token = security.compute_session_token(request.session, request.env)
            request.session.context = request.env.user.context_get()

            request.session.modified = True

            _logger.info("Autologin SUCCESS for user: %s (ID: %d) from IP: %s",
                         user_login, user_id, client_ip)

            return werkzeug.utils.redirect('/web', 303)

        except Exception as e:
            _logger.error("Autologin FAILED: %s", str(e), exc_info=True)
            return request.render('web.login', {
                'error': 'Login failed'
            })

    @http.route('/saas/cleanup_tokens', type='json', auth='user', methods=['POST'])
    def cleanup_expired_tokens(self):
        """Cleanup expired tokens"""
        try:
            count = request.env['saas.auth.token'].sudo().cleanup_expired_tokens()
            remaining = request.env['saas.auth.token'].sudo().search_count([])

            _logger.info("Cleaned %d expired tokens, %d remaining", count, remaining)

            return {
                'success': True,
                'cleaned': count,
                'remaining': remaining
            }
        except Exception as e:
            _logger.error("Cleanup failed: %s", str(e))
            return {'success': False, 'error': str(e)}