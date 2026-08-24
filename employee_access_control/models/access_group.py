import re

from odoo import api, fields, models


PRIVILEGED_ACCESS_GROUPS = [
    "Inventory Configuration",
    "Contact Creation",
    "Time off Configuration",
    "Planning Delete Permission",
    "Pin Code Permission",
    "Multi Companies",
    "Create Transfer Permission",
    "Product Creation",
    "Copy to PO Permission",
    "Approval Rule",
    "Extra Apps",
    "Health Claim Edit",
    "Post and Register Payment Permission",
    "Planning Configuration",
    "Multi Currencies",
    "Health Claim Config",
    "Reset to Draft Permission",
]

APPLICATION_ROLE_GROUPS = [
    ("HR", "Planning", "Odoo Light"),
    ("Manager", "Planning", "Odoo Light"),
    ("System Admin", "Planning", "Odoo Light"),
    ("User", "Planning", "Odoo Light"),
    ("User", "Registration Executive", "EHR"),
    ("User", "Registration Assistant", "EHR"),
    ("User", "Appointment Executive", "EHR"),
    ("User", "Appointment Assistant", "EHR"),
    ("User", "Nursing Supervisor", "EHR"),
    ("User", "Registered Nurse", "EHR"),
    ("User", "Healthcare Assistant", "EHR"),
    ("User", "Inventory Management & Control", "EHR"),
    ("User", "Inventory Controller", "EHR"),
    ("User", "Pharmacist", "EHR"),
    ("User", "Pharmacy Assistant", "EHR"),
    ("User", "Medical Technologist (Laboratory)", "EHR"),
    ("User", "Laboratory Technician", "EHR"),
    ("User", "Laboratory Assistant", "EHR"),
    ("User", "Phlebotomist", "EHR"),
    ("User", "Radiographer", "EHR"),
    ("User", "Imaging Technician", "EHR"),
    ("User", "Imaging Assistant", "EHR"),
    ("User", "Physiotherapist", "EHR"),
    ("User", "Physiotherapy Aide", "EHR"),
    ("User", "Accountant", "EHR"),
    ("User", "Billing Executive", "EHR"),
    ("User", "Biller", "EHR"),
    ("User", "Lab Biller", "EHR"),
    ("User", "Physician", "EHR"),
    ("User", "Physician Assistant", "EHR"),
    ("User", "Chart Note Data Entry Assistant", "EHR"),
    ("User", "Operation Manager", "EHR"),
    ("User", "Clinical Operation", "EHR"),
    ("User", "System Manager", "EHR"),
    ("HR", "Employees", "Odoo Light"),
    ("Manager", "Employees", "Odoo Light"),
    ("System Admin", "Employees", "Odoo Light"),
    ("User", "Employees", "Odoo Light"),
    ("HR", "Time Off", "Odoo Light"),
    ("Manager", "Time Off", "Odoo Light"),
    ("System Admin", "Time Off", "Odoo Light"),
    ("User", "Time Off", "Odoo Light"),
    ("Employee Manager", "Contracts", "Odoo Light"),
    ("System Admin", "Contracts", "Odoo Light"),
    ("HR", "Recruitment", "Odoo Light"),
    ("Manager", "Recruitment", "Odoo Light"),
    ("System Admin", "Recruitment", "Odoo Light"),
    ("All Approver", "Expenses", "Odoo Light"),
    ("System Admin", "Expenses", "Odoo Light"),
    ("Team Approver", "Expenses", "Odoo Light"),
    ("User", "Expenses", "Odoo Light"),
    ("HR", "Attendances", "Odoo Light"),
    ("Manager", "Attendances", "Odoo Light"),
    ("System Admin", "Attendances", "Odoo Light"),
    ("User", "Attendances", "Odoo Light"),
    ("Finance", "Health Claim", "Odoo Light"),
    ("HR", "Health Claim", "Odoo Light"),
    ("Manager", "Health Claim", "Odoo Light"),
    ("System Admin", "Health Claim", "Odoo Light"),
    ("User", "Health Claim", "Odoo Light"),
    ("User", "Phlebotomist", "LIMS"),
    ("User", "Lab Technician", "LIMS"),
    ("User", "Senior Lab Technician", "LIMS"),
    ("User", "Pathologist", "LIMS"),
    ("Administrator", "Approvals", "Odoo Standard"),
    ("User", "Approvals", "Odoo Standard"),
    ("HR", "Attendances", "Odoo Standard"),
    ("Manager", "Attendances", "Odoo Standard"),
    ("System Admin", "Attendances", "Odoo Standard"),
    ("User", "Attendances", "Odoo Standard"),
    ("Employee Manager", "Contracts", "Odoo Standard"),
    ("System Admin", "Contracts", "Odoo Standard"),
    ("Admin", "Dashboard", "Odoo Standard"),
    ("User", "Dashboard", "Odoo Standard"),
    ("HR", "Employees", "Odoo Standard"),
    ("Manager", "Employees", "Odoo Standard"),
    ("System Admin", "Employees", "Odoo Standard"),
    ("User", "Employees", "Odoo Standard"),
    ("All Approver", "Expenses", "Odoo Standard"),
    ("System Admin", "Expenses", "Odoo Standard"),
    ("Team Approver", "Expenses", "Odoo Standard"),
    ("User", "Expenses", "Odoo Standard"),
    ("Finance", "Health Claim", "Odoo Standard"),
    ("HR", "Health Claim", "Odoo Standard"),
    ("Manager", "Health Claim", "Odoo Standard"),
    ("System Admin", "Health Claim", "Odoo Standard"),
    ("User", "Health Claim", "Odoo Standard"),
    ("Administrator", "Helpdesk", "Odoo Standard"),
    ("User", "Helpdesk", "Odoo Standard"),
    ("Manager", "Sale Center", "Odoo Standard"),
    ("Read-Only Access", "Sale Center", "Odoo Standard"),
    ("Write Access", "Sale Center", "Odoo Standard"),
    ("System Admin", "Sales", "Odoo Standard"),
    ("User : All Documents", "Sales", "Odoo Standard"),
    ("User : Own Documents Only", "Sales", "Odoo Standard"),
    ("Accountant", "Accounting", "Odoo Standard"),
    ("Advance User", "Accounting", "Odoo Standard"),
    ("Billing", "Accounting", "Odoo Standard"),
    ("Bookkeeper", "Accounting", "Odoo Standard"),
    ("Read-only", "Accounting", "Odoo Standard"),
    ("System Admin", "Inventory", "Odoo Standard"),
    ("User", "Inventory", "Odoo Standard"),
    ("System Admin", "Manufacturing", "Odoo Standard"),
    ("User", "Manufacturing", "Odoo Standard"),
    ("Administrator", "Partner Access", "Odoo Standard"),
    ("User", "Partner Access", "Odoo Standard"),
    ("HR", "Planning", "Odoo Standard"),
    ("Manager", "Planning", "Odoo Standard"),
    ("System Admin", "Planning", "Odoo Standard"),
    ("User", "Planning", "Odoo Standard"),
    ("Administrator", "Product", "Odoo Standard"),
    ("User", "Product", "Odoo Standard"),
    ("User", "Purchase", "Odoo Standard"),
    ("Subcon User", "Purchase", "Odoo Standard"),
    ("Administrator", "Purchase", "Odoo Standard"),
    ("HR", "Recruitment", "Odoo Standard"),
    ("Manager", "Recruitment", "Odoo Standard"),
    ("System Admin", "Recruitment", "Odoo Standard"),
    ("Administrator", "Surveys", "Odoo Standard"),
    ("User", "Surveys", "Odoo Standard"),
    ("HR", "Time Off", "Odoo Standard"),
    ("Manager", "Time Off", "Odoo Standard"),
    ("System Admin", "Time Off", "Odoo Standard"),
    ("User", "Time Off", "Odoo Standard"),
]


