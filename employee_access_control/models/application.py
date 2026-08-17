import re

from odoo import api, fields, models


class EmployeeAccessApplication(models.Model):
    _name = "employee.access.application"
    _description = "Employee Access Application"
    _order = "sequence, name, id"
    _check_company_auto = True

    @api.model
    def _exclude_internal_employee_access_modules(self):
        applications = self.sudo().with_context(active_test=False).search(
            [
                ("name", "=", "Employee Access Control"),
                ("system_id.name", "in", ["Odoo Light", "Odoo Standard"]),
            ]
        )
        applications.write({"active": False})
        return True

    @api.model
    def _default_system_id(self):
        company_id = self.env.company.id
        return self.env["employee.access.system"].search(
            [
                ("company_id", "=", company_id),
                ("name", "=", "Odoo Light"),
            ],
            limit=1,
        ) or self.env["employee.access.system"].search(
            [("company_id", "=", company_id)],
            order="sequence asc, name asc",
            limit=1,
        )

    name = fields.Char(required=True)
    code = fields.Char()
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    system_id = fields.Many2one(
        "employee.access.system",
        string="System",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
        default=_default_system_id,
    )
    facility_ids = fields.Many2many(
        "employee.access.facility",
        "employee_access_application_facility_rel",
        "application_id",
        "facility_id",
        string="Facilities",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
    )
    description = fields.Text()
    url = fields.Char(string="URL")
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _company_code_uniq = models.Constraint(
        "unique(company_id, code)",
        "Application code must be unique per company.",
    )

    @api.depends("name", "system_id.name")
    def _compute_display_name(self):
        for application in self:
            if application.system_id:
                application.display_name = (
                    f"{application.name} ( {application.system_id.name} )"
                )
            else:
                application.display_name = application.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = self._generate_code(vals)
        return super().create(vals_list)

    def _generate_code(self, vals):
        name = (vals.get("name") or "application").strip().upper()
        base = re.sub(r"[^A-Z0-9]+", "_", name).strip("_") or "APPLICATION"
        base = base[:40]

        company_id = vals.get("company_id") or self.env.company.id
        candidate = base
        index = 2
        while self.search_count([("company_id", "=", company_id), ("code", "=", candidate)]):
            candidate = f"{base}_{index}"
            index += 1
        return candidate
