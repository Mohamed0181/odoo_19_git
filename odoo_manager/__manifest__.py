# -*- coding: utf-8 -*-
{
    'name': 'Odoo Management',
    'version': '19.0.1.0.0',
    'category': 'Odoo Management',
    'summary': 'Control odoo instances and prevent module uninstallation',
    'author': 'Optimum Smart Solutions',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'view/saas_block_ui.xml',
    ],
    'auto_install': True,
    'installable': True,
    'application': False,
}
