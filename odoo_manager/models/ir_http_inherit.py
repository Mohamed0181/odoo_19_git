# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden

# Paths that are always accessible even if the subscription is stopped
ALWAYS_ALLOWED_PREFIXES = (
    '/web/static/',          # Static files (CSS, JS, Images)
    '/saas/client/',         # SaaS manager control endpoints
    '/web/manifest.json',    # Web manifest
    '/favicon.ico',
    '/web/assets/',          # Bundled assets
)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _pre_dispatch(cls, rule, args):
        """
        Intercepts requests before dispatching to check subscription status.
        Odoo 18/19 compatible.
        """
        super()._pre_dispatch(rule, args)

        path = request.httprequest.path

        # Always allow essential system paths and control endpoints
        for prefix in ALWAYS_ALLOWED_PREFIXES:
            if path.startswith(prefix):
                return

        # Retrieve subscription status from system parameters
        status = request.env['ir.config_parameter'].sudo().get_param(
            'saas.subscription_status', 'active'
        )

        if status == 'active':
            return

        # ── Subscription Stopped Logic ──────────────────────────────────────

        # Block all JSON-RPC requests (data fetching, button clicks, etc.)
        if request.httprequest.is_json:
            raise Forbidden(
                "Subscription is stopped. Please contact support to renew."
            )

        # For standard HTTP GET requests (like loading /web), we let them pass
        # This allows the saas_block_ui.xml template to render the overlay
        # effectively hiding the Odoo interface while showing the block message.