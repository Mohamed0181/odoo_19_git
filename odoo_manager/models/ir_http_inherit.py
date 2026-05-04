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
    def _pre_dispatch(cls, rule, args):
        """
        Modified signature to accept rule and args for Odoo 19 compatibility.
        Prevents TypeError while managing subscription states.
        """
        # 1. Correct super call with required arguments
        super()._pre_dispatch(rule, args)

        path = request.httprequest.path

        # 2. Allow essential system assets and control paths
        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        # 3. Retrieve status from system parameters
        status = request.env['ir.config_parameter'].sudo().get_param(
            'saas.subscription_status', 'active'
        )

        if status == 'active':
            return

        # 4. Handle 'stopped' state logic
        if request.httprequest.is_json:
            try:
                # We block only writing/modifying actions to allow the UI to load
                body = request.get_json_data()
                params = body.get('params', {})
                method = params.get('method', '')

                # Block operations that modify data
                if method in ('write', 'create', 'unlink', 'action_done'):
                    raise Forbidden("Subscription expired. Changes are not allowed.")
            except Exception:
                # Fallback for unexpected JSON structures
                pass

        # We do NOT raise Forbidden for GET requests here.
        # This allows the Web Client to load and display the red banner.