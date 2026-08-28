from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EmployeeAccessProfile(models.Model):
    _name = "employee.access.profile"
    _description = "Employee Access Profile"
    _order = "employee_name, system_id, id desc"
    _check_company_auto = True
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name")
    employee_name = fields.Char(required=True)
    fingerprint_id = fields.Char(string="Fingerprint ID")
    employee_email = fields.Char(string="Employee Email")
    department = fields.Char()
    position = fields.Char()
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
    )
    system_id = fields.Many2one(
        "employee.access.system",
        string="System",
        required=True,
        ondelete="restrict",
    )
    access_company_ids = fields.Many2many(
        "res.company",
        "employee_access_profile_company_rel",
        "profile_id",
        "company_id",
        string="Access Companies",
    )
    access_facility_ids = fields.Many2many(
        "employee.access.facility",
        "employee_access_profile_facility_rel",
        "profile_id",
        "facility_id",
        string="Access Facilities",
        domain="[('company_id', 'in', access_company_ids), ('active', '=', True)]",
    )
    application_ids = fields.Many2many(
        "employee.access.application",
        "employee_access_profile_application_rel",
        "profile_id",
        "application_id",
        string="Granted Applications",
        domain="[('system_id', '=', system_id), ('active', '=', True)]",
    )
    required_privileged_access = fields.Boolean(string="Required Privileged Access")
    state = fields.Selection(
        [
            ("pending", "Pending Provisioning"),
            ("active", "Active"),
            ("revoked", "Revoked"),
        ],
        required=True,
        default="pending",
    )
    request_ids = fields.One2many(
        "employee.access.request",
        "profile_id",
        string="Requests",
    )
    provisioning_task_ids = fields.One2many(
        "employee.access.provision.task",
        "profile_id",
        string="Provisioning Tasks",
    )
    audit_log_ids = fields.One2many(
        "employee.access.audit.log",
        "profile_id",
        string="Audit History",
    )
    last_request_id = fields.Many2one(
        "employee.access.request",
        string="Last Request",
        readonly=True,
        ondelete="set null",
    )
    last_provisioned_on = fields.Datetime(string="Last Provisioned On", readonly=True)
    last_provisioned_by_id = fields.Many2one(
        "res.users",
        string="Last Provisioned By",
        readonly=True,
        ondelete="set null",
    )

    @api.depends("employee_name", "system_id.name")
    def _compute_display_name(self):
        for profile in self:
            parts = [profile.employee_name or ""]
            if profile.system_id:
                parts.append(profile.system_id.name)
            profile.display_name = " - ".join(filter(bool, parts))


