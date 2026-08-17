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
    def _application_line_commands(self, system):
        return [
            Command.create(
                {
                    "application_id": application.id,
                    "access_group_id": self._default_access_group(application).id,
                }
            )
            for application in self._applications_for_system(system)
        ]

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
    employee_name = fields.Char(string="Manual Employee Name", required=True)
    employee_source = fields.Selection(
        [
            ("odoo_user", "Odoo User"),
            ("manual", "Manual Entry"),
        ],
        string="Employee Source",
        required=True,
        default="manual",
        tracking=True,
    )
    requested_user_id = fields.Many2one(
        "res.users",
        string="Odoo User",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        tracking=True,
    )
    employee_display_name = fields.Char(
        string="Employee",
        compute="_compute_employee_display_name",
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
        string="Facilities Access",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
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
    required_privileged_access = fields.Boolean(string="Required Privileged Access")
    manager_approver_id = fields.Many2one(
        "res.users",
        string="ERP Admin Approver",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        tracking=True,
    )
    credential_approver_id = fields.Many2one(
        "res.users",
        string="Credential Management Approver",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        tracking=True,
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
    requires_credential_approval = fields.Boolean(
        string="Credential Management",
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
            request.requires_credential_approval = bool(request.system_id)

    @api.depends(
        "employee_name",
        "employee_email",
        "fingerprint_id",
        "company_id",
        "system_id",
    )
    def _compute_existing_access_status(self):
        for request in self:
            profile = request._find_existing_active_profile()
            request.has_existing_active_access = bool(profile)
            request.duplicate_create_blocked = bool(profile)
            if not profile:
                request.existing_access_message = False
            elif profile.system_id == request.system_id:
                request.existing_access_message = (
                    f"Active access already exists for {profile.system_id.name}. "
                    "Use Update for changes."
                )
            else:
                request.existing_access_message = (
                    f"Active access already exists for {profile.system_id.name}. "
                    f"Use Update to move to {request.system_id.name}."
                )
            if request.duplicate_create_blocked:
                request.request_type = "update"

    @api.depends("provisioning_task_ids")
    def _compute_provisioning_task_count(self):
        for request in self:
            request.provisioning_task_count = len(request.provisioning_task_ids)

    @api.depends("requested_user_id.name", "employee_name")
    def _compute_employee_display_name(self):
        for request in self:
            request.employee_display_name = (
                request.requested_user_id.name or request.employee_name
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
            request.application_line_ids = [
                Command.clear(),
                *self._application_line_commands(request.system_id),
            ]
            if request.system_id:
                request.manager_approver_id = (
                    request._get_erp_admin_approver()
                    or request._fallback_approval_user()
                )
                request.credential_approver_id = (
                    request._get_credential_approver()
                    or request._fallback_approval_user()
                )
            request._sync_request_type_with_existing_access()

    @api.onchange("employee_name", "employee_email", "fingerprint_id", "company_id")
    def _onchange_employee_identity(self):
        for request in self:
            request._sync_request_type_with_existing_access()

    @api.onchange("requested_user_id")
    def _onchange_requested_user_id(self):
        for request in self:
            if request.requested_user_id:
                request.employee_source = "odoo_user"
                request.employee_name = request.requested_user_id.name
                request.employee_email = (
                    request.requested_user_id.email or request.requested_user_id.login
                )

    @api.onchange("employee_source")
    def _onchange_employee_source(self):
        for request in self:
            if request.employee_source == "manual":
                request.requested_user_id = False

    @api.model_create_multi
    def create(self, vals_list):
        default_system = self._default_system_id()
        for vals in vals_list:
            requested_user = self.env["res.users"].browse(vals.get("requested_user_id"))
            if requested_user:
                vals["employee_source"] = "odoo_user"
                vals["employee_name"] = requested_user.name
                vals["employee_email"] = requested_user.email or requested_user.login
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
        if vals.get("employee_source") == "manual":
            vals["requested_user_id"] = False
        requested_user = self.env["res.users"].browse(vals.get("requested_user_id"))
        if requested_user:
            vals.update(
                {
                    "employee_source": "odoo_user",
                    "employee_name": requested_user.name,
                    "employee_email": requested_user.email or requested_user.login,
                }
            )
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
        if "requested_user_id" in vals or "employee_email" in vals:
            self._subscribe_related_users()
        return result

    @api.constrains("employee_source", "requested_user_id")
    def _check_employee_source(self):
        for request in self:
            if request.employee_source == "odoo_user" and not request.requested_user_id:
                raise ValidationError("Select an Odoo User for the employee source.")

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
               SET employee_source = 'odoo_user'
             WHERE requested_user_id IS NOT NULL
               AND employee_source != 'odoo_user'
            """
        )

    def action_submit(self):
        self._normalize_request_type_from_existing_access()
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
            credential_approver = (
                request.credential_approver_id
                or request._get_credential_approver()
                or request._fallback_approval_user()
            )
            request.write(
                {
                    "state": "to_approve",
                    "manager_approver_id": erp_approver.id,
                    "credential_approver_id": credential_approver.id,
                }
            )
            request._set_approval_lines(
                erp_approver,
                credential_approver,
                erp_state="to_approve",
                credential_state="waiting",
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
            request._mark_approval_line("credential_management", "to_approve")
            request.write({"state": "credential_approval"})
            request._schedule_approval_activity(
                request.credential_approver_id,
                "Credential Management approval required",
            )
            request._log_event(
                "manager_approved",
                f"{approver_label} Approval completed by {self.env.user.name}.",
            )

    def action_approve(self):
        for request in self:
            if request.state != "credential_approval":
                raise ValidationError(
                    "Only requests awaiting Credential Management Approval can be approved."
                )
            request._check_assigned_approver(
                request.credential_approver_id,
                "Credential Management",
            )
            request._ensure_approval_lines()
            request._complete_approval_activity(
                "Credential Management approval required"
            )
            request._mark_approval_line("credential_management", "approved")
            profile = request._get_or_create_profile()
            task = request._create_provisioning_task(profile)
            request.write({"state": "approved", "profile_id": profile.id})
            request._log_event(
                "credential_approved",
                f"Credential Management Approval completed by {self.env.user.name}.",
                profile=profile,
            )
            request._log_event(
                "approved",
                "All approvals completed. Request is waiting for the vendor.",
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
            elif request.state == "credential_approval":
                request._mark_approval_line("credential_management", "rejected")
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
            task.action_mark_done()

    def action_mark_inactive(self):
        for request in self:
            if request.state != "active":
                raise ValidationError("Only an active created user can be marked inactive.")
            inactive_date = fields.Date.context_today(request)
            if request.profile_id:
                request.profile_id.write({"state": "revoked"})
            request.write({"state": "inactive", "inactive_date": inactive_date})
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
        if self.fingerprint_id:
            domain.append(("fingerprint_id", "=", self.fingerprint_id))
        elif self.employee_email:
            domain.append(("employee_email", "=", self.employee_email))
        else:
            domain.append(("employee_name", "=", self.employee_name))
        return domain

    def _existing_profile_system_domain(self):
        self.ensure_one()
        system_ids = self.system_id.ids
        if self.system_id.name == "Odoo Standard":
            light_system = self.env["employee.access.system"].search(
                [("name", "=", "Odoo Light")],
                limit=1,
            )
            if light_system:
                system_ids = list(set(system_ids + light_system.ids))
        return [("system_id", "in", system_ids)] if system_ids else []

    def _find_existing_active_profile(self):
        self.ensure_one()
        if not self.system_id or not self.company_id:
            return self.env["employee.access.profile"]
        domain = self._matching_profile_domain() + self._existing_profile_system_domain()
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
        if self._find_existing_active_profile():
            self.request_type = "update"
        elif self.request_type != "create":
            self.request_type = "create"

    def _normalize_request_type_from_existing_access(self):
        for request in self:
            if request.state != "draft":
                continue
            target_request_type = "update" if request._find_existing_active_profile() else "create"
            if request.request_type != target_request_type:
                super(EmployeeAccessRequest, request).write({"request_type": target_request_type})

    def _validate_duplicate_create_requests(self):
        for request in self:
            if request.request_type == "create" and request._find_existing_active_profile():
                raise ValidationError(
                    "Active access already exists for this employee. Use Update instead of Create."
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
                "assigned_user_id": self._get_vendor_owner().id,
            }
        )

    def _get_vendor_owner(self):
        self.ensure_one()
        return (
            self.system_id.owner_id
            or self.manager_approver_id
            or self._fallback_approval_user()
        )

    def _get_vendor_ticket_recipients(self):
        self.ensure_one()
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
                "default_model": task._name,
                "default_res_ids": task.ids,
                "default_composition_mode": "comment",
                "default_partner_ids": self.system_id.mail_recipient_ids.ids,
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
        approval_rule = self._get_access_approval_rule()
        erp_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == self._erp_admin_step_name()
        )[:1]
        return erp_step.approver_user_id or approval_rule.approver_user_id

    def _get_credential_approver(self):
        self.ensure_one()
        approval_rule = self._get_access_approval_rule()
        credential_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == "Credential Management"
        )[:1]
        return credential_step.approver_user_id or approval_rule.approver_user_id

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
        credential_approver = (
            self.credential_approver_id
            or self._get_credential_approver()
            or self._fallback_approval_user()
        )
        super(EmployeeAccessRequest, self).write(
            {
                "manager_approver_id": system_approver.id,
                "credential_approver_id": credential_approver.id,
            }
        )
        self._set_approval_lines(
            system_approver,
            credential_approver,
            erp_state="waiting",
            credential_state="waiting",
        )

    def _set_approval_lines(
        self,
        erp_approver,
        credential_approver,
        erp_state,
        credential_state,
    ):
        self.ensure_one()
        system_role = self._system_approval_role()
        values_by_role = {
            system_role: {
                "sequence": 10,
                "approver_user_id": erp_approver.id,
                "state": erp_state,
            },
            "credential_management": {
                "sequence": 20,
                "approver_user_id": credential_approver.id,
                "state": credential_state,
            },
        }
        obsolete_system_lines = self.approval_line_ids.filtered(
            lambda approval_line: approval_line.role in ("erp_admin", "hrms_admin")
            and approval_line.role != system_role
        )
        obsolete_system_lines.unlink()
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
        credential_approver = (
            self.credential_approver_id
            or self._get_credential_approver()
            or self._fallback_approval_user()
        )
        state_by_request_state = {
            "to_approve": ("to_approve", "waiting"),
            "credential_approval": ("approved", "to_approve"),
            "approved": ("approved", "approved"),
            "provisioning": ("approved", "approved"),
            "active": ("approved", "approved"),
            "inactive": ("approved", "approved"),
        }
        erp_state, credential_state = state_by_request_state.get(
            self.state,
            ("waiting", "waiting"),
        )
        self._set_approval_lines(
            erp_approver,
            credential_approver,
            erp_state,
            credential_state,
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
            credential_approver = (
                request.credential_approver_id
                or request._get_credential_approver()
                or request._fallback_approval_user()
            )
            request.write(
                {
                    "manager_approver_id": erp_approver.id,
                    "credential_approver_id": credential_approver.id,
                }
            )
            request._ensure_approval_lines()
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
        task.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=vendor_owner.id,
            summary=summary,
            note=(
                f"Please complete vendor provisioning for {self.employee_name} "
                f"({self.reference}) in {self.system_id.name}."
            ),
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

    def _subscribe_related_users(self):
        for request in self:
            related_user = request.requested_user_id
            if not related_user and request.employee_email:
                related_user = self.env["res.users"].search(
                    [
                        "|",
                        ("email", "=ilike", request.employee_email),
                        ("login", "=ilike", request.employee_email),
                    ],
                    limit=1,
                )
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
        partner_ids = self.requested_user_id.partner_id.ids
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

    _request_role_uniq = models.Constraint(
        "unique(request_id, role)",
        "Each approval role can appear only once per request.",
    )


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

    _request_application_uniq = models.Constraint(
        "unique(request_id, application_id)",
        "Each application module can appear only once per request.",
    )
