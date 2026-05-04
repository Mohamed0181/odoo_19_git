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
        super()._pre_dispatch(rule, args)
        path = request.httprequest.path

        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        status = request.env['ir.config_parameter'].sudo().get_param('saas.subscription_status', 'active')

        # Only block actions if the status is explicitly 'stopped'
        if status != 'stopped':
            return

        if request.httprequest.is_json:
            try:
                body = request.get_json_data()
                method = body.get('params', {}).get('method', '')
                # Block modifying methods only
                if method in ('write', 'create', 'unlink', 'action_done'):
                    raise Forbidden("Subscription suspended. Please contact support.")
            except Exception:
                pass