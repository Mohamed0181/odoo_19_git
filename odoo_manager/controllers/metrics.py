# -*- coding: utf-8 -*-
import os
import logging
from odoo import http
from odoo.http import request, Response
from odoo.tools import config
from odoo.sql_db import db_connect

from odoo.addons.odoo_manager.models.ir_http_inherit import HTTP_METRICS, ROUTE_METRICS

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
                            _logger.warning("SaasMetrics: size error %s: %s", fp, e)
        return total_size

    def _gauge(self, name, help_text, value, labels=None):
        label_str = ""
        if labels:
            pairs = ",".join(f'{k}="{v}"' for k, v in labels.items())
            label_str = f"{{{pairs}}}"
        return [
            f"# HELP {name} {help_text}",
            f"# TYPE {name} gauge",
            f"{name}{label_str} {value}",
        ]

    @http.route(
        '/metrics',
        type='http',
        auth='none',
        methods=['GET'],
        csrf=False,
    )
    def prometheus_metrics(self, db=None, **kwargs):
        metrics = []
        db_name = db or (
            request.env.cr.dbname
            if (request.env and request.env.cr)
            else None
        )

        if not db_name:
            metrics += self._gauge('odoo_error', 'Odoo metrics error indicator.', 1, {'reason': 'no_db_param'})
            return self._text_response(metrics)

        try:
            conn = db_connect(db_name)
        except Exception as e:
            _logger.error("SaasMetrics: cannot connect to db '%s': %s", db_name, e)
            metrics += self._gauge('odoo_error', 'Odoo metrics error indicator.', 1,
                                   {'reason': 'db_connect_failed', 'database': db_name})
            return self._text_response(metrics)

        try:
            with conn.cursor() as cr:
                # 1. Filestore Metrics
                data_dir = config.get('data_dir', '/var/lib/odoo')
                filestore_path = os.path.join(data_dir, 'filestore', db_name)
                filestore_size = self._get_dir_size(filestore_path)

                metrics += self._gauge('odoo_filestore_size_bytes', 'Total size of the Odoo filestore in bytes.',
                                       filestore_size, {'database': db_name})

                if os.path.exists(filestore_path):
                    for entry in os.scandir(filestore_path):
                        if entry.is_dir():
                            folder_size = self._get_dir_size(entry.path)
                            metrics += self._gauge('odoo_filestore_folder_size_bytes',
                                                   'Size of individual filestore folders', folder_size,
                                                   {'database': db_name, 'folder': entry.name})

                # 2. Database Tables Metrics
                try:
                    cr.execute("""
                               SELECT relname as table_name, pg_total_relation_size(relid) as size
                               FROM pg_catalog.pg_statio_user_tables
                               ORDER BY pg_total_relation_size(relid) DESC LIMIT 20
                               """)
                    for table_name, size in cr.fetchall():
                        metrics += self._gauge('odoo_db_table_size_bytes', 'Size of database tables', size,
                                               {'database': db_name, 'table': table_name})
                except Exception as e:
                    _logger.warning("SaasMetrics: table size calculation failed: %s", e)

                # 3. General Statistics
                try:
                    cr.execute("SELECT count(*) FROM res_users WHERE active = true")
                    active_users = cr.fetchone()[0]
                    metrics += self._gauge('odoo_active_users_total', 'Number of active Odoo users.', active_users,
                                           {'database': db_name})
                except Exception as e:
                    _logger.warning("SaasMetrics: user count failed: %s", e)

                try:
                    cr.execute("SELECT count(*) FROM ir_module_module WHERE state = 'installed'")
                    module_count = cr.fetchone()[0]
                    metrics += self._gauge('odoo_installed_modules_total', 'Number of installed Odoo modules.',
                                           module_count, {'database': db_name})
                except Exception as e:
                    _logger.warning("SaasMetrics: module count failed: %s", e)

                try:
                    cr.execute("SELECT count(*) FROM ir_cron WHERE active = true")
                    cron_count = cr.fetchone()[0]
                    metrics += self._gauge('odoo_active_cron_jobs_total', 'Number of active scheduled actions.',
                                           cron_count, {'database': db_name})
                except Exception as e:
                    _logger.warning("SaasMetrics: cron count failed: %s", e)

                try:
                    cr.execute("SELECT count(*) FROM ir_attachment")
                    attach_count = cr.fetchone()[0]
                    metrics += self._gauge('odoo_attachments_total', 'Total number of attachments stored.',
                                           attach_count, {'database': db_name})
                except Exception as e:
                    _logger.warning("SaasMetrics: attachment count failed: %s", e)

                # 4. Mails Metrics
                try:
                    cr.execute("SELECT state, count(*) FROM mail_mail GROUP BY state")
                    for state, count in cr.fetchall():
                        metrics += self._gauge('odoo_mail_outgoing_total', 'Total outgoing mails by state', count,
                                               {'database': db_name, 'state': state})
                    cr.execute("SELECT count(*) FROM mail_message WHERE message_type = 'email'")
                    incoming_count = cr.fetchone()[0]
                    metrics += self._gauge('odoo_mail_incoming_total', 'Total incoming mails', incoming_count,
                                           {'database': db_name, 'state': 'received'})
                except Exception as e:
                    _logger.warning("SaasMetrics: mails calculation failed: %s", e)

                # 5. Log Statistics (Optimized Single Pass)
                try:
                    cr.execute("""
                               SELECT COUNT(*) FILTER (WHERE level IN ('ERROR', 'CRITICAL')) AS errors, COUNT(*) FILTER (WHERE level = 'WARNING') AS warnings, COUNT(*) FILTER (WHERE message ILIKE '%MemoryError%' OR message ILIKE '%Memory limit%') AS mem_odoo, COUNT(*) FILTER (WHERE message ILIKE '%out of memory%') AS mem_pg, COUNT(*) FILTER (WHERE message ILIKE '%could not serialize access%' OR message ILIKE '%SerializationFailure%') AS serialization
                               FROM ir_logging
                               """)
                    log_stats = cr.fetchone()
                    if log_stats:
                        metrics += self._gauge('odoo_log_errors_total', 'Total errors', log_stats[0] or 0,
                                               {'database': db_name})
                        metrics += self._gauge('odoo_log_warnings_total', 'Total warnings', log_stats[1] or 0,
                                               {'database': db_name})
                        metrics += self._gauge('odoo_log_mem_odoo_total', 'Odoo memory limit occurrences',
                                               log_stats[2] or 0, {'database': db_name})
                        metrics += self._gauge('odoo_log_mem_pg_total', 'PG memory limit occurrences',
                                               log_stats[3] or 0, {'database': db_name})
                        metrics += self._gauge('odoo_log_serialization_total', 'Serialization failures',
                                               log_stats[4] or 0, {'database': db_name})
                except Exception as e:
                    _logger.warning("SaasMetrics: logs calculation failed: %s", e)

        except Exception as e:
            _logger.error("SaasMetrics: error reading metrics for '%s': %s", db_name, e)
            metrics += self._gauge('odoo_error', 'Odoo metrics error indicator.', 1,
                                   {'reason': 'query_failed', 'database': db_name})

        # 6. Global HTTP & XML-RPC Metrics
        db_http_metrics = HTTP_METRICS.get(db_name, {'count': 0, 'duration_sum': 0.0, 'xmlrpc_count': 0})

        metrics += self._gauge('odoo_http_requests_total', 'Total number of HTTP requests.', db_http_metrics['count'],
                               {'database': db_name})
        metrics += self._gauge('odoo_http_request_duration_seconds_sum', 'Total duration of HTTP requests in seconds.',
                               db_http_metrics['duration_sum'], {'database': db_name})
        metrics += self._gauge('odoo_http_request_duration_seconds_count',
                               'Number of HTTP requests for duration calculation.', db_http_metrics['count'],
                               {'database': db_name})
        metrics += self._gauge('odoo_http_xmlrpc_total', 'Total XML-RPC requests.', db_http_metrics['xmlrpc_count'],
                               {'database': db_name})

        # 7. Routes Duration Metrics
        for key, data in ROUTE_METRICS.items():
            if data['db'] == db_name:
                metrics += self._gauge('odoo_http_route_duration_seconds_sum', 'Total duration per route',
                                       data['duration_sum'], {'database': db_name, 'route': data['route']})
                metrics += self._gauge('odoo_http_route_duration_seconds_count', 'Total requests per route',
                                       data['count'], {'database': db_name, 'route': data['route']})

        return self._text_response(metrics)

    def _text_response(self, metrics: list):
        body = "\n".join(metrics) + "\n"
        return request.make_response(body, headers=[('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')])