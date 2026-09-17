import html
import requests
from app.config import settings

HEADERS = {"User-Agent": "MalltipleAgent/1.0", "Content-Type": "application/json"}

def _get_auth():
    return {
        "consumer_key": settings.CONSUMER_KEY,
        "consumer_secret": settings.CONSUMER_SECRET
    }

def search_products(query: str, per_page: int = 4) -> dict:
    clean_query = query.strip()
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/products"
    params = {**_get_auth(), "search": clean_query, "per_page": per_page}

    try:
        res = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        products = res.json() if res.status_code == 200 else []

        if not products and len(clean_query.split()) > 1:
            words = [w for w in clean_query.split() if len(w) > 2]
            if words:
                fallback = requests.get(endpoint, params={**_get_auth(), "search": words[0], "per_page": per_page}, headers=HEADERS, timeout=8)
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

def get_categories() -> dict:
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/products/categories"
    params = {**_get_auth(), "per_page": 50, "hide_empty": True}
    try:
        res = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            return {"categories": [html.unescape(c.get("name")) for c in res.json() if c.get("name") not in ["All", "Uncategorized"]]}
        return {"error": "Failed to fetch categories"}
    except Exception as e:
        return {"error": str(e)}

def build_customer_cart(items: list) -> dict:
    """
    Safely calculates total price and provides direct link 
    for customer to review cart and pay securely on Malltiple.
    """
    if not items:
        return {"success": False, "error": "Cart is empty."}

    total_price = 0.0
    item_summaries = []
    primary_id = items[0]["product_id"]
    primary_qty = items[0].get("quantity", 1)

    for item in items:
        pid = item.get("product_id")
        qty = item.get("quantity", 1)

        res = requests.get(f"{settings.STORE_URL}/wp-json/wc/v3/products/{pid}", params=_get_auth(), headers=HEADERS, timeout=8)
        if res.status_code == 200:
            pdata = res.json()
            p_price = float(pdata.get("price") or 0.0)
            p_name = pdata.get("name")
            subtotal = p_price * qty
            total_price += subtotal
            item_summaries.append(f"{p_name} (x{qty}) - {subtotal:,.2f} Naira")

    # Native, 100% fail-safe direct Add-to-Cart URL
    cart_url = f"{settings.STORE_URL}/cart/?add-to-cart={primary_id}&quantity={primary_qty}"

    return {
        "success": True,
        "items": item_summaries,
        "total_naira": f"{total_price:,.2f}",
        "cart_url": cart_url,
        "message": f"Cart total is {total_price:,.2f} Naira. Click the link to review and pay securely on Malltiple."
    }

def track_order_live(order_id: int) -> dict:
    endpoint = f"{settings.STORE_URL}/wp-json/wc/v3/orders/{order_id}"
    try:
        res = requests.get(endpoint, params=_get_auth(), headers=HEADERS, timeout=8)
        if res.status_code == 200:
            order = res.json()
            notes_res = requests.get(f"{endpoint}/notes", params=_get_auth(), headers=HEADERS, timeout=8)
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
