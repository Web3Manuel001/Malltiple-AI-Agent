import json
from datetime import datetime
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.cart import CustomerCart
from app.services.woocommerce import get_product_by_id

def get_or_create_cart(customer_id: str) -> dict:
    db = SessionLocal()
    cart_entry = db.query(CustomerCart).filter(CustomerCart.customer_id == str(customer_id)).first()
    if not cart_entry:
        cart_entry = CustomerCart(customer_id=str(customer_id), items_json="[]")
        db.add(cart_entry)
        db.commit()
        db.refresh(cart_entry)

    items = json.loads(cart_entry.items_json)
    db.close()
    return {"customer_id": str(customer_id), "items": items}

def add_product_to_cart(customer_id: str, product_id: int, quantity: int = 1, customer_phone: str = "") -> dict:
    pdata = get_product_by_id(product_id)
    if not pdata.get("found"):
        return {"success": False, "error": f"Product #{product_id} not found in catalog. Search for the item first to verify the ID."}
    if not pdata.get("in_stock"):
        return {"success": False, "error": f"{pdata['name']} is currently out of stock."}

    db = SessionLocal()
    cart_entry = db.query(CustomerCart).filter(CustomerCart.customer_id == str(customer_id)).first()
    if not cart_entry:
        cart_entry = CustomerCart(customer_id=str(customer_id), items_json="[]")
        db.add(cart_entry)

    items = json.loads(cart_entry.items_json)

    # Check if item already exists in cart
    found = False
    for itm in items:
        if itm["product_id"] == product_id:
            itm["quantity"] += quantity
            found = True
            break

    if not found:
        items.append({
            "product_id": product_id,
            "name": pdata["name"],
            "unit_price": pdata["price"],
            "quantity": quantity
        })

    cart_entry.items_json = json.dumps(items)
    cart_entry.updated_at = datetime.utcnow()
    db.commit()
    db.close()

    return view_customer_cart(customer_id, customer_phone)

def view_customer_cart(customer_id: str, customer_phone: str = "") -> dict:
    cart_data = get_or_create_cart(customer_id)
    items = cart_data["items"]

    if not items:
        return {
            "empty": True,
            "message": "Your cart is currently empty. Tell me what products you want to add!"
        }

    total_naira = sum(item["unit_price"] * item["quantity"] for item in items)
    item_lines = [
        f"• {item['name']} (x{item['quantity']}) — {item['unit_price'] * item['quantity']:,.2f} Naira"
        for item in items
    ]

    # Direct Checkout URL that drops item directly into checkout and never 404s or empties
    primary_id = items[0]["product_id"]
    primary_qty = items[0]["quantity"]
    
    phone_param = f"&billing_phone={customer_phone}" if customer_phone else ""
    checkout_url = f"{settings.STORE_URL}/checkout/?add-to-cart={primary_id}&quantity={primary_qty}{phone_param}"

    return {
        "empty": False,
        "items": item_lines,
        "total_naira": f"{total_naira:,.2f}",
        "checkout_url": checkout_url,
        "message": f"Cart items:\n" + "\n".join(item_lines) + f"\n\nTotal: {total_naira:,.2f} Naira.\n👉 Complete Checkout Here: {checkout_url}"
    }

def clear_customer_cart(customer_id: str) -> dict:
    db = SessionLocal()
    cart_entry = db.query(CustomerCart).filter(CustomerCart.customer_id == str(customer_id)).first()
    if cart_entry:
        cart_entry.items_json = "[]"
        cart_entry.updated_at = datetime.utcnow()
        db.commit()
    db.close()
    return {"success": True, "message": "Your cart has been cleared."}
