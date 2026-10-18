from odoo import models, fields

class ResCompany(models.Model):
    _inherit = "res.company"

    approval_threshold = fields.Monetary(
        string="Approval Threshold",
        default=5000.0,
        currency_field="currency_id",
    )