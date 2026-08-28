from markupsafe import Markup, escape

from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError


class EmployeeAccessRequest(models.Model):
    _name = "employee.access.request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Employee Access Request"
    _order = "request_date desc, id desc"
    _check_company_auto = True
    _rec_name = "employee_display_name"

    @api.model
    def _default_system_id(self):
        return self.env["employee.access.system"].search(
            [],
            order="sequence asc, name asc",
            limit=1,
        )

    @api.model
    def _applications_for_system(self, system):
        if not system:
            return self.env["employee.access.application"]
        return self.env["employee.access.application"].search(
            [("system_id", "=", system.id), ("active", "=", True)],
            order="sequence asc, name asc",
        )

    @api.model
    def _default_application_ids(self):
        return self._applications_for_system(self._default_system_id())

    @api.model
    def _application_line_commands(self, system, profile=None):
        same_system_profile = bool(profile and profile.system_id == system)
        existing_application_ids = set(profile.application_ids.ids) if profile else set()
        existing_application_names = (
            {
                (application.name or "").strip().casefold()
                for application in profile.application_ids
            }
            if profile
            else set()
        )
        previous_lines_by_application = {}
        if profile and profile.last_request_id:
            previous_lines_by_application = {
                (
                    line.application_id.id
                    if same_system_profile
                    else (line.application_id.name or "").strip().casefold()
                ): line
                for line in profile.last_request_id.application_line_ids
                if not line.remove_access
            }

        commands = []
        for application in self._applications_for_system(system):
            application_name = (application.name or "").strip().casefold()
            has_existing_application = bool(
                profile
                and (
                    application.id in existing_application_ids
                    if same_system_profile
                    else application_name in existing_application_names
                )
            )
            previous_line = previous_lines_by_application.get(
                application.id if same_system_profile else application_name
            )
            access_group = self._existing_or_default_access_group(
                application,
                previous_line,
                use_default=not profile or has_existing_application,
            )
            commands.append(
                Command.create(
                    {
                        "application_id": application.id,
                        "access_group_id": access_group.id,
                        "remove_access": bool(profile and not has_existing_application),
                    }
                )
            )
        return commands

    @api.model
    def _existing_or_default_access_group(
        self, application, previous_line, use_default=True
    ):
        previous_group = (
            previous_line.access_group_id
            if previous_line
            else self.env["employee.access.group"]
        )
        if (
            previous_group
            and previous_group.active
            and previous_group.application_id == application
            and previous_group.display_type == "application_role"
        ):
            return previous_group
        if previous_group and previous_group.display_type == "application_role":
            matching_group = self.env["employee.access.group"].search(
                [
                    ("application_id", "=", application.id),
                    ("name", "=ilike", previous_group.name),
                    ("display_type", "=", "application_role"),
                    ("active", "=", True),
                ],
                order="sequence, id",
                limit=1,
            )
            if matching_group:
                return matching_group
        return self._default_access_group(application) if use_default else previous_group

    @api.model
    def _default_access_group(self, application):
        groups = self.env["employee.access.group"].search(
            [
                ("application_id", "=", application.id),
                ("display_type", "=", "application_role"),
                ("active", "=", True),
            ],
            order="default_role desc, sequence, name, id",
        )
        return groups.filtered("default_role")[:1] or groups.filtered(
            lambda group: group.name.strip().lower() == "user"
        )[:1]

    @api.model
    def _default_application_line_ids(self):
        return self._application_line_commands(self._default_system_id())

    @api.model
    def get_system_overview_matrix(self, options=None):
        """Return the read-only, dynamic application/role matrix for the overview."""
        options = options or {}
        system_id = int(options.get("system_id") or 0)
        status = options.get("status")
        query = (options.get("query") or "").strip()

        systems = self.env["employee.access.system"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("name", "in", ["Odoo Light", "Odoo Standard"]),
                ("active", "=", True),
            ],
            order="sequence, name, id",
        )
        if system_id not in systems.ids:
            system_id = 0

        selected_systems = systems.filtered(lambda item: item.id == system_id) or systems
        applications = self.env["employee.access.application"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("system_id", "in", selected_systems.ids),
                ("active", "=", True),
            ],
            order="sequence, name, id",
        )

        # Light and Standard commonly contain applications with the same name. They
        # share one visual column; each row still gets the role from its own system.
        headers = []
        header_names = set()
        for application in applications:
            key = (application.name or "").strip().casefold()
            if key and key not in header_names:
                header_names.add(key)
                headers.append({"key": key, "name": application.name})

        domain = [
            ("state", "in", ["active", "inactive"]),
            ("system_id", "in", selected_systems.ids),
        ]
        if status in ("active", "inactive"):
            domain.append(("state", "=", status))
        if query:
            domain += [
                "|",
                "|",
                ("overview_employee_display_name", "ilike", query),
                ("access_company_ids.name", "ilike", query),
                ("system_id.name", "ilike", query),
            ]

        requests = self.search(domain, order="overview_employee_display_name, system_id, id")
        rows = []
        for request in requests:
            roles = {}
            included_lines = request.application_line_ids.filtered(
                lambda line: not line.remove_access
            ).sorted(lambda line: (line.sequence, line.application_id.name or "", line.id))
            for line in included_lines:
                key = (line.application_id.name or "").strip().casefold()
                if key:
                    roles[key] = line.access_group_id.name or "Not Assigned"
            rows.append(
                {
                    "id": request.id,
                    "employee": request.overview_employee_display_name,
                    "access_companies": ", ".join(request.access_company_ids.mapped("name")),
                    "access_company_names": request.access_company_ids.mapped("name"),
                    "system": request.system_id.name,
                    "status": request.access_status,
                    "roles": roles,
                }
            )

        return {
            "systems": [{"id": system.id, "name": system.name} for system in systems],
            "headers": headers,
            "rows": rows,
        }

    @api.model
    def _normalize_application_line_commands(self, commands, system):
        normalized_commands = []
        pending_create_indexes = []
        used_application_ids = set()
        for command in commands:
            if not isinstance(command, (list, tuple)) or len(command) < 3:
                normalized_commands.append(command)
                continue
            operation, record_id, command_values = command
            if operation != Command.CREATE or not isinstance(command_values, dict):
                normalized_commands.append(command)
                continue
            values = dict(command_values)
            application_id = values.get("application_id")
            access_group_value = values.get("access_group_id")
            if isinstance(access_group_value, dict):
                access_group_id = access_group_value.get("id")
            elif isinstance(access_group_value, (list, tuple)):
                access_group_id = access_group_value[0] if access_group_value else False
            else:
                access_group_id = access_group_value
            if not application_id and access_group_id:
                access_group = self.env["employee.access.group"].browse(access_group_id)
                application_id = access_group.application_id.id
                values["application_id"] = application_id
            if application_id:
                used_application_ids.add(application_id)
            else:
                pending_create_indexes.append(len(normalized_commands))
            normalized_commands.append((operation, record_id, values))

        remaining_applications = self._applications_for_system(system).filtered(
            lambda application: application.id not in used_application_ids
        )
        if len(pending_create_indexes) == len(remaining_applications):
            for command_index, application in zip(
                pending_create_indexes,
                remaining_applications,
            ):
                operation, record_id, values = normalized_commands[command_index]
                normalized_commands[command_index] = (
                    operation,
                    record_id,
                    {**values, "application_id": application.id},
                )
        return normalized_commands

    reference = fields.Char(
        required=True,
        copy=False,
        default=lambda self: self.env["ir.sequence"].next_by_code("employee.access.request") or "New",
    )
    employee_name = fields.Char(string="Employee Name Snapshot", required=True)
    employee_source = fields.Selection(
        [
            ("employee", "Employees Module"),
        ],
        string="Employee Source",
        required=True,
        default="employee",
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee Name",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
        tracking=True,
        ondelete="restrict",
    )
    requested_user_id = fields.Many2one(
        "res.users",
        string="Odoo User",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        tracking=True,
    )
    employee_display_name = fields.Char(
        string="Employee Display Name",
        compute="_compute_employee_display_name",
        store=True,
        index=True,
    )
    overview_employee_display_name = fields.Char(
        string="Employee",
        compute="_compute_overview_employee_display_name",
        store=True,
        index=True,
    )
    fingerprint_id = fields.Char(string="Fingerprint ID")
    employee_email = fields.Char(string="Employee Email")
    department = fields.Char()
    position = fields.Char()
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    profile_id = fields.Many2one(
        "employee.access.profile",
        string="Access Profile",
        readonly=True,
        ondelete="set null",
    )
    request_date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    system_id = fields.Many2one(
        "employee.access.system",
        string="System",
        required=True,
        default=_default_system_id,
    )
    request_type = fields.Selection(
        [
            ("create", "Create"),
            ("update", "Update"),
        ],
        required=True,
        default="create",
    )
    access_company_ids = fields.Many2many(
        "res.company",
        "employee_access_request_company_rel",
        "request_id",
        "company_id",
        string="Access Companies",
    )
    access_facility_ids = fields.Many2many(
        "employee.access.facility",
        "employee_access_request_facility_rel",
        "request_id",
        "facility_id",
        string="Access Facilities",
        domain="[('company_id', 'in', access_company_ids), ('active', '=', True)]",
    )
    application_line_ids = fields.One2many(
        "employee.access.request.application.line",
        "request_id",
        string="Application Access",
        default=_default_application_line_ids,
        copy=True,
    )
    application_ids = fields.Many2many(
        "employee.access.application",
        "employee_access_request_application_rel",
        "request_id",
        "application_id",
        string="Included Applications",
        domain="[('system_id', '=', system_id), ('active', '=', True)]",
        compute="_compute_application_ids",
        store=True,
    )
    application_count = fields.Integer(
        string="Selected Modules",
        compute="_compute_application_count",
    )
    overview_application_names = fields.Char(
        string="Application Modules",
        compute="_compute_overview_access_details",
        store=True,
        readonly=True,
    )
    overview_access_role_names = fields.Char(
        string="Access Roles",
        compute="_compute_overview_access_details",
        store=True,
        readonly=True,
    )
    required_privileged_access = fields.Boolean(string="Required Privileged Access")
    manager_approver_id = fields.Many2one(
        "res.users",
        string="ERP Admin Approver",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        tracking=True,
    )
    credential_approver_id = fields.Many2one(
        "res.users",
        string="Legacy Credential Management Approver",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        tracking=True,
    )
    mark_done_user_id = fields.Many2one(
        "res.users",
        string="Mark Done User",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        tracking=True,
        help=(
            "The assigned login user who can finish the request after the vendor "
            "email is sent. Employee Access and system administrators can also finish it."
        ),
    )
    state = fields.Selection(
        [
            ("draft", "To Approve"),
            ("to_approve", "Submitted for Approval"),
            ("credential_approval", "Credential Management Approval"),
            ("approved", "Approved"),
            ("provisioning", "Waiting for Vendor"),
            ("active", "Done"),
            ("inactive", "Inactive"),
            ("rejected", "Rejected"),
        ],
        required=True,
        default="draft",
        tracking=True,
    )
    overview_name = fields.Char(
        string="Name",
        related="system_id.name",
        store=True,
        readonly=True,
    )
    access_status = fields.Selection(
        [
            ("active", "Active"),
            ("inactive", "Inactive"),
        ],
        string="Account Status",
        compute="_compute_system_overview_fields",
        store=True,
        readonly=True,
    )
    active_date = fields.Date(
        string="Active Date",
        compute="_compute_system_overview_fields",
        store=True,
        readonly=True,
    )
    inactive_date = fields.Date(string="Inactive Date", readonly=True, tracking=True)
    workflow_status_label = fields.Char(
        compute="_compute_workflow_status_label",
        string="Current Approval Status",
    )
    list_status_label = fields.Char(
        compute="_compute_list_status_labels",
        string="Status",
    )
    approval_status_label = fields.Char(
        compute="_compute_list_status_labels",
        string="Approval Status",
    )
    approval_line_ids = fields.One2many(
        "employee.access.request.approval.line",
        "request_id",
        string="Approvers",
        copy=False,
    )
    approval_rule_id = fields.Many2one(
        "employee.access.approval.rule",
        string="Approval Rule",
        compute="_compute_approval_configuration",
    )
    requires_erp_admin_approval = fields.Boolean(
        string="ERP Admin (Standard)",
        compute="_compute_approval_configuration",
    )
    requires_hrms_admin_approval = fields.Boolean(
        string="HRMS Admin (Light)",
        compute="_compute_approval_configuration",
    )
    note = fields.Text(string="Request Notes")
    has_existing_active_access = fields.Boolean(
        compute="_compute_existing_access_status",
        string="Has Existing Active Access",
    )
    duplicate_create_blocked = fields.Boolean(
        compute="_compute_existing_access_status",
        string="Duplicate Create Blocked",
    )
    existing_access_message = fields.Char(
        compute="_compute_existing_access_status",
        string="Existing Access Message",
    )
    provisioning_task_ids = fields.One2many(
        "employee.access.provision.task",
        "request_id",
        string="Provisioning Tasks",
    )
    audit_log_ids = fields.One2many(
        "employee.access.audit.log",
        "request_id",
        string="Audit History",
    )
    provisioning_task_count = fields.Integer(
        compute="_compute_provisioning_task_count",
        string="Provisioning Task Count",
    )

    @api.depends(
        "application_line_ids.application_id",
        "application_line_ids.remove_access",
    )
    def _compute_application_ids(self):
        for request in self:
            request.application_ids = request.application_line_ids.filtered(
                lambda line: not line.remove_access
            ).mapped("application_id")

    @api.depends("application_ids")
    def _compute_application_count(self):
        for request in self:
            request.application_count = len(request.application_ids)

    @api.depends(
        "application_line_ids.application_id.name",
        "application_line_ids.access_group_id.name",
        "application_line_ids.remove_access",
        "application_line_ids.sequence",
    )
    def _compute_overview_access_details(self):
        for request in self:
            included_lines = request.application_line_ids.filtered(
                lambda line: not line.remove_access
            ).sorted(lambda line: (line.sequence, line.application_id.name or ""))
            request.overview_application_names = ", ".join(
                included_lines.mapped("application_id.name")
            )
            request.overview_access_role_names = ", ".join(
                line.access_group_id.name or "No Role" for line in included_lines
            )

    @api.depends("state", "system_id.name")
    def _compute_workflow_status_label(self):
        for request in self:
            labels = {
                "draft": "To Approve",
                "to_approve": f"Waiting {request._system_approver_label()} Approval",
                "credential_approval": "Waiting Credential Management Approval",
                "approved": "All Approved",
                "provisioning": "Waiting for Vendor",
                "active": "Done",
                "inactive": "Inactive",
                "rejected": "Rejected",
            }
            request.workflow_status_label = labels.get(request.state, "")

    @api.depends("state", "system_id.name")
    def _compute_list_status_labels(self):
        status_labels = {
            "draft": "To Approve",
            "to_approve": "Submitted for Approval",
            "credential_approval": "Submitted for Approval",
            "approved": "Waiting for Vendor",
            "provisioning": "Waiting for Vendor",
            "active": "Done",
            "inactive": "Inactive",
            "rejected": "Rejected",
        }
        for request in self:
            approval_labels = {
                "draft": "To Approve",
                "to_approve": f"Waiting {request._system_approver_label()} Approval",
                "credential_approval": "Waiting Credential Management Approval",
                "approved": "All Approved",
                "provisioning": "All Approved",
                "active": "All Approved",
                "inactive": "All Approved",
                "rejected": "Rejected",
            }
            request.list_status_label = status_labels.get(request.state, "")
            request.approval_status_label = approval_labels.get(request.state, "")

    @api.depends("company_id", "system_id")
    def _compute_approval_configuration(self):
        for request in self:
            request.approval_rule_id = (
                request._get_access_approval_rule()
                if request.company_id
                else False
            )
            request.requires_erp_admin_approval = (
                request.system_id.name == "Odoo Standard"
            )
            request.requires_hrms_admin_approval = (
                request.system_id.name == "Odoo Light"
            )

    @api.depends(
        "employee_id.user_id",
        "employee_name",
        "employee_email",
        "fingerprint_id",
        "requested_user_id",
        "company_id",
        "system_id",
    )
    def _compute_existing_access_status(self):
        for request in self:
            profile = request._find_existing_active_profile()
            has_existing_access = request._has_existing_active_access(profile)
            request.has_existing_active_access = has_existing_access
            request.duplicate_create_blocked = has_existing_access
            if not has_existing_access:
                request.existing_access_message = False
            else:
                request.existing_access_message = (
                    f"Active access already exists for {request.system_id.name}. "
                    "Use Update for changes."
                )
            if request.duplicate_create_blocked:
                request.request_type = "update"

    @api.depends("provisioning_task_ids")
    def _compute_provisioning_task_count(self):
        for request in self:
            request.provisioning_task_count = len(request.provisioning_task_ids)

    @api.depends("employee_id.name", "employee_name")
    def _compute_employee_display_name(self):
        for request in self:
            request.employee_display_name = request.employee_id.name or request.employee_name

    @api.depends(
        "employee_id.name",
        "employee_id.company_id.name",
        "employee_name",
        "company_id.name",
    )
    def _compute_overview_employee_display_name(self):
        for request in self:
            employee_name = request.employee_id.name or request.employee_name or ""
            company_name = (
                request.employee_id.company_id.name
                if request.employee_id and request.employee_id.company_id
                else request.company_id.name
            )
            request.overview_employee_display_name = (
                f"{employee_name} ({company_name})"
                if employee_name and company_name
                else employee_name
            )

    @api.depends("state", "request_date", "provisioning_task_ids.completed_on")
    def _compute_system_overview_fields(self):
        for request in self:
            request.access_status = (
                request.state if request.state in ("active", "inactive") else False
            )
            completed_tasks = request.provisioning_task_ids.filtered("completed_on")
            latest_task = completed_tasks.sorted("completed_on", reverse=True)[:1]
            request.active_date = (
                fields.Date.to_date(latest_task.completed_on)
                if latest_task
                else request.request_date
                if request.state in ("active", "inactive")
                else False
            )

    @api.onchange("system_id")
    def _onchange_system_id(self):
        for request in self:
            profile = request._find_existing_active_profile()
            request.application_line_ids = [
                Command.clear(),
                *self._application_line_commands(request.system_id, profile=profile),
            ]
            if request.system_id:
                request.manager_approver_id = (
                    request._get_erp_admin_approver()
                    or request._fallback_approval_user()
                )
                request.mark_done_user_id = (
                    request._get_mark_done_user()
                    or request._fallback_approval_user()
                )
            request._prefill_existing_active_access(profile=profile, include_applications=False)

    def _employee_snapshot_values(self, employee):
        return {
            "employee_source": "employee",
            "employee_name": employee.name,
            "employee_email": employee.work_email or False,
            "fingerprint_id": employee.employee_access_fingerprint_id or False,
            "department": employee.department_id.name or False,
            "position": employee.job_id.name or employee.job_title or False,
            "company_id": employee.company_id.id,
            "requested_user_id": employee.user_id.id or False,
        }

    @api.model
    def _get_or_create_employee_from_legacy_values(self, vals):
        """Convert old API/import payloads into an Employees-module record."""
        Employee = self.env["hr.employee"].sudo().with_context(active_test=False)
        company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
        user = self.env["res.users"].browse(vals.get("requested_user_id"))
        email = vals.get("employee_email") or (user.email if user else False)
        name = vals.get("employee_name") or (user.name if user else False)
        fingerprint = vals.get("fingerprint_id") or (
            user.employee_access_fingerprint_id if user else False
        )
        department_name = vals.get("department") or (
            user.employee_access_department if user else False
        )
        position = vals.get("position") or (
            user.employee_access_position if user else False
        )
        domain = [("company_id", "=", company.id)]
        if user:
            domain.append(("user_id", "=", user.id))
        elif email:
            domain.append(("work_email", "=ilike", email))
        elif name:
            domain.append(("name", "=", name))
        else:
            raise ValidationError("Select an Employee from the Employees module.")
        employee = Employee.search(domain, order="id", limit=1)
        if employee:
            return employee
        department = self.env["hr.department"]
        if department_name:
            department = self.env["hr.department"].sudo().search(
                [("name", "=", department_name), ("company_id", "in", [False, company.id])],
                limit=1,
            )
        employee = Employee.create(
            {
                "name": name,
                "work_email": email or False,
                "company_id": company.id,
                "user_id": user.id or False,
                "department_id": department.id or False,
                "job_title": position or False,
                "employee_access_fingerprint_id": fingerprint or False,
            }
        )
        return employee

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for request in self:
            if request.employee_id:
                for field_name, value in request._employee_snapshot_values(
                    request.employee_id
                ).items():
                    setattr(request, field_name, value)
                request._prefill_existing_active_access(
                    profile=request._find_existing_active_profile_any_system(),
                    sync_system=True,
                )

    @api.onchange("access_company_ids")
    def _onchange_access_company_ids(self):
        for request in self:
            selected_company_ids = set(request.access_company_ids.ids)
            request.access_facility_ids = request.access_facility_ids.filtered(
                lambda facility: facility.company_id.id in selected_company_ids
            )

    @api.model_create_multi
    def create(self, vals_list):
        default_system = self._default_system_id()
        for vals in vals_list:
            employee = self.env["hr.employee"].browse(vals.get("employee_id"))
            if not employee:
                employee = self._get_or_create_employee_from_legacy_values(vals)
                vals["employee_id"] = employee.id
            vals.update(self._employee_snapshot_values(employee))
            if "application_line_ids" not in vals:
                system = self.env["employee.access.system"].browse(
                    vals.get("system_id")
                ) or default_system
                vals["application_line_ids"] = self._application_line_commands(system)
            else:
                system = self.env["employee.access.system"].browse(
                    vals.get("system_id")
                ) or default_system
                vals["application_line_ids"] = self._normalize_application_line_commands(
                    vals["application_line_ids"],
                    system,
                )
        records = super().create(vals_list)
        records._normalize_request_type_from_existing_access()
        for record in records:
            record._initialize_draft_approvers()
            record._subscribe_related_users()
            record._log_event("draft", "Employee access request created.")
        return records

    def write(self, vals):
        vals = dict(vals)
        if "employee_id" in vals:
            employee = self.env["hr.employee"].browse(vals["employee_id"])
            if not employee:
                raise ValidationError("Select an Employee from the Employees module.")
            vals.update(self._employee_snapshot_values(employee))
        if "system_id" in vals and "application_line_ids" not in vals:
            system = self.env["employee.access.system"].browse(vals["system_id"])
            vals["application_line_ids"] = [
                Command.clear(),
                *self._application_line_commands(system),
            ]
        elif "application_line_ids" in vals and len(self) == 1:
            vals = dict(vals)
            system = self.env["employee.access.system"].browse(
                vals.get("system_id")
            ) or self.system_id
            vals["application_line_ids"] = self._normalize_application_line_commands(
                vals["application_line_ids"],
                system,
            )
        result = super().write(vals)
        self._normalize_request_type_from_existing_access()
        if "system_id" in vals:
            for request in self.filtered(lambda item: item.state == "draft"):
                request._initialize_draft_approvers(force_system_approver=True)
        if "employee_id" in vals or "requested_user_id" in vals or "employee_email" in vals:
            self._subscribe_related_users()
        return result

    @api.constrains("employee_id")
    def _check_employee_source(self):
        for request in self:
            if not request.employee_id:
                raise ValidationError("Select an Employee from the Employees module.")

    @api.constrains("access_company_ids", "access_facility_ids")
    def _check_access_facility_companies(self):
        for request in self:
            invalid_facilities = request.access_facility_ids.filtered(
                lambda facility: facility.company_id not in request.access_company_ids
            )
            if invalid_facilities:
                raise ValidationError(
                    "Every access facility must belong to a selected access company."
                )

    @api.constrains("system_id", "application_line_ids")
    def _check_application_system(self):
        for request in self:
            incompatible = request.application_line_ids.filtered(
                lambda line: line.application_id.system_id != request.system_id
            )
            if incompatible:
                raise ValidationError(
                    "Every application module must belong to the selected system."
                )

    def init(self):
        self.env.cr.execute(
            """
            UPDATE employee_access_request
               SET employee_source = 'employee'
             WHERE employee_source IS NULL OR employee_source != 'employee'
            """
        )

    @api.model
    def _normalize_employee_sources(self):
        self.init()
        for request in self.sudo().with_context(active_test=False).search(
            [("employee_id", "=", False)], order="id"
        ):
            employee = request._get_or_create_employee_from_legacy_values(
                {
                    "requested_user_id": request.requested_user_id.id,
                    "employee_name": request.employee_name,
                    "employee_email": request.employee_email,
                    "fingerprint_id": request.fingerprint_id,
                    "department": request.department,
                    "position": request.position,
                    "company_id": request.company_id.id,
                }
            )
            super(EmployeeAccessRequest, request.with_context(tracking_disable=True)).write(
                {"employee_id": employee.id, **request._employee_snapshot_values(employee)}
            )
        return True

    @api.model
    def _backfill_completed_odoo_user_accounts(self):
        """Create native users for completed tickets from releases before user sync."""
        requests = self.sudo().with_context(active_test=False).search(
            [
                ("state", "in", ["active", "inactive"]),
                ("system_id.is_odoo_system", "=", True),
                "|",
                ("requested_user_id", "=", False),
                ("employee_id.user_id", "=", False),
            ],
            order="id",
        )
        for request in requests:
            request._sync_odoo_user_account()
            if request.state == "inactive":
                if request.profile_id and request.profile_id.state != "revoked":
                    request.profile_id.write({"state": "revoked"})
                request._archive_odoo_user_if_unused()
        return True

    def action_submit(self):
        self._normalize_request_type_from_existing_access()
        self._validate_no_pending_duplicate_requests()
        self._validate_duplicate_create_requests()
        if any(not request.application_ids for request in self):
            raise ValidationError(
                "Select at least one application module before submitting the request."
            )
        for request in self:
            erp_approver = (
                request.manager_approver_id
                or request._get_erp_admin_approver()
                or request._fallback_approval_user()
            )
            mark_done_user = (
                request.mark_done_user_id
                or request._get_mark_done_user()
                or request.credential_approver_id
                or request._fallback_approval_user()
            )
            request.write(
                {
                    "state": "to_approve",
                    "manager_approver_id": erp_approver.id,
                    "mark_done_user_id": mark_done_user.id,
                }
            )
            request._set_approval_lines(
                erp_approver,
                erp_state="to_approve",
            )
            request._schedule_approval_activity(
                erp_approver,
                f"{request._system_approver_label()} approval required",
            )
            request._log_event(
                "submitted",
                "Request user step completed. Request submitted for "
                f"{request._system_approver_label()} Approval.",
            )

    def action_manager_approve(self):
        for request in self:
            if request.state != "to_approve":
                raise ValidationError(
                    "Only requests awaiting system administrator approval can be approved."
                )
            approver_label = request._system_approver_label()
            request._check_assigned_approver(
                request.manager_approver_id,
                approver_label,
            )
            request._ensure_approval_lines()
            request._complete_approval_activity(
                f"{approver_label} approval required"
            )
            request._mark_approval_line(
                request._system_approval_role(),
                "approved",
            )
            profile = request._get_or_create_profile()
            task = request._create_provisioning_task(profile)
            request.write({"state": "approved", "profile_id": profile.id})
            request._log_event(
                "manager_approved",
                f"{approver_label} Approval completed by {self.env.user.name}.",
                profile=profile,
            )
            request._log_event(
                "approved",
                "System administrator approval completed. Request is waiting to be sent to the vendor.",
                profile=profile,
            )
            request._log_event(
                "task_created",
                "Provisioning task created for this request.",
                profile=profile,
                task=task,
            )

    def action_approve(self):
        """Complete legacy records that were already in the removed credential step."""
        for request in self:
            if request.state != "credential_approval":
                raise ValidationError(
                    "This request is not in the legacy approval step."
                )
            request._ensure_approval_lines()
            profile = request._get_or_create_profile()
            task = request._create_provisioning_task(profile)
            request.write({"state": "approved", "profile_id": profile.id})
            request._log_event(
                "approved",
                "Removed Credential Management step skipped. Request is ready for the vendor.",
                profile=profile,
            )
            request._log_event(
                "task_created",
                "Provisioning task created for this request.",
                profile=profile,
                task=task,
            )

    def action_reject(self):
        for request in self:
            if request.state == "to_approve":
                request._mark_approval_line(
                    request._system_approval_role(),
                    "rejected",
                )
            request.write({"state": "rejected"})
            request._log_event("rejected", "Request rejected.")

    def action_reset_to_draft(self):
        for request in self:
            request.approval_line_ids.unlink()
            request.write({"state": "draft"})
            request._log_event("reset", "Request reset to draft.")

    def action_start_provisioning(self):
        action = False
        for request in self:
            task = request.provisioning_task_ids.filtered(
                lambda item: item.state in ("pending", "in_progress")
            )[:1]
            if task:
                vendor_owner = request._get_vendor_owner()
                task.assigned_user_id = vendor_owner.id
                action = task.action_start()
                request._schedule_vendor_activity(task, resend=False)
        return action

    def action_resend_vendor_notification(self):
        for request in self:
            if request.state != "provisioning":
                raise ValidationError(
                    "Vendor notification can only be resent while waiting for the vendor."
                )
            task = request.provisioning_task_ids.filtered(
                lambda item: item.state == "in_progress"
            )[:1]
            if not task:
                raise ValidationError("No vendor ticket is currently in progress.")
            vendor_owner = request._get_vendor_owner()
            task.assigned_user_id = vendor_owner.id
            action = request._open_vendor_ticket_email_composer(task, resend=True)
            request._schedule_vendor_activity(task, resend=True)
            return action

    def action_mark_active(self):
        action = False
        for request in self:
            if request.state != "provisioning":
                raise ValidationError(
                    "Send the request to the vendor before finishing the ticket."
                )
            task = request.provisioning_task_ids.filtered(
                lambda item: item.state == "in_progress"
            )[:1]
            if not task:
                raise ValidationError("No vendor ticket is currently in progress.")
            request._check_mark_done_user()
            action = task.action_mark_done()
        return action

    def action_mark_inactive(self):
        for request in self:
            if request.state != "active":
                raise ValidationError("Only an active created user can be marked inactive.")
            inactive_date = fields.Date.context_today(request)
            if request.profile_id:
                request.profile_id.write({"state": "revoked"})
            request.write({"state": "inactive", "inactive_date": inactive_date})
            request._archive_odoo_user_if_unused()
            request._log_event(
                "deactivated",
                "Vendor confirmed that the user account is inactive.",
                profile=request.profile_id,
            )

    def action_reactivate(self):
        for request in self:
            if request.state != "inactive":
                raise ValidationError("Only an inactive created user can be reactivated.")
            if request.profile_id:
                request.profile_id.write({"state": "active"})
            request.write({"state": "active", "inactive_date": False})
            request._reactivate_odoo_user()
            request._log_event(
                "reactivated",
                "Vendor confirmed that the user account is active again.",
                profile=request.profile_id,
            )

    def action_view_profile(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Access Profile",
            "res_model": "employee.access.profile",
            "view_mode": "form",
            "res_id": self.profile_id.id,
            "target": "current",
        }

    def action_view_provisioning_tasks(self):
        self.ensure_one()
        tasks = self.provisioning_task_ids
        action = {
            "type": "ir.actions.act_window",
            "name": "Vendor Ticket",
            "res_model": "employee.access.provision.task",
            "view_mode": "list,form",
            "domain": [("id", "in", tasks.ids)],
            "context": {"default_request_id": self.id, "default_profile_id": self.profile_id.id},
            "target": "current",
        }
        if len(tasks) == 1:
            action.update({"view_mode": "form", "res_id": tasks.id})
        return action

    def _matching_profile_domain(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("state", "=", "active"),
        ]
        odoo_user = (
            self._get_active_odoo_user()
            if self.system_id.is_odoo_system and self.employee_id
            else self.env["res.users"]
        )
        if odoo_user:
            domain.extend(
                [
                    "|",
                    ("last_request_id.employee_id", "=", self.employee_id.id),
                    ("last_request_id.requested_user_id", "=", odoo_user.id),
                ]
            )
        elif self.system_id.is_odoo_system and self.employee_id:
            # A provisioned Odoo account can predate the explicit hr.employee ->
            # res.users link. The completed request is still a safe identity link;
            # unlike fingerprint matching it cannot belong to a reused value. Exact
            # email matching keeps active profiles created by older releases usable.
            if self.employee_email:
                domain.extend(
                    [
                        "|",
                        ("last_request_id.employee_id", "=", self.employee_id.id),
                        ("employee_email", "=ilike", self.employee_email),
                    ]
                )
            else:
                domain.append(("last_request_id.employee_id", "=", self.employee_id.id))
        elif self.fingerprint_id:
            domain.append(("fingerprint_id", "=", self.fingerprint_id))
        elif self.employee_email:
            domain.append(("employee_email", "=", self.employee_email))
        else:
            domain.append(("employee_name", "=", self.employee_name))
        return domain

    def _existing_profile_system_domain(self):
        self.ensure_one()
        return [("system_id", "=", self.system_id.id)] if self.system_id else []

    def _get_active_odoo_user(self):
        """Return the selected employee's active internal Odoo login, if any."""
        self.ensure_one()
        user = self.employee_id.user_id or self.requested_user_id
        if not user or not user.active or user.share:
            return self.env["res.users"]
        if self.company_id and self.company_id not in user.company_ids:
            return self.env["res.users"]
        return user

    def _has_existing_active_access(self, profile=None):
        self.ensure_one()
        if (
            self.system_id.is_odoo_system
            and self.employee_id
            and self._get_active_odoo_user()
        ):
            return True
        return bool(profile or self._find_existing_active_profile())

    def _find_existing_active_profile(self):
        self.ensure_one()
        if not self.system_id or not self.company_id:
            return self.env["employee.access.profile"]
        matching_domain = self._matching_profile_domain()
        profile = self.env["employee.access.profile"].search(
            matching_domain + self._existing_profile_system_domain(),
            order="id desc",
            limit=1,
        )
        if not profile and self.system_id.is_odoo_system:
            profile = self.env["employee.access.profile"].search(
                matching_domain + [("system_id.is_odoo_system", "=", True)],
                order="id desc",
                limit=1,
            )
        return profile

    def _find_existing_active_profile_any_system(self):
        self.ensure_one()
        if not self.company_id:
            return self.env["employee.access.profile"]
        domain = self._matching_profile_domain()
        return self.env["employee.access.profile"].search(
            domain,
            order="id desc",
            limit=1,
        )

    def _get_or_create_profile(self):
        self.ensure_one()
        profile = self.profile_id or self._find_existing_active_profile()
        if not profile:
            profile = self.env["employee.access.profile"].create(
                {
                    "employee_name": self.employee_name,
                    "fingerprint_id": self.fingerprint_id,
                    "employee_email": self.employee_email,
                    "department": self.department,
                    "position": self.position,
                    "company_id": self.company_id.id,
                    "system_id": self.system_id.id,
                    "state": "pending",
                }
            )
            self._log_event(
                "profile_linked",
                "Access profile created for this employee and system.",
                profile=profile,
            )
        return profile

    def _sync_profile_from_request(self, profile):
        self.ensure_one()
        profile.write(
            {
                "employee_name": self.employee_name,
                "fingerprint_id": self.fingerprint_id,
                "employee_email": self.employee_email,
                "department": self.department,
                "position": self.position,
                "company_id": self.company_id.id,
                "system_id": self.system_id.id,
                "access_company_ids": [Command.set(self.access_company_ids.ids)],
                "access_facility_ids": [Command.set(self.access_facility_ids.ids)],
                "application_ids": [Command.set(self.application_ids.ids)],
                "required_privileged_access": self.required_privileged_access,
                "last_request_id": self.id,
            }
        )

    def _sync_request_type_with_existing_access(self):
        self.ensure_one()
        if self._has_existing_active_access():
            self.request_type = "update"
        elif self.request_type != "create":
            self.request_type = "create"

    def _prefill_existing_active_access(
        self, profile=None, include_applications=True, sync_system=False
    ):
        self.ensure_one()
        profile = profile or self._find_existing_active_profile()
        if not profile:
            self._sync_request_type_with_existing_access()
            return

        if sync_system and self.system_id != profile.system_id:
            self.system_id = profile.system_id
            self.manager_approver_id = (
                self._get_erp_admin_approver() or self._fallback_approval_user()
            )
            self.mark_done_user_id = (
                self._get_mark_done_user() or self._fallback_approval_user()
            )

        if sync_system and not self.employee_id:
            self.employee_name = profile.employee_name
            self.fingerprint_id = profile.fingerprint_id
            self.employee_email = profile.employee_email
            self.department = profile.department
            self.position = profile.position
        self.request_type = "update"
        self.access_company_ids = [Command.set(profile.access_company_ids.ids)]
        self.access_facility_ids = [Command.set(profile.access_facility_ids.ids)]
        self.required_privileged_access = profile.required_privileged_access
        if include_applications:
            self.application_line_ids = [
                Command.clear(),
                *self._application_line_commands(self.system_id, profile=profile),
            ]

    def _normalize_request_type_from_existing_access(self):
        for request in self:
            if request.state != "draft":
                continue
            target_request_type = (
                "update" if request._has_existing_active_access() else "create"
            )
            if request.request_type != target_request_type:
                super(EmployeeAccessRequest, request).write({"request_type": target_request_type})

    def _validate_duplicate_create_requests(self):
        for request in self:
            if request.request_type == "create" and request._has_existing_active_access():
                raise ValidationError(
                    "Active access already exists for this employee. Use Update instead of Create."
                )

    def _validate_no_pending_duplicate_requests(self):
        blocking_states = (
            "to_approve",
            "credential_approval",
            "approved",
            "provisioning",
        )
        for request in self:
            if not request.employee_id or not request.company_id or not request.system_id:
                continue
            existing_request = self.search(
                [
                    ("id", "!=", request.id),
                    ("employee_id", "=", request.employee_id.id),
                    ("company_id", "=", request.company_id.id),
                    ("system_id", "=", request.system_id.id),
                    ("state", "in", blocking_states),
                ],
                order="request_date desc, id desc",
                limit=1,
            )
            if existing_request:
                status = existing_request.list_status_label or dict(
                    self._fields["state"].selection
                ).get(existing_request.state, existing_request.state)
                raise ValidationError(
                    f"Request {existing_request.reference} is already {status}. "
                    "Complete or reject the existing request before submitting another request."
                )

    def _create_provisioning_task(self, profile):
        self.ensure_one()
        existing_task = self.provisioning_task_ids.filtered(
            lambda task: task.state in ("pending", "in_progress")
        )[:1]
        if existing_task:
            return existing_task
        return self.env["employee.access.provision.task"].create(
            {
                "request_id": self.id,
                "profile_id": profile.id,
                "assigned_user_id": self._get_mark_done_user_for_request().id,
            }
        )

    def _get_vendor_owner(self):
        self.ensure_one()
        return self._get_mark_done_user_for_request()

    def _get_mark_done_user_for_request(self):
        self.ensure_one()
        return (
            self.mark_done_user_id
            or self._get_mark_done_user()
            or self.credential_approver_id
            or self.system_id.owner_id
            or self.manager_approver_id
            or self._fallback_approval_user()
        )

    def _get_vendor_ticket_partner_ids(self):
        self.ensure_one()
        user_recipients = self.system_id.recipient_user_ids
        if user_recipients:
            users_without_email = user_recipients.filtered(
                lambda user: not (user.email or "").strip()
            )
            if users_without_email:
                raise ValidationError(
                    "Selected recipient users do not have email addresses. "
                    "Add user emails before sending the vendor email."
                )
            return user_recipients.mapped("partner_id").ids

        employee_recipients = self.system_id.recipient_employee_ids
        if not employee_recipients:
            return self.system_id.mail_recipient_ids.ids

        partners = self.env["res.partner"].sudo()
        for employee in employee_recipients:
            email = (employee.work_email or "").strip()
            if not email:
                continue
            partner = False
            if "work_contact_id" in employee._fields:
                partner = employee.work_contact_id
            if not partner:
                partner = partners.search([("email", "=ilike", email)], limit=1)
            if not partner:
                partner = partners.create(
                    {
                        "name": employee.name,
                        "email": email,
                        "company_id": employee.company_id.id or False,
                    }
                )
            partners |= partner
        if not partners:
            raise ValidationError(
                "Selected recipient employees do not have work emails. "
                "Add employee work emails before sending the vendor email."
            )
        return partners.ids

    def _get_vendor_ticket_recipients(self):
        self.ensure_one()
        users_without_email = self.system_id.recipient_user_ids.filtered(
            lambda user: not (user.email or "").strip()
        )

        if users_without_email:
            raise ValidationError(
                "Selected recipient users do not have email addresses. "
                "Add user emails before sending the vendor email."
            )
        recipient_emails = [
            email.strip()
            for email in self.system_id.recipient_user_ids.mapped("email")
            if email and email.strip()
        ]
        if not recipient_emails:
            recipient_emails = [
                email.strip()
                for email in self.system_id.recipient_employee_ids.mapped("work_email")
                if email and email.strip()
            ]
        if not recipient_emails:
            recipient_emails = [
                email.strip()
                for email in self.system_id.mail_recipient_ids.mapped("email")
                if email and email.strip()
            ]
        recipient_emails = list(dict.fromkeys(recipient_emails))
        if not recipient_emails:
            raise ValidationError(
                "Mail recipients are not configured for "
                f"{self.system_id.name}. Open Configuration > Systems and add recipients first."
            )
        return ", ".join(recipient_emails)

    def _sync_odoo_user_account(self):
        """Create or update the real internal Odoo login for an Odoo request."""
        self.ensure_one()
        if not self.system_id.is_odoo_system:
            return self.env["res.users"]

        Users = self.env["res.users"].sudo().with_context(active_test=False)
        user = self.employee_id.user_id or self.requested_user_id
        if not user:
            user = Users._employee_access_get_or_create(
                name=self.employee_name,
                fingerprint=self.fingerprint_id,
                email=self.employee_email,
                department=self.department,
                position=self.position,
                company=self.company_id,
                employee=self.employee_id,
            )

        allowed_companies = self.access_company_ids | self.company_id
        selected_roles = self.application_line_ids.filtered(
            lambda line: not line.remove_access and line.access_group_id
        ).mapped("access_group_id")
        application_groups = self.env["employee.access.group"].sudo().search(
            [("application_id", "in", self.application_line_ids.application_id.ids)]
        )
        managed_odoo_groups = application_groups.mapped("odoo_group_ids")
        requested_odoo_groups = selected_roles.mapped("odoo_group_ids")
        internal_group = self.env.ref("base.group_user")
        groups_to_remove = managed_odoo_groups - requested_odoo_groups
        groups_to_add = requested_odoo_groups | internal_group

        values = {
            "name": self.employee_name,
            "email": self.employee_email or False,
            "employee_access_fingerprint_id": self.fingerprint_id or False,
            "employee_access_department": self.department or False,
            "employee_access_position": self.position or False,
            "employee_access_user_type": self.system_id.user_type,
            "active": True,
            "company_ids": [Command.link(company.id) for company in allowed_companies],
            "groups_id": [
                *[Command.unlink(group.id) for group in groups_to_remove],
                *[Command.link(group.id) for group in groups_to_add],
            ],
        }
        if user.company_id not in allowed_companies:
            values["company_id"] = self.company_id.id
        user.with_context(
            no_reset_password=True,
            employee_access_skip_status_sync=True,
        ).write(values)

        if self.employee_id and self.employee_id.user_id != user:
            self.employee_id.sudo().write({"user_id": user.id})
        if self.requested_user_id != user:
            self.sudo().write({"requested_user_id": user.id})
        return user

    def _archive_odoo_user_if_unused(self):
        for request in self.filtered("system_id.is_odoo_system"):
            user = request.employee_id.user_id or request.requested_user_id
            if not user or user == self.env.user:
                continue
            other_active_access = self.sudo().search_count(
                [
                    ("id", "!=", request.id),
                    ("state", "=", "active"),
                    ("system_id.is_odoo_system", "=", True),
                    "|",
                    ("requested_user_id", "=", user.id),
                    ("employee_id", "=", request.employee_id.id),
                ]
            )
            if not other_active_access:
                user.sudo().with_context(
                    employee_access_skip_status_sync=True
                ).active = False

    def _reactivate_odoo_user(self):
        for request in self.filtered("system_id.is_odoo_system"):
            user = request.employee_id.user_id or request.requested_user_id
            if user:
                user.sudo().with_context(
                    active_test=False,
                    employee_access_skip_status_sync=True,
                ).write(
                    {
                        "active": True,
                        "employee_access_user_type": request.system_id.user_type,
                    }
                )

    def _odoo_user_form_action(self, user):
        self.ensure_one()
        if not user:
            return False
        action = self.env["ir.actions.actions"]._for_xml_id("base.action_res_users")
        action.update(
            {
                "name": user.name,
                "res_id": user.id,
                "views": [(self.env.ref("base.view_users_form").id, "form")],
                "view_mode": "form",
                "domain": [],
                "target": "current",
            }
        )
        return action

    def _get_vendor_ticket_email(self):
        self.ensure_one()
        return self._get_vendor_ticket_recipients()

    def _vendor_ticket_subject(self, task):
        self.ensure_one()
        action = "Create" if self.request_type == "create" else "Update"
        subject = f"[{task.ticket_reference}] {action} Odoo access - {self.employee_name}"
        if task.ticket_reference != self.reference:
            subject = f"{subject} ({self.reference})"
        return subject

    def _vendor_ticket_body(self, task, resend=False):
        self.ensure_one()
        access_companies = ", ".join(self.access_company_ids.mapped("name")) or "-"
        application_rows = []
        for line in self.application_line_ids.filtered(lambda item: not item.remove_access):
            role_name = line.access_group_id.name if line.access_group_id else "No access"
            application_rows.append(
                Markup("<tr><td>%s</td><td>%s</td></tr>")
                % (escape(line.application_id.name), escape(role_name))
            )
        application_table = Markup("".join(str(row) for row in application_rows))
        if not application_table:
            application_table = Markup('<tr><td colspan="2">No application access selected</td></tr>')
        resend_note = (
            Markup("<p><strong>Reminder:</strong> This vendor ticket is being resent.</p>")
            if resend
            else Markup("")
        )
        return Markup(
            """
            <p>Dear Vendor Support,</p>
            <p>Please process the following approved employee access request.</p>
            %s
            <table style="border-collapse:collapse; width:100%%">
                <tr><td><strong>Ticket</strong></td><td>%s</td></tr>
                <tr><td><strong>Request</strong></td><td>%s</td></tr>
                <tr><td><strong>Request Type</strong></td><td>%s</td></tr>
                <tr><td><strong>Employee</strong></td><td>%s</td></tr>
                <tr><td><strong>Fingerprint ID</strong></td><td>%s</td></tr>
                <tr><td><strong>Employee Email</strong></td><td>%s</td></tr>
                <tr><td><strong>Department</strong></td><td>%s</td></tr>
                <tr><td><strong>Position</strong></td><td>%s</td></tr>
                <tr><td><strong>System</strong></td><td>%s</td></tr>
                <tr><td><strong>Access Companies</strong></td><td>%s</td></tr>
                <tr><td><strong>Privileged Access</strong></td><td>%s</td></tr>
            </table>
            <h4>Application Access</h4>
            <table style="border-collapse:collapse; width:100%%" border="1" cellpadding="6">
                <thead><tr><th>Application</th><th>Access Role</th></tr></thead>
                <tbody>%s</tbody>
            </table>
            <p>Please reply to this email when provisioning is complete and include the
            vendor ticket number if your portal creates a separate reference.</p>
            <p>Regards,<br/>Employee Access Control</p>
            """
        ) % (
            resend_note,
            escape(task.ticket_reference),
            escape(self.reference),
            escape(dict(self._fields["request_type"].selection).get(self.request_type)),
            escape(self.employee_name),
            escape(self.fingerprint_id or "-"),
            escape(self.employee_email or "-"),
            escape(self.department or "-"),
            escape(self.position or "-"),
            escape(self.system_id.name),
            escape(access_companies),
            escape("Yes" if self.required_privileged_access else "No"),
            application_table,
        )

    def _open_vendor_ticket_email_composer(self, task, resend=False):
        self.ensure_one()
        vendor_email = self._get_vendor_ticket_recipients()
        subject = self._vendor_ticket_subject(task)
        task.write(
            {
                "vendor_email": vendor_email,
                "vendor_subject": subject,
                "vendor_portal_url": self.system_id.vendor_portal_url,
            }
        )
        compose_form = self.env.ref("mail.email_compose_message_wizard_form")
        return {
            "name": "Compose Vendor Email",
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "mail.compose.message",
            "views": [(compose_form.id, "form")],
            "view_id": compose_form.id,
            "target": "new",
            "context": {
                "default_model": self._name,
                "default_res_ids": self.ids,
                "default_composition_mode": "comment",
                "default_partner_ids": self._get_vendor_ticket_partner_ids(),
                "default_subject": subject,
                "default_body": self._vendor_ticket_body(task, resend=resend),
                "default_email_layout_xmlid": "mail.mail_notification_layout",
                "default_notify_skip_followers": True,
                "clicked_on_full_composer": True,
                "force_email": True,
                "employee_access_vendor_task_id": task.id,
                "employee_access_vendor_resend": resend,
            },
        }

    def _get_access_approval_rule(self):
        self.ensure_one()
        return self.env["employee.access.approval.rule"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("model_name", "=", "employee_access_control"),
                ("active", "=", True),
            ],
            order="sequence, id",
            limit=1,
        )

    def _erp_admin_step_name(self):
        self.ensure_one()
        return {
            "Odoo Standard": "ERP Admin (Standard)",
            "Odoo Light": "HRMS Admin(Light)",
            "EHR": "EHR Admin",
            "LIMS": "LIMS Admin",
            "RIS": "RIS Admin",
        }.get(self.system_id.name, "ERP Admin (Standard)")

    def _system_approval_role(self):
        self.ensure_one()
        return "hrms_admin" if self.system_id.name == "Odoo Light" else "erp_admin"

    def _system_approver_label(self):
        self.ensure_one()
        return "HRMS Admin" if self.system_id.name == "Odoo Light" else "ERP Admin"

    def _get_erp_admin_approver(self):
        self.ensure_one()
        configured_step = self.system_id.request_approver_step_id
        if configured_step.approver_user_id:
            return configured_step.approver_user_id
        approval_rule = self._get_access_approval_rule()
        erp_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == self._erp_admin_step_name()
        )[:1]
        return erp_step.approver_user_id or approval_rule.approver_user_id

    def _get_mark_done_user(self):
        self.ensure_one()
        configured_step = self.system_id.handover_approver_step_id
        if configured_step.approver_user_id:
            return configured_step.approver_user_id
        approval_rule = self._get_access_approval_rule()
        mark_done_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == "Mark Done"
        )[:1]
        legacy_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == "Credential Management"
        )[:1]
        return (
            mark_done_step.approver_user_id
            or legacy_step.approver_user_id
            or approval_rule.approver_user_id
        )

    def _fallback_approval_user(self):
        self.ensure_one()
        return self.env.ref("base.user_admin")

    def _initialize_draft_approvers(self, force_system_approver=False):
        self.ensure_one()
        if self.state != "draft" or not self.id:
            return
        configured_system_approver = (
            self._get_erp_admin_approver()
            or self._fallback_approval_user()
        )
        system_approver = (
            configured_system_approver
            if force_system_approver
            else self.manager_approver_id or configured_system_approver
        )
        mark_done_user = (
            self.mark_done_user_id
            or self._get_mark_done_user()
            or self.credential_approver_id
            or self._fallback_approval_user()
        )
        super(EmployeeAccessRequest, self).write(
            {
                "manager_approver_id": system_approver.id,
                "mark_done_user_id": mark_done_user.id,
            }
        )
        self._set_approval_lines(
            system_approver,
            erp_state="waiting",
        )

    def _set_approval_lines(
        self,
        erp_approver,
        erp_state,
    ):
        self.ensure_one()
        system_role = self._system_approval_role()
        values_by_role = {
            system_role: {
                "sequence": 10,
                "approver_user_id": erp_approver.id,
                "state": erp_state,
            },
        }
        obsolete_lines = self.approval_line_ids.filtered(
            lambda approval_line: approval_line.role == "credential_management"
            or (
                approval_line.role in ("erp_admin", "hrms_admin")
                and approval_line.role != system_role
            )
        )
        obsolete_lines.unlink()
        for role, values in values_by_role.items():
            line = self.approval_line_ids.filtered(
                lambda approval_line: approval_line.role == role
            )[:1]
            if line:
                line.write(values)
            else:
                self.env["employee.access.request.approval.line"].create(
                    {"request_id": self.id, "role": role, **values}
                )

    def _ensure_approval_lines(self):
        self.ensure_one()
        erp_approver = (
            self.manager_approver_id
            or self._get_erp_admin_approver()
            or self._fallback_approval_user()
        )
        state_by_request_state = {
            "to_approve": "to_approve",
            "credential_approval": "approved",
            "approved": "approved",
            "provisioning": "approved",
            "active": "approved",
            "inactive": "approved",
        }
        erp_state = state_by_request_state.get(
            self.state,
            "waiting",
        )
        self._set_approval_lines(
            erp_approver,
            erp_state,
        )

    def _mark_approval_line(self, role, state):
        self.ensure_one()
        line = self.approval_line_ids.filtered(
            lambda approval_line: approval_line.role == role
        )[:1]
        if not line:
            return
        values = {"state": state}
        if state == "approved":
            values.update(
                {
                    "approved_by_id": self.env.user.id,
                    "approved_on": fields.Datetime.now(),
                }
            )
        line.write(values)

    @api.model
    def _backfill_approval_tracking(self):
        requests = self.search(
            [
                ("state", "in", [
                    "draft",
                    "to_approve",
                    "credential_approval",
                    "approved",
                    "provisioning",
                    "active",
                    "inactive",
                ]),
            ]
        )
        for request in requests:
            if request.state == "draft":
                request._initialize_draft_approvers()
                continue
            erp_approver = (
                request.manager_approver_id
                or request._get_erp_admin_approver()
                or request._fallback_approval_user()
            )
            mark_done_user = (
                request.mark_done_user_id
                or request._get_mark_done_user()
                or request.credential_approver_id
                or request._fallback_approval_user()
            )
            request.write(
                {
                    "manager_approver_id": erp_approver.id,
                    "mark_done_user_id": mark_done_user.id,
                }
            )
            request._ensure_approval_lines()
            if request.state == "credential_approval":
                request.action_approve()
        return True

    def _schedule_approval_activity(self, user, summary):
        self.ensure_one()
        if user:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=summary,
                note=f"{summary} for {self.employee_name} ({self.reference}).",
            )

    def _schedule_vendor_activity(self, task, resend=False):
        self.ensure_one()
        vendor_owner = task.assigned_user_id or self._get_vendor_owner()
        summary = "Vendor provisioning required"
        note = (
            f"Please complete vendor provisioning for {self.employee_name} "
            f"({self.reference}) in {self.system_id.name}."
        )
        existing_activity = task.activity_ids.filtered(
            lambda activity: activity.active
            and activity.summary == summary
            and activity.user_id == vendor_owner
        )[:1]
        if existing_activity:
            existing_activity.write({"note": note})
        else:
            task.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=vendor_owner.id,
                summary=summary,
                note=note,
            )
        message = (
            f"Admin notification resent to {vendor_owner.name}."
            if resend
            else f"Admin notification sent to {vendor_owner.name}."
        )
        self._log_event("vendor_notification_sent", message, task=task)
        task.message_post(body=message, subtype_xmlid="mail.mt_note")

    def _complete_vendor_activity(self):
        self.ensure_one()
        activities = self.provisioning_task_ids.mapped("activity_ids").filtered(
            lambda activity: activity.summary == "Vendor provisioning required"
            and activity.active
        )
        if activities:
            activities.action_feedback(feedback=f"Completed by {self.env.user.name}.")

    def _complete_approval_activity(self, summary):
        self.ensure_one()
        activities = self.activity_ids.filtered(
            lambda activity: activity.summary == summary and activity.active
        )
        if activities:
            activities.action_feedback(feedback=f"Completed by {self.env.user.name}.")

    def _check_assigned_approver(self, assigned_user, approval_label):
        self.ensure_one()
        if (
            assigned_user
            and assigned_user != self.env.user
            and not self.env.user.has_group(
                "employee_access_control.group_employee_access_administrator"
            )
        ):
            raise ValidationError(
                f"Only {assigned_user.name} can complete {approval_label} Approval."
            )

    def _check_mark_done_user(self):
        self.ensure_one()
        assigned_user = self._get_mark_done_user_for_request()
        is_administrator = (
            self.env.is_superuser()
            or self.env.user.has_group(
                "employee_access_control.group_employee_access_administrator"
            )
            or self.env.user.has_group("base.group_system")
        )
        if assigned_user != self.env.user and not is_administrator:
            raise ValidationError(
                f"Only {assigned_user.name} or an administrator can mark this "
                "request as done."
            )

    def _subscribe_related_users(self):
        for request in self:
            related_user = request.employee_id.user_id or request.requested_user_id
            if related_user.partner_id:
                request.message_subscribe(partner_ids=related_user.partner_id.ids)

    def _log_event(self, event_type, message, profile=False, task=False):
        self.ensure_one()
        audit_log = self.env["employee.access.audit.log"].sudo().create(
            {
                "company_id": self.company_id.id,
                "request_id": self.id,
                "profile_id": profile.id if profile else False,
                "task_id": task.id if task else False,
                "event_type": event_type,
                "message": message,
                "performed_by_id": self.env.user.id,
            }
        )
        partner_ids = (self.employee_id.user_id or self.requested_user_id).partner_id.ids
        self.message_post(
            body=message,
            subtype_xmlid="mail.mt_note",
            partner_ids=partner_ids,
        )
        return audit_log