class EmployeeAccessProvisionTask(models.Model):
    _name = "employee.access.provision.task"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Employee Access Provisioning Task"
    _order = "create_date desc, id desc"
    _check_company_auto = True
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name")
    ticket_reference = fields.Char(
        string="Ticket",
        required=True,
        copy=False,
        readonly=True,
        default="New",
        index=True,
    )
    request_id = fields.Many2one(
        "employee.access.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    profile_id = fields.Many2one(
        "employee.access.profile",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="request_id.company_id",
        store=True,
        readonly=True,
    )
    system_id = fields.Many2one(
        "employee.access.system",
        related="request_id.system_id",
        store=True,
        readonly=True,
    )
    request_access_status = fields.Selection(
        related="request_id.access_status",
        string="User Status",
        readonly=True,
    )
    employee_email = fields.Char(
        related="request_id.employee_email",
        string="Employee Email",
        readonly=True,
    )
    fingerprint_id = fields.Char(
        related="request_id.fingerprint_id",
        string="Fingerprint ID",
        readonly=True,
    )
    assigned_user_id = fields.Many2one(
        "res.users",
        string="Assigned To",
        default=lambda self: self.env.user,
        domain="[('share', '=', False)]",
    )
    vendor_email = fields.Char(string="Vendor Email", readonly=True, tracking=True)
    vendor_subject = fields.Char(string="Email Subject", readonly=True)
    vendor_portal_url = fields.Char(string="Vendor Portal URL", readonly=True)
    external_ticket_reference = fields.Char(
        string="Vendor Ticket Reference",
        tracking=True,
        help="Ticket number returned by the external vendor helpdesk.",
    )
    first_sent_on = fields.Datetime(string="First Sent On", readonly=True)
    last_sent_on = fields.Datetime(string="Last Sent On", readonly=True)
    resend_count = fields.Integer(string="Resend Count", readonly=True)
    last_vendor_message_id = fields.Many2one(
        "mail.message",
        string="Last Vendor Email",
        readonly=True,
        ondelete="set null",
    )
    state = fields.Selection(
        [
            ("pending", "Ready to Send"),
            ("in_progress", "Waiting for Vendor"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
    )
    note = fields.Text(string="Provisioning Notes")
    started_on = fields.Datetime(readonly=True)
    completed_on = fields.Datetime(readonly=True)
    completed_by_id = fields.Many2one(
        "res.users",
        string="Completed By",
        readonly=True,
        ondelete="set null",
    )
    audit_log_ids = fields.One2many(
        "employee.access.audit.log",
        "task_id",
        string="Audit History",
    )

    @api.model_create_multi
    def create(self, vals_list):
        request_ids = {
            vals.get("request_id")
            for vals in vals_list
            if vals.get("request_id")
            and vals.get("ticket_reference") in (None, False, "New")
        }
        requests = self.env["employee.access.request"].browse(request_ids)
        request_refs = {request.id: request.reference for request in requests}
        for vals in vals_list:
            request_id = vals.get("request_id")
            if request_id and vals.get("ticket_reference") in (None, False, "New"):
                vals["ticket_reference"] = request_refs.get(request_id) or "New"
        return super().create(vals_list)

    def init(self):
        self.env.cr.execute(
            "SELECT to_regclass('employee_access_provision_task'), to_regclass('employee_access_request')"
        )
        task_table, request_table = self.env.cr.fetchone()
        if not task_table or not request_table:
            return

        self.env.cr.execute(
            """
            UPDATE employee_access_provision_task task
               SET ticket_reference = request.reference
              FROM employee_access_request request
             WHERE task.request_id = request.id
               AND task.ticket_reference LIKE 'VT%%'
               AND request.reference IS NOT NULL
               AND request.reference != ''
            """
        )
        self.env.cr.execute(
            """
            UPDATE mail_message message
               SET model = 'employee.access.request',
                   res_id = task.request_id,
                   message_type = 'email'
              FROM employee_access_provision_task task
             WHERE message.id = task.last_vendor_message_id
               AND (
                    message.model != 'employee.access.request'
                    OR message.res_id != task.request_id
                    OR message.message_type != 'email'
               )
            """
        )
        self.env.cr.execute(
            """
            UPDATE mail_activity activity
               SET res_model_id = task_model.id,
                   res_id = task.id
              FROM employee_access_provision_task task,
                   ir_model request_model,
                   ir_model task_model
             WHERE request_model.model = 'employee.access.request'
               AND task_model.model = 'employee.access.provision.task'
               AND activity.res_model_id = request_model.id
               AND activity.res_id = task.request_id
               AND activity.summary = 'Vendor provisioning required'
            """
        )

    @api.depends("ticket_reference", "request_id.employee_name", "system_id.name")
    def _compute_display_name(self):
        for task in self:
            parts = [task.ticket_reference or "", task.request_id.employee_name or ""]
            if task.system_id:
                parts.append(task.system_id.name)
            task.display_name = " - ".join(filter(bool, parts)) or "Provisioning Task"

    def action_resend_notification(self):
        for task in self:
            task.request_id.action_resend_vendor_notification()

    def action_open_request(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Odoo User Account Request",
            "res_model": "employee.access.request",
            "view_mode": "form",
            "res_id": self.request_id.id,
            "target": "current",
        }

    def action_start(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state == "pending":
            self.write(
                {
                    "state": "in_progress",
                    "started_on": now,
                }
            )
            self.request_id.write({"state": "provisioning"})
            self.request_id._log_event(
                "provisioning_started",
                "Request sent to the vendor. Vendor ticket is in progress.",
                task=self,
            )
        return self.request_id._open_vendor_ticket_email_composer(self, resend=False)

    def action_mark_done(self):
        now = fields.Datetime.now()
        action = False
        for task in self:
            if task.state != "in_progress":
                raise ValidationError(
                    "Send the vendor ticket before marking it as done."
                )
            if not task.first_sent_on:
                raise ValidationError(
                    "Send the vendor email before marking the request as done."
                )
            task.request_id._check_mark_done_user()
            odoo_user = task.request_id._sync_odoo_user_account()
            task.write(
                {
                    "state": "done",
                    "completed_on": now,
                    "completed_by_id": self.env.user.id,
                }
            )
            task.request_id._sync_profile_from_request(task.profile_id)
            task.profile_id.write(
                {
                    "state": "active",
                    "last_request_id": task.request_id.id,
                    "last_provisioned_on": now,
                    "last_provisioned_by_id": self.env.user.id,
                }
            )
            task.request_id._complete_vendor_activity()
            task.request_id.write({"state": "active"})
            task.request_id._log_event(
                "provisioned",
                (
                    f"Vendor ticket finished. Odoo user {odoo_user.login} was "
                    "created or updated and the request was completed."
                    if odoo_user
                    else "Vendor ticket finished. Access profile activated and request completed."
                ),
                profile=task.profile_id,
                task=task,
            )
            action = task.request_id._odoo_user_form_action(odoo_user)
        return action

    def action_mark_user_inactive(self):
        for task in self:
            task.request_id.action_mark_inactive()

    def action_reactivate_user(self):
        for task in self:
            task.request_id.action_reactivate()

    def action_mark_failed(self):
        for task in self:
            task.write({"state": "failed"})
            task.request_id.write({"state": "approved"})
            task.request_id._log_event(
                "provisioning_failed",
                "Provisioning failed.",
                task=task,
            )

    def action_cancel(self):
        for task in self:
            task.write({"state": "cancelled"})
            task.request_id._log_event(
                "provisioning_cancelled",
                "Provisioning task cancelled.",
                task=task,
            )


class EmployeeAccessAuditLog(models.Model):
    _name = "employee.access.audit.log"
    _description = "Employee Access Audit History"
    _order = "performed_on desc, id desc"
    _check_company_auto = True

    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
    )
    request_id = fields.Many2one(
        "employee.access.request",
        ondelete="cascade",
        index=True,
    )
    profile_id = fields.Many2one(
        "employee.access.profile",
        ondelete="cascade",
        index=True,
    )
    task_id = fields.Many2one(
        "employee.access.provision.task",
        ondelete="cascade",
        index=True,
    )
    event_type = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("manager_approved", "System Admin Approved"),
            ("credential_approved", "Credential Approved"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("reset", "Reset"),
            ("profile_linked", "Profile Linked"),
            ("task_created", "Task Created"),
            ("provisioning_started", "Provisioning Started"),
            ("vendor_notification_sent", "Vendor Notification Sent"),
            ("provisioned", "Provisioned"),
            ("deactivated", "Deactivated"),
            ("reactivated", "Reactivated"),
            ("provisioning_failed", "Provisioning Failed"),
            ("provisioning_cancelled", "Provisioning Cancelled"),
        ],
        required=True,
    )
    message = fields.Text(required=True)
    performed_by_id = fields.Many2one(
        "res.users",
        string="Performed By",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
    )
    performed_on = fields.Datetime(required=True, default=fields.Datetime.now)
