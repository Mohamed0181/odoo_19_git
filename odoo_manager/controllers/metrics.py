# -*- coding: utf-8 -*-
"""
SaaS Metrics Controller
========================
Exposes Prometheus-compatible /metrics endpoint for each Odoo client database.

Usage by Prometheus:
    GET http://<branch_container>:8069/metrics?db=<database_name>

Fixes applied vs original:
  [1] auth='none'  → no session/DB needed to reach the route.
  [2] db= query param  → read from URL, not from cursor.
  [3] Manual db_connect() → opens a real cursor to the target DB.
  [4] Extra metrics: active users, installed modules count.
"""

import os
import logging
from odoo import http
from odoo.http import request, Response
from odoo.tools import config
from odoo.sql_db import db_connect

_logger = logging.getLogger(__name__)


class SaasMetricsController(http.Controller):

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_dir_size(self, path):
        """Return total size of a directory tree in bytes."""
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
        """Build a Prometheus GAUGE block."""
        label_str = ""
        if labels:
            pairs = ",".join(f'{k}="{v}"' for k, v in labels.items())
            label_str = f"{{{pairs}}}"
        return [
            f"# HELP {name} {help_text}",
            f"# TYPE {name} gauge",
            f"{name}{label_str} {value}",
        ]

    # -------------------------------------------------------------------------
    # Endpoint
    # -------------------------------------------------------------------------

    @http.route(
        '/metrics',
        type='http',
        auth='none',          # FIX [1]: no session required
        methods=['GET'],
        csrf=False,
    )
    def prometheus_metrics(self, db=None, **kwargs):
        """
        Prometheus scrape endpoint.
        Prometheus config must pass:
            params:
              db: ['<database_name>']
        """
        metrics = []

        # FIX [2]: read db from query param; fallback to cursor db if available
        db_name = db or (
            request.env.cr.dbname
            if (request.env and request.env.cr)
            else None
        )

        if not db_name:
            metrics += self._gauge(
                'odoo_error',
                'Odoo metrics error indicator.',
                1,
                {'reason': 'no_db_param'},
            )
            return self._text_response(metrics)

        # FIX [3]: open a real connection to the requested DB
        try:
            conn = db_connect(db_name)
        except Exception as e:
            _logger.error("SaasMetrics: cannot connect to db '%s': %s", db_name, e)
            metrics += self._gauge(
                'odoo_error',
                'Odoo metrics error indicator.',
                1,
                {'reason': 'db_connect_failed', 'database': db_name},
            )
            return self._text_response(metrics)

        try:
            with conn.cursor() as cr:
                # ── Filestore size ─────────────────────────────────────────
                data_dir = config.get('data_dir', '/var/lib/odoo')
                filestore_path = os.path.join(data_dir, 'filestore', db_name)
                filestore_size = self._get_dir_size(filestore_path)
                metrics += self._gauge(
                    'odoo_filestore_size_bytes',
                    'Total size of the Odoo filestore in bytes.',
                    filestore_size,
                    {'database': db_name},
                )

                # ── Active users ───────────────────────────────────────────
                try:
                    cr.execute(
                        "SELECT count(*) FROM res_users WHERE active = true"
                    )
                    active_users = cr.fetchone()[0]
                    metrics += self._gauge(
                        'odoo_active_users_total',
                        'Number of active Odoo users.',
                        active_users,
                        {'database': db_name},
                    )
                except Exception as e:
                    _logger.warning("SaasMetrics: user count failed: %s", e)

                # ── Installed modules ──────────────────────────────────────
                try:
                    cr.execute(
                        "SELECT count(*) FROM ir_module_module WHERE state = 'installed'"
                    )
                    module_count = cr.fetchone()[0]
                    metrics += self._gauge(
                        'odoo_installed_modules_total',
                        'Number of installed Odoo modules.',
                        module_count,
                        {'database': db_name},
                    )
                except Exception as e:
                    _logger.warning("SaasMetrics: module count failed: %s", e)

                # ── Active IR cron jobs ────────────────────────────────────
                try:
                    cr.execute(
                        "SELECT count(*) FROM ir_cron WHERE active = true"
                    )
                    cron_count = cr.fetchone()[0]
                    metrics += self._gauge(
                        'odoo_active_cron_jobs_total',
                        'Number of active scheduled actions.',
                        cron_count,
                        {'database': db_name},
                    )
                except Exception as e:
                    _logger.warning("SaasMetrics: cron count failed: %s", e)

                # ── Attachments count ──────────────────────────────────────
                try:
                    cr.execute("SELECT count(*) FROM ir_attachment")
                    attach_count = cr.fetchone()[0]
                    metrics += self._gauge(
                        'odoo_attachments_total',
                        'Total number of attachments stored.',
                        attach_count,
                        {'database': db_name},
                    )
                except Exception as e:
                    _logger.warning("SaasMetrics: attachment count failed: %s", e)

        except Exception as e:
            _logger.error("SaasMetrics: error reading metrics for '%s': %s", db_name, e)
            metrics += self._gauge(
                'odoo_error',
                'Odoo metrics error indicator.',
                1,
                {'reason': 'query_failed', 'database': db_name},
            )

        return self._text_response(metrics)

    def _text_response(self, metrics: list):
        body = "\n".join(metrics) + "\n"
        return request.make_response(
            body,
            headers=[('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')]
        )