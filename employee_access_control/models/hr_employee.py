from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    employee_access_fingerprint_id = fields.Char(
        string="Fingerprint ID",
        index=True,
        copy=False,
        help="Fingerprint identifier used when requesting system access.",
    )
