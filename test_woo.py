import os
import requests
from dotenv import load_dotenv

load_dotenv()

STORE_URL = os.getenv("WOO_STORE_URL")
CONSUMER_KEY = os.getenv("WOO_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("WOO_CONSUMER_SECRET")

def get_auth_params(extra_params=None):
    """Helper to attach credentials as query parameters."""
    params = {
        "consumer_key": CONSUMER_KEY,
        "consumer_secret": CONSUMER_SECRET
    }
    if extra_params:
        params.update(extra_params)
    return params

def test_orders():
    """Test reading orders to verify permission for customer support."""
    endpoint = f"{STORE_URL}/wp-json/wc/v3/orders"
    params = get_auth_params({"per_page": 1})
    headers = {"User-Agent": "MalltipleAgent/1.0"}

    print("\nChecking Order API access...")
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            orders = response.json()
            if orders:
                sample_order = orders[0]
                print("✅ SUCCESS: Order API accessible!")
                print(f"• Latest Order ID: #{sample_order.get('id')}")
                print(f"• Status:          {sample_order.get('status')}")
                print(f"• Total:           ₦{sample_order.get('total')}")
            else:
                print("✅ SUCCESS: Order API accessible! (No orders in store yet).")
        elif response.status_code == 403:
            print("❌ Permission Denied on Orders. Key may need 'Read/Write' permission.")
        else:
            print(f"❌ Orders API returned status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Error fetching orders: {e}")

if __name__ == "__main__":
    test_orders()