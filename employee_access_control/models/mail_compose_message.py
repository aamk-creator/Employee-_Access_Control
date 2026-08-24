from odoo import fields, models


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    def _action_send_mail(self, auto_commit=False):
        mails, messages = super()._action_send_mail(auto_commit=auto_commit)
        task_id = self.env.context.get("employee_access_vendor_task_id")
        if not task_id:
            return mails, messages

        task = self.env["employee.access.provision.task"].browse(task_id).exists()
        if not task:
            return mails, messages

        # Render vendor correspondence as a full email card (subject + HTML body)
        # in the access request chatter instead of as a plain comment.
        messages.write({"message_type": "email"})

        now = fields.Datetime.now()
        values = {
            "last_sent_on": now,
            "last_vendor_message_id": messages[-1].id if messages else False,
        }
        if self.env.context.get("employee_access_vendor_resend"):
            values["resend_count"] = task.resend_count + 1
        elif not task.first_sent_on:
            values["first_sent_on"] = now
        task.write(values)
        return mails, messages
