from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = "sale.order"

    blue_order_id = fields.Char(string="Marketplace Blue Order ID", copy=False, index=True, readonly=True)

    _sql_constraints = [
        ("blue_order_id_uniq", "unique(blue_order_id)",
         "This marketplace order has already been imported."),
    ]
