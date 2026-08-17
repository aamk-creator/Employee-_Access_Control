/** @odoo-module */

import { registry } from "@web/core/registry";
import {
    DateTimeField,
    dateField,
} from "@web/views/fields/datetime/datetime_field";

class RequestDateField extends DateTimeField {
    getFormattedValue(valueIndex) {
        const value = this.values[valueIndex];
        return value ? value.toFormat("dd/MM/yy") : "";
    }
}

registry.category("fields").add("request_date_ddmmyy", {
    ...dateField,
    component: RequestDateField,
});
