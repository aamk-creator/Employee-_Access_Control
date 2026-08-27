from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install")
class TestEmployeeAccessRequest(TransactionCase):
    def setUp(self):
        super().setUp()

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

    def test_odoo_system_ui_configuration_is_seeded(self):
        System = self.env["employee.access.system"]
        System._configure_odoo_systems()

        expected_values = {
            "Odoo Light": (
                "light",
                "Light Users",
                "HRMS Admin(Light)",
            ),
            "Odoo Standard": (
                "standard",
                "Standard Users",
                "ERP Admin (Standard)",
            ),
        }
        for system_name, (user_type, tag_name, request_step_name) in (
            expected_values.items()
        ):
            system = System.search(
                [
                    ("company_id", "=", self.env.company.id),
                    ("name", "=", system_name),
                ],
                limit=1,
            )
            self.assertTrue(system.is_odoo_system)
            self.assertEqual(system.user_type, user_type)
            self.assertIn(tag_name, system.tag_ids.mapped("name"))
            self.assertEqual(system.request_approver_step_id.name, request_step_name)
            self.assertFalse(system.handover_approver_step_id)

        system_view = self.env.ref(
            "employee_access_control.view_employee_access_system_form"
        )
        self.assertIn("recipient_employee_ids", system_view.arch_db)
        self.assertIn('name="mail_recipient_ids" invisible="1"', system_view.arch_db)

    def test_system_approver_configuration_controls_request_workflow(self):
        system = self.env["employee.access.system"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("name", "=", "Odoo Standard"),
            ],
            limit=1,
        )
        system._configure_odoo_systems()
        approval_rule = self.env["employee.access.approval.rule"].search(
            [
                ("company_id", "=", self.env.company.id),
                ("model_name", "=", "employee_access_control"),
                ("active", "=", True),
            ],
            limit=1,
        )
        request_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == "ERP Admin (Standard)"
        )[:1]
        handover_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == "Mark Done"
        )[:1]
        request_approver = self.env["res.users"].create(
            {
                "name": "Configured Request Approver",
                "login": "configured.request.approver@example.com",
                "email": "configured.request.approver@example.com",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
            }
        )
        handover_approver = self.env["res.users"].create(
            {
                "name": "Configured Handover Approver",
                "login": "configured.handover.approver@example.com",
                "email": "configured.handover.approver@example.com",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
            }
        )
        request_step.approver_user_id = request_approver
        handover_step.approver_user_id = handover_approver
        system.write(
            {
                "request_approver_step_id": request_step.id,
                "handover_approver_step_id": handover_step.id,
            }
        )
        employee = self.env["hr.employee"].create(
            {
                "name": "Configured Workflow Employee",
                "company_id": self.env.company.id,
            }
        )
        request = self.env["employee.access.request"].create(
            {
                "employee_id": employee.id,
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self.assertEqual(request._get_erp_admin_approver(), request_approver)
        self.assertEqual(request._get_mark_done_user(), handover_approver)
        self.assertEqual(request.manager_approver_id, request_approver)
        self.assertEqual(request.mark_done_user_id, handover_approver)

    def test_facility_catalog_is_seeded_for_all_companies_and_idempotent(self):
        Facility = self.env["employee.access.facility"].with_context(
            active_test=False
        )
        companies = self.env["res.company"].with_context(active_test=False).search([])
        catalog = Facility._employee_access_facility_catalog
        catalog_codes = [label.rsplit(" - ", 1)[1] for label in catalog]

        Facility._ensure_employee_access_facilities()
        initial_count = Facility.search_count([("code", "in", catalog_codes)])
        Facility._ensure_employee_access_facilities()

        self.assertEqual(
            Facility.search_count([("code", "in", catalog_codes)]),
            initial_count,
        )
        for company in companies:
            facilities = Facility.search(
                [
                    ("company_id", "=", company.id),
                    ("code", "in", catalog_codes),
                ]
            )
            self.assertEqual(len(facilities), 32)
            self.assertEqual(set(facilities.mapped("name")), set(catalog))
            self.assertTrue(all(facilities.mapped("active")))

    def test_new_company_automatically_receives_facility_catalog(self):
        company = self.env["res.company"].create(
            {"name": "Facility Catalog Test Company"}
        )
        facilities = self.env["employee.access.facility"].search(
            [("company_id", "=", company.id)]
        )

        self.assertEqual(len(facilities), 32)
        self.assertIn("P005", facilities.mapped("code"))
        self.assertIn("L018", facilities.mapped("code"))

    def test_access_facilities_follow_selected_company_across_companies(self):
        access_company = self.env["res.company"].create(
            {"name": "Cross Company Facility Parent"}
        )
        facility = self.env["employee.access.facility"].search(
            [("company_id", "=", access_company.id)],
            limit=1,
        )
        system = self.env["employee.access.system"].search([], limit=1)

        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Cross Company Facility Selection User",
                "company_id": self.env.company.id,
                "system_id": system.id,
                "access_company_ids": [Command.set(access_company.ids)],
                "access_facility_ids": [Command.set(facility.ids)],
            }
        )

        self.assertEqual(request.access_company_ids, access_company)
        self.assertEqual(request.access_facility_ids, facility)

        current_company_facility = self.env["employee.access.facility"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        with self.assertRaisesRegex(
            ValidationError,
            "Every access facility must belong",
        ):
            request.access_facility_ids = [Command.set(current_company_facility.ids)]

    def test_removing_access_company_clears_its_facilities(self):
        first_company, second_company = self.env["res.company"].create(
            [
                {"name": "First Facility Parent"},
                {"name": "Second Facility Parent"},
            ]
        )
        first_facility = self.env["employee.access.facility"].search(
            [("company_id", "=", first_company.id)],
            limit=1,
        )
        second_facility = self.env["employee.access.facility"].search(
            [("company_id", "=", second_company.id)],
            limit=1,
        )
        request = self.env["employee.access.request"].new(
            {
                "access_company_ids": [
                    Command.set([first_company.id, second_company.id])
                ],
                "access_facility_ids": [
                    Command.set([first_facility.id, second_facility.id])
                ],
            }
        )

        request.access_company_ids = [Command.set(first_company.ids)]
        request._onchange_access_company_ids()

        self.assertEqual(request.access_facility_ids.ids, first_facility.ids)

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
                row["need_purchase_users"],
                max(expected_active - system.total_licensed_users, 0),
            )
            self.assertEqual(
                row["swap_users"],
                (
                    max(system.total_licensed_users - expected_active, 0)
                    if expected_active
                    else 0
                ),
            )

    def test_dashboard_swap_is_zero_without_active_users(self):
        system = self.env["employee.access.system"].search(
            [
                ("name", "=", "Odoo Light"),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )
        self.env["employee.access.request"].search(
            [("system_id", "=", system.id), ("state", "=", "active")]
        ).write({"state": "draft"})
        system.total_licensed_users = 100

        row = next(
            row
            for row in system.get_dashboard_data()
            if row["name"] == "Odoo Light"
        )

        self.assertEqual(row["active_users"], 0)
        self.assertEqual(row["swap_users"], 0)

    def test_dashboard_purchase_count_increases_above_license_capacity(self):
        system = self.env["employee.access.system"].search(
            [
                ("name", "=", "Odoo Light"),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )
        active_users = self.env["employee.access.request"].search_count(
            [("system_id", "=", system.id), ("state", "=", "active")]
        )

        system.total_licensed_users = active_users
        row_at_capacity = next(
            row
            for row in system.get_dashboard_data()
            if row["name"] == "Odoo Light"
        )
        self.assertEqual(row_at_capacity["swap_users"], 0)
        self.assertEqual(row_at_capacity["need_purchase_users"], 0)

        system.total_licensed_users = max(active_users - 1, 0)
        if not active_users:
            self.env["employee.access.request"].create(
                {
                    "employee_name": "License Capacity Test User",
                    "employee_email": "license.capacity.test@example.com",
                    "company_id": self.env.company.id,
                    "system_id": system.id,
                    "state": "active",
                }
            )
        row_above_capacity = next(
            row
            for row in system.get_dashboard_data()
            if row["name"] == "Odoo Light"
        )
        self.assertEqual(row_above_capacity["swap_users"], 0)
        self.assertEqual(row_above_capacity["need_purchase_users"], 1)

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
                "groups_id": [
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

        other_company_facility = self.env["employee.access.facility"].sudo().search(
            [("company_id", "=", other_company.id)],
            limit=1,
        )
        visible_other_company_facility = (
            self.env["employee.access.facility"]
            .with_user(access_user)
            .with_context(allowed_company_ids=[current_company.id])
            .search([("id", "=", other_company_facility.id)])
        )
        self.assertEqual(visible_other_company_facility, other_company_facility)

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
        system = self.env["employee.access.system"].search(
            [("name", "in", ["Odoo Light", "Odoo Standard"])],
            limit=1,
        )
        internal_application = Application.search(
            [
                ("name", "=", "Employee Access Control"),
                ("system_id", "=", system.id),
            ],
            limit=1,
        ) or Application.create(
            {
                "name": "Employee Access Control",
                "company_id": system.company_id.id,
                "system_id": system.id,
            }
        )

        Application._exclude_internal_employee_access_modules()

        self.assertFalse(internal_application.active)

    def test_sample_applications_are_seeded_and_idempotent(self):
        Application = self.env["employee.access.application"].with_context(
            active_test=False
        )

        Application._load_sample_applications()
        seeded_before = Application.search(
            [
                ("company_id", "=", self.env.company.id),
                (
                    "system_id.name",
                    "in",
                    ["Odoo Light", "Odoo Standard", "EHR", "LIMS"],
                ),
                ("active", "=", True),
            ]
        )
        Application._load_sample_applications()
        seeded_after = Application.search(
            [
                ("company_id", "=", self.env.company.id),
                (
                    "system_id.name",
                    "in",
                    ["Odoo Light", "Odoo Standard", "EHR", "LIMS"],
                ),
                ("active", "=", True),
            ]
        )

        self.assertTrue(
            seeded_after.filtered(
                lambda application: application.name == "Accountant"
                and application.system_id.name == "EHR"
            )
        )
        self.assertTrue(
            seeded_after.filtered(
                lambda application: application.name == "Accounting"
                and application.system_id.name == "Odoo Standard"
            )
        )
        self.assertTrue(
            seeded_after.filtered(
                lambda application: application.name == "Main Cashier (Treasury)"
                and application.system_id.name == "EHR"
            )
        )
        self.assertEqual(set(seeded_after.ids), set(seeded_before.ids))

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

    def test_employee_source_uses_employees_module(self):
        system = self.env["employee.access.system"].search([], limit=1)
        department = self.env["hr.department"].create(
            {"name": "Operations", "company_id": self.env.company.id}
        )
        job = self.env["hr.job"].create(
            {"name": "Officer", "company_id": self.env.company.id}
        )
        employee = self.env["hr.employee"].create(
            {
                "name": "Employees Module Employee",
                "work_email": "module.employee@example.com",
                "department_id": department.id,
                "job_id": job.id,
                "employee_access_fingerprint_id": "EMP-001",
                "company_id": self.env.company.id,
            }
        )
        request = self.env["employee.access.request"].create(
            {
                "employee_id": employee.id,
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self.assertEqual(
            dict(self.env["employee.access.request"]._fields["employee_source"].selection),
            {"employee": "Employees Module"},
        )
        self.assertEqual(request.employee_source, "employee")
        self.assertEqual(request.employee_display_name, employee.name)
        self.assertEqual(request.employee_email, employee.work_email)
        self.assertEqual(request.fingerprint_id, "EMP-001")
        self.assertEqual(request.department, department.name)
        self.assertEqual(request.position, job.name)

    def test_request_form_uses_single_employee_name_selector(self):
        employee_field = self.env["employee.access.request"].fields_get(
            ["employee_id"],
            ["string"],
        )["employee_id"]
        form_view = self.env.ref(
            "employee_access_control.view_employee_access_request_form"
        )

        self.assertEqual(employee_field["string"], "Employee Name")
        self.assertIn('widget="many2one_avatar_employee"', form_view.arch_db)
        self.assertNotIn('<field name="employee_name"', form_view.arch_db)

    def test_employee_source_requires_employee(self):
        system = self.env["employee.access.system"].search([], limit=1)
        with self.assertRaises(ValidationError):
            self.env["employee.access.request"].create(
                {"company_id": self.env.company.id, "system_id": system.id}
            )

    def test_employee_onchange_uses_employee_data(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Selected Employee",
                "work_email": "selected.employee@example.com",
                "company_id": self.env.company.id,
            }
        )
        request = self.env["employee.access.request"].new(
            {"employee_id": employee.id, "company_id": self.env.company.id}
        )
        request._onchange_employee_id()

        self.assertEqual(request.employee_name, employee.name)
        self.assertEqual(request.employee_email, employee.work_email)
        self.assertEqual(request.employee_source, "employee")

    def test_local_user_seed_uses_fingerprint_before_duplicate_email(self):
        Users = self.env["res.users"]
        first_user = Users._employee_access_get_or_create(
            name="Seed User One",
            fingerprint="seed-fingerprint-1",
            email="shared.seed@example.com",
            department="IT",
            position="User",
            company=self.env.company,
        )
        second_user = Users._employee_access_get_or_create(
            name="Seed User Two",
            fingerprint="seed-fingerprint-2",
            email="shared.seed@example.com",
            department="HR",
            position="Manager",
            company=self.env.company,
        )
        repeated_first_user = Users._employee_access_get_or_create(
            name="Seed User One Updated",
            fingerprint="seed-fingerprint-1",
            email="shared.seed@example.com",
            department="IT",
            position="Administrator",
            company=self.env.company,
        )

        self.assertNotEqual(first_user, second_user)
        self.assertEqual(repeated_first_user, first_user)
        self.assertEqual(first_user.employee_access_position, "Administrator")
        self.assertNotEqual(first_user.login, second_user.login)

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

    def test_system_overview_lists_application_modules_and_matching_roles(self):
        system = self.env["employee.access.system"].search([], limit=1)
        application = self.env["employee.access.application"].search(
            [("system_id", "=", system.id), ("active", "=", True)],
            order="sequence, name",
            limit=1,
        )
        access_role = self.env["employee.access.group"].search(
            [
                ("application_id", "=", application.id),
                ("display_type", "=", "application_role"),
                ("active", "=", True),
            ],
            order="sequence, name",
            limit=1,
        )
        self.assertTrue(application)
        self.assertTrue(access_role)

        request = self.env["employee.access.request"].create(
            {
                "employee_name": "System Overview Access Test",
                "company_id": self.env.company.id,
                "system_id": system.id,
                "application_line_ids": [
                    Command.create(
                        {
                            "application_id": application.id,
                            "access_group_id": access_role.id,
                        }
                    )
                ],
            }
        )

        self.assertEqual(request.overview_application_names, application.name)
        self.assertEqual(request.overview_access_role_names, access_role.name)

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
        companies |= facilities.company_id
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
        compose_action = request.action_start_provisioning()
        self._send_composer_action(compose_action)
        request.with_user(request.mark_done_user_id).action_mark_active()

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

    def test_request_follows_erp_vendor_and_assigned_mark_done_flow(self):
        system = self.env["employee.access.system"].search(
            [("name", "=", "Odoo Standard")],
            limit=1,
        ) or self.env["employee.access.system"].search([], limit=1)
        recipient_employee = self.env["hr.employee"].create(
            {
                "name": "Odoo Vendor Employee",
                "work_email": "odoo.vendor@example.com",
                "company_id": self.env.company.id,
            }
        )
        system.write(
            {
                "owner_id": self.env.user.id,
                "recipient_employee_ids": [Command.set(recipient_employee.ids)],
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
        self.assertEqual(len(request.approval_line_ids), 1)
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "erp_admin"
            ).state,
            "to_approve",
        )
        with self.assertRaises(ValidationError):
            request.action_approve()

        request.with_user(request.manager_approver_id).action_manager_approve()
        request.invalidate_recordset()

        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approval_status_label, "All Approved")
        self.assertEqual(
            request.approval_line_ids.filtered(
                lambda line: line.role == "erp_admin"
            ).state,
            "approved",
        )
        self.assertEqual(request.list_status_label, "Waiting for Vendor")
        self.assertEqual(request.approval_status_label, "All Approved")
        self.assertEqual(set(request.approval_line_ids.mapped("state")), {"approved"})
        self.assertEqual(
            request.provisioning_task_ids.assigned_user_id,
            request.mark_done_user_id,
        )

        compose_action = request.action_start_provisioning()
        self.assertEqual(request.state, "provisioning")
        ticket = request.provisioning_task_ids
        self.assertEqual(ticket.assigned_user_id, request.mark_done_user_id)
        self.assertEqual(ticket.ticket_reference, request.reference)
        self.assertEqual(ticket.vendor_email, "odoo.vendor@example.com")
        self.assertEqual(ticket.vendor_portal_url, system.vendor_portal_url)
        self.assertFalse(ticket.first_sent_on)
        self.assertFalse(ticket.last_vendor_message_id)
        with self.assertRaisesRegex(ValidationError, "Send the vendor email"):
            request.with_user(request.mark_done_user_id).action_mark_active()
        self.assertEqual(
            compose_action["context"]["default_partner_ids"],
            request._get_vendor_ticket_partner_ids(),
        )
        self.assertEqual(
            compose_action["context"]["default_subject"],
            ticket.vendor_subject,
        )
        self.assertEqual(
            compose_action["context"]["default_model"],
            "employee.access.request",
        )
        self.assertEqual(compose_action["context"]["default_res_ids"], request.ids)

        self._send_composer_action(compose_action)
        ticket.invalidate_recordset()
        self.assertTrue(ticket.first_sent_on)
        self.assertTrue(ticket.last_vendor_message_id)
        self.assertEqual(
            ticket.last_vendor_message_id.partner_ids.mapped("email"),
            ["odoo.vendor@example.com"],
        )
        self.assertEqual(
            ticket.last_vendor_message_id.model,
            "employee.access.request",
        )
        self.assertEqual(ticket.last_vendor_message_id.message_type, "email")
        self.assertEqual(ticket.last_vendor_message_id.res_id, request.id)
        self.assertIn(ticket.last_vendor_message_id, request.message_ids)
        self.assertIn(ticket.ticket_reference, ticket.vendor_subject)
        self.assertNotIn(f"({request.reference})", ticket.vendor_subject)
        self.assertTrue(
            ticket.activity_ids.filtered(
                lambda activity: activity.summary == "Vendor provisioning required"
                and activity.user_id == request.mark_done_user_id
            )
        )
        self.assertEqual(
            len(
                ticket.activity_ids.filtered(
                    lambda activity: activity.summary == "Vendor provisioning required"
                    and activity.active
                )
            ),
            1,
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
        self.assertEqual(
            len(
                ticket.activity_ids.filtered(
                    lambda activity: activity.summary == "Vendor provisioning required"
                    and activity.active
                )
            ),
            1,
        )
        notification_logs = request.audit_log_ids.filtered(
            lambda log: log.event_type == "vendor_notification_sent"
        )
        self.assertEqual(len(notification_logs), 2)

        unassigned_user = self.env["res.users"].create(
            {
                "name": "Unassigned Mark Done User",
                "login": "unassigned.mark.done@example.com",
                "email": "unassigned.mark.done@example.com",
                "company_id": self.env.company.id,
                "company_ids": [Command.set(self.env.company.ids)],
                "groups_id": [
                    Command.link(
                        self.env.ref(
                            "employee_access_control.group_employee_access_user"
                        ).id
                    )
                ],
            }
        )
        with self.assertRaisesRegex(
            ValidationError, "Only .* or an administrator can mark"
        ):
            request.with_user(unassigned_user).action_mark_active()

        request.with_user(self.env.ref("base.user_root")).action_mark_active()
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
        recipients = self.env["hr.employee"].create(
            [
                {
                    "name": "Vendor Support",
                    "work_email": "support@example.com",
                    "company_id": self.env.company.id,
                },
                {
                    "name": "System Owner",
                    "work_email": "owner@example.com",
                    "company_id": self.env.company.id,
                },
            ]
        )
        system.write(
            {
                "recipient_employee_ids": [Command.set(recipients.ids)],
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
        self.assertEqual(
            set(ticket.vendor_email.split(", ")),
            {"support@example.com", "owner@example.com"},
        )
        self._send_composer_action(compose_action)
        ticket.invalidate_recordset()
        self.assertEqual(
            set(ticket.last_vendor_message_id.partner_ids.mapped("email")),
            {"support@example.com", "owner@example.com"},
        )

    def test_vendor_ticket_email_falls_back_to_legacy_partner_recipients(self):
        system = self.env["employee.access.system"].search([], limit=1)
        recipients = self.env["res.partner"].create(
            [
                {"name": "Legacy Vendor Support", "email": "legacy.support@example.com"},
                {"name": "Legacy System Owner", "email": "legacy.owner@example.com"},
            ]
        )
        system.write(
            {
                "mail_recipient_ids": [Command.set(recipients.ids)],
                "recipient_employee_ids": [Command.clear()],
            }
        )
        request = self.env["employee.access.request"].create(
            {
                "employee_name": "Legacy Multi Recipient User",
                "employee_email": "legacy.multi.recipient@example.com",
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        self._complete_approval_flow(request)
        compose_action = request.action_start_provisioning()

        ticket = request.provisioning_task_ids
        self.assertEqual(
            set(ticket.vendor_email.split(", ")),
            {"legacy.support@example.com", "legacy.owner@example.com"},
        )
        self._send_composer_action(compose_action)
        ticket.invalidate_recordset()
        self.assertEqual(ticket.last_vendor_message_id.partner_ids, recipients)

    def test_odoo_light_uses_hrms_admin_and_configured_mark_done_user(self):
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
        mark_done_step = approval_rule.approval_step_ids.filtered(
            lambda step: step.name == "Mark Done"
        )[:1]
        mark_done_step.approver_user_id = self.env.user

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
        self.assertEqual(request.approval_rule_id, approval_rule)
        self.assertEqual(request.mark_done_user_id, self.env.user)
        self.assertEqual(len(request.approval_line_ids), 1)
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

    def test_existing_active_access_prefills_profile_and_application_roles(self):
        system = self.env["employee.access.system"].search(
            [("name", "=", "Odoo Standard")],
            limit=1,
        ) or self.env["employee.access.system"].search([], limit=1)
        applications = self.env["employee.access.application"].search(
            [("system_id", "=", system.id), ("active", "=", True)],
            order="sequence, name",
            limit=2,
        )
        self.assertTrue(applications)
        selected_application = applications[:1]
        selected_role = self.env["employee.access.group"].search(
            [
                ("application_id", "=", selected_application.id),
                ("display_type", "=", "application_role"),
                ("active", "=", True),
            ],
            order="sequence desc, id desc",
            limit=1,
        )
        self.assertTrue(selected_role)
        access_company = self.env["res.company"].create(
            {"name": "Existing Access Company"}
        )
        previous_request = self.env["employee.access.request"].create(
            {
                "employee_name": "Jazz Existing Access",
                "fingerprint_id": "202-prefill-test",
                "company_id": self.env.company.id,
                "system_id": system.id,
                "application_line_ids": [
                    Command.create(
                        {
                            "application_id": selected_application.id,
                            "access_group_id": selected_role.id,
                        }
                    )
                ],
            }
        )
        profile = self.env["employee.access.profile"].create(
            {
                "employee_name": previous_request.employee_name,
                "fingerprint_id": previous_request.fingerprint_id,
                "employee_email": "jazz.prefill@example.com",
                "department": "HR Dept",
                "position": "HR Officer",
                "company_id": self.env.company.id,
                "system_id": system.id,
                "state": "active",
                "access_company_ids": [Command.set(access_company.ids)],
                "application_ids": [Command.set(selected_application.ids)],
                "required_privileged_access": True,
                "last_request_id": previous_request.id,
            }
        )

        other_system = self.env["employee.access.system"].search(
            [("id", "!=", system.id)],
            limit=1,
        )
        request = self.env["employee.access.request"].new(
            {
                "employee_id": previous_request.employee_id.id,
                "company_id": self.env.company.id,
                "system_id": other_system.id or system.id,
            }
        )
        profile_department = self.env["hr.department"].create(
            {"name": profile.department, "company_id": self.env.company.id}
        )
        previous_request.employee_id.write(
            {
                "work_email": profile.employee_email,
                "employee_access_fingerprint_id": profile.fingerprint_id,
                "department_id": profile_department.id,
                "job_title": profile.position,
            }
        )
        request._onchange_employee_id()

        self.assertEqual(request.system_id, system)
        self.assertEqual(request.fingerprint_id, profile.fingerprint_id)
        self.assertEqual(request.employee_email, profile.employee_email)
        self.assertEqual(request.department, profile.department)
        self.assertEqual(request.position, profile.position)
        self.assertEqual(request.request_type, "update")
        self.assertEqual(request.access_company_ids._origin, access_company)
        self.assertTrue(request.required_privileged_access)
        selected_line = request.application_line_ids.filtered(
            lambda line: line.application_id == selected_application
        )
        self.assertEqual(selected_line.access_group_id, selected_role)
        self.assertFalse(selected_line.remove_access)
        unselected_lines = request.application_line_ids - selected_line
        self.assertTrue(all(unselected_lines.mapped("remove_access")))
        self.assertFalse(any(unselected_lines.mapped("access_group_id")))

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

    def test_pending_request_blocks_duplicate_submission(self):
        system = self.env["employee.access.system"].search([], limit=1)
        employee = self.env["hr.employee"].create(
            {
                "name": "Pending Duplicate Validation User",
                "work_email": "pending.duplicate@example.com",
                "company_id": self.env.company.id,
            }
        )

        for blocking_state in (
            "to_approve",
            "credential_approval",
            "approved",
            "provisioning",
        ):
            with self.subTest(blocking_state=blocking_state):
                existing_request = self.env["employee.access.request"].create(
                    {
                        "employee_id": employee.id,
                        "company_id": self.env.company.id,
                        "system_id": system.id,
                        "state": blocking_state,
                    }
                )
                duplicate_request = self.env["employee.access.request"].create(
                    {
                        "employee_id": employee.id,
                        "company_id": self.env.company.id,
                        "system_id": system.id,
                    }
                )

                with self.assertRaisesRegex(
                    ValidationError,
                    rf"Request {existing_request.reference} is already",
                ):
                    duplicate_request.action_submit()

                existing_request.unlink()
                duplicate_request.unlink()

    def test_rejected_request_does_not_block_new_submission(self):
        system = self.env["employee.access.system"].search([], limit=1)
        employee = self.env["hr.employee"].create(
            {
                "name": "Rejected Duplicate Validation User",
                "work_email": "rejected.duplicate@example.com",
                "company_id": self.env.company.id,
            }
        )
        self.env["employee.access.request"].create(
            {
                "employee_id": employee.id,
                "company_id": self.env.company.id,
                "system_id": system.id,
                "state": "rejected",
            }
        )
        new_request = self.env["employee.access.request"].create(
            {
                "employee_id": employee.id,
                "company_id": self.env.company.id,
                "system_id": system.id,
            }
        )

        new_request.action_submit()

        self.assertEqual(new_request.state, "to_approve")
