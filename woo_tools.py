import os
import requests
from dotenv import load_dotenv

load_dotenv()

STORE_URL = os.getenv("WOO_STORE_URL")
CONSUMER_KEY = os.getenv("WOO_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("WOO_CONSUMER_SECRET")

HEADERS = {"User-Agent": "MalltipleAgent/1.0"}

def _get_auth_params(extra_params=None):
    params = {
        "consumer_key": CONSUMER_KEY,
        "consumer_secret": CONSUMER_SECRET
    }
    if extra_params:
        params.update(extra_params)
    return params

def search_products(query: str, per_page: int = 4) -> dict:
    """
    Smart product search with automatic keyword trimming and fuzzy fallback.
    """
    clean_query = query.strip()
    endpoint = f"{STORE_URL}/wp-json/wc/v3/products"

    # Attempt 1: Direct Search
    params = _get_auth_params({"search": clean_query, "per_page": per_page})

    try:
        response = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        products = response.json() if response.status_code == 200 else []

        # Attempt 2 (Fuzzy Fallback): If 0 results and query has multiple words,
        # try searching with the primary keyword (first word or longest word)
        if not products and len(clean_query.split()) > 1:
            words = [w for w in clean_query.split() if len(w) > 2]
            if words:
                fallback_keyword = words[0]  # E.g. from "Quaker Olds" -> try "Quaker"
                print(f"🔄 [Fuzzy Fallback] Retrying search with root keyword: '{fallback_keyword}'...")
                params = _get_auth_params({"search": fallback_keyword, "per_page": per_page})
                fallback_res = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
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
def get_order_status(order_id: int) -> dict:
    """
    Fetch the current status, total, and shipping notes of a specific order.
    """
    endpoint = f"{STORE_URL}/wp-json/wc/v3/orders/{order_id}"
    params = _get_auth_params()

    try:
        response = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            order = response.json()
            return {
                "found": True,
                "order_id": order.get("id"),
                "status": order.get("status"),
                "total_naira": order.get("total"),
                "date_created": order.get("date_created"),
                "items": [item.get("name") for item in order.get("line_items", [])]
            }
        elif response.status_code == 404:
            return {"found": False, "message": f"Order #{order_id} does not exist."}
        else:
            return {"error": f"Store returned status code {response.status_code}"}
    except Exception as e:
        return {"error": f"Failed to get order status: {str(e)}"}

def get_categories() -> dict:
    """
    Fetch all active product categories available on Malltiple.
    """
    endpoint = f"{STORE_URL}/wp-json/wc/v3/products/categories"
    params = _get_auth_params({"per_page": 25, "hide_empty": True})

    try:
        response = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            categories = response.json()
            cat_list = [c.get("name") for c in categories if c.get("name") != "Uncategorized"]
            return {"categories": cat_list}
        return {"error": f"Failed to fetch categories: {response.status_code}"}
    except Exception as e:
        return {"error": f"Category fetch error: {str(e)}"}

def find_customer_in_woocommerce(identifier: str) -> dict:
    """
    Search live WooCommerce orders by email or phone number to retrieve
    real customer billing details and past order history.
    """
    clean_id = str(identifier).strip()
    endpoint = f"{STORE_URL}/wp-json/wc/v3/orders"
    params = _get_auth_params({"search": clean_id, "per_page": 3})

    try:
        response = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            orders = response.json()
            if not orders:
                return {"found": False, "message": f"No past orders found in store for '{clean_id}'."}

            # Extract customer profile from their most recent order
            latest_order = orders[0]
            billing = latest_order.get("billing", {})
            first_name = billing.get("first_name", "")
            last_name = billing.get("last_name", "")
            full_name = f"{first_name} {last_name}".strip() or "Valued Customer"
            city = billing.get("city", "")
            phone = billing.get("phone", "")
            email = billing.get("email", "")

            # Compile recent order summaries
            order_history = []
            for o in orders:
                order_history.append({
                    "order_id": o.get("id"),
                    "status": o.get("status"),
                    "total_naira": o.get("total"),
                    "date": o.get("date_created", "")[:10]
                })

            return {
                "found": True,
                "name": full_name,
                "phone": phone,
                "email": email,
                "city": city,
                "last_order_id": latest_order.get("id"),
                "order_history": order_history
            }
        return {"found": False, "error": f"WooCommerce returned status {response.status_code}"}
    except Exception as e:
        return {"found": False, "error": f"Search error: {str(e)}"}