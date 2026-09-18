import html
import requests
import secrets
import string
from app.core.config import settings

HEADERS = {"User-Agent": "MalltipleAgent/1.0", "Content-Type": "application/json"}

def get_auth_params():
    return {
        "consumer_key": settings.CONSUMER_KEY,
        "consumer_secret": settings.CONSUMER_SECRET
    }

def normalize_nigerian_phone(phone: str) -> list:
    clean = ''.join(filter(str.isdigit, str(phone)))
    if len(clean) >= 10:
        last10 = clean[-10:]
        return [f"0{last10}", f"234{last10}", last10]
    return [clean] if clean else []

def find_or_create_wc_customer(email: str = None, phone: str = None, name: str = "Customer") -> dict:
    clean_email = (email or "").strip().lower()
    phone_variants = normalize_nigerian_phone(phone) if phone else []

    # 1. Search existing WooCommerce registered users by email
    if clean_email:
        res = requests.get(
            f"{settings.STORE_URL}/wp-json/wc/v3/customers",
            params={**get_auth_params(), "search": clean_email, "role": "all"},
            headers=HEADERS,
            timeout=8
        )
        if res.status_code == 200 and res.json():
            for cust in res.json():
                if cust.get("email", "").lower() == clean_email:
                    return {
                        "found": True,
                        "customer_id": cust.get("id"),
                        "name": f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or name,
                        "email": cust.get("email"),
                        "phone": cust.get("billing", {}).get("phone") or (phone_variants[0] if phone_variants else ""),
                        "city": cust.get("billing", {}).get("city", "")
                    }

    # 2. Search orders by email or phone
    search_terms = ([clean_email] if clean_email else []) + phone_variants
    for term in search_terms:
        res = requests.get(
            f"{settings.STORE_URL}/wp-json/wc/v3/orders",
            params={**get_auth_params(), "search": term, "per_page": 1},
            headers=HEADERS,
            timeout=8
        )
        if res.status_code == 200 and res.json():
            order = res.json()[0]
            billing = order.get("billing", {})
            return {
                "found": True,
                "customer_id": order.get("customer_id") or None,
                "name": f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or name,
                "email": billing.get("email") or clean_email,
                "phone": billing.get("phone") or (phone_variants[0] if phone_variants else ""),
                "city": billing.get("city", "")
            }

    # 3. If not found and email provided, register new account with valid username & password
    if clean_email:
        username = clean_email.split('@')[0] + "_" + secrets.token_hex(2)
        first_name = name.split()[0] if name else "Customer"
        last_name = " ".join(name.split()[1:]) if len(name.split()) > 1 else ""
        temp_password = secrets.token_urlsafe(12)

        payload = {
            "email": clean_email,
            "username": username,
            "password": temp_password,
            "first_name": first_name,
            "last_name": last_name,
            "billing": {
                "first_name": first_name,
                "last_name": last_name,
                "email": clean_email,
                "phone": phone_variants[0] if phone_variants else ""
            }
        }
        res = requests.post(
            f"{settings.STORE_URL}/wp-json/wc/v3/customers",
            params=get_auth_params(),
            json=payload,
            headers=HEADERS,
            timeout=8
        )
        if res.status_code in [200, 201]:
            cust = res.json()
            return {
                "found": True,
                "customer_id": cust.get("id"),
                "name": name,
                "email": clean_email,
                "phone": phone_variants[0] if phone_variants else "",
                "city": "",
                "created_now": True
            }

    return {"found": False, "message": "No account found. Please provide your email address to link your Malltiple account."}

def create_account_order(customer_id: int, line_items: list, customer_data: dict) -> dict:
    """
    Creates a pending order linked directly to customer_id.
    Appears in their Malltiple App and Website under 'My Account' -> 'Orders'!
    """
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/orders"
    params = get_auth_params()

    full_name = customer_data.get("name") or "Customer"
    first_name = full_name.split()[0]
    last_name = " ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else ""

    payload = {
        "customer_id": customer_id or 0,  # Links order directly to their Malltiple user account!
        "payment_method": "paystack",
        "payment_method_title": "Paystack (Debit Card / Bank Transfer)",
        "set_paid": False,
        "status": "pending",
        "billing": {
            "first_name": first_name,
            "last_name": last_name,
            "email": customer_data.get("email", ""),
            "phone": customer_data.get("phone", ""),
            "city": customer_data.get("city") or "Lagos",
            "country": "NG"
        },
        "shipping": {
            "first_name": first_name,
            "last_name": last_name,
            "city": customer_data.get("city") or "Lagos",
            "country": "NG"
        },
        "line_items": line_items
    }

    try:
        res = requests.post(endpoint, params=params, json=payload, headers=HEADERS, timeout=10)
        if res.status_code in [200, 201]:
            order = res.json()
            order_id = order.get("id")
            total = order.get("total")
            pay_url = order.get("payment_url") or f"{settings.STORE_URL}/checkout/order-pay/{order_id}/?pay_for_order=true&key={order.get('order_key')}"

            return {
                "success": True,
                "order_id": order_id,
                "total_naira": total,
                "payment_url": pay_url,
                "message": (
                    f"Order #{order_id} for {total} Naira has been placed under your account!\n\n"
                    f"📱 You can log into your Malltiple App/Site to see it under 'My Account > Orders', "
                    f"or pay immediately using this secure Paystack link:\n{pay_url}"
                )
            }
        return {"success": False, "error": f"Store returned status {res.status_code}: {res.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
                "in_stock": p.get("stock_status") == "instock"
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
