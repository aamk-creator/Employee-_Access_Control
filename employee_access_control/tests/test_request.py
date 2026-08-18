from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install")
class TestEmployeeAccessRequest(TransactionCase):
    def _send_composer_action(self, action):
        self.assertEqual(action["res_model"], "mail.compose.message")
        self.assertEqual(action["target"], "new")
        composer = self.env["mail.compose.message"].with_context(
            action["context"]
        ).create({})
        composer._action_send_mail()
        return composer

    def _complete_approval_flow(self, request):
        request.action_submit()
        request.with_user(request.manager_approver_id).action_manager_approve()
        request.with_user(request.credential_approver_id).action_approve()
        request.invalidate_recordset()

    def test_system_owner_domain_uses_odoo_company_value(self):
        owner_field = self.env["employee.access.system"].fields_get(
            ["owner_id"],
            ["domain"],
        )["owner_id"]

        self.assertEqual(
            owner_field["domain"],
            "[('share', '=', False), ('company_ids', 'in', company_id)]",
        )

    def test_system_code_is_generated_when_not_entered(self):
        system = self.env["employee.access.system"].create(
            {
                "name": "New Payroll System",
                "company_id": self.env.company.id,
            }
        )

        self.assertEqual(system.code, "NEW_PAYROLL_SYSTEM")

    def test_dashboard_uses_system_license_and_created_user_counts(self):
        rows = self.env["employee.access.system"].get_dashboard_data()
        rows_by_name = {row["name"]: row for row in rows}
        Request = self.env["employee.access.request"]

        self.assertEqual(set(rows_by_name), {"Odoo Light", "Odoo Standard"})
        for system_name, row in rows_by_name.items():
            system = self.env["employee.access.system"].search(
                [
                    ("name", "=", system_name),
                    ("company_id", "=", self.env.company.id),
                ],
                limit=1,
            )
            expected_active = Request.search_count(
                [("system_id", "=", system.id), ("state", "=", "active")]
            )
            expected_inactive = Request.search_count(
                [("system_id", "=", system.id), ("state", "=", "inactive")]
            )

            self.assertEqual(row["licensed_users"], system.total_licensed_users)
            self.assertEqual(row["active_users"], expected_active)
            self.assertEqual(row["inactive_users"], expected_inactive)
            self.assertEqual(
                row["swap_users"],
                max(system.total_licensed_users - expected_active, 0),
            )

    def test_active_company_filters_requests_and_dashboard(self):
        current_company = self.env.company
        other_company = self.env["res.company"].create(
            {"name": "Employee Access Isolation Test Company"}
        )
        self.env.user.sudo().write(
            {"company_ids": [Command.link(other_company.id)]}
        )
        access_user = self.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Employee Access Isolation Test User",
                "login": "employee.access.isolation.test",
                "company_id": current_company.id,
                "company_ids": [
                    Command.set([current_company.id, other_company.id])
                ],
                "group_ids": [
                    Command.link(
                        self.env.ref(
                            "employee_access_control.group_employee_access_user"
                        ).id
                    )
                ],
            }
        )

        current_system = self.env["employee.access.system"].search(
            [
                ("name", "=", "Odoo Standard"),
                ("company_id", "=", current_company.id),
            ],
            limit=1,
        )
        other_system = (
            self.env["employee.access.system"]
            .sudo()
            .with_context(allowed_company_ids=[other_company.id])
            .create(
                {
                    "name": "Odoo Standard",
                    "company_id": other_company.id,
                    "total_licensed_users": 10,
                }
            )
        )
        Request = self.env["employee.access.request"].sudo()
        current_request = Request.create(
            {
                "employee_name": "Current Company User",
                "employee_email": "current.company@example.com",
                "company_id": current_company.id,
                "system_id": current_system.id,
                "state": "active",
            }
        )
        other_request = Request.with_context(
            allowed_company_ids=[other_company.id]
        ).create(
            {
                "employee_name": "Other Company User",
                "employee_email": "other.company@example.com",
                "company_id": other_company.id,
                "system_id": other_system.id,
                "state": "active",
            }
        )

        candidate_ids = [current_request.id, other_request.id]
        current_company_requests = (
            self.env["employee.access.request"]
            .with_user(access_user)
            .with_context(allowed_company_ids=[current_company.id])
            .search([("id", "in", candidate_ids)])
        )
        other_company_requests = (
            self.env["employee.access.request"]
            .with_user(access_user)
            .with_context(allowed_company_ids=[other_company.id])
            .search([("id", "in", candidate_ids)])
        )

        self.assertEqual(current_company_requests.ids, current_request.ids)
        self.assertEqual(other_company_requests.ids, other_request.ids)

        dashboard_rows = (
            self.env["employee.access.system"]
            .with_user(access_user)
            .with_context(allowed_company_ids=[other_company.id])
            .get_dashboard_data()
        )
        standard_row = next(
            row for row in dashboard_rows if row["name"] == "Odoo Standard"
        )
        self.assertEqual(standard_row["active_users"], 1)
        self.assertEqual(standard_row["licensed_users"], 10)

    def test_internal_employee_access_module_is_excluded(self):
        Application = self.env["employee.access.application"].with_context(
            active_test=False
        )

        Application._exclude_internal_employee_access_modules()

        applications = Application.search(
            [
                ("name", "=", "Employee Access Control"),
                ("system_id.name", "in", ["Odoo Light", "Odoo Standard"]),
            ]
        )
        self.assertTrue(applications)
        self.assertFalse(any(applications.mapped("active")))

    def test_company_seed_is_complete_and_idempotent(self):
        company_names = {
            "CLL Health Holdings Ltd",
            "OEC Healthcare Co Ltd",
            "CLL Primary Care Co Ltd",
            "SSP Healthcare Co Ltd",
            "Care for Life and Longevity Co Ltd",
            "Right Healthcare Co Ltd",
            "Right Medical Centre",
            "AYTK Healthcare Co Ltd",
            "CLL Ambulatory Care Co Ltd",
            "CoreLink Labs Co Ltd",
            "IET For Life Co Ltd",
            "CLL Radiology Co Ltd",
            "CLL Medical Transport Services Co Ltd",
            "CLL Home Care Co Ltd",
            "CLL Diagnostics Co Ltd",
            "Hope Healthcare Co Ltd",
            "Ingyin Phyu Clinic",
            "CLL Health Stores",
            "AHARA",
            "Bahosi Fertility Centre Co Ltd",
            "Mahar Myaing Clinic",
        }
        Company = self.env["res.company"].with_context(active_test=False)

        Company._ensure_employee_access_companies()
        Company._ensure_employee_access_companies()

        companies = Company.search([("name", "in", list(company_names))])
        self.assertEqual(set(companies.mapped("name")), company_names)
        self.assertEqual(len(companies), len(company_names))

    def test_odoo_standard_application_roles_are_seeded(self):
        AccessGroup = self.env["employee.access.group"].with_context(active_test=False)
        Application = self.env["employee.access.application"].with_context(active_test=False)

        AccessGroup._load_sample_groups()

        applications = Application.search(
            [
                ("company_id", "=", self.env.company.id),
                ("system_id.name", "=", "Odoo Standard"),
                ("active", "=", True),
            ]
        )
        missing_applications = []
        roles_by_application = {}
        for application in applications:
            roles = AccessGroup.search(
                [
                    ("company_id", "=", self.env.company.id),
                    ("system_id.name", "=", "Odoo Standard"),
                    ("application_id", "=", application.id),
                    ("display_type", "=", "application_role"),
                    ("active", "=", True),
                ]
            )
            roles_by_application[application.name] = set(roles.mapped("name"))
            if not roles:
                missing_applications.append(application.name)

        self.assertFalse(missing_applications)
        self.assertEqual(
            roles_by_application["Dashboard"],
            {"Admin", "User"},
        )
        self.assertEqual(
            roles_by_application["Purchase"],
            {"User", "Subcon User", "Administrator"},
        )
        self.assertEqual(
            roles_by_application["Surveys"],
            {"User", "Administrator"},
        )

    def test_default_system_uses_first_available_system(self):
        expected_system = self.env["employee.access.system"].search(
            [],
            order="sequence asc, name asc",
            limit=1,
        )

        defaults = self.env["employee.access.request"].default_get(["system_id"])

        self.assertEqual(defaults.get("system_id"), expected_system.id)

    def test_employee_source_supports_odoo_user_and_manual_entry(self):
        system = self.env["employee.access.system"].search([], limit=1)
        odoo_request = self.env["employee.access.request"].create(
            {
                "requested_user_id": self.env.user.id,
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )
        manual_request = self.env["employee.access.request"].create(
            {
                "employee_source": "manual",
                "employee_name": "Manual Employee",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self.assertEqual(odoo_request.employee_source, "odoo_user")
        self.assertEqual(odoo_request.employee_display_name, self.env.user.name)
        self.assertEqual(manual_request.employee_source, "manual")
        self.assertEqual(manual_request.employee_display_name, "Manual Employee")

    def test_request_automatically_includes_system_applications(self):
        system = self.env["employee.access.system"].search([], limit=1)
        expected_applications = self.env["employee.access.application"].search(
            [("system_id", "=", system.id), ("active", "=", True)]
        )
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Application Test User",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self.assertTrue(expected_applications)
        self.assertEqual(request.application_ids, expected_applications)
        request.action_submit()
        self.assertEqual(request.state, "to_approve")

    def test_changing_system_replaces_application_access(self):
        systems = self.env["employee.access.system"].search([], limit=2)
        self.assertEqual(len(systems), 2)
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "System Change Test User",
                "company_id": self.env.company.id,
                "system_id": systems[0].id,
            }
        )

        request.write({"system_id": systems[1].id})

        expected_applications = self.env["employee.access.application"].search(
            [("system_id", "=", systems[1].id), ("active", "=", True)]
        )
        self.assertEqual(request.application_ids, expected_applications)

    def test_missing_application_is_restored_from_selected_access_role(self):
        system = self.env["employee.access.system"].search(
            [("name", "=", "Odoo Standard")],
            limit=1,
        ) or self.env["employee.access.system"].search([], limit=1)
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Application Payload Repair User",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )
        source_line = request.application_line_ids.filtered("access_group_id")[:1]
        self.assertTrue(source_line)
        access_group = source_line.access_group_id

        request.write(
            {
                "application_line_ids": [
                    Command.clear(),
                    Command.create(
                        {"access_group_id": access_group.id}
                    ),
                ]
            }
        )

        self.assertEqual(len(request.application_line_ids), 1)
        self.assertEqual(
            request.application_line_ids.application_id,
            access_group.application_id,
        )
        request_view = self.env.ref(
            "employee_access_control.view_employee_access_request_form"
        )
        self.assertIn('force_save="1"', request_view.arch_db)

    def test_request_rejects_application_from_another_system(self):
        applications = self.env["employee.access.application"].search(
            [("system_id", "!=", False)],
            order="system_id",
        )
        first_application = applications[0]
        other_application = applications.filtered(
            lambda application: application.system_id != first_application.system_id
        )[:1]
        self.assertTrue(other_application)

        with self.assertRaises(ValidationError):
            self.env["employee.access.request"].create(
                {
                    "employee_name": "Invalid Application Test User",
                    "company_id": self.env.company.id,
                    "system_id": first_application.system_id.id,
                    "application_line_ids": [
                        Command.create({"application_id": other_application.id})
                    ],
                }
            )

    def test_module_can_be_removed_for_one_request(self):
        system = self.env["employee.access.system"].search([], limit=1)
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Special Access Test User",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )
        line = request.application_line_ids[:1]
        original_count = request.application_count

        line.remove_access = True

        self.assertNotIn(line.application_id, request.application_ids)
        self.assertEqual(request.application_count, original_count - 1)

    def test_approve_creates_profile_task_and_audit_entries(self):
        system = self.env["employee.access.system"].search([], limit=1)
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Provision User",
                "employee_email": "provision@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self._complete_approval_flow(request)

        self.assertEqual(request.state, "approved")
        self.assertTrue(request.profile_id)
        self.assertEqual(request.profile_id.state, "pending")
        self.assertEqual(len(request.provisioning_task_ids), 1)
        self.assertEqual(request.provisioning_task_ids.state, "pending")
        self.assertTrue(
            request.audit_log_ids.filtered(lambda log: log.event_type == "approved")
        )
        self.assertTrue(
            request.audit_log_ids.filtered(lambda log: log.event_type == "task_created")
        )

    def test_mark_active_syncs_profile_and_completes_task(self):
        system = self.env["employee.access.system"].search([], limit=1)
        recipient = self.env["res.partner"].create(
            {"name": "Vendor Tickets", "email": "vendor.tickets@example.com"}
        )
        system.mail_recipient_ids = [Command.set(recipient.ids)]
        companies = self.env["res.company"].search([], limit=2)
        facilities = self.env["employee.access.facility"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Active User",
                "employee_email": "active@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
                "access_company_ids": [Command.set(companies.ids)],
                "access_facility_ids": [Command.set(facilities.ids)],
                "required_privileged_access": True,
            }
        )

        self._complete_approval_flow(request)
        request.action_start_provisioning()
        request.action_mark_active()

        self.assertEqual(request.state, "active")
        self.assertEqual(request.access_status, "active")
        self.assertTrue(request.active_date)
        self.assertFalse(request.inactive_date)
        self.assertEqual(request.profile_id.state, "active")
        self.assertEqual(request.provisioning_task_ids.state, "done")
        self.assertEqual(request.profile_id.application_ids, request.application_ids)
        self.assertEqual(request.profile_id.access_company_ids, request.access_company_ids)
        self.assertEqual(request.profile_id.access_facility_ids, request.access_facility_ids)
        self.assertTrue(request.profile_id.required_privileged_access)

        request.provisioning_task_ids.action_mark_user_inactive()

        self.assertEqual(request.state, "inactive")
        self.assertEqual(request.access_status, "inactive")
        self.assertTrue(request.inactive_date)
        self.assertEqual(request.profile_id.state, "revoked")
        self.assertTrue(
            request.audit_log_ids.filtered(
                lambda log: log.event_type == "deactivated"
            )
        )

        request.provisioning_task_ids.action_reactivate_user()

        self.assertEqual(request.state, "active")
        self.assertEqual(request.access_status, "active")
        self.assertFalse(request.inactive_date)
        self.assertEqual(request.profile_id.state, "active")
        self.assertTrue(
            request.audit_log_ids.filtered(
                lambda log: log.event_type == "reactivated"
            )
        )

    def test_request_follows_erp_credential_vendor_ticket_flow(self):
        system = self.env["employee.access.system"].search(
            [("name", "=", "Odoo Standard")],
            limit=1,
        ) or self.env["employee.access.system"].search([], limit=1)
        system.write(
            {
                "owner_id": self.env.user.id,
                "mail_recipient_ids": [
                    Command.set(
                        self.env["res.partner"]
                        .create({"name": "Odoo Vendor", "email": "odoo.vendor@example.com"})
                        .ids
                    )
                ],
                "vendor_portal_url": "https://support.vendor.example.com",
            }
        )
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Staged Approval User",
                "employee_email": "staged.approval@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        request.action_submit()

        self.assertEqual(request.state, "to_approve")
        self.assertTrue(request.requires_erp_admin_approval)
        self.assertFalse(request.requires_hrms_admin_approval)
        self.assertEqual(request.list_status_label, "Submitted for Approval")
        self.assertEqual(
            request.approval_status_label,
            "Waiting ERP Admin Approval",
        )
        self.assertEqual(len(request.approval_line_ids), 2)
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "erp_admin"
            ).state,
            "to_approve",
        )
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "credential_management"
            ).state,
            "waiting",
        )
        with self.assertRaises(ValidationError):
            request.action_approve()

        request.with_user(request.manager_approver_id).action_manager_approve()
        request.invalidate_recordset()

        self.assertEqual(request.state, "credential_approval")
        self.assertEqual(
            request.approval_status_label,
            "Waiting Credential Management Approval",
        )
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "erp_admin"
            ).state,
            "approved",
        )
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "credential_management"
            ).state,
            "to_approve",
        )

        request.with_user(request.credential_approver_id).action_approve()
        request.invalidate_recordset()

        self.assertEqual(request.state, "approved")
        self.assertEqual(request.list_status_label, "Waiting for Vendor")
        self.assertEqual(request.approval_status_label, "All Approved")
        self.assertEqual(set(request.approval_line_ids.mapped("state")), {"approved"})
        self.assertEqual(request.provisioning_task_ids.assigned_user_id, self.env.user)

        compose_action = request.action_start_provisioning()
        self.assertEqual(request.state, "provisioning")
        ticket = request.provisioning_task_ids
        self.assertEqual(ticket.assigned_user_id, system.owner_id)
        self.assertEqual(ticket.ticket_reference, request.reference)
        self.assertEqual(ticket.vendor_email, "odoo.vendor@example.com")
        self.assertEqual(ticket.vendor_portal_url, system.vendor_portal_url)
        self.assertFalse(ticket.first_sent_on)
        self.assertFalse(ticket.last_vendor_message_id)
        self.assertEqual(
            compose_action["context"]["default_partner_ids"],
            system.mail_recipient_ids.ids,
        )
        self.assertEqual(
            compose_action["context"]["default_subject"],
            ticket.vendor_subject,
        )
        self.assertEqual(
            compose_action["context"]["default_model"],
            "employee.access.provision.task",
        )
        self.assertEqual(compose_action["context"]["default_res_ids"], ticket.ids)

        self._send_composer_action(compose_action)
        ticket.invalidate_recordset()
        self.assertTrue(ticket.first_sent_on)
        self.assertTrue(ticket.last_vendor_message_id)
        self.assertEqual(
            ticket.last_vendor_message_id.partner_ids,
            system.mail_recipient_ids,
        )
        self.assertEqual(
            ticket.last_vendor_message_id.model,
            "employee.access.provision.task",
        )
        self.assertEqual(ticket.last_vendor_message_id.res_id, ticket.id)
        self.assertIn(ticket.ticket_reference, ticket.vendor_subject)
        self.assertNotIn(f"({request.reference})", ticket.vendor_subject)
        self.assertTrue(
            ticket.activity_ids.filtered(
                lambda activity: activity.summary == "Vendor provisioning required"
                and activity.user_id == system.owner_id
            )
        )
        self.assertTrue(
            ticket.message_ids.filtered(
                lambda message: "Admin notification sent" in (message.body or "")
            )
        )

        notification_logs = request.audit_log_ids.filtered(
            lambda log: log.event_type == "vendor_notification_sent"
        )
        self.assertEqual(len(notification_logs), 1)

        resend_action = request.action_resend_vendor_notification()
        self.assertEqual(ticket.resend_count, 0)
        self.assertTrue(resend_action["context"]["employee_access_vendor_resend"])
        self._send_composer_action(resend_action)
        ticket.invalidate_recordset()
        self.assertEqual(ticket.resend_count, 1)
        self.assertTrue(ticket.last_sent_on)
        notification_logs = request.audit_log_ids.filtered(
            lambda log: log.event_type == "vendor_notification_sent"
        )
        self.assertEqual(len(notification_logs), 2)

        request.action_mark_active()
        self.assertEqual(request.state, "active")
        self.assertEqual(request.list_status_label, "Done")
        self.assertFalse(
            ticket.activity_ids.filtered(
                lambda activity: activity.summary == "Vendor provisioning required"
                and activity.active
            )
        )

    def test_vendor_ticket_email_uses_multiple_system_recipients(self):
        system = self.env["employee.access.system"].search([], limit=1)
        recipients = self.env["res.partner"].create(
            [
                {"name": "Vendor Support", "email": "support@example.com"},
                {"name": "System Owner", "email": "owner@example.com"},
            ]
        )
        system.write(
            {
                "mail_recipient_ids": [Command.set(recipients.ids)],
            }
        )
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Multi Recipient User",
                "employee_email": "multi.recipient@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self._complete_approval_flow(request)
        compose_action = request.action_start_provisioning()

        ticket = request.provisioning_task_ids
        self.assertEqual(ticket.vendor_email, "support@example.com, owner@example.com")
        self._send_composer_action(compose_action)
        ticket.invalidate_recordset()
        self.assertEqual(
            ticket.last_vendor_message_id.partner_ids,
            recipients,
        )

    def test_odoo_light_uses_hrms_admin_and_default_credential_approver(self):
        system = self.env["employee.access.system"].search(
            [("name", "=", "Odoo Light")],
            limit=1,
        )
        self.assertTrue(system)
        approval_rule = self.env["employee.access.approval.rule"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("model_name", "=", "employee_access_control"),
                ("active", "=", True),
            ],
            limit=1,
        )
        credential_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == "Credential Management"
        )[:1]
        credential_step.approver_user_id = self.env.user

        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Light Approval User",
                "employee_email": "light.approval@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self.assertFalse(request.requires_erp_admin_approval)
        self.assertTrue(request.requires_hrms_admin_approval)
        self.assertTrue(request.requires_credential_approval)
        self.assertEqual(request.approval_rule_id, approval_rule)
        self.assertEqual(request.credential_approver_id, self.env.user)
        self.assertEqual(len(request.approval_line_ids), 2)
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "hrms_admin"
            ).state,
            "waiting",
        )
        self.assertFalse(
            request.approval_line_ids.filtered(
                lambda line: line.role == "erp_admin"
            )
        )

        request.action_submit()

        self.assertEqual(
            request.approval_status_label,
            "Waiting HRMS Admin Approval",
        )
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "hrms_admin"
            ).state,
            "to_approve",
        )

    def test_same_system_existing_active_access_forces_update_request_type(self):
        systems = self.env["employee.access.system"].search(
            [("name", "in", ["Odoo Light", "Odoo Standard"])],
            order="name asc",
        )
        light_system = systems.filtered(lambda system: system.name == "Odoo Light")[:1]
        self.assertTrue(light_system)

        self.env["employee.access.profile"].create(
            {
                "employee_name": "Upgrade User",
                "employee_email": "upgrade@example.com",
                "company_id": self.env.company.id,
                "system_id": light_system.id,
                "state": "active",
            }
        )

        request = self.env["employee.access.request"].new(
            {
                "employee_name": "Upgrade User",
                "employee_email": "upgrade@example.com",
                "company_id": self.env.company.id,
                "system_id": light_system.id,
            }
        )
        request._onchange_system_id()

        self.assertEqual(request.request_type, "update")
        self.assertTrue(request.duplicate_create_blocked)

    def test_light_to_standard_access_defaults_to_create_request_type(self):
        systems = self.env["employee.access.system"].search(
            [("name", "in", ["Odoo Light", "Odoo Standard"])],
            order="name asc",
        )
        light_system = systems.filtered(lambda system: system.name == "Odoo Light")[:1]
        standard_system = systems.filtered(lambda system: system.name == "Odoo Standard")[:1]
        self.assertTrue(light_system)
        self.assertTrue(standard_system)

        self.env["employee.access.profile"].create(
            {
                "employee_name": "Upgrade User",
                "employee_email": "upgrade@example.com",
                "company_id": self.env.company.id,
                "system_id": light_system.id,
                "state": "active",
            }
        )

        request = self.env["employee.access.request"].new(
            {
                "employee_name": "Upgrade User",
                "employee_email": "upgrade@example.com",
                "company_id": self.env.company.id,
                "system_id": standard_system.id,
            }
        )
        request._onchange_system_id()

        self.assertEqual(request.request_type, "create")
        self.assertFalse(request.duplicate_create_blocked)

    def test_standard_to_light_access_defaults_to_create_request_type(self):
        systems = self.env["employee.access.system"].search(
            [("name", "in", ["Odoo Light", "Odoo Standard"])],
            order="name asc",
        )
        light_system = systems.filtered(lambda system: system.name == "Odoo Light")[:1]
        standard_system = systems.filtered(lambda system: system.name == "Odoo Standard")[:1]
        self.assertTrue(light_system)
        self.assertTrue(standard_system)

        self.env["employee.access.profile"].create(
            {
                "employee_name": "Downgrade User",
                "employee_email": "downgrade@example.com",
                "company_id": self.env.company.id,
                "system_id": standard_system.id,
                "state": "active",
            }
        )

        request = self.env["employee.access.request"].new(
            {
                "employee_name": "Downgrade User",
                "employee_email": "downgrade@example.com",
                "company_id": self.env.company.id,
                "system_id": light_system.id,
            }
        )
        request._onchange_system_id()

        self.assertEqual(request.request_type, "create")
        self.assertFalse(request.duplicate_create_blocked)

    def test_duplicate_create_is_normalized_to_update(self):
        system = self.env["employee.access.system"].search(
            [("name", "=", "Odoo Light")],
            limit=1,
        ) or self.env["employee.access.system"].search([], limit=1)

        self.env["employee.access.profile"].create(
            {
                "employee_name": "Duplicate User",
                "employee_email": "duplicate@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
                "state": "active",
            }
        )

        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Duplicate User",
                "employee_email": "duplicate@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
                "request_type": "create",
            }
        )

        self.assertEqual(request.request_type, "update")
        request.action_submit()
        self.assertEqual(request.state, "to_approve")
