/** @odoo-module */

import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";

patch(SwitchCompanyMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.employeeAccessHeaderOrder = new Map();
        onWillStart(async () => {
            try {
                const configurations = await this.orm.searchRead(
                    "employee.access.header.company",
                    [["company_id", "in", user.allowedCompanies.map((company) => company.id)]],
                    ["company_id", "sequence"],
                    { order: "sequence, id" }
                );
                this.employeeAccessHeaderOrder = new Map(
                    configurations.map((configuration) => [
                        configuration.company_id?.id || configuration.company_id?.[0],
                        configuration.sequence,
                    ])
                );
                this.resetState();
            } catch {
                // Keep Odoo's normal company switcher available if configuration cannot load.
                this.employeeAccessHeaderOrder = new Map();
            }
        });
    },

    get isSingleCompany() {
        return this.computeVisibleCompanies().length === 1;
    },

    get hasLotsOfCompanies() {
        return this.employeeAccessHeaderOrder?.size ? false : super.hasLotsOfCompanies;
    },

    computeVisibleCompanies() {
        if (!this.employeeAccessHeaderOrder?.size) {
            return super.computeVisibleCompanies(...arguments);
        }
        return user.allowedCompanies
            .filter((company) => this.employeeAccessHeaderOrder.has(company.id))
            .filter((company) => this.matchSearch(company.name))
            .sort(
                (companyA, companyB) =>
                    this.employeeAccessHeaderOrder.get(companyA.id) -
                    this.employeeAccessHeaderOrder.get(companyB.id)
            )
            .map((company) => ({ company, level: 0 }));
    },
});
