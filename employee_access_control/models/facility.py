from odoo import fields, models


class EmployeeAccessFacility(models.Model):
    _name = "employee.access.facility"
    _description = "Employee Access Facility"
    _order = "sequence, name, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    address = fields.Text()
    description = fields.Text()
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _company_code_uniq = models.Constraint(
        "unique(company_id, code)",
        "Facility code must be unique per company.",
    )
