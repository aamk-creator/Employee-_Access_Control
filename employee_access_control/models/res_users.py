import re

from odoo import Command, api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        dashboard_action = self.env.ref(
            "employee_access_control.action_employee_access_dashboard",
            raise_if_not_found=False,
        )
        if dashboard_action:
            users.filtered(
                lambda user: not user.share and not user.action_id
            ).write({"action_id": dashboard_action.id})
        return users

    employee_access_user_type = fields.Selection(
        [
            ("light", "Odoo Light"),
            ("standard", "Odoo Standard"),
        ],
        string="Odoo License Type",
        default="standard",
        index=True,
        help="License category used by the Employee Access Control dashboard.",
    )

    employee_access_fingerprint_id = fields.Char(
        string="Fingerprint ID",
        index=True,
        copy=False,
    )
    employee_access_department = fields.Char(string="Department")
    employee_access_position = fields.Char(string="Position")

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            UPDATE res_users
               SET employee_access_user_type = 'standard'
             WHERE share = FALSE
               AND employee_access_user_type IS NULL
               AND login NOT IN ('__system__', '__export__')
            """
        )
        self.env.cr.execute(
            """
            UPDATE res_users
               SET employee_access_user_type = NULL
             WHERE login IN ('__system__', '__export__')
            """
        )

    @api.model
    def _ensure_employee_access_home_action(self):
        dashboard_action = self.env.ref(
            "employee_access_control.action_employee_access_dashboard"
        )
        users = self.sudo().with_context(active_test=False).search(
            [
                ("share", "=", False),
                ("login", "not in", ["__system__", "__export__"]),
                ("action_id", "=", False),
            ]
        )
        users.write({"action_id": dashboard_action.id})
        return True

    @api.model
    def _employee_access_available_login(self, preferred_login, fingerprint, name):
        Users = self.sudo().with_context(active_test=False)
        preferred_login = (preferred_login or "").strip().lower()
        if preferred_login and not Users.search_count(
            [("login", "=ilike", preferred_login)]
        ):
            return preferred_login

        identity = fingerprint or re.sub(r"[^a-z0-9]+", ".", (name or "employee").lower())
        identity = identity.strip(".") or "employee"
        base_login = f"employee.{identity}@local.invalid"
        login = base_login
        suffix = 2
        while Users.search_count([("login", "=ilike", login)]):
            login = f"employee.{identity}.{suffix}@local.invalid"
            suffix += 1
        return login

    @api.model
    def _employee_access_get_or_create(
        self,
        *,
        name,
        fingerprint=False,
        email=False,
        department=False,
        position=False,
        company,
        employee=False,
    ):
        Users = self.sudo().with_context(active_test=False)
        fingerprint = (fingerprint or "").strip()
        email = (email or "").strip()
        user = Users.browse()

        if fingerprint:
            user = Users.search(
                [("employee_access_fingerprint_id", "=", fingerprint)],
                order="id",
                limit=1,
            )
        if not user and email:
            email_candidates = Users.search(
                ["|", ("login", "=ilike", email), ("email", "=ilike", email)],
                order="id",
            )
            user = email_candidates.filtered(
                lambda candidate: (
                    not candidate.employee_access_fingerprint_id
                    or candidate.employee_access_fingerprint_id == fingerprint
                )
                and (
                    not employee
                    or not candidate.employee_ids
                    or employee in candidate.employee_ids
                )
            )[:1]

        values = {
            "name": name,
            "email": email or False,
            "employee_access_fingerprint_id": fingerprint or False,
            "employee_access_department": department or False,
            "employee_access_position": position or False,
        }
        if user:
            values["company_ids"] = [Command.link(company.id)]
            user.write(values)
            return user

        values.update(
            {
                "login": self._employee_access_available_login(email, fingerprint, name),
                "company_id": company.id,
                "company_ids": [Command.set(company.ids)],
                "groups_id": [Command.set(self.env.ref("base.group_user").ids)],
                "active": True,
            }
        )
        return Users.with_context(no_reset_password=True).create(values)

    def write(self, vals):
        sync_status = (
            "active" in vals
            and not self.env.context.get("employee_access_skip_status_sync")
        )
        previous_active = {user.id: user.active for user in self} if sync_status else {}
        result = super().write(vals)
        if sync_status:
            changed_users = self.filtered(
                lambda user: previous_active.get(user.id) != user.active
            )
            changed_users._employee_access_sync_request_status()
        return result

    def _employee_access_sync_request_status(self):
        """Keep Odoo access tickets aligned with manual User Settings changes."""
        Requests = self.env["employee.access.request"].sudo()
        inactive_date = fields.Date.context_today(self)
        for user in self.with_context(active_test=False):
            linked_domain = [
                ("system_id.is_odoo_system", "=", True),
                "|",
                ("requested_user_id", "=", user.id),
                ("employee_id.user_id", "=", user.id),
            ]
            if not user.active:
                requests = Requests.search(linked_domain + [("state", "=", "active")])
                for request in requests:
                    if request.profile_id:
                        request.profile_id.write({"state": "revoked"})
                    request.write(
                        {"state": "inactive", "inactive_date": inactive_date}
                    )
                    request._log_event(
                        "deactivated",
                        "Odoo user account was archived from User Settings.",
                        profile=request.profile_id,
                    )
                continue

            inactive_domain = linked_domain + [("state", "=", "inactive")]
            matching_request = Requests.search(
                inactive_domain
                + [("system_id.user_type", "=", user.employee_access_user_type)],
                order="inactive_date desc, id desc",
                limit=1,
            )
            request = matching_request or Requests.search(
                inactive_domain,
                order="inactive_date desc, id desc",
                limit=1,
            )
            if request:
                if request.profile_id:
                    request.profile_id.write({"state": "active"})
                request.write({"state": "active", "inactive_date": False})
                request._log_event(
                    "reactivated",
                    "Odoo user account was reactivated from User Settings.",
                    profile=request.profile_id,
                )
