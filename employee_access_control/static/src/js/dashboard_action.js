/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

class EmployeeAccessDashboard extends Component {
    static template = "employee_access_control.DashboardAction";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            systems: [],
            error: false,
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const systems = await this.orm.call(
                "employee.access.system",
                "get_dashboard_data",
                []
            );
            this.state.systems.splice(0, this.state.systems.length, ...systems);
        } catch (error) {
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }

    formatNumber(value) {
        return new Intl.NumberFormat().format(value || 0);
    }

    async refreshDashboard() {
        await this.loadDashboard();
    }

    openSystem(system) {
        if (!system.id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: system.name,
            res_model: "employee.access.system",
            res_id: system.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openUsers(system, status = false) {
        if (!system.id) {
            return;
        }
        const additionalContext = {
            search_default_system_id: system.id,
        };
        if (status) {
            additionalContext[`search_default_overview_${status}`] = 1;
        }
        this.action.doAction(
            "employee_access_control.action_employee_access_system_overview",
            { additionalContext }
        );
    }
}

registry.category("actions").add("employee_access_control.dashboard", EmployeeAccessDashboard);
