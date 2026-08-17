/** @odoo-module */

import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";

const HEADER_COMPANY_NAMES = [
    "CLL Health Holdings Ltd",
    "Right Healthcare Co Ltd",
    "Right Medical Centre",
    "CoreLink Labs Co Ltd",
    "IET For Life Co Ltd",
    "CLL Radiology Co Ltd",
    "CLL Diagnostics Co Ltd",
    "Hope Healthcare Co Ltd",
];

const headerCompanyOrder = new Map(
    HEADER_COMPANY_NAMES.map((companyName, index) => [companyName, index])
);

patch(SwitchCompanyMenu.prototype, {
    get isSingleCompany() {
        return this.computeVisibleCompanies().length === 1;
    },

    get hasLotsOfCompanies() {
        return false;
    },

    computeVisibleCompanies() {
        return user.allowedCompanies
            .filter((company) => headerCompanyOrder.has(company.name))
            .filter((company) => this.matchSearch(company.name))
            .sort(
                (companyA, companyB) =>
                    headerCompanyOrder.get(companyA.name) -
                    headerCompanyOrder.get(companyB.name)
            )
            .map((company) => ({ company, level: 0 }));
    },
});
