from odoo import fields, models


class EmployeeAccessHeaderCompany(models.Model):
    _name = "employee.access.header.company"
    _description = "Employee Access Header Company"
    _order = "sequence, id"
    _rec_name = "company_id"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        (
            "company_uniq",
            "unique(company_id)",
            "A company can only appear once in the header company list.",
        ),
    ]

