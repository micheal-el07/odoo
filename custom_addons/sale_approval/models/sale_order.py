from odoo import models, fields, api
from odoo.exceptions import UserError

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
            order.approval_state = "to_approve"


    def action_approve(self):
        for order in self:
            if order.approval_state != "to_approve":
                raise UserError("Only orders waiting for approval can be approved.")
            
            order.approval_state = "approved"


    def action_reject(self):
        for order in self:
            if order.approval_state != "to_approve":
                raise UserError("Only orders waiting for approval can be rejected.")
            
            order.approval_state = "rejected"


    def action_confirm(self):
        for order in self:
            if order.needs_approval and order.approval_state != "approved":
                raise UserError("Failed to approve order.")

        return super().action_confirm()