# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

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
        Odoo 19 compatible pre_dispatch.
        Blocks modifications if status is 'stopped'.
        """
        # Call super with correct Odoo 19 arguments[cite: 1]
        super()._pre_dispatch(rule, args)

        path = request.httprequest.path

        # 1. Allow essential system and auth paths[cite: 1]
        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        # 2. Check subscription status[cite: 1]
        status = request.env['ir.config_parameter'].sudo().get_param('saas.subscription_status', 'active')

        if status == 'active' or status == 'warning':
            return

        # 3. Handle 'stopped' status[cite: 1]
        if request.httprequest.is_json:
            try:
                body = request.get_json_data()
                method = body.get('params', {}).get('method', '')

                # Block modification methods while allowing read-only UI loading[cite: 1]
                if method in ('write', 'create', 'unlink', 'action_done'):
                    raise Forbidden("Subscription suspended. Actions are restricted.")
            except Exception:
                pass