from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError


class EmployeeAccessApprovalRule(models.Model):
    _name = "employee.access.approval.rule"
    _description = "Employee Access Approval Rule"
    _order = "sequence, name, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)
    approval_step_ids = fields.One2many(
        "employee.access.approval.step",
        "approval_rule_id",
        string="Approval Steps",
        copy=True,
    )
    model_name = fields.Selection(
        [
            ("employee_access_control", "Employee Access Control"),
            ("user_handover_request", "User Handover Request"),
        ],
        string="Model",
        required=True,
    )
    request_type = fields.Selection(
        [
            ("access", "Access"),
            ("asset", "Asset"),
            ("onboarding", "Onboarding"),
            ("offboarding", "Offboarding"),
        ],
        required=True,
        default="access",
    )
    approver_type = fields.Selection(
        [
            ("user", "User"),
            ("odoo_group", "Odoo Group"),
            ("manager", "Manager"),
        ],
        required=True,
        default="manager",
    )
    approver_user_id = fields.Many2one(
        "res.users",
        string="Approver User",
        domain="[('share', '=', False), '|', ('company_ids', '=', False), ('company_ids', 'in', [company_id])]",
    )
    approver_group_id = fields.Many2one("res.groups", string="Approver Odoo Group")
    system_id = fields.Many2one(
        "employee.access.system",
        string="System",
        domain="[('company_id', '=', company_id)]",
        check_company=True,
    )
    application_id = fields.Many2one(
        "employee.access.application",
        string="Application",
        domain="[('company_id', '=', company_id), ('system_id', '=', system_id)]",
        check_company=True,
    )
    access_group_id = fields.Many2one(
        "employee.access.group",
        string="Access Group",
        domain="[('company_id', '=', company_id), ('system_id', '=', system_id)]",
        check_company=True,
    )
    minimum_approvals = fields.Integer(required=True, default=1)
    description = fields.Text()

    @api.constrains("minimum_approvals")
    def _check_minimum_approvals(self):
        for record in self:
            if record.minimum_approvals < 1:
                raise ValidationError("Minimum approvals must be at least 1.")

    @api.constrains("approver_type", "approver_user_id", "approver_group_id")
    def _check_approver_assignment(self):
        for record in self:
            if record.approver_type == "user" and not record.approver_user_id:
                raise ValidationError("Approver user is required when approver type is User.")
            if record.approver_type == "odoo_group" and not record.approver_group_id:
                raise ValidationError("Approver Odoo group is required when approver type is Odoo Group.")

    @api.constrains("system_id", "application_id", "access_group_id")
    def _check_scope_consistency(self):
        for record in self:
            if record.application_id and record.system_id and record.application_id.system_id != record.system_id:
                raise ValidationError("Application must belong to the selected system.")
            if record.access_group_id and record.system_id and record.access_group_id.system_id != record.system_id:
                raise ValidationError("Access group must belong to the selected system.")

    @api.onchange("system_id")
    def _onchange_system_id(self):
        if self.application_id and self.application_id.system_id != self.system_id:
            self.application_id = False
        if self.access_group_id and self.access_group_id.system_id != self.system_id:
            self.access_group_id = False

    @api.model
    def _load_sample_approval_rules(self):
        companies = self.env["res.company"].sudo().search([("active", "=", True)])
        for company in companies:
            self.with_company(company)._load_sample_approval_rules_for_company(company)
        return True

    @api.model
    def _load_sample_approval_rules_for_company(self, company):
        steps_by_model = {
            "employee_access_control": [
                (10, "Senior Manager", False, "by_field"),
                (20, "Director", False, "optional"),
                (30, "ERP Admin (Standard)", False, "by_user"),
                (40, "HRMS Admin(Light)", False, "by_user"),
                (50, "EHR Admin", False, "by_user"),
                (60, "LIMS Admin", False, "by_user"),
                (70, "RIS Admin", False, "by_user"),
                (80, "Mark Done", True, "by_user"),
                (90, "Google Workspace Admin", False, "by_user"),
            ],
            "user_handover_request": [
                (10, "Senior Manager", False, "by_field"),
                (20, "ERP Admin (Standard)", False, "by_user"),
                (30, "HRMS Admin (Light)", False, "by_user"),
                (40, "EHR Admin", False, "by_user"),
                (50, "LIMS Admin", False, "by_user"),
                (60, "RIS Admin", False, "by_user"),
                (70, "Google Workspace Admin", False, "by_user"),
                (80, "Mark Done", True, "by_user"),
            ],
        }
        sample_rules = [
            {
                "name": "Approval Flow",
                "model_name": "employee_access_control",
                "request_type": "access",
            },
            {
                "name": "Handover",
                "model_name": "user_handover_request",
                "request_type": "offboarding",
            },
        ]
        for values in sample_rules:
            record = self.with_context(active_test=False).search(
                [
                    ("company_id", "=", company.id),
                    ("name", "=", values["name"]),
                    ("model_name", "=", values["model_name"]),
                ],
                limit=1,
            )
            rule_values = {
                **values,
                "company_id": company.id,
                "sequence": 10,
                "active": True,
                "approver_type": "manager",
                "minimum_approvals": 1,
            }
            if record:
                record.write(rule_values)
            else:
                record = self.create(rule_values)
            desired_steps = steps_by_model[values["model_name"]]
            desired_names = {name for _, name, _, _ in desired_steps}
            for sequence, name, mandatory, approval_type in desired_steps:
                step = record.approval_step_ids.filtered(
                    lambda approval_step: approval_step.name == name
                )[:1]
                legacy_step = record.approval_step_ids.filtered(
                    lambda approval_step: approval_step.name == "Credential Management"
                )[:1]
                step_values = {
                    "sequence": sequence,
                    "name": name,
                    "mandatory": mandatory,
                    "approval_type": approval_type,
                }
                if name == "Mark Done" and not step and legacy_step.approver_user_id:
                    step_values["approver_user_id"] = legacy_step.approver_user_id.id
                if step:
                    step.write(step_values)
                else:
                    record.approval_step_ids = [Command.create(step_values)]
            obsolete_steps = record.approval_step_ids.filtered(
                lambda approval_step: approval_step.name not in desired_names
            )
            obsolete_steps.unlink()
        return True


class EmployeeAccessApprovalStep(models.Model):
    _name = "employee.access.approval.step"
    _description = "Employee Access Approval Step"
    _order = "sequence, id"
    _check_company_auto = True

    approval_rule_id = fields.Many2one(
        "employee.access.approval.rule",
        string="Approval Rule",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="approval_rule_id.company_id",
        store=True,
        index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    mandatory = fields.Boolean()
    approval_type = fields.Selection(
        [
            ("by_field", "By Field"),
            ("optional", "Optional"),
            ("by_user", "By User"),
        ],
        string="Type",
        required=True,
        default="by_user",
    )
    approver_user_id = fields.Many2one(
        "res.users",
        string="Approver User",
        domain="[('share', '=', False), ('company_ids', 'in', [company_id])]",
        ondelete="restrict",
    )
