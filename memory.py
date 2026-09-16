import sqlite3
from datetime import datetime
from woo_tools import find_customer_in_woocommerce

DB_FILE = "malltiple.db"

def init_db():
    """Initializes SQLite tables and handles schema migration for email."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        phone TEXT PRIMARY KEY,
        email TEXT,
        name TEXT,
        city TEXT,
        last_order_id INTEGER,
        notes TEXT,
        updated_at TIMESTAMP
    )
    """)

    # Safe migration: Add email column if it doesn't exist yet
    try:
        cursor.execute("ALTER TABLE customers ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        created_at TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

def get_customer(identifier: str) -> dict:
    """
    1. Checks local SQLite first.
    2. If not found, searches live WooCommerce orders.
    3. If found in WooCommerce, automatically saves/caches to SQLite.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    clean_id = str(identifier).strip().lower()

    # Step 1: Check SQLite
    cursor.execute("""
        SELECT phone, email, name, city, last_order_id, notes 
        FROM customers 
        WHERE LOWER(phone) = ? OR LOWER(email) = ?
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    conn.close()

    if row and row[2]:  # If found and has a name
        return {
            "found": True,
            "source": "memory",
            "phone": row[0],
            "email": row[1],
            "name": row[2],
            "city": row[3],
            "last_order_id": row[4],
            "notes": row[5]
        }

    # Step 2: Fallback to live WooCommerce
    print(f"\n🔍 [Store Search] Searching live WooCommerce for '{identifier}'...")
    live_data = find_customer_in_woocommerce(identifier)

    if live_data.get("found"):
        # Step 3: Cache live customer to SQLite
        save_or_update_customer(
            phone=live_data.get("phone"),
            email=live_data.get("email"),
            name=live_data.get("name"),
            city=live_data.get("city"),
            last_order_id=live_data.get("last_order_id")
        )
        live_data["source"] = "live_store"
        return live_data

    return {"found": False, "message": f"No customer account or past orders found for {identifier}."}

def save_or_update_customer(phone: str = None, email: str = None, name: str = None, city: str = None, last_order_id: int = None, notes: str = None) -> dict:
    """
    Save or update customer details using phone or email.
    """
    if not phone and not email:
        return {"error": "Either phone number or email address is required."}

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    # Search for an existing record by phone or email
    cursor.execute("""
        SELECT phone, email, name, city, last_order_id, notes 
        FROM customers 
        WHERE (phone IS NOT NULL AND phone = ?) OR (email IS NOT NULL AND LOWER(email) = LOWER(?))
    """, (phone or "", email or ""))
    
    existing = cursor.fetchone()

    if existing:
        primary_key = existing[0] or phone
        new_email = email or existing[1]
        new_name = name or existing[2]
        new_city = city or existing[3]
        new_order = last_order_id or existing[4]
        new_notes = notes or existing[5]

        cursor.execute("""
            UPDATE customers 
            SET email = ?, name = ?, city = ?, last_order_id = ?, notes = ?, updated_at = ?
            WHERE phone = ?
        """, (new_email, new_name, new_city, new_order, new_notes, now, primary_key))
    else:
        # Generate placeholder key if customer only gave email
        primary_key = phone if phone else f"email_{email}"
        cursor.execute("""
            INSERT INTO customers (phone, email, name, city, last_order_id, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (primary_key, email, name, city, last_order_id, notes, now))

    conn.commit()
    conn.close()
    return {"status": "success", "message": "Customer profile saved successfully."}

init_db()

def log_message(user_id: str, sender: str, text: str, user_name: str = "Unknown"):
    """Saves every interaction (customer, AI, human) into the audit table."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            user_name TEXT,
            sender TEXT,
            message TEXT,
            timestamp TIMESTAMP
        )
    """)

    cursor.execute("""
        INSERT INTO chat_audit_logs (user_id, user_name, sender, message, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (str(user_id), user_name, sender, text, now))

    conn.commit()
    conn.close()

def add_agent(telegram_id: str, name: str):
    """Register a new human customer care agent."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_agents (
            telegram_id TEXT PRIMARY KEY,
            name TEXT,
            is_active INTEGER DEFAULT 1,
            added_at TIMESTAMP
        )
    """)
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO support_agents (telegram_id, name, is_active, added_at)
        VALUES (?, ?, 1, ?)
    """, (str(telegram_id), name, now))
    conn.commit()
    conn.close()
    return f"Agent {name} ({telegram_id}) registered successfully."

def is_authorized_agent(telegram_id: str) -> dict:
    """Check if a telegram ID belongs to an active agent or admin."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_agents (
            telegram_id TEXT PRIMARY KEY,
            name TEXT,
            is_active INTEGER DEFAULT 1,
            added_at TIMESTAMP
        )
    """)
    cursor.execute("SELECT name FROM support_agents WHERE telegram_id = ? AND is_active = 1", (str(telegram_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"authorized": True, "name": row[0]}
    return {"authorized": False, "name": None}

def get_all_active_agents() -> list:
    """Retrieve all registered human agents to broadcast escalations."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_agents (
            telegram_id TEXT PRIMARY KEY,
            name TEXT,
            is_active INTEGER DEFAULT 1,
            added_at TIMESTAMP
        )
    """)
    cursor.execute("SELECT telegram_id, name FROM support_agents WHERE is_active = 1")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1]} for r in rows]