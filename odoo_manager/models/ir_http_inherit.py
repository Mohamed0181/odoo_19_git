# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

# Paths that are always allowed to ensure Login/Logout and Control work
ALWAYS_ALLOWED_PATHS = (
    '/web/static/',
    '/saas/client/',
    '/web/assets/',
    '/favicon.ico',
    '/web/login',
    '/web/session/logout',
    '/web/session/authenticate',
)

class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        """
        Odoo 19 compatible _pre_dispatch.
        Allows Authentication and SaaS control paths even when stopped.
        """
        super()._pre_dispatch(rule, args)

        path = request.httprequest.path

        # 1. Allow essential and authentication paths
        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        # 2. Check Subscription Status
        status = request.env['ir.config_parameter'].sudo().get_param(
            'saas.subscription_status', 'active'
        )

        if status == 'active':
            return

        # 3. Handle Restricted State
        if request.httprequest.is_json:
            try:
                body = request.get_json_data()
                params = body.get('params', {})
                method = params.get('method', '')

                # Block data modification but allow reading for UI consistency
                if method in ('write', 'create', 'unlink', 'action_done'):
                    raise Forbidden("Subscription expired. Actions are restricted.")
            except Exception:
                pass