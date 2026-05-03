# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
import secrets
import logging
import werkzeug
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

# ✅ Rate Limiting Storage
RATE_LIMIT_STORAGE = {}


class SaasAutoLoginController(http.Controller):

    def _check_rate_limit(self, key, max_attempts=5, window_minutes=5):
        """
        التحقق من Rate Limiting

        Args:
            key: المفتاح (IP أو user_id)
            max_attempts: عدد المحاولات المسموحة
            window_minutes: النافذة الزمنية بالدقائق

        Returns:
            (allowed: bool, remaining: int)
        """
        now = datetime.now()

        # تنظيف السجلات القديمة
        if key in RATE_LIMIT_STORAGE:
            RATE_LIMIT_STORAGE[key] = [
                timestamp for timestamp in RATE_LIMIT_STORAGE[key]
                if now - timestamp < timedelta(minutes=window_minutes)
            ]

        # التحقق من العدد
        attempts = len(RATE_LIMIT_STORAGE.get(key, []))

        if attempts >= max_attempts:
            return False, 0

        # تسجيل المحاولة الجديدة
        if key not in RATE_LIMIT_STORAGE:
            RATE_LIMIT_STORAGE[key] = []
        RATE_LIMIT_STORAGE[key].append(now)

        return True, max_attempts - attempts - 1

    def _verify_admin_password(self, admin_password, db_name):
        """
        التحقق من كلمة مرور الأدمن - محدّث لـ Odoo 19

        Args:
            admin_password: كلمة المرور
            db_name: اسم قاعدة البيانات

        Returns:
            bool: True إذا كانت كلمة المرور صحيحة
        """
        try:
            # ✅ في Odoo 19، نستخدم authenticate API
            import xmlrpc.client

            # الحصول على الـ URL الحالي
            base_url = request.httprequest.host_url.rstrip('/')

            # محاولة المصادقة
            common = xmlrpc.client.ServerProxy(f'{base_url}/xmlrpc/2/common')

            try:
                uid = common.authenticate(
                    db_name,
                    'admin',  # اسم المستخدم
                    admin_password,
                    {}
                )

                if uid:
                    _logger.info("✅ Admin password verified for database: %s", db_name)
                    return True
                else:
                    _logger.warning("⚠️ Invalid admin password for database: %s", db_name)
                    return False

            except Exception as auth_error:
                _logger.warning("⚠️ Authentication failed: %s", str(auth_error))
                return False

        except Exception as e:
            _logger.error("❌ Error verifying admin password: %s", str(e))
            return False

    def _get_client_ip(self):
        """الحصول على IP العميل الحقيقي"""
        # تحقق من X-Forwarded-For (في حالة استخدام Proxy/Load Balancer)
        forwarded_for = request.httprequest.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()

        return request.httprequest.remote_addr

    def _is_ip_allowed(self, ip):
        """
        التحقق من أن الـ IP مسموح له

        يمكنك تخصيص هذه الدالة حسب احتياجك:
        - السماح لـ IPs محددة فقط
        - السماح لـ ranges معينة
        - الحظر من blacklist
        """
        # ✅ مثال 1: السماح لأي IP (غير آمن!)
        # return True

        # ✅ مثال 2: السماح لـ localhost و IPs محددة
        allowed_ips = [
            '127.0.0.1',
            '::1',
            'localhost',
            # أضف IPs السيرفرات بتاعتك هنا
        ]

        # جلب IPs المسموحة من System Parameters
        try:
            allowed_param = request.env['ir.config_parameter'].sudo().get_param(
                'saas.autologin.allowed_ips', ''
            )
            if allowed_param:
                allowed_ips.extend([ip.strip() for ip in allowed_param.split(',')])
        except:
            pass

        # التحقق من الشبكات المحلية
        if ip.startswith(('192.168.', '10.', '172.16.', '172.17.')):
            return True

        return ip in allowed_ips

    @http.route('/saas/generate_auth_link', type='http', auth='none', methods=['POST'], csrf=False)
    def generate_auth_link(self, **kwargs):
        """توليد رابط تسجيل دخول تلقائي - نسخة آمنة"""
        try:
            client_ip = self._get_client_ip()
            _logger.info("🔐 Auth link request from IP: %s", client_ip)

            # ✅ 1. التحقق من الـ IP
            if not self._is_ip_allowed(client_ip):
                _logger.warning("🚫 Blocked request from unauthorized IP: %s", client_ip)
                return request.make_json_response({
                    'success': False,
                    'error': 'Unauthorized IP address'
                }, status=403)

            # ✅ 2. Rate Limiting
            allowed, remaining = self._check_rate_limit(client_ip, max_attempts=10, window_minutes=5)
            if not allowed:
                _logger.warning("🚫 Rate limit exceeded for IP: %s", client_ip)
                return request.make_json_response({
                    'success': False,
                    'error': 'Too many requests. Please try again later.'
                }, status=429)

            # قراءة البيانات
            user_id = None
            admin_password = None

            if request.httprequest.data:
                try:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                    user_id = data.get('user_id')
                    admin_password = data.get('admin_password')
                    _logger.info("📥 Data from JSON body: user_id=%s", user_id)
                except:
                    pass

            if not user_id:
                user_id = kwargs.get('user_id')
                admin_password = kwargs.get('admin_password')
                _logger.info("📥 Data from kwargs: user_id=%s", user_id)

            if not user_id or not admin_password:
                _logger.error("❌ Missing user_id or admin_password")
                return request.make_json_response({
                    'success': False,
                    'error': 'Missing user_id or admin_password'
                })

            user_id = int(user_id)
            current_db = request.env.cr.dbname

            # ✅ 3. التحقق من كلمة مرور الأدمن (مهم جداً!)
            if not self._verify_admin_password(admin_password, current_db):
                _logger.error("❌ Invalid admin password from IP: %s", client_ip)
                return request.make_json_response({
                    'success': False,
                    'error': 'Invalid admin credentials'
                }, status=401)

            # التحقق من المستخدم
            user = request.env['res.users'].sudo().browse(user_id)
            if not user.exists():
                _logger.error("❌ User ID %d not found", user_id)
                return request.make_json_response({
                    'success': False,
                    'error': f'User ID {user_id} not found'
                })

            if not user.active:
                _logger.error("❌ User ID %d is inactive", user_id)
                return request.make_json_response({
                    'success': False,
                    'error': 'User is inactive'
                })

            # ✅ 4. توليد token مع مدة قصيرة (2 دقيقة فقط)
            auth_token = request.env['saas.auth.token'].sudo().generate_token(
                user_id=user_id,
                user_login=user.login,
                db_name=current_db,
                expires_minutes=2  # ✅ تقليل المدة لـ 2 دقيقة
            )

            base = request.httprequest.host_url.rstrip('/')
            auth_url = f"{base}/saas/autologin?token={auth_token.token}"

            _logger.info("✅ Auth token generated for user %s (ID: %d) from IP: %s",
                         user.login, user_id, client_ip)

            return request.make_json_response({
                'success': True,
                'auth_url': auth_url,
                'token': auth_token.token,
                'expires_at': auth_token.expires_at.isoformat()
            })

        except Exception as e:
            _logger.error("❌ Generate link failed: %s", str(e), exc_info=True)
            return request.make_json_response({
                'success': False,
                'error': 'Internal server error'
            }, status=500)

    @http.route('/saas/autologin', type='http', auth='public', methods=['GET'], csrf=False)
    def autologin(self, token, **kwargs):
        """تسجيل الدخول التلقائي - نسخة آمنة"""
        try:
            client_ip = self._get_client_ip()
            _logger.info("🔑 Autologin attempt from IP: %s with token: %s...", client_ip, token[:10])

            # ✅ Rate Limiting على الـ autologin أيضاً
            allowed, remaining = self._check_rate_limit(f"autologin_{client_ip}", max_attempts=20, window_minutes=5)
            if not allowed:
                _logger.warning("🚫 Autologin rate limit exceeded for IP: %s", client_ip)
                return request.render('web.login', {
                    'error': 'عدد كبير من المحاولات. حاول مرة أخرى لاحقاً.'
                })

            # التحقق من الـ token
            token_data = request.env['saas.auth.token'].sudo().validate_and_consume_token(token)

            if not token_data:
                _logger.warning("⚠️ Invalid/expired token from IP: %s", client_ip)
                return request.render('web.login', {
                    'error': 'رمز التسجيل غير صالح أو منتهي الصلاحية'
                })

            user_id = token_data['user_id']
            user_login = token_data['user_login']
            db_name = token_data['db_name']

            # التحقق من المستخدم مرة أخرى
            user = request.env['res.users'].sudo().browse(user_id)
            if not user.exists() or not user.active:
                _logger.error("❌ User not found or inactive")
                return request.render('web.login', {
                    'error': 'المستخدم غير موجود أو غير نشط'
                })

            # تسجيل الدخول
            request.session.logout(keep_db=True)

            request.session.uid = user_id
            request.session.login = user_login
            request.session.db = db_name
            request.session.session_token = secrets.token_hex(16)
            request.session.context = {
                'lang': user.lang or 'en_US',
                'tz': user.tz or 'UTC',
                'uid': user_id,
            }

            request.update_env(user=user_id)
            request.session.modified = True

            _logger.info("✅ Autologin SUCCESS for user: %s (ID: %d) from IP: %s",
                         user_login, user_id, client_ip)

            return werkzeug.utils.redirect('/web', 303)

        except Exception as e:
            _logger.error("❌ Autologin FAILED: %s", str(e), exc_info=True)
            return request.render('web.login', {
                'error': 'فشل تسجيل الدخول'
            })

    @http.route('/saas/cleanup_tokens', type='json', auth='user', methods=['POST'])
    def cleanup_expired_tokens(self):
        """تنظيف الـ tokens المنتهية"""
        try:
            count = request.env['saas.auth.token'].sudo().cleanup_expired_tokens()
            remaining = request.env['saas.auth.token'].sudo().search_count([])

            _logger.info("🧹 Cleaned %d expired tokens, %d remaining", count, remaining)

            return {
                'success': True,
                'cleaned': count,
                'remaining': remaining
            }
        except Exception as e:
            _logger.error("❌ Cleanup failed: %s", str(e))
            return {'success': False, 'error': str(e)}