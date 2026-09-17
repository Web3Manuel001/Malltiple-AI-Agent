import os
import html
import requests
from dotenv import load_dotenv

load_dotenv()

STORE_URL = os.getenv("WOO_STORE_URL")
CONSUMER_KEY = os.getenv("WOO_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("WOO_CONSUMER_SECRET")
HEADERS = {"User-Agent": "MalltipleAgent/1.0", "Content-Type": "application/json"}

def _get_auth_params(extra_params=None):
    params = {
        "consumer_key": CONSUMER_KEY,
        "consumer_secret": CONSUMER_SECRET
    }
    if extra_params:
        params.update(extra_params)
    return params

def search_products(query: str, per_page: int = 4) -> dict:
    """Smart product search with fuzzy fallback."""
    clean_query = query.strip()
    endpoint = f"{STORE_URL}/wp-json/wc/v3/products"
    params = _get_auth_params({"search": clean_query, "per_page": per_page})

    try:
        response = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        products = response.json() if response.status_code == 200 else []

        if not products and len(clean_query.split()) > 1:
            words = [w for w in clean_query.split() if len(w) > 2]
            if words:
                fallback_res = requests.get(endpoint, params=_get_auth_params({"search": words[0], "per_page": per_page}), headers=HEADERS, timeout=8)
                if fallback_res.status_code == 200:
                    products = fallback_res.json()

        if not products:
            return {"found": False, "message": f"No products found matching '{clean_query}'."}

        clean_results = []
        for item in products:
            clean_results.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "price_naira": item.get("price"),
                "in_stock": item.get("stock_status") == "instock",
                "permalink": item.get("permalink")
            })
        return {"found": True, "count": len(clean_results), "products": clean_results}
    except Exception as e:
        return {"error": f"Product search error: {str(e)}"}

def get_categories() -> dict:
    """Fetch all active categories."""
    endpoint = f"{STORE_URL}/wp-json/wc/v3/products/categories"
    params = _get_auth_params({"per_page": 50, "hide_empty": True})
    try:
        response = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            return {"categories": [html.unescape(c.get("name")) for c in response.json() if c.get("name") not in ["All", "Uncategorized"]]}
        return {"error": "Failed to fetch categories"}
    except Exception as e:
        return {"error": str(e)}

def create_order_and_payment_link(customer_name: str, phone: str, delivery_address: str, city: str, line_items: list) -> dict:
    """
    Creates a real pending order in WooCommerce and returns an error-free,
    secure direct Paystack/WooCommerce payment URL.
    line_items format: [{"product_id": 18376, "quantity": 1}]
    """
    endpoint = f"{STORE_URL}/wp-json/wc/v3/orders"
    params = _get_auth_params()

    first_name = customer_name.split()[0]
    last_name = " ".join(customer_name.split()[1:]) if len(customer_name.split()) > 1 else ""

    payload = {
        "payment_method": "paystack",
        "payment_method_title": "Debit Card / Bank Transfer (Paystack)",
        "set_paid": False,
        "billing": {
            "first_name": first_name,
            "last_name": last_name,
            "address_1": delivery_address,
            "city": city,
            "country": "NG",
            "phone": phone
        },
        "shipping": {
            "first_name": first_name,
            "last_name": last_name,
            "address_1": delivery_address,
            "city": city,
            "country": "NG"
        },
        "line_items": line_items
    }

    try:
        response = requests.post(endpoint, params=params, json=payload, headers=HEADERS, timeout=12)
        if response.status_code in [200, 201]:
            order = response.json()
            order_id = order.get("id")
            order_key = order.get("order_key")
            total = order.get("total")

            # Official WooCommerce direct Pay-for-Order link:
            # When clicked, opens Paystack checkout cleanly on Malltiple with zero friction!
            payment_url = f"{STORE_URL}/checkout/order-pay/{order_id}/?pay_for_order=true&key={order_key}"

            return {
                "success": True,
                "order_id": order_id,
                "total_naira": total,
                "payment_url": payment_url,
                "message": f"Order #{order_id} created for {total} Naira. Pay securely using the link."
            }
        return {"success": False, "error": f"Store returned status {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to create order: {str(e)}"}

def track_order_live(order_id: int) -> dict:
    """
    Checks order fulfillment status and pulls courier/rider tracking notes.
    """
    endpoint = f"{STORE_URL}/wp-json/wc/v3/orders/{order_id}"
    params = _get_auth_params()

    try:
        response = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            order = response.json()

            # Also pull order notes to see if a courier/tracking link was added
            notes_endpoint = f"{STORE_URL}/wp-json/wc/v3/orders/{order_id}/notes"
            notes_res = requests.get(notes_endpoint, params=params, headers=HEADERS, timeout=8)
            dispatch_notes = []
            if notes_res.status_code == 200:
                for n in notes_res.json():
                    if n.get("customer_note"):
                        dispatch_notes.append(n.get("note"))

            return {
                "found": True,
                "order_id": order.get("id"),
                "status": order.get("status"),
                "total_naira": order.get("total"),
                "date_created": order.get("date_created", "")[:10],
                "shipping_city": order.get("shipping", {}).get("city", "N/A"),
                "items": [f"{i.get('name')} (x{i.get('quantity')})" for i in order.get("line_items", [])],
                "dispatch_updates": dispatch_notes if dispatch_notes else ["Order is being processed at the warehouse."]
            }
        elif response.status_code == 404:
            return {"found": False, "message": f"Order #{order_id} not found."}
        return {"found": False, "error": f"Status {response.status_code}"}
    except Exception as e:
        return {"found": False, "error": str(e)}

# Backward compatibility alias
get_order_status = track_order_live
