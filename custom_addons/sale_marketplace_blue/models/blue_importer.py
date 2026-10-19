import logging
import time
from datetime import datetime, timezone

import requests

from odoo import models
from odoo.exceptions import UserError
from psycopg2 import IntegrityError, errors

_logger = logging.getLogger(__name__)

class BlueImporter(models.AbstractModel):
    _name = "blue.importer"
    _description = "Marketplace Blue order importer"

    def _get_or_create_partner(self, order):
        """Find a customer by email, or create one."""
        Partner = self.env["res.partner"]
        email = order.get("customer_email")

        # Match by email, never by name: many different customers share a name.
        partner = Partner.search([("email", "=", email)], limit=1) if email else Partner

        if not partner:
            # create() returns the new record, so we can return it directly.
            partner = Partner.create({
                "name": order.get("customer_name") or email or "Marketplace Customer",
                "email": email or False,
                "phone": order.get("customer_phone") or False,
            })

        return partner

    def _prepare_order_lines(self, order):
        """Return order_line commands, or raise if an SKU is unknown."""
        Product = self.env["product.product"]
        commands = []

        for line in order.get("lines", []):
            sku = line.get("seller_sku")
            product = Product.search([("default_code", "=", sku)], limit=1) if sku else Product
            
            if not product:
                raise UserError("Unknown SKU %r in Blue order %s" % (sku, order["id"]))

            commands.append((0, 0, {
                "product_id": product.id,
                "product_uom_qty": line["qty"],
                "tax_id": [(5, 0, 0)],
                "price_unit": float(line["price"]),  # Blue sends money as a string
            }))

        if not commands:
            raise UserError("Blue order %s has no lines" % order["id"])
        return commands

    def _to_utc_naive(self, iso_string):
        """'2026-10-17T14:41:19+08:00' -> naive UTC datetime, which is what Odoo stores."""
        dt = datetime.fromisoformat(iso_string)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def import_order(self, order):
        """Create a sale.order from one Blue order dict.
        Return the new order, or None if it was already imported."""
        SaleOrder = self.env["sale.order"]
        blue_id = str(order["id"])

        # 1. Already imported? Then do nothing.
        if SaleOrder.search([("blue_order_id", "=", blue_id)], limit=1):
            return None

        # 2. Customer, 3. lines (raises before anything is created if a SKU is missing)
        partner = self._get_or_create_partner(order)
        lines = self._prepare_order_lines(order)

        # 4. Create the quotation
        return SaleOrder.create({
            "partner_id": partner.id,
            "blue_order_id": blue_id,
            "client_order_ref": order.get("seller_reference"),
            "date_order": self._to_utc_naive(order["created_at"]),
            "order_line": lines,
        })

    # --- Fetching and the sync loop -------------------------------------

    def _blue_settings(self):
        """Base URL and API key come from system parameters, not from code."""
        params = self.env["ir.config_parameter"].sudo()
        base_url = params.get_param("sale_marketplace_blue.base_url", "http://host.docker.internal:8102")
        api_key = params.get_param("sale_marketplace_blue.api_key", "blue-test-key")
        return base_url.rstrip("/"), api_key

    def _fetch_page(self, cursor=None, limit=50, retries=3):
        """GET one page of PAID orders. Waits and retries on 429 (rate limited)."""
        base_url, api_key = self._blue_settings()
        params = {"limit": limit, "payment_status": "PAID"}
        if cursor:
            params["cursor"] = cursor

        for attempt in range(retries):
            resp = requests.get(
                base_url + "/seller/orders",
                headers={"Authorization": "Bearer " + api_key},
                params=params,
                timeout=10,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 1))
                _logger.warning("Blue rate limited us, waiting %ss", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()

        raise UserError("Marketplace Blue is rate limiting us; try again later.")

    def sync_orders(self, max_pages=20):
        """Import every PAID order. One bad order never stops the batch.
        Returns counts so a button/cron/log can show what happened."""
        result = {"created": 0, "skipped": 0, "failed": 0, "errors": []}
        cursor = None

        for _page in range(max_pages):  # hard stop so a bad cursor can't loop forever
            page = self._fetch_page(cursor=cursor)

            for order in page["data"]:
                try:
                    # A savepoint makes each order all-or-nothing, including
                    # any partner that was created before the error.
                    with self.env.cr.savepoint():
                        created = self.import_order(order)

                # except errors.UniqueViolation:
                #     result["skipped"] += 1
                #     continue

                except Exception as exc:
                    result["failed"] += 1
                    result["errors"].append("Order %s: %s" % (order.get("id"), exc))
                    _logger.warning("Blue order %s failed: %s", order.get("id"), exc)
                    continue

                if created:
                    result["created"] += 1
                else:
                    result["skipped"] += 1

            if not page.get("has_next"):
                break
            cursor = page["next_cursor"]

        return result
