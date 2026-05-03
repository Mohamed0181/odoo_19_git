# -*- coding: utf-8 -*-
from odoo import models, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    """
    وراثة موديل المستخدمين لإضافة فحص الحد الأقصى
    """
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        """
        فحص الحد الأقصى قبل إنشاء مستخدم جديد
        Odoo 18 compatible with create_multi
        """
        # فحص عدد المستخدمين الداخليين الجدد فقط
        internal_users_count = 0
        for vals in vals_list:
            # التحقق من أن المستخدم ليس shared user
            if not vals.get('share', False):
                internal_users_count += 1

        # إذا كان هناك مستخدمين داخليين جدد، نفحص الحد
        if internal_users_count > 0:
            limit_control = self.env['saas.user.limit.control'].sudo().search([], limit=1)

            if limit_control:
                current_count = self.search_count([
                    ('share', '=', False),
                    ('active', '=', True)
                ])

                new_total = current_count + internal_users_count

                if new_total > limit_control.max_users:
                    raise ValidationError(_(
                        '🚫 Cannot Create User - Limit Reached!\n\n'
                        '📊 User Limit Summary:\n'
                        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
                        'Maximum Allowed Users: %s\n'
                        'Current Active Users: %s\n'
                        'Trying to Add: %s user(s)\n'
                        'Would Result In: %s users\n\n'
                        '💡 Solution:\n'
                        'Contact your system administrator to increase the user limit.\n'
                    ) % (
                                              limit_control.max_users,
                                              current_count,
                                              internal_users_count,
                                              new_total
                                          ))

                _logger.info(
                    "✅ User creation allowed: %s/%s users",
                    new_total,
                    limit_control.max_users
                )

        return super().create(vals_list)

    def write(self, vals):
        """
        منع تحويل shared user إلى internal user إذا تجاوز الحد
        """
        result = super().write(vals)

        # إذا تم تغيير share من True إلى False
        if 'share' in vals and not vals['share']:
            limit_control = self.env['saas.user.limit.control'].sudo().search([], limit=1)

            if limit_control:
                current_count = self.search_count([
                    ('share', '=', False),
                    ('active', '=', True)
                ])

                if current_count > limit_control.max_users:
                    raise ValidationError(_(
                        '🚫 Cannot Convert to Internal User!\n\n'
                        'Current internal users (%s) would exceed the limit (%s).\n'
                        'Please contact your administrator.'
                    ) % (current_count, limit_control.max_users))

        return result