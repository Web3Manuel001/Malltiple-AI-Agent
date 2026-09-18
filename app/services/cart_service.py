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

def add_product_to_cart(customer_id: str, product_id: int, quantity: int = 1) -> dict:
    pdata = get_product_by_id(product_id)
    if not pdata.get("found"):
        return {"success": False, "error": f"Product #{product_id} not found in catalog. Search for the item first to get the verified ID."}
    if not pdata.get("in_stock"):
        return {"success": False, "error": f"{pdata['name']} is currently out of stock."}

    db = SessionLocal()
    cart_entry = db.query(CustomerCart).filter(CustomerCart.customer_id == str(customer_id)).first()
    if not cart_entry:
        cart_entry = CustomerCart(customer_id=str(customer_id), items_json="[]")
        db.add(cart_entry)

    items = json.loads(cart_entry.items_json)

    # Check if item is already in cart
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
            "quantity": quantity,
            "permalink": pdata.get("permalink")
        })

    cart_entry.items_json = json.dumps(items)
    cart_entry.updated_at = datetime.utcnow()
    db.commit()
    db.close()

    return view_customer_cart(customer_id)

def remove_product_from_cart(customer_id: str, product_id: int) -> dict:
    """Removes a product completely from the customer's cart."""
    db = SessionLocal()
    cart_entry = db.query(CustomerCart).filter(CustomerCart.customer_id == str(customer_id)).first()
    if not cart_entry:
        db.close()
        return {"success": True, "message": "Your cart is already empty."}

    items = json.loads(cart_entry.items_json)
    updated_items = [itm for itm in items if itm["product_id"] != product_id]

    cart_entry.items_json = json.dumps(updated_items)
    cart_entry.updated_at = datetime.utcnow()
    db.commit()
    db.close()

    return view_customer_cart(customer_id)

def view_customer_cart(customer_id: str) -> dict:
    cart_data = get_or_create_cart(customer_id)
    items = cart_data["items"]

    if not items:
        return {
            "empty": True,
            "message": "Your cart is currently empty. Tell me what product you'd like to add!"
        }

    total_naira = sum(item["unit_price"] * item["quantity"] for item in items)
    item_lines = []
    
    for item in items:
        pid = item['product_id']
        qty = item['quantity']
        # Fail-safe root URL that forces WooCommerce to populate the cart and redirect
        add_url = f"{settings.STORE_URL}/?add-to-cart={pid}&quantity={qty}"
        item_lines.append(f"• {item['name']} (x{qty}) — {item['unit_price'] * qty:,.2f} Naira\n  [Add & View]({add_url})")

    primary_id = items[0]["product_id"]
    primary_qty = items[0]["quantity"]
    main_checkout_url = f"{settings.STORE_URL}/?add-to-cart={primary_id}&quantity={primary_qty}"

    summary = (
        f"🛒 *Your Malltiple Cart:*\n" +
        "\n".join(item_lines) +
        f"\n\n*Total:* {total_naira:,.2f} Naira\n" +
        f"👉 *Open Cart & Checkout:* [Click Here]({main_checkout_url})"
    )

    return {
        "empty": False,
        "items": items,
        "total_naira": f"{total_naira:,.2f}",
        "checkout_url": main_checkout_url,
        "message": summary
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
