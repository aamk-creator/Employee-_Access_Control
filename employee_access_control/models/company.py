from odoo import api, models


class ResCompany(models.Model):
    _inherit = "res.company"

    _employee_access_header_company_names = (
        "CLL Health Holdings Ltd",
        "Right Healthcare Co Ltd",
        "Right Medical Centre",
        "CoreLink Labs Co Ltd",
        "IET For Life Co Ltd",
        "CLL Radiology Co Ltd",
        "CLL Diagnostics Co Ltd",
        "Hope Healthcare Co Ltd",
    )

    @api.model
    def _ensure_employee_access_companies(self):
        company_names = [
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
        ]
        Company = self.sudo().with_context(active_test=False)
        companies = Company.search([("name", "in", company_names)])
        companies_by_name = {company.name: company for company in companies}

        for company_name in company_names:
            company = companies_by_name.get(company_name)
            if company:
                if not company.active:
                    company.active = True
                continue
            companies_by_name[company_name] = Company.create({"name": company_name})

        administrator = self.env.ref("base.user_admin", raise_if_not_found=False)
        if administrator:
            administrator.sudo().company_ids |= Company.browse(
                [companies_by_name[name].id for name in company_names]
            )

        self._ensure_employee_access_header_companies(companies_by_name)

        return True

    @api.model
    def _ensure_employee_access_header_companies(self, companies_by_name):
        """Create the initial DB configuration once, without resetting later edits."""
        parameter = self.env["ir.config_parameter"].sudo()
        marker = "employee_access_control.header_companies_initialized"
        if parameter.get_param(marker):
            return

        HeaderCompany = self.env["employee.access.header.company"].sudo()
        configured_company_ids = set(HeaderCompany.search([]).company_id.ids)
        values = []
        for index, company_name in enumerate(
            self._employee_access_header_company_names, start=1
        ):
            company = companies_by_name[company_name]
            if company.id not in configured_company_ids:
                values.append({"company_id": company.id, "sequence": index * 10})
        if values:
            HeaderCompany.create(values)
        parameter.set_param(marker, "1")
