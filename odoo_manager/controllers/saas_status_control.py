# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SHARED_SECRET_PARAM = 'saas.manager.secret'
SUBSCRIPTION_STATUS_PARAM = 'saas.subscription_status'


class SaasStatusController(http.Controller):

    @http.route('/saas/client/set_status', type='json', auth='none', methods=['POST'], csrf=False)
    def set_subscription_status(self, **kwargs):
        """
        Updates subscription status.
        Supported statuses: active, warning, stopped.
        """
        try:
            data = kwargs or request.get_json_data().get('params', {})
            incoming_secret = data.get('secret', '')
            new_status = data.get('status', '')

            # Validate status input
            if new_status not in ('active', 'warning', 'stopped'):
                return {
                    'success': False,
                    'error': f'Invalid status: {new_status}. Use active, warning, or stopped.'
                }

            # Verify shared secret
            stored_secret = request.env['ir.config_parameter'].sudo().get_param(SHARED_SECRET_PARAM, '')
            if not stored_secret or incoming_secret != stored_secret:
                _logger.warning("Unauthorized status update attempt from IP: %s", request.httprequest.remote_addr)
                return {'success': False, 'error': 'Unauthorized'}

            # Save new status to system parameters
            request.env['ir.config_parameter'].sudo().set_param(SUBSCRIPTION_STATUS_PARAM, new_status)

            _logger.info("Subscription status updated to: %s", new_status)
            return {'success': True, 'status': new_status}

        except Exception as e:
            _logger.error("SaaS Control Error: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/saas/client/ping', type='json', auth='none', methods=['POST'], csrf=False)
    def ping(self, **kwargs):
        """ Checks connectivity and returns current status. """
        try:
            data = kwargs or request.get_json_data().get('params', {})
            incoming_secret = data.get('secret', '')
            stored_secret = request.env['ir.config_parameter'].sudo().get_param(SHARED_SECRET_PARAM, '')

            if not stored_secret or incoming_secret != stored_secret:
                return {'success': False, 'error': 'Unauthorized'}

            current_status = request.env['ir.config_parameter'].sudo().get_param(SUBSCRIPTION_STATUS_PARAM, 'active')
            return {
                'success': True,
                'module': 'odoo_manager',
                'status': current_status,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}