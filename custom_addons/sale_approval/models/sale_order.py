from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime

class SaleOrder(models.Model):
    _inherit = "sale.order"

    approval_state = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("to_approve", "To Approve"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="not_required",
        copy=False,
        tracking=True,
    )

    needs_approval = fields.Boolean(compute="_compute_needs_approval")
    approved_by = fields.Many2one("res.users", string="Approved By", copy=False, readonly=True)
    approved_date  = fields.Datetime(string="Approved On", copy=False, readonly=True)

    @api.depends("amount_total", "company_id.approval_threshold")
    def _compute_needs_approval(self):
        for order in self:
            order.needs_approval = order.amount_total > order.company_id.approval_threshold


    def action_request_approval(self):
        for order in self:
            if not order.needs_approval:
                raise UserError("This order does not need approval.")
            if order.approval_state not in ("not_required", "rejected"):
                raise UserError("Approval was already requested or granted.")
            order.message_post(body="Approval requested by %s." % self.env.user.name)
            order.approval_state = "to_approve"


    def action_approve(self):
        for order in self:
            if not self.env.user.has_group("sale_approval.group_sale_approver"):
                raise UserError("You are not allowed to approve or reject orders.")
            
            if order.approval_state != "to_approve":
                raise UserError("Only orders waiting for approval can be approved.")

            order.write({
                "approval_state": "approved",
                "approved_by": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
            # order.approval_state = "approved"
            order.message_post(body=f"Order {order.id} is approved by {self.env.user.name}.")


    def action_reject(self):
        for order in self:
            if not self.env.user.has_group("sale_approval.group_sale_approver"):
                raise UserError("You are not allowed to approve or reject orders.")
            
            if order.approval_state != "to_approve":
                raise UserError("Only orders waiting for approval can be rejected.")
            
            # order.approval_state = "rejected"
            order.write({
                "approval_state": "rejected",
                "approved_by": False,
                "approved_date": False,
            })
            # order.approval_state = "approved"
            order.message_post(body=f"Order {order.id} is rejected by {self.env.user.name}.")


    def action_confirm(self):
        for order in self:
            if order.needs_approval and order.approval_state != "approved":
                raise UserError("Failed to approve order.")

        return super().action_confirm()