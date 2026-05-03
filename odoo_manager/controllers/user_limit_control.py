# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class UserLimitControl(models.Model):
    """
    موديل للتحكم في عدد المستخدمين في قاعدة البيانات
    يتم تثبيته تلقائياً ولا يمكن حذفه
    """
    _name = 'saas.user.limit.control'
    _description = 'SaaS User Limit Control'
    _rec_name = 'display_name'

    name = fields.Char(
        string='Name',
        default='User Limit Control',
        readonly=True,
        required=True
    )

    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    max_users = fields.Integer(
        string='Maximum Users',
        default=1,
        required=True,
        help='Maximum number of internal users allowed in this database'
    )

    current_users_count = fields.Integer(
        string='Current Users',
        compute='_compute_current_users_count',
        store=False
    )

    remaining_users = fields.Integer(
        string='Remaining Slots',
        compute='_compute_remaining_users',
        store=False
    )

    limit_reached = fields.Boolean(
        string='Limit Reached',
        compute='_compute_limit_reached',
        store=False
    )

    active = fields.Boolean(
        string='Active',
        default=True,
        readonly=True
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        readonly=True
    )

    @api.depends('name')
    def _compute_display_name(self):
        """حساب اسم العرض"""
        for rec in self:
            rec.display_name = f"{rec.name} ({rec.max_users} users)"

    @api.depends('max_users')
    def _compute_current_users_count(self):
        """حساب عدد المستخدمين الحاليين (بدون shared users)"""
        for rec in self:
            rec.current_users_count = self.env['res.users'].search_count([
                ('share', '=', False),  # مستخدمين داخليين فقط
                ('active', '=', True)
            ])

    @api.depends('max_users', 'current_users_count')
    def _compute_remaining_users(self):
        """حساب عدد المستخدمين المتبقية"""
        for rec in self:
            rec.remaining_users = max(0, rec.max_users - rec.current_users_count)

    @api.depends('current_users_count', 'max_users')
    def _compute_limit_reached(self):
        """التحقق من الوصول للحد الأقصى"""
        for rec in self:
            rec.limit_reached = rec.current_users_count >= rec.max_users

    @api.model_create_multi
    def create(self, vals_list):
        """
        منع إنشاء أكثر من سجل واحد
        Odoo 18 uses create_multi by default
        """
        existing = self.search([])
        if existing:
            raise ValidationError(_(
                'Only one User Limit Control record is allowed per database!\n'
                'Please update the existing record instead.'
            ))

        records = super().create(vals_list)

        for record in records:
            _logger.info(
                "✅ User Limit Control created: max_users=%s",
                record.max_users
            )

        return records

    def write(self, vals):
        """
        السماح بتحديث max_users فقط
        منع تعديل الحقول الأساسية
        """
        # منع تعديل بعض الحقول
        protected_fields = ['name', 'active', 'company_id']
        for field in protected_fields:
            if field in vals and field != 'max_users':
                vals.pop(field)
                _logger.warning(
                    "⚠️ Attempt to modify protected field '%s' blocked",
                    field
                )

        result = super().write(vals)

        if 'max_users' in vals:
            _logger.info(
                "✅ User limit updated to: %s",
                vals['max_users']
            )

        return result

    def unlink(self):
        """منع الحذف نهائياً"""
        raise ValidationError(_(
            '🚫 Cannot delete User Limit Control!\n\n'
            'This record is essential for database management and cannot be removed.\n'
            'If you need to change the user limit, please update the "Maximum Users" field instead.'
        ))

    @api.model
    def get_user_limit(self):
        """
        الحصول على الحد الأقصى للمستخدمين
        دالة مساعدة للاستخدام في أماكن أخرى
        """
        control = self.search([], limit=1)
        return control.max_users if control else 1

    @api.model
    def check_user_limit(self, raise_exception=True):
        """
        التحقق من عدم تجاوز الحد الأقصى

        Args:
            raise_exception (bool): رفع خطأ إذا تم تجاوز الحد

        Returns:
            bool: True إذا لم يتم تجاوز الحد، False خلاف ذلك
        """
        control = self.search([], limit=1)

        if not control:
            _logger.warning("⚠️ No user limit control found!")
            return True

        current_count = self.env['res.users'].search_count([
            ('share', '=', False),
            ('active', '=', True)
        ])

        if current_count >= control.max_users:
            if raise_exception:
                raise ValidationError(_(
                    '🚫 User Limit Reached!\n\n'
                    'Maximum users: %s\n'
                    'Current users: %s\n\n'
                    'Cannot create more internal users. '
                    'Please contact your administrator to increase the limit.'
                ) % (control.max_users, current_count))
            return False

        return True

    @api.model
    def update_limit_from_saas(self, new_limit):
        """
        تحديث الحد من نظام SaaS الرئيسي
        يتم استدعاؤها من saas.subscription

        Args:
            new_limit (int): الحد الجديد

        Returns:
            bool: True إذا تم التحديث بنجاح
        """
        control = self.search([], limit=1)

        if not control:
            # إنشاء سجل جديد إذا لم يكن موجوداً
            control = self.create({
                'name': 'User Limit Control',
                'max_users': new_limit
            })
            _logger.info("✅ User limit control created with limit: %s", new_limit)
        else:
            control.max_users = new_limit
            _logger.info("✅ User limit updated to: %s", new_limit)

        return True

    def action_view_users(self):
        """عرض المستخدمين الحاليين"""
        self.ensure_one()

        return {
            'name': _('Internal Users'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.users',
            'view_mode': 'list,form',
            'domain': [('share', '=', False), ('active', '=', True)],
            'context': {'create': False},  # منع الإنشاء من هذه الشاشة
        }