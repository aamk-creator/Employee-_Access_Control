from odoo import api, fields, models


class EmployeeAccessFacility(models.Model):
    _name = "employee.access.facility"
    _description = "Employee Access Facility"
    _order = "sequence, name, id"
    _check_company_auto = True

    _employee_access_facility_catalog = (
        "81st STREET CLINIC - P005",
        "ARYU THUKHA MULTI-SPECIALTY CLINIC - A002",
        "BO MYAT TUN CLINIC - P008",
        "CLL HEALTH CLINIC - P006",
        "CLL HEALTH HOME CARE - P801",
        "CLL HEALTH MEDICAL TRANSPORTATION SERVICES - P901",
        "DUWUN CLINIC - P001",
        "EXCEL SQUARE CLINIC - A005",
        "INGYIN PHYU CLINIC - A006",
        "MAHAR MYAING CLINIC - A004",
        "OEC POLYCLINIC - A001",
        "SADDAN SIN MIN CLINIC - P002",
        "SEA LION MEDICAL TRAVEL - MM",
        "SHIN SAW PU CLINIC - P003",
        "TAMWE LAY CLINIC - P004",
        "THUWUNNA POLYCLINIC - A003",
        "LANMADAW CENTRE - L001",
        "INSEIN CENTRE - L002",
        "NORTH OKKALAPA CENTRE - L003",
        "THINGANGYUN CENTRE - L004",
        "MANDALAY-77th STREET CENTRE - L006",
        "NAY PYI TAW-ZIWAKA CENTRE - L007",
        "PYINMANA CENTRE - L008",
        "BAGO CENTRE - L009",
        "TAUNGOO CENTRE - L011",
        "MYAUNG MYA CENTRE - L012",
        "MAWLAMYINE CENTRE - L013",
        "HPA AN CENTRE - L014",
        "TAUNGGYI CENTRE - L015",
        "KENG TUNG CENTRE - L016",
        "PYIN OO LWIN CENTRE - L017",
        "SHWE BON THAR CENTRE - L018",
    )

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    address = fields.Text()
    description = fields.Text()
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        (
            "company_code_uniq",
            "unique(company_id, code)",
            "Facility code must be unique per company.",
        ),
    ]

    @api.model
    def _ensure_employee_access_facilities(self, companies=None):
        """Synchronize the standard facility catalog for every target company."""
        if companies is None:
            companies = self.env["res.company"].sudo().with_context(
                active_test=False
            ).search([])
        else:
            companies = companies.sudo().with_context(active_test=False).exists()
        if not companies:
            return True

        catalog = [
            (label, label.rsplit(" - ", 1)[1])
            for label in self._employee_access_facility_catalog
        ]
        catalog_codes = [code for _label, code in catalog]
        Facility = self.sudo().with_context(active_test=False)
        existing = Facility.search(
            [
                ("company_id", "in", companies.ids),
                ("code", "in", catalog_codes),
            ]
        )
        existing_by_company_code = {
            (facility.company_id.id, facility.code): facility
            for facility in existing
        }
        create_values = []

        for company in companies:
            for sequence, (label, code) in enumerate(catalog, start=1):
                facility = existing_by_company_code.get((company.id, code))
                values = {
                    "name": label,
                    "sequence": sequence * 10,
                    "active": True,
                }
                if facility:
                    changed_values = {
                        field_name: value
                        for field_name, value in values.items()
                        if facility[field_name] != value
                    }
                    if changed_values:
                        facility.write(changed_values)
                    continue
                create_values.append(
                    {
                        **values,
                        "code": code,
                        "company_id": company.id,
                    }
                )

        if create_values:
            Facility.create(create_values)
        return True
