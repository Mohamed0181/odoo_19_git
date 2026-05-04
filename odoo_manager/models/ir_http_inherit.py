# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

# Paths that must remain accessible for Login/Logout and System Control
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
        Ensures users can log out even when the subscription is stopped.
        """
        super()._pre_dispatch(rule, args)

        path = request.httprequest.path

        # 1. Bypass check for essential and auth paths
        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        # 2. Check current subscription status
        status = request.env['ir.config_parameter'].sudo().get_param(
            'saas.subscription_status', 'active'
        )

        if status == 'active':
            return

        # 3. Block JSON actions that modify data
        if request.httprequest.is_json:
            try:
                body = request.get_json_data()
                params = body.get('params', {})
                method = params.get('method', '')

                # Prevent writing/creating/deleting while stopped
                if method in ('write', 'create', 'unlink', 'action_done'):
                    raise Forbidden("Subscription suspended. Please contact support.")
            except Exception:
                pass