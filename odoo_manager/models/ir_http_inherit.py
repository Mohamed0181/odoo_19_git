# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

# المسارات المسموح بها دائماً (حتى لو الاشتراك متوقف)
ALWAYS_ALLOWED_PREFIXES = (
    '/web/static/',          # ملفات CSS/JS/Images
    '/saas/client/',         # endpoint الـ SaaS manager
    '/web/manifest.json',    # manifest
    '/favicon.ico',
    '/web/assets/',
)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)

        path = request.httprequest.path

        # السماح دائماً للمسارات الأساسية
        for prefix in ALWAYS_ALLOWED_PREFIXES:
            if path.startswith(prefix):
                return

        # قراءة حالة الاشتراك
        status = request.env['ir.config_parameter'].sudo().get_param(
            'saas.subscription_status', 'active'
        )

        if status == 'active':
            return

        # ── الاشتراك متوقف ──────────────────────────────────────────────────

        # JSON requests (RPC calls, actions, data fetching) → 403
        if request.httprequest.is_json:
            raise Forbidden(
                "Subscription is stopped. Please contact support to renew."
            )

        # HTTP GET على /web أو أي صفحة أودو → نتركه يمر لكي يُرندر الـ block screen
        # الـ saas_block_ui.xml هيخفي الـ UI ويظهر رسالة الحجب تلقائياً
        # لا نعمل Forbidden هنا لأننا نحتاج الصفحة تتحمل لتظهر الرسالة
