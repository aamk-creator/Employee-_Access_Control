from odoo import fields, models


class EmployeeAccessSystemTag(models.Model):
    _name = "employee.access.system.tag"
    _description = "Employee Access System Tag"
    _order = "name, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    color = fields.Integer()
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)

    _company_name_uniq = models.Constraint(
        "unique(company_id, name)",
        "System tag name must be unique per company.",
    )
