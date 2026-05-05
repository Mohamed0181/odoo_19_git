# -*- coding: utf-8 -*-
import time
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

HTTP_METRICS = {}

ALWAYS_ALLOWED_PATHS = (
    '/web/static/',
    '/saas/client/',
    '/web/assets/',
    '/favicon.ico',
    '/web/login',
    '/web/session/logout',
    '/web/session/authenticate',
    '/web/dataset/call_kw/res.users/read',
    '/web/dataset/call_kw/res.users/context_get',
)

ALLOWED_METHODS_WHEN_STOPPED = {
    'read', 'search_read', 'search', 'search_count', 'fields_get',
    'onchange', 'default_get', 'get_views', 'load_views', 'get_filters',
    'name_search', 'name_get', 'context_get', 'action_load', 'read_group',
    'fields_view_get', 'web_search_read',
}

BLOCKED_METHODS_WHEN_STOPPED = {
    'write', 'create', 'unlink', 'action_done', 'action_confirm',
    'action_cancel', 'action_post', 'action_validate', 'button_confirm',
    'button_validate', 'button_cancel',
}


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        path = request.httprequest.path

        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        if 'logout' in path or 'session/destroy' in path:
            return

        status = request.env['ir.config_parameter'].sudo().get_param(
            'saas.subscription_status', 'active'
        )

        if status in ('active', 'warning'):
            return

        if status == 'stopped':
            if request.httprequest.is_json:
                try:
                    body = request.get_json_data()
                    params = body.get('params', {})
                    method = params.get('method', '')
                    model = params.get('model', '')

                    if model in ('res.users', 'res.lang') and method in ALLOWED_METHODS_WHEN_STOPPED:
                        return

                    if method in ALLOWED_METHODS_WHEN_STOPPED:
                        return

                    if method in BLOCKED_METHODS_WHEN_STOPPED:
                        raise Forbidden(
                            "Subscription suspended. Write operations are restricted."
                        )
                except Forbidden:
                    raise
                except Exception:
                    pass

    @classmethod
    def _dispatch(cls, endpoint):
        start_time = time.time()

        try:
            response = super()._dispatch(endpoint)
            return response
        finally:
            duration = time.time() - start_time
            db_name = 'unknown'

            if request and hasattr(request, 'session') and getattr(request.session, 'db', False):
                db_name = request.session.db

            if db_name not in HTTP_METRICS:
                HTTP_METRICS[db_name] = {
                    'count': 0,
                    'duration_sum': 0.0,
                    'xmlrpc_count': 0
                }

            HTTP_METRICS[db_name]['count'] += 1
            HTTP_METRICS[db_name]['duration_sum'] += duration

            if request.httprequest.path.startswith('/xmlrpc'):
                HTTP_METRICS[db_name]['xmlrpc_count'] += 1