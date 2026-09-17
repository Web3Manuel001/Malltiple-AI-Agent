import json
from groq import Groq
from app.core.config import settings
from app.services.woocommerce import search_products, get_categories, track_order_live
from app.services.cart_service import add_product_to_cart, view_customer_cart, clear_customer_cart

client = Groq(api_key=settings.GROQ_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products in catalog by 1-2 core keywords.",
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
            "description": "Add a product to the customer's personal shopping cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Numeric product ID"},
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
            "description": "View the customer's current shopping cart items, total in Naira, and checkout link.",
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

SYSTEM_PROMPT = """
You are the official customer assistant for Malltiple (malltiple.com.ng), a Nigerian online marketplace.
Help customers search products, manage their personal cart, and track orders.

CART & SHOPPING WORKFLOW:
- When customers search for items, use `search_products`.
- When they want to add an item to their cart, call `add_to_cart` with the product_id and quantity.
- When they ask "what is in my cart?" or "how much is my total?", call `view_cart`.
- Provide the checkout link so they can complete payment securely on the Malltiple website.

RULES:
- Never write 'N' or '₦' before numbers. Always write '11,500 Naira'.
- If customer demands a human or reports a double debit/dispute, call `escalate_to_human`.
- Keep answers short, friendly, and helpful.
"""

def execute_turn(customer_id: str, history: list) -> tuple:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-6:]
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
                    result = add_product_to_cart(customer_id, args.get("product_id"), args.get("quantity", 1))
                elif fn == "view_cart":
                    result = view_customer_cart(customer_id)
                elif fn == "clear_cart":
                    result = clear_customer_cart(customer_id)
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
