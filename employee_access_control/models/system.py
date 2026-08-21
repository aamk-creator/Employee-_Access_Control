from odoo import api, fields, models


class EmployeeAccessSystem(models.Model):
    _name = "employee.access.system"
    _description = "Employee Access System"
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
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
    )
    total_licensed_users = fields.Integer(
        string="Total Licensed Users",
        help="Total number of licensed users available for this system.",
    )
    mail_recipient_ids = fields.Many2many(
        "res.partner",
        "employee_access_system_mail_recipient_rel",
        "system_id",
        "partner_id",
        string="Vendor Recipients",
        help="Vendor site email recipients that receive provisioning emails.",
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

    _company_code_uniq = models.Constraint(
        "unique(company_id, code)",
        "System code must be unique per company.",
    )

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
    def get_dashboard_data(self):
        system_names = ["Odoo Light", "Odoo Standard"]
        systems = self.search(
            [
                ("name", "in", system_names),
                ("company_id", "=", self.env.company.id),
            ]
        )
        systems_by_name = {system.name: system for system in systems}
        Request = self.env["employee.access.request"]
        dashboard_rows = []

        for system_name in system_names:
            system = systems_by_name.get(system_name)
            active_users = (
                Request.search_count(
                    [("system_id", "=", system.id), ("state", "=", "active")]
                )
                if system
                else 0
            )
            inactive_users = (
                Request.search_count(
                    [("system_id", "=", system.id), ("state", "=", "inactive")]
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
