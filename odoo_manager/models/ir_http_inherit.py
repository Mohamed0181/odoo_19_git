# -*- coding: utf-8 -*-
import time
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

# Global dictionary to store HTTP metrics for Prometheus
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

# JSON-RPC methods that are safe to allow even when stopped (read-only)
ALLOWED_METHODS_WHEN_STOPPED = {
    'read', 'search_read', 'search', 'search_count', 'fields_get',
    'onchange', 'default_get', 'get_views', 'load_views', 'get_filters',
    'name_search', 'name_get', 'context_get', 'action_load', 'read_group',
    'fields_view_get', 'web_search_read',
}

# Methods that must be blocked when stopped
BLOCKED_METHODS_WHEN_STOPPED = {
    'write', 'create', 'unlink', 'action_done', 'action_confirm',
    'action_cancel', 'action_post', 'action_validate', 'button_confirm',
    'button_validate', 'button_cancel',
}


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        """
        Odoo 18/19 compatible pre_dispatch.
        Blocks write operations when subscription status is 'stopped'.
        Navbar and logout remain fully accessible at all times.
        """
        super()._pre_dispatch(rule, args)
        path = request.httprequest.path

        # Always allow essential system, auth, and static paths
        for prefix in ALWAYS_ALLOWED_PATHS:
            if path.startswith(prefix):
                return

        # Allow all logout-related actions regardless of status
        if 'logout' in path or 'session/destroy' in path:
            return

        # Read subscription status
        status = request.env['ir.config_parameter'].sudo().get_param(
            'saas.subscription_status', 'active'
        )

        # active or warning: full access
        if status in ('active', 'warning'):
            return

        # stopped: block write operations, allow read-only
        if status == 'stopped':
            if request.httprequest.is_json:
                try:
                    body = request.get_json_data()
                    params = body.get('params', {})
                    method = params.get('method', '')
                    model = params.get('model', '')

                    # Always allow user session / preference reads
                    if model in ('res.users', 'res.lang') and method in ALLOWED_METHODS_WHEN_STOPPED:
                        return

                    # Allow all explicitly safe methods
                    if method in ALLOWED_METHODS_WHEN_STOPPED:
                        return

                    # Block all write/create/delete/action methods
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
        """
        Override _dispatch to track HTTP request count and duration for metrics.
        """
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
                HTTP_METRICS[db_name] = {'count': 0, 'duration_sum': 0.0}

            HTTP_METRICS[db_name]['count'] += 1
            HTTP_METRICS[db_name]['duration_sum'] += duration