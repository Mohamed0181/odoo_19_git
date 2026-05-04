# -*- coding: utf-8 -*-
"""
SaaS Status Controller
======================
Endpoint to receive subscription status change commands from the main server.
Protected by a shared secret stored in ir.config_parameter.
"""

import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SHARED_SECRET_PARAM = 'saas.manager.secret'
SUBSCRIPTION_STATUS_PARAM = 'saas.subscription_status'


class SaasStatusController(http.Controller):

    @http.route(
        '/saas/client/set_status',
        type='json',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def set_subscription_status(self, **kwargs):
        """
        Receives subscription status update request.
        Handles Odoo 19 JSON-RPC structure by checking kwargs first.
        """
        try:
            # Extract data from kwargs (standard for Odoo type='json')
            # or fallback to params from raw json data
            data = kwargs or request.get_json_data().get('params', {})

            incoming_secret = data.get('secret', '')
            new_status = data.get('status', '')

            # Validate requested status
            if new_status not in ('active', 'stopped'):
                _logger.error("SaaS Control: Invalid status received: %s", new_status)
                return {
                    'success': False,
                    'error': f'Invalid status: {new_status}. Use active or stopped.'
                }

            # Verify the shared secret from system parameters
            stored_secret = request.env['ir.config_parameter'].sudo().get_param(
                SHARED_SECRET_PARAM, ''
            )

            if not stored_secret or incoming_secret != stored_secret:
                _logger.warning(
                    "SaaS status update rejected: invalid secret from %s",
                    request.httprequest.remote_addr
                )
                return {'success': False, 'error': 'Unauthorized'}

            # Apply the new status to the system parameters[cite: 1]
            request.env['ir.config_parameter'].sudo().set_param(
                SUBSCRIPTION_STATUS_PARAM, new_status
            )

            _logger.info(
                "SaaS subscription status updated to '%s' via HTTP from %s",
                new_status,
                request.httprequest.remote_addr
            )

            return {'success': True, 'status': new_status}

        except Exception as e:
            _logger.error("Error in set_subscription_status: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route(
        '/saas/client/ping',
        type='json',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def ping(self, **kwargs):
        """
        Check if the management module is installed and active.
        Used by the main server to verify connectivity before sending status updates.
        """
        try:
            data = kwargs or request.get_json_data().get('params', {})
            incoming_secret = data.get('secret', '')

            stored_secret = request.env['ir.config_parameter'].sudo().get_param(
                SHARED_SECRET_PARAM, ''
            )

            if not stored_secret or incoming_secret != stored_secret:
                return {'success': False, 'error': 'Unauthorized'}

            # Get current subscription status[cite: 1]
            current_status = request.env['ir.config_parameter'].sudo().get_param(
                SUBSCRIPTION_STATUS_PARAM, 'active'
            )

            return {
                'success': True,
                'module': 'odoo_manager',
                'status': current_status,
            }

        except Exception as e:
            _logger.error("Error in SaaS ping: %s", str(e))
            return {'success': False, 'error': str(e)}