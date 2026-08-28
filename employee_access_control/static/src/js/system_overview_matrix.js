/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

class EmployeeAccessSystemOverviewMatrix extends Component {
    static template = "employee_access_control.SystemOverviewMatrix";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const params = this.props.action.params || {};
        this.state = useState({
            loading: true,
            error: false,
            query: "",
            systemId: Number(params.system_id || 0),
            status: params.status || "",
            systems: [],
            headers: [],
            rows: [],
            expandedCompanyRows: {},
        });
        onWillStart(() => this.loadMatrix());
    }

    async loadMatrix() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const result = await this.orm.call(
                "employee.access.request",
                "get_system_overview_matrix",
                [{
                    query: this.state.query,
                    system_id: this.state.systemId,
                    status: this.state.status,
                }]
            );
            this.state.systems.splice(0, this.state.systems.length, ...result.systems);
            this.state.headers.splice(0, this.state.headers.length, ...result.headers);
            this.state.rows.splice(0, this.state.rows.length, ...result.rows);
            this.state.expandedCompanyRows = {};
        } catch (error) {
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }

    async onSystemChange(event) {
        this.state.systemId = Number(event.target.value || 0);
        await this.loadMatrix();
    }

    async onStatusChange(event) {
        this.state.status = event.target.value;
        await this.loadMatrix();
    }

    async onSearchKeydown(event) {
        if (event.key === "Enter") {
            await this.loadMatrix();
        }
    }

    roleFor(row, header) {
        return row.roles[header.key] || "—";
    }

    hasRoles(row) {
        return Object.keys(row.roles).length > 0;
    }

    accessCompanies(row) {
        return row.access_company_names || [];
    }

    visibleAccessCompanies(row) {
        const companies = this.accessCompanies(row);
        return this.state.expandedCompanyRows[row.id] ? companies : companies.slice(0, 2);
    }

    hiddenCompanyCount(row) {
        return Math.max(this.accessCompanies(row).length - 2, 0);
    }

    toggleAccessCompanies(row) {
        this.state.expandedCompanyRows[row.id] = !this.state.expandedCompanyRows[row.id];
    }

    openRequest(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: row.employee,
            res_model: "employee.access.request",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add(
    "employee_access_control.system_overview_matrix",
    EmployeeAccessSystemOverviewMatrix
);
