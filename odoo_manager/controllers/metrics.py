import os
import logging
from odoo import http
from odoo.http import request
from odoo.tools import config

_logger = logging.getLogger(__name__)


class SaasMetricsController(http.Controller):

    def _get_dir_size(self, path):
        total_size = 0
        if os.path.exists(path):
            for dirpath, _, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp):
                        try:
                            total_size += os.path.getsize(fp)
                        except OSError as e:
                            _logger.warning("SaasMetrics: Failed to get size of %s: %s", fp, e)
                            continue
        return total_size

    @http.route('/metrics', type='http', auth='public', methods=['GET'], csrf=False)
    def prometheus_metrics(self, **kwargs):
        metrics = []
        db_name = request.env.cr.dbname if request.env else None

        if db_name:
            data_dir = config.get('data_dir')
            filestore_path = os.path.join(data_dir, 'filestore', db_name)

            filestore_size = self._get_dir_size(filestore_path)

            metrics.append("# HELP odoo_filestore_size_bytes Total size of Odoo filestore in bytes.")
            metrics.append("# TYPE odoo_filestore_size_bytes gauge")
            metrics.append(f'odoo_filestore_size_bytes{{database="{db_name}"}} {filestore_size}')
        else:
            metrics.append("# HELP odoo_error No database resolved for metrics.")
            metrics.append("# TYPE odoo_error gauge")
            metrics.append('odoo_error{reason="no_db"} 1')

        response_body = "\n".join(metrics) + "\n"
        return request.make_response(
            response_body,
            headers=[('Content-Type', 'text/plain; version=0.0.4')]
        )