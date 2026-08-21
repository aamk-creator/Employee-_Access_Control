import re

from odoo import Command, api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    employee_access_fingerprint_id = fields.Char(
        string="Fingerprint ID",
        index=True,
        copy=False,
    )
    employee_access_department = fields.Char(string="Department")
    employee_access_position = fields.Char(string="Position")

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
                lambda candidate: not candidate.employee_access_fingerprint_id
                or candidate.employee_access_fingerprint_id == fingerprint
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
                "group_ids": [Command.set(self.env.ref("base.group_user").ids)],
                "active": True,
            }
        )
        return Users.with_context(no_reset_password=True).create(values)
