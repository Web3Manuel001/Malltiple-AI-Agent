import json
from groq import Groq
from app.core.config import settings
from app.services.woocommerce import (
    search_products, get_categories, track_order_live, 
    find_or_create_wc_customer
)
from app.services.cart_service import (
    add_product_to_cart, remove_product_from_cart, 
    view_customer_cart, clear_customer_cart
)
from app.services.customer_service import link_customer_identity

client = Groq(api_key=settings.GROQ_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products in catalog. ALWAYS call this first to get the real product ID.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Keyword"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_customer_account",
            "description": "Look up or link customer's Malltiple account by email or phone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Customer email"},
                    "phone": {"type": "string", "description": "Customer phone"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add a verified product ID to the customer's cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Numeric product ID"},
                    "quantity": {"type": "integer", "description": "Quantity", "default": 1}
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove a product from the customer's cart by its product ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Product ID to remove"}
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "View current shopping cart items, total in Naira, and checkout link.",
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
    has_account = customer_profile.get("has_profile", False)
    cust_name = customer_profile.get("name") or "Customer"
    cust_email = customer_profile.get("email") or "None"
    cust_phone = customer_profile.get("phone") or "None"

    return f"""
You are the official shopping assistant for Malltiple (malltiple.com.ng).

CUSTOMER ACCOUNT STATUS:
- Linked Account: {'YES' if has_account else 'NO'}
- Name: {cust_name}
- Email: {cust_email}
- Phone: {cust_phone}

SHOPPING & CART POLICY (STRICT):
1. When a customer asks for a product, ALWAYS call `search_products` first to get the verified product ID and live price in Naira.
2. If the customer wants to add an item to their cart, and their account is NOT linked (no email/phone):
   - Politely ask for their email address or phone number: "To save items to your Malltiple account, what is your email or phone number?"
   - Once they provide it, call `verify_customer_account(email, phone)` then immediately call `add_to_cart`.
3. If they ask to remove an item, call `remove_from_cart(product_id)`.
4. If they ask to see their cart, call `view_cart`.
5. Keep answers concise, helpful, and speak all prices in Naira (e.g. '11,500 Naira').
"""

def execute_turn(customer_key: str, customer_profile: dict, history: list) -> tuple:
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
            return "Sorry, I had a brief connection issue. Could you repeat that?", False, ""

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
                elif fn == "verify_customer_account":
                    result = find_or_create_wc_customer(
                        email=args.get("email"),
                        phone=args.get("phone"),
                        name=customer_profile.get("name", "Customer")
                    )
                    if result.get("found"):
                        link_customer_identity(
                            telegram_id=customer_key,
                            name=result.get("name"),
                            phone=result.get("phone"),
                            email=result.get("email"),
                            city=result.get("city")
                        )
                        customer_profile["has_profile"] = True
                        customer_profile.update(result)
                elif fn == "add_to_cart":
                    result = add_product_to_cart(customer_key, args.get("product_id"), args.get("quantity", 1))
                elif fn == "remove_from_cart":
                    result = remove_product_from_cart(customer_key, args.get("product_id"))
                elif fn == "view_cart":
                    result = view_customer_cart(customer_key)
                elif fn == "clear_cart":
                    result = clear_customer_cart(customer_key)
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
