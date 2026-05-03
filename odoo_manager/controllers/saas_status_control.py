# -*- coding: utf-8 -*-
"""
SaaS Status Controller (على قاعدة العميل)
===========================================
Endpoint يستقبل أوامر تغيير حالة الاشتراك من السيرفر الرئيسي.
محمي بـ shared secret مخزون في ir.config_parameter.

ملاحظة: هذا الـ endpoint مكتوب كـ backup فقط.
الطريقة الأساسية هي psycopg2 مباشرة من السيرفر.
هذا يُستخدم لو أراد المدير تغيير الحالة يدوياً عبر HTTP.
"""

import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SHARED_SECRET_PARAM = 'saas.manager.secret'
SUBSCRIPTION_STATUS_PARAM = 'saas.subscription_status'


class SaasStatusController(http.Controller):

    @http.route(
        '/saas/client/set_status',
        type='json',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def set_subscription_status(self, **kwargs):
        """
        يستقبل طلب تغيير حالة الاشتراك.

        Body المطلوب:
        {
            "secret": "<shared_secret>",
            "status": "active" | "stopped"
        }
        """
        try:
            body = request.get_json_data()
            incoming_secret = body.get('secret', '')
            new_status = body.get('status', '')

            # التحقق من الحالة المطلوبة
            if new_status not in ('active', 'stopped'):
                return {'success': False, 'error': 'Invalid status. Use active or stopped.'}

            # التحقق من الـ secret
            stored_secret = request.env['ir.config_parameter'].sudo().get_param(
                SHARED_SECRET_PARAM, ''
            )

            if not stored_secret or incoming_secret != stored_secret:
                _logger.warning(
                    "⚠️ SaaS status update rejected: invalid secret from %s",
                    request.httprequest.remote_addr
                )
                return {'success': False, 'error': 'Unauthorized'}

            # تطبيق الحالة الجديدة
            request.env['ir.config_parameter'].sudo().set_param(
                SUBSCRIPTION_STATUS_PARAM, new_status
            )

            _logger.info(
                "✅ SaaS subscription status updated to '%s' via HTTP from %s",
                new_status,
                request.httprequest.remote_addr
            )

            return {'success': True, 'status': new_status}

        except Exception as e:
            _logger.error("❌ Error in set_subscription_status: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route(
        '/saas/client/ping',
        type='json',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def ping(self, **kwargs):
        """
        للتحقق من أن الموديول مثبت ويعمل.
        يُستخدم من السيرفر الرئيسي للتأكد قبل إرسال الحالة.
        """
        try:
            body = request.get_json_data()
            incoming_secret = body.get('secret', '')

            stored_secret = request.env['ir.config_parameter'].sudo().get_param(
                SHARED_SECRET_PARAM, ''
            )

            if not stored_secret or incoming_secret != stored_secret:
                return {'success': False, 'error': 'Unauthorized'}

            current_status = request.env['ir.config_parameter'].sudo().get_param(
                SUBSCRIPTION_STATUS_PARAM, 'active'
            )

            return {
                'success': True,
                'module': 'odoo_manager',
                'status': current_status,
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}
