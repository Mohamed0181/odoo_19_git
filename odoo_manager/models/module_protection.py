# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError

class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    def button_immediate_uninstall(self):
        """ Prevent uninstallation of the management module """
        for module in self:
            if module.name == 'odoo_manager':
                raise UserError(_(
                    "Security Restriction: The module '%s' is critical for system management "
                    "and cannot be uninstalled."
                ) % module.shortdesc)
        return super(IrModuleModule, self).button_immediate_uninstall()

    def unlink(self):
        """ Prevent deletion of the module record """
        for module in self:
            if module.name == 'odoo_manager':
                raise UserError(_("Critical Module: Deletion of this record is prohibited."))
        return super(IrModuleModule, self).unlink()