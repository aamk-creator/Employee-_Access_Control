import re

from odoo import api, fields, models


ADDITIONAL_SEEDED_APPLICATIONS = [
    ("EHR", "Main Cashier (Treasury)"),
]


class EmployeeAccessApplication(models.Model):
    _name = "employee.access.application"
    _description = "Employee Access Application"
    _order = "sequence, name, id"
    _check_company_auto = True

    @api.model
    def _load_sample_applications(self):
        companies = self.env["res.company"].sudo().search([("active", "=", True)])
        for company in companies:
            self.with_company(company)._load_sample_applications_for_company(company)
        return True

    @api.model
    def _load_sample_applications_for_company(self, company):
        from .access_group import APPLICATION_ROLE_GROUPS

        system_model = self.env["employee.access.system"].sudo().with_context(
            active_test=False
        )
        application_model = self.sudo().with_context(active_test=False)
        system_names = ["Odoo Light", "Odoo Standard", "EHR", "LIMS"]
        systems_by_name = {}

        for sequence, system_name in enumerate(system_names, start=1):
            system = system_model.search(
                [("company_id", "=", company.id), ("name", "=", system_name)],
                limit=1,
            )
            if system:
                if not system.active:
                    system.active = True
            else:
                system_values = {
                    "name": system_name,
                    "company_id": company.id,
                    "sequence": sequence * 10,
                }
                if system_name == "Odoo Light":
                    system_values.update(
                        {"is_odoo_system": True, "user_type": "light"}
                    )
                elif system_name == "Odoo Standard":
                    system_values.update(
                        {"is_odoo_system": True, "user_type": "standard"}
                    )
                system = system_model.create(
                    system_values
                )
            systems_by_name[system_name] = system

        application_pairs = sorted(
            {
                (system_name, application_name)
                for _, application_name, system_name in APPLICATION_ROLE_GROUPS
            }
            | set(ADDITIONAL_SEEDED_APPLICATIONS),
            key=lambda item: (system_names.index(item[0]), item[1]),
        )
        for system_name, application_name in application_pairs:
            system = systems_by_name[system_name]
            application = application_model.search(
                [
                    ("company_id", "=", company.id),
                    ("system_id", "=", system.id),
                    ("name", "=", application_name),
                ],
                limit=1,
            )
            values = {
                "company_id": company.id,
                "system_id": system.id,
                "name": application_name,
                "active": True,
                "sequence": 10,
            }
            if application:
                application.write(values)
            else:
                application_model.create(values)

        return True

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

    _sql_constraints = [
        (
            "company_code_uniq",
            "unique(company_id, code)",
            "Application code must be unique per company.",
        ),
    ]

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
