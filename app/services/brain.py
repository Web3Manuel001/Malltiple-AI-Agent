import json
import logging
from groq import Groq
from app.core.config import settings
from app.services.woocommerce import (
    search_products, get_categories, track_order_live, 
    find_or_create_wc_customer, create_account_order
)
from app.services.cart_service import (
    add_product_to_cart, remove_product_from_cart, 
    view_customer_cart, clear_customer_cart
)
from app.services.customer_service import link_customer_identity

logger = logging.getLogger("brain")
client = Groq(api_key=settings.GROQ_API_KEY)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products in catalog. ALWAYS call this first to get the verified product ID.",
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
            "description": "Add a verified product ID to customer's cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Numeric product ID"},
                    "quantity": {"type": "integer", "default": 1}
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove a product from the cart by its product ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer"}
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
            "name": "create_account_order",
            "description": "Place an official order attached to the customer's Malltiple account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "line_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "quantity": {"type": "integer", "default": 1}
                            },
                            "required": ["product_id", "quantity"]
                        }
                    },
                    "delivery_city": {"type": "string", "default": "Lagos"}
                },
                "required": ["line_items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "track_order_live",
            "description": "Track order status and dispatch updates using Order ID.",
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
    cust_name = customer_profile.get("name") or "Customer"
    cust_email = customer_profile.get("email") or "None"
    cust_phone = customer_profile.get("phone") or "None"
    cust_id = customer_profile.get("customer_id") or "Guest"

    return f"""
You are the official shopping assistant for Malltiple (malltiple.com.ng).

CUSTOMER ACCOUNT:
- Account ID: {cust_id}
- Name: {cust_name}
- Email: {cust_email}
- Phone: {cust_phone}

SHOPPING & CART RULES:
1. When asked for an item, call `search_products` first to get the verified product ID and price.
2. If customer wants to add an item or buy, and their Account ID is 'Guest' (no email on file):
   - Ask for their email address: "To link your Malltiple account, what is your email address?"
   - Once provided, immediately call `verify_customer_account(email)` and then proceed to add their items!
3. To add an item, call `add_to_cart(product_id, quantity)`.
4. Always speak prices in Naira (e.g. '550 Naira', '11,500 Naira', never 'N550').
5. After adding an item, ALWAYS give them the confirmation with the item name, total in Naira, and the checkout link.
"""

def execute_turn(customer_key: str, customer_profile: dict, history: list) -> tuple:
    system_prompt = build_system_prompt(customer_profile)
    messages = [{"role": "system", "content": system_prompt}] + history[-5:]
    escalated = False
    reason = ""

    # Allow up to 4 tool executions
    for _ in range(4):
        try:
            res = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=400
            )
        except Exception as e:
            logger.error(f"Groq error: {e}")
            return "Sorry, I had a brief connection glitch. Could you repeat that?", False, ""

        msg = res.choices[0].message

        # Case 1: Model wants to call one or more tools
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
                        customer_profile["customer_id"] = result.get("customer_id")
                        customer_profile["email"] = result.get("email")
                        customer_profile["name"] = result.get("name")
                elif fn == "add_to_cart":
                    result = add_product_to_cart(customer_key, args.get("product_id"), args.get("quantity", 1))
                elif fn == "remove_from_cart":
                    result = remove_product_from_cart(customer_key, args.get("product_id"))
                elif fn == "view_cart":
                    result = view_customer_cart(customer_key)
                elif fn == "create_account_order":
                    cust_id = customer_profile.get("customer_id")
                    result = create_account_order(
                        customer_id=cust_id,
                        line_items=args.get("line_items", []),
                        customer_data=customer_profile
                    )
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
        
        # Case 2: Model generated its natural response
        else:
            return msg.content or "", escalated, reason

    # If all turns were tools, force ONE final conversational generation without tools
    try:
        final_res = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=messages,
            tool_choice="none",
            temperature=0.2,
            max_tokens=400
        )
        return final_res.choices[0].message.content or "", escalated, reason
    except Exception:
        return "I've updated your items! Would you like to view your cart or proceed to checkout?", False, ""
