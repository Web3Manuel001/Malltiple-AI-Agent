import html
import requests
from app.core.config import settings

HEADERS = {"User-Agent": "MalltipleAgent/1.0", "Content-Type": "application/json"}

def get_auth_params():
    return {
        "consumer_key": settings.CONSUMER_KEY,
        "consumer_secret": settings.CONSUMER_SECRET
    }

def search_products(query: str, per_page: int = 4) -> dict:
    clean_query = query.strip()
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/products"
    params = {**get_auth_params(), "search": clean_query, "per_page": per_page}

    try:
        res = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        products = res.json() if res.status_code == 200 else []

        if not products and len(clean_query.split()) > 1:
            words = [w for w in clean_query.split() if len(w) > 2]
            if words:
                fallback = requests.get(endpoint, params={**get_auth_params(), "search": words[0], "per_page": per_page}, headers=HEADERS, timeout=8)
                if fallback.status_code == 200:
                    products = fallback.json()

        if not products:
            return {"found": False, "message": f"No products found matching '{clean_query}'."}

        clean = []
        for item in products:
            clean.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "price_naira": item.get("price"),
                "in_stock": item.get("stock_status") == "instock",
                "permalink": item.get("permalink")
            })
        return {"found": True, "count": len(clean), "products": clean}
    except Exception as e:
        return {"error": f"Search error: {str(e)}"}

def get_product_by_id(product_id: int) -> dict:
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/products/{product_id}"
    try:
        res = requests.get(endpoint, params=get_auth_params(), headers=HEADERS, timeout=8)
        if res.status_code == 200:
            p = res.json()
            return {
                "found": True,
                "id": p.get("id"),
                "name": p.get("name"),
                "price": float(p.get("price") or 0.0),
                "in_stock": p.get("stock_status") == "instock",
                "permalink": p.get("permalink")
            }
        return {"found": False}
    except Exception:
        return {"found": False}

def get_categories() -> dict:
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/products/categories"
    params = {**get_auth_params(), "per_page": 50, "hide_empty": True}
    try:
        res = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            return {"categories": [html.unescape(c.get("name")) for c in res.json() if c.get("name") not in ["All", "Uncategorized"]]}
        return {"error": "Failed to fetch categories"}
    except Exception as e:
        return {"error": str(e)}

# --- ACCOUNT-LINKED CART OPERATIONS ---

def find_or_create_wc_customer(email: str = None, phone: str = None, name: str = "Customer") -> dict:
    """
    Looks up customer account on WooCommerce by email or phone.
    Creates an account if they don't have one yet.
    """
    clean_email = (email or "").strip().lower()
    clean_phone = (phone or "").strip()

    # 1. Search by email
    if clean_email:
        res = requests.get(f"{settings.STORE_URL}/wp-json/wc/v3/customers", params={**get_auth_params(), "email": clean_email}, headers=HEADERS, timeout=8)
        if res.status_code == 200 and res.json():
            cust = res.json()[0]
            return {
                "found": True,
                "customer_id": cust.get("id"),
                "name": f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or name,
                "email": cust.get("email"),
                "phone": cust.get("billing", {}).get("phone") or clean_phone,
                "city": cust.get("billing", {}).get("city")
            }

    # 2. Search recent orders by phone if email wasn't provided
    if clean_phone:
        res = requests.get(f"{settings.STORE_URL}/wp-json/wc/v3/orders", params={**get_auth_params(), "search": clean_phone, "per_page": 1}, headers=HEADERS, timeout=8)
        if res.status_code == 200 and res.json():
            order = res.json()[0]
            billing = order.get("billing", {})
            return {
                "found": True,
                "customer_id": order.get("customer_id") or None,
                "name": f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or name,
                "email": billing.get("email") or clean_email,
                "phone": billing.get("phone") or clean_phone,
                "city": billing.get("city")
            }

    # 3. Create a new WooCommerce customer if not found
    if clean_email:
        first_name = name.split()[0]
        last_name = " ".join(name.split()[1:]) if len(name.split()) > 1 else ""
        payload = {
            "email": clean_email,
            "first_name": first_name,
            "last_name": last_name,
            "billing": {"first_name": first_name, "last_name": last_name, "phone": clean_phone, "email": clean_email}
        }
        res = requests.post(f"{settings.STORE_URL}/wp-json/wc/v3/customers", params=get_auth_params(), json=payload, headers=HEADERS, timeout=8)
        if res.status_code in [200, 201]:
            cust = res.json()
            return {
                "found": True,
                "customer_id": cust.get("id"),
                "name": name,
                "email": clean_email,
                "phone": clean_phone
            }

    return {"found": False, "message": "Please provide an email or phone number to access your account."}

def track_order_live(order_id: int) -> dict:
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/orders/{order_id}"
    try:
        res = requests.get(endpoint, params=get_auth_params(), headers=HEADERS, timeout=8)
        if res.status_code == 200:
            order = res.json()
            notes_res = requests.get(f"{endpoint}/notes", params=get_auth_params(), headers=HEADERS, timeout=8)
            dispatch = [n.get("note") for n in notes_res.json() if n.get("customer_note")] if notes_res.status_code == 200 else []
            return {
                "found": True,
                "order_id": order.get("id"),
                "status": order.get("status"),
                "total_naira": order.get("total"),
                "date_created": order.get("date_created", "")[:10],
                "items": [f"{i.get('name')} (x{i.get('quantity')})" for i in order.get("line_items", [])],
                "dispatch_updates": dispatch if dispatch else ["Order is being processed at the warehouse."]
            }
        return {"found": False, "message": f"Order #{order_id} not found."}
    except Exception as e:
        return {"found": False, "error": str(e)}
