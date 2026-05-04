# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

ALWAYS_ALLOWED_PATHS = (
    '/web/static/',
    '/saas/client/',
    '/web/assets/',
    '/favicon.ico',
)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls):
        """
        Modified for Odoo 19 to support banner view without white screen.
        """
        # Call super first if needed, but in pre_dispatch usually we check our logic
        path = request.httprequest.path

        # 1. Allow Essential Assets
        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        # 2. Check Subscription Status
        status = request.env['ir.config_parameter'].sudo().get_param('saas.subscription_status', 'active')

        if status == 'active':
            return

        # 3. Handle Stopped State
        # Allow UI rendering but block crucial actions
        if request.httprequest.is_json:
            # Check if this is a 'write', 'create' or 'unlink' call (simplified)
            body = request.get_json_data()
            method = body.get('params', {}).get('method', '')

            if method in ('write', 'create', 'unlink', 'action_done'):
                raise Forbidden("Subscription expired. Action blocked.")

        # For GET requests, we let them pass so the user can see the App list and our Red Banner