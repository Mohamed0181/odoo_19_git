# -*- coding: utf-8 -*-

from odoo import api, fields, models
from datetime import datetime, timedelta
import secrets
import logging

_logger = logging.getLogger(__name__)


class SaasAuthToken(models.Model):
    _name = 'saas.auth.token'
    _description = 'SaaS Authentication Token'
    _order = 'create_date desc'

    token = fields.Char(string='Token', required=True, index=True)
    user_id = fields.Integer(string='User ID', required=True)
    user_login = fields.Char(string='User Login', required=True)
    db_name = fields.Char(string='Database Name', required=True)
    expires_at = fields.Datetime(string='Expires At', required=True, index=True)
    used = fields.Boolean(string='Used', default=False)
    used_at = fields.Datetime(string='Used At')

    _sql_constraints = [
        ('token_unique', 'unique(token)', 'Token must be unique!')
    ]

    @api.model
    def generate_token(self, user_id, user_login, db_name, expires_minutes=10):
        """توليد token جديد"""
        token = secrets.token_urlsafe(40)
        expires_at = datetime.now() + timedelta(minutes=expires_minutes)
        
        # حذف الـ tokens القديمة المنتهية للمستخدم
        self.cleanup_expired_tokens()
        
        auth_token = self.create({
            'token': token,
            'user_id': user_id,
            'user_login': user_login,
            'db_name': db_name,
            'expires_at': expires_at,
        })
        
        _logger.info("✅ Token generated for user %s (ID: %d) - expires at %s", 
                     user_login, user_id, expires_at)
        
        return auth_token

    @api.model
    def validate_and_consume_token(self, token):
        """التحقق من الـ token واستخدامه (مرة واحدة فقط)"""
        auth_token = self.search([
            ('token', '=', token),
            ('used', '=', False),
            ('expires_at', '>', fields.Datetime.now())
        ], limit=1)
        
        if not auth_token:
            _logger.warning("⚠️ Token not found or already used/expired")
            return None
        
        # تحديد الـ token كمستخدم
        auth_token.write({
            'used': True,
            'used_at': fields.Datetime.now()
        })
        
        _logger.info("✅ Token validated for user %s (ID: %d)", 
                     auth_token.user_login, auth_token.user_id)
        
        return {
            'user_id': auth_token.user_id,
            'user_login': auth_token.user_login,
            'db_name': auth_token.db_name,
        }

    @api.model
    def cleanup_expired_tokens(self):
        """تنظيف الـ tokens المنتهية والمستخدمة"""
        # حذف الـ tokens المنتهية أو المستخدمة لأكثر من ساعة
        expired = self.search([
            '|',
            ('expires_at', '<', fields.Datetime.now()),
            '&',
            ('used', '=', True),
            ('used_at', '<', fields.Datetime.now() - timedelta(hours=1))
        ])
        
        count = len(expired)
        if count > 0:
            expired.unlink()
            _logger.info("🧹 Cleaned %d expired/used tokens", count)
        
        return count
