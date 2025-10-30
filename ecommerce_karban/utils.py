import frappe
from ecommerce_integrations.unicommerce.customer import _check_if_customer_exists
from ecommerce_integrations.unicommerce.constants import (
	ADDRESS_JSON_FIELD,
	CUSTOMER_CODE_FIELD,
	SETTINGS_DOCTYPE,
	UNICOMMERCE_COUNTRY_MAPPING,
	UNICOMMERCE_INDIAN_STATES_MAPPING,
)
from typing import Any
from frappe import _
import json
from frappe.utils.nestedset import get_root_of

def sync_customer_custom(order):
	"""Using order create a new customer.

	Note: Unicommerce doesn't deduplicate customer."""
	frappe.log_error(
		_("Syncing customer from Unicommerce order {0}").format(order.get("customerGSTIN")),
		_("Unicommerce Customer Sync")
	)
	customer = _create_new_customer(order)
	_create_customer_addresses(order.get("addresses") or [], customer, order.get("customerGSTIN"))
	return customer

def _create_new_customer(order):
    """Create a new customer from Sales Order address data"""

    address = order.get("billingAddress") or (order.get("addresses") and order.get("addresses")[0])
    address.pop("id", None)  # this is not important and can be different for same address
    customer_code = order.get("customerCode")

    customer = _check_if_customer_exists(address, customer_code)
    if customer:
        if order.get("customerGSTIN") != "null":
            frappe.db.set_value("Customer", customer.name, "gstin", order.get("customerGSTIN"))
            frappe.db.set_value("Customer", customer.name, "gst_category", "Registered Regular")
        else:
            frappe.db.set_value("Customer", customer.name, "gstin", "")
            frappe.db.set_value("Customer", customer.name, "gst_category", "Unregistered")
        return customer

    setting = frappe.get_cached_doc(SETTINGS_DOCTYPE)
    customer_group = (
        frappe.db.get_value(
            "Unicommerce Channel", {"channel_id": order["channel"]}, fieldname="customer_group"
        )
        or setting.default_customer_group
    )

    name = address.get("name") or order["channel"] + " customer"
    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": name,
            "customer_group": customer_group,
            "territory": get_root_of("Territory"),
            "customer_type": "Individual",
            "gstin": order.get("customerGSTIN") if order.get("customerGSTIN") != "null" else "",
            "gst_category": "Registered Regular" if order.get("customerGSTIN") != "null" else "Unregistered",
            ADDRESS_JSON_FIELD: json.dumps(address),
            CUSTOMER_CODE_FIELD: customer_code,
        }
    )

    customer.flags.ignore_mandatory = True
    customer.insert(ignore_permissions=True)

    return customer


def _create_customer_addresses(addresses: list[dict[str, Any]], customer, gstin) -> None:
	"""Create address from dictionary containing fields used in Address doctype of ERPNext.

	Unicommerce orders contain address list,
	if there is only one address it's both shipping and billing,
	else first is billing and second is shipping"""

	if len(addresses) == 1:
		_create_customer_address(addresses[0], "Billing", customer, gstin, also_shipping=True)
	elif len(addresses) >= 2:
		_create_customer_address(addresses[0], "Billing", customer, gstin)
		_create_customer_address(addresses[1], "Shipping", customer, gstin)


def _create_customer_address(uni_address, address_type, customer, gstin, also_shipping=False):
	country_code = uni_address.get("country")
	country = UNICOMMERCE_COUNTRY_MAPPING.get(country_code)

	state = uni_address.get("state")
	if country_code == "IN" and state in UNICOMMERCE_INDIAN_STATES_MAPPING:
		state = UNICOMMERCE_INDIAN_STATES_MAPPING.get(state)

	frappe.get_doc(
		{
			"address_line1": uni_address.get("addressLine1") or "Not provided",
			"address_line2": uni_address.get("addressLine2"),
			"address_type": address_type,
			"city": uni_address.get("city"),
			"country": country,
			"county": uni_address.get("district"),
			"doctype": "Address",
			"email_id": uni_address.get("email"),
			"phone": uni_address.get("phone"),
			"pincode": uni_address.get("pincode"),
			"state": state,
			"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			"is_primary_address": int(address_type == "Billing"),
			"is_shipping_address": int(also_shipping or address_type == "Shipping"),
			"gstin": gstin if gstin != "null" else "",
			"gst_category": "Registered Regular" if gstin != "null" else "Unregistered",
		}
	).insert(ignore_mandatory=True)
