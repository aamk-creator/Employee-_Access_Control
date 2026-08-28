from odoo import Command, api, fields, models
from odoo.exceptions import AccessError


class EmployeeAccessSystem(models.Model):
    _name = "employee.access.system"
    _description = "Employee Access System"
    _order = "sequence, name, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    image_1920 = fields.Image(
        string="Image",
        max_width=1920,
        max_height=1920,
    )
    code = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    facility_ids = fields.Many2many(
        "employee.access.facility",
        "employee_access_system_facility_rel",
        "system_id",
        "facility_id",
        string="Facilities",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
    )
    tag_ids = fields.Many2many(
        "employee.access.system.tag",
        "employee_access_system_tag_rel",
        "system_id",
        "tag_id",
        string="Tags",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
    )
    is_odoo_system = fields.Boolean(string="Is Odoo System")
    user_type = fields.Selection(
        [
            ("light", "Light User"),
            ("standard", "Standard User"),
        ],
        string="User Type",
    )
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
    )
    total_licensed_users = fields.Integer(
        string="Total Licensed Users",
        help="Total number of licensed users available for this system.",
    )
    request_approver_step_id = fields.Many2one(
        "employee.access.approval.step",
        string="Request Approver",
        domain="[('company_id', '=', company_id), ('approval_rule_id.model_name', '=', 'employee_access_control')]",
        check_company=True,
        ondelete="set null",
        help="Approval step whose assigned user approves requests for this system.",
    )
    handover_approver_step_id = fields.Many2one(
        "employee.access.approval.step",
        string="Handover Approver",
        domain="[('company_id', '=', company_id), ('approval_rule_id.model_name', '=', 'employee_access_control')]",
        check_company=True,
        ondelete="set null",
        help="Approval step whose assigned user completes the vendor handover.",
    )
    mail_recipient_ids = fields.Many2many(
        "res.partner",
        "employee_access_system_mail_recipient_rel",
        "system_id",
        "partner_id",
        string="Legacy Recipients",
        help="Legacy vendor email recipients kept for existing configurations.",
    )
    recipient_employee_ids = fields.Many2many(
        "hr.employee",
        "employee_access_system_recipient_employee_rel",
        "system_id",
        "employee_id",
        string="Legacy Employee Recipients",
        help="Legacy employee recipients kept for existing configurations.",
    )
    recipient_user_ids = fields.Many2many(
        "res.users",
        "employee_access_system_recipient_user_rel",
        "system_id",
        "user_id",
        string="Recipients",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        help="Odoo users that receive provisioning emails for this system.",
    )
    vendor_ticket_email = fields.Char(
        string="Vendor Site Ticket Email",
        help=(
            "Email address used by the vendor support portal to create a ticket. "
            "For example: support@vendor.example.com."
        ),
    )
    vendor_portal_url = fields.Char(
        string="Vendor Portal URL",
        help="Optional vendor support portal URL used for reference.",
    )
    description = fields.Text()
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        (
            "company_code_uniq",
            "unique(company_id, code)",
            "System code must be unique per company.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = self._generate_code(vals)
        return super().create(vals_list)

    def _generate_code(self, vals):
        company_id = vals.get("company_id") or self.env.company.id
        base = (vals.get("name") or "System").upper()
        base = "".join(char if char.isalnum() else "_" for char in base)
        base = "_".join(part for part in base.split("_") if part) or "SYSTEM"
        candidate = base[:40]
        index = 2
        while self.search_count([("company_id", "=", company_id), ("code", "=", candidate)]):
            suffix = f"_{index}"
            candidate = f"{base[:40 - len(suffix)]}{suffix}"
            index += 1
        return candidate

    @api.model
    def _configure_odoo_systems(self):
        """Apply the Odoo-system defaults after approval rules are available."""
        companies = self.env["res.company"].sudo().search([("active", "=", True)])
        system_model = self.sudo().with_context(active_test=False)
        tag_model = self.env["employee.access.system.tag"].sudo().with_context(
            active_test=False
        )
        rule_model = self.env["employee.access.approval.rule"].sudo().with_context(
            active_test=False
        )
        system_defaults = {
            "Odoo Light": {
                "user_type": "light",
                "tag_name": "Light Users",
                "request_step_name": "HRMS Admin(Light)",
            },
            "Odoo Standard": {
                "user_type": "standard",
                "tag_name": "Standard Users",
                "request_step_name": "ERP Admin (Standard)",
            },
        }

        for company in companies:
            approval_rule = rule_model.search(
                [
                    ("company_id", "=", company.id),
                    ("model_name", "=", "employee_access_control"),
                    ("active", "=", True),
                ],
                order="sequence, id",
                limit=1,
            )
            if not approval_rule:
                continue
            for system_name, defaults in system_defaults.items():
                system = system_model.search(
                    [
                        ("company_id", "=", company.id),
                        ("name", "=", system_name),
                    ],
                    limit=1,
                )
                if not system:
                    continue
                tag = tag_model.search(
                    [
                        ("company_id", "=", company.id),
                        ("name", "=", defaults["tag_name"]),
                    ],
                    limit=1,
                )
                if tag:
                    if not tag.active:
                        tag.active = True
                else:
                    tag = tag_model.create(
                        {
                            "company_id": company.id,
                            "name": defaults["tag_name"],
                        }
                    )
                request_step = approval_rule.approval_step_ids.filtered(
                    lambda step, step_name=defaults["request_step_name"]: (
                        step.name == step_name
                    )
                )[:1]
                values = {
                    "is_odoo_system": True,
                    "user_type": defaults["user_type"],
                    "tag_ids": [Command.link(tag.id)],
                }
                if request_step:
                    values["request_approver_step_id"] = request_step.id
                system.write(values)

        return True

    @api.model
    def _remove_seeded_handover_approvers(self):
        """Remove the former automatic Mark Done value once, preserving later choices."""
        parameter = self.env["ir.config_parameter"].sudo()
        migration_key = (
            "employee_access_control.handover_approver_default_removed_v9_2"
        )
        if parameter.get_param(migration_key):
            return True

        systems = self.sudo().with_context(active_test=False).search(
            [
                ("name", "in", ["Odoo Light", "Odoo Standard"]),
                ("handover_approver_step_id.name", "=", "Mark Done"),
            ]
        )
        systems.write({"handover_approver_step_id": False})
        parameter.set_param(migration_key, "1")
        return True

    @api.model
    def get_dashboard_data(self):
        system_names = ["Odoo Light", "Odoo Standard"]
        systems = self.search(
            [
                ("name", "in", system_names),
                ("company_id", "=", self.env.company.id),
            ]
        )
        systems_by_name = {system.name: system for system in systems}
        Users = self.env["res.users"].sudo()
        dashboard_rows = []

        for system_name in system_names:
            system = systems_by_name.get(system_name)
            user_domain = [
                ("share", "=", False),
                ("login", "not in", ["__system__", "__export__"]),
                ("company_ids", "in", [self.env.company.id]),
                ("employee_access_user_type", "=", system.user_type),
            ] if system else []
            active_users = (
                Users.search_count(user_domain + [("active", "=", True)])
                if system
                else 0
            )
            inactive_users = (
                Users.with_context(active_test=False).search_count(
                    user_domain + [("active", "=", False)]
                )
                if system
                else 0
            )
            licensed_users = system.total_licensed_users if system else 0
            utilization_percent = (
                round(active_users * 100 / licensed_users) if licensed_users else 0
            )
            dashboard_rows.append(
                {
                    "id": system.id if system else False,
                    "name": system_name,
                    "company_id": system.company_id.id if system else False,
                    "user_type": system.user_type if system else False,
                    "licensed_users": licensed_users,
                    "need_purchase_users": max(active_users - licensed_users, 0),
                    "active_users": active_users,
                    "swap_users": max(licensed_users - active_users, 0),
                    "inactive_users": inactive_users,
                    "utilization_percent": utilization_percent,
                    "utilization_bar_percent": min(utilization_percent, 100),
                }
            )

        return dashboard_rows

    @api.model
    def get_odoo_users_action(self, system_id, status="active"):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(
                "Only an Odoo Settings administrator can manage user accounts."
            )

        system = self.browse(system_id).exists()
        if not system or not system.is_odoo_system:
            raise AccessError("Select a valid Odoo system.")
        if system.company_id not in self.env.user.company_ids:
            raise AccessError("You cannot manage users for this company.")

        domain = [
            ("share", "=", False),
            ("login", "not in", ["__system__", "__export__"]),
            ("company_ids", "in", [system.company_id.id]),
            ("employee_access_user_type", "=", system.user_type),
        ]
        context = {
            "search_default_filter_no_share": 1,
            "show_user_group_warning": True,
        }
        if status == "inactive":
            domain.append(("active", "=", False))
            context.update({"active_test": False, "search_default_Inactive": 1})
        else:
            domain.append(("active", "=", True))

        action = self.env["ir.actions.actions"]._for_xml_id("base.action_res_users")
        action.update(
            {
                "name": f"{system.name} {'Inactive' if status == 'inactive' else 'Active'} Users",
                "domain": domain,
                "context": context,
                "target": "current",
            }
        )
        return action