class EmployeeAccessGroup(models.Model):
    _name = "employee.access.group"
    _description = "Employee Access Group"
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
    system_id = fields.Many2one(
        "employee.access.system",
        string="System",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
    )
    application_id = fields.Many2one(
        "employee.access.application",
        string="Application",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
        ondelete="restrict",
    )
    application_ids = fields.Many2many(
        "employee.access.application",
        "employee_access_group_application_rel",
        "access_group_id",
        "application_id",
        string="Applications",
        domain="[('company_id', '=', company_id), ('system_id', '=', system_id)]",
        check_company=True,
    )
    description = fields.Text()
    sequence = fields.Integer(default=10)
    default_role = fields.Boolean(string="Default Role")
    display_type = fields.Selection(
        [
            ("privileged_checkbox", "Checkbox (Privileged Access)"),
            ("application_role", "Selection (Application Role)"),
        ],
        required=True,
        default="application_role",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "company_code_uniq",
            "unique(company_id, code)",
            "Access group code must be unique per company.",
        ),
    ]

    @api.onchange("application_id")
    def _onchange_application_id(self):
        for record in self:
            if record.application_id:
                record.system_id = record.application_id.system_id

    @api.onchange("system_id")
    def _onchange_system_id(self):
        for record in self:
            if record.application_id and record.application_id.system_id != record.system_id:
                record.application_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("application_id") and not vals.get("system_id"):
                vals["system_id"] = self.env["employee.access.application"].browse(
                    vals["application_id"]
                ).system_id.id
            if not vals.get("code"):
                vals["code"] = self._generate_code(vals)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("application_id") and "system_id" not in vals:
            vals = dict(vals)
            vals["system_id"] = self.env["employee.access.application"].browse(
                vals["application_id"]
            ).system_id.id
        return super().write(vals)

    def _generate_code(self, vals):
        parts = [
            vals.get("display_type") or "group",
            vals.get("name") or "group",
        ]
        application = self.env["employee.access.application"].browse(
            vals.get("application_id")
        )
        if application:
            parts.extend([application.system_id.name, application.name])
        base = re.sub(r"[^A-Z0-9]+", "_", "_".join(parts).upper()).strip("_")
        company_id = vals.get("company_id") or self.env.company.id
        candidate = base
        index = 2
        while self.search_count([("company_id", "=", company_id), ("code", "=", candidate)]):
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    @api.model
    def _load_sample_groups(self):
        companies = self.env["res.company"].sudo().search([("active", "=", True)])
        for company in companies:
            self.with_company(company)._load_sample_groups_for_company(company)
        return True

    @api.model
    def _load_sample_groups_for_company(self, company):
        application_model = self.env["employee.access.application"].with_context(active_test=False)
        system_model = self.env["employee.access.system"].with_context(active_test=False)
        expected_codes = set()

        for name in PRIVILEGED_ACCESS_GROUPS:
            code = f"PRIVILEGED_{self._slug(name)}"
            expected_codes.add(code)
            self._upsert_sample_group(
                company,
                name,
                "privileged_checkbox",
                code,
            )

        for name, application_name, system_name in APPLICATION_ROLE_GROUPS:
            system = system_model.search(
                [("company_id", "=", company.id), ("name", "=", system_name)],
                limit=1,
            )
            application = application_model.search(
                [
                    ("company_id", "=", company.id),
                    ("name", "=", application_name),
                    ("system_id", "=", system.id),
                ],
                limit=1,
            )
            code = f"ROLE_{self._slug(system_name)}_{self._slug(application_name)}_{self._slug(name)}"
            expected_codes.add(code)
            self._upsert_sample_group(
                company,
                name,
                "application_role",
                code,
                application=application,
                system=system,
            )

        seeded_groups = self.with_context(active_test=False).search(
            [("company_id", "=", company.id), ("code", "like", "PRIVILEGED_%")]
        ) | self.with_context(active_test=False).search(
            [("company_id", "=", company.id), ("code", "like", "ROLE_%")]
        )
        seeded_groups.filtered(lambda group: group.code not in expected_codes).write(
            {"active": False}
        )
        return True

    @api.model
    def _upsert_sample_group(
        self,
        company,
        name,
        display_type,
        code,
        application=None,
        system=None,
    ):
        values = {
            "name": name,
            "code": code,
            "company_id": company.id,
            "application_id": application.id if application else False,
            "system_id": system.id if system else False,
            "sequence": 10,
            "default_role": False,
            "display_type": display_type,
            "active": True,
        }
        record = self.with_context(active_test=False).search(
            [("company_id", "=", company.id), ("code", "=", code)],
            limit=1,
        )
        if record:
            record.write(values)
        else:
            self.create(values)

    @api.model
    def _slug(self, value):
        return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
