/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { onWillStart, useEffect, useState } from "@odoo/owl";

export class ApplicationRoleDropdowns extends X2ManyField {
    static template = "employee_access_control.ApplicationRoleDropdowns";
    static props = X2ManyField.props;

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.roleState = useState({
            loading: false,
            optionsByApplication: {},
        });
        this.loadedSignature = "";
        onWillStart(() => this.loadRoleOptions());
        useEffect(
            () => {
                if (this.applicationSignature !== this.loadedSignature) {
                    this.loadRoleOptions();
                }
            },
            () => [this.applicationSignature]
        );
    }

    get lines() {
        return this.list.records;
    }

    relationalId(value) {
        return value?.id || value?.[0] || false;
    }

    relationalName(value) {
        return value?.display_name || value?.[1] || "";
    }

    get applicationIds() {
        return this.lines
            .map((line) => this.relationalId(line.data.application_id))
            .filter((applicationId) => Boolean(applicationId));
    }

    get applicationSignature() {
        return [...this.applicationIds].sort((left, right) => left - right).join(",");
    }

    applicationName(line) {
        const displayName = this.relationalName(line.data.application_id);
        return displayName.replace(/\s+\(\s*[^()]+\s*\)\s*$/, "");
    }

    selectedRoleId(line) {
        return this.relationalId(line.data.access_group_id) || "";
    }

    roleOptions(line) {
        const applicationId = this.relationalId(line.data.application_id);
        return this.roleState.optionsByApplication[applicationId] || [];
    }

    async loadRoleOptions() {
        const applicationIds = this.applicationIds;
        this.loadedSignature = this.applicationSignature;
        if (!applicationIds.length) {
            this.roleState.optionsByApplication = {};
            return;
        }
        this.roleState.loading = true;
        const groups = await this.orm.searchRead(
            "employee.access.group",
            [
                ["application_id", "in", applicationIds],
                ["display_type", "=", "application_role"],
                ["active", "=", true],
            ],
            ["name", "application_id", "default_role", "sequence"],
            { order: "sequence, name, id" }
        );
        const optionsByApplication = {};
        for (const group of groups) {
            const applicationId = group.application_id?.[0];
            if (!optionsByApplication[applicationId]) {
                optionsByApplication[applicationId] = [];
            }
            optionsByApplication[applicationId].push(group);
        }
        this.roleState.optionsByApplication = optionsByApplication;
        this.roleState.loading = false;
    }

    async onRoleChange(line, event) {
        const roleId = Number(event.target.value) || false;
        const role = this.roleOptions(line).find((option) => option.id === roleId);
        await line.update({
            // Odoo 17 expects a Many2one client value as [id, display_name].
            // Passing the object shape used by newer clients makes
            // _preprocessMany2oneChanges try to iterate a non-iterable value.
            access_group_id: role ? [role.id, role.name] : false,
            remove_access: !role,
        });
    }
}

registry.category("fields").add("application_role_dropdowns", {
    ...x2ManyField,
    component: ApplicationRoleDropdowns,
});
