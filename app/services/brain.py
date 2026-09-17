import json
from groq import Groq
from app.core.config import settings
from app.services.woocommerce import search_products, get_categories, track_order_live
from app.services.cart_service import add_product_to_cart, view_customer_cart, clear_customer_cart
from app.services.customer_service import link_customer_identity

client = Groq(api_key=settings.GROQ_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products in catalog by 1-2 core keywords. ALWAYS call this first to get real product IDs.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search keyword"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add a product to the customer's personal shopping cart using its verified product_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Numeric product ID from search_products"},
                    "quantity": {"type": "integer", "description": "Quantity to add", "default": 1}
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "View current shopping cart items, total in Naira, and direct checkout link.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_cart",
            "description": "Clear all items from the customer's shopping cart.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_customer_details",
            "description": "Remember the customer's name, phone, email, or delivery city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "city": {"type": "string"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "track_order_live",
            "description": "Track order fulfillment status and dispatch updates using Order ID.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "List all product departments available on Malltiple.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Escalate conversation to human staff for complaints or customer demand.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"]
            }
        }
    }
]

def build_system_prompt(customer_profile: dict) -> str:
    cust_name = customer_profile.get("name") or "Valued Customer"
    cust_phone = customer_profile.get("phone") or "Not provided"
    cust_email = customer_profile.get("email") or "Not provided"
    cust_city = customer_profile.get("city") or "Not provided"

    return f"""
You are the official shopping assistant for Malltiple (malltiple.com.ng), a Nigerian marketplace.

CURRENT CUSTOMER PROFILE:
- Name: {cust_name}
- Phone: {cust_phone}
- Email: {cust_email}
- Location: {cust_city}

CRITICAL SHOPPING & CART RULES:
1. ALWAYS call `search_products` first when a customer asks for an item so you have the real `product_id`. NEVER guess a product ID.
2. When the customer wants to add an item to their cart, call `add_to_cart(product_id, quantity)`.
3. If the customer mentions their name, phone, or email, call `save_customer_details` to link their profile.
4. When showing cart totals, provide the checkout link so they can tap and pay securely on Malltiple.

CURRENCY & TONE:
- Write all prices in Naira (e.g. '11,500 Naira', never 'N11,500').
- If customer demands a human or reports a double debit, call `escalate_to_human`.
"""

def execute_turn(telegram_id: str, customer_profile: dict, history: list) -> tuple:
    system_prompt = build_system_prompt(customer_profile)
    messages = [{"role": "system", "content": system_prompt}] + history[-6:]
    escalated = False
    reason = ""

    while True:
        try:
            res = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=400
            )
        except Exception:
            return "Sorry, I had a brief connection glitch. Could you repeat that?", False, ""

        msg = res.choices[0].message
        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            })

            for call in msg.tool_calls:
                fn = call.function.name
                args = json.loads(call.function.arguments)
                tool_id = call.id

                if fn == "search_products":
                    result = search_products(args.get("query", ""))
                elif fn == "add_to_cart":
                    result = add_product_to_cart(
                        customer_id=telegram_id, 
                        product_id=args.get("product_id"), 
                        quantity=args.get("quantity", 1),
                        customer_phone=customer_profile.get("phone", "")
                    )
                elif fn == "view_cart":
                    result = view_customer_cart(telegram_id, customer_profile.get("phone", ""))
                elif fn == "clear_cart":
                    result = clear_customer_cart(telegram_id)
                elif fn == "save_customer_details":
                    result = link_customer_identity(
                        telegram_id=telegram_id,
                        name=args.get("name"),
                        phone=args.get("phone"),
                        email=args.get("email"),
                        city=args.get("city")
                    )
                    # Update active profile in place
                    customer_profile.update(result)
                elif fn == "track_order_live":
                    result = track_order_live(args.get("order_id", 0))
                elif fn == "get_categories":
                    result = get_categories()
                elif fn == "escalate_to_human":
                    escalated = True
                    reason = args.get("reason", "Customer requested human support.")
                    result = {"status": "escalated", "message": "Support team notified."}
                else:
                    result = {"error": "Unknown tool"}

                messages.append({"role": "tool", "tool_call_id": tool_id, "name": fn, "content": json.dumps(result)})
            continue
        else:
            return msg.content or "", escalated, reason