class EmployeeAccessRequestApprovalLine(models.Model):
    _name = "employee.access.request.approval.line"
    _description = "Employee Access Request Approval"
    _order = "sequence, id"
    _check_company_auto = True

    request_id = fields.Many2one(
        "employee.access.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="request_id.company_id",
        store=True,
        index=True,
    )
    sequence = fields.Integer(default=10)
    role = fields.Selection(
        [
            ("erp_admin", "ERP Admin"),
            ("hrms_admin", "HRMS Admin"),
            ("credential_management", "Credential Management"),
        ],
        required=True,
    )
    approver_user_id = fields.Many2one(
        "res.users",
        string="Approver",
        required=True,
        ondelete="restrict",
    )
    state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("to_approve", "To Approve"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        required=True,
        default="waiting",
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Approved By",
        readonly=True,
        ondelete="set null",
    )
    approved_on = fields.Datetime(readonly=True)

    _sql_constraints = [
        (
            "request_role_uniq",
            "unique(request_id, role)",
            "Each approval role can appear only once per request.",
        ),
    ]


class EmployeeAccessRequestApplicationLine(models.Model):
    _name = "employee.access.request.application.line"
    _description = "Employee Access Request Application"
    _order = "sequence, application_id, id"

    request_id = fields.Many2one(
        "employee.access.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    application_id = fields.Many2one(
        "employee.access.application",
        string="Application Module",
        required=True,
        ondelete="restrict",
    )
    access_group_id = fields.Many2one(
        "employee.access.group",
        string="Access Role",
        domain="[('application_id', '=', application_id), ('display_type', '=', 'application_role'), ('active', '=', True)]",
        ondelete="restrict",
    )
    sequence = fields.Integer(related="application_id.sequence", store=True)
    remove_access = fields.Boolean(string="Remove Access")

    @api.constrains("application_id", "access_group_id")
    def _check_access_group_application(self):
        for line in self:
            if line.access_group_id and line.access_group_id.application_id != line.application_id:
                raise ValidationError("Access role must belong to the selected application.")

    _sql_constraints = [
        (
            "request_application_uniq",
            "unique(request_id, application_id)",
            "Each application module can appear only once per request.",
        ),
    ]
