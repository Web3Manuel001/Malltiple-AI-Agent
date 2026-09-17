import sqlite3
from datetime import datetime

DB_FILE = "malltiple.db"

def init_db():
    """Initializes and migrates all database tables."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. Customer Profiles
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

    # 2. Support Agents Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS support_agents (
        telegram_id TEXT PRIMARY KEY,
        name TEXT,
        is_active INTEGER DEFAULT 1,
        total_time_seconds INTEGER DEFAULT 0,
        tickets_resolved INTEGER DEFAULT 0,
        added_at TIMESTAMP
    )
    """)

    # 3. Support Sessions (Tracks exact handling time per ticket)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ticket_sessions (
        ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id TEXT,
        customer_name TEXT,
        assigned_agent_id TEXT,
        assigned_agent_name TEXT,
        status TEXT DEFAULT 'open',
        claimed_at TIMESTAMP,
        resolved_at TIMESTAMP,
        duration_seconds INTEGER DEFAULT 0
    )
    """)

    # 4. CSAT Customer Satisfaction Ratings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS csat_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER,
        customer_id TEXT,
        agent_id TEXT,
        agent_name TEXT,
        rating INTEGER, -- 1 to 5 stars
        created_at TIMESTAMP
    )
    """)

    # 5. Full Chat Audit Logs
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

    conn.commit()
    conn.close()

# --- AGENT & ANALYTICS FUNCTIONS ---

def add_agent(telegram_id: str, name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO support_agents (telegram_id, name, is_active, total_time_seconds, tickets_resolved, added_at)
        VALUES (?, ?, 1, 0, 0, ?)
    """, (str(telegram_id), name, now))
    conn.commit()
    conn.close()
    return f"Agent {name} ({telegram_id}) registered successfully."

def is_authorized_agent(telegram_id: str) -> dict:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM support_agents WHERE telegram_id = ? AND is_active = 1", (str(telegram_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"authorized": True, "name": row[0]}
    return {"authorized": False, "name": None}

def get_all_active_agents() -> list:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id, name FROM support_agents WHERE is_active = 1")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1]} for r in rows]

def record_ticket_claim(customer_id: str, customer_name: str, agent_id: str, agent_name: str) -> int:
    """Logs when an agent claims a ticket to begin timing handling duration."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO ticket_sessions (customer_id, customer_name, assigned_agent_id, assigned_agent_name, status, claimed_at)
        VALUES (?, ?, ?, ?, 'claimed', ?)
    """, (str(customer_id), customer_name, str(agent_id), agent_name, now))
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return ticket_id

def record_ticket_resolution(customer_id: str, agent_id: str) -> dict:
    """Calculates exact handling duration and closes the ticket session."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now()

    # Find open claimed session
    cursor.execute("""
        SELECT ticket_id, claimed_at, assigned_agent_name 
        FROM ticket_sessions 
        WHERE customer_id = ? AND status = 'claimed' 
        ORDER BY ticket_id DESC LIMIT 1
    """, (str(customer_id),))
    row = cursor.fetchone()

    duration = 0
    ticket_id = None
    agent_name = "Agent"

    if row:
        ticket_id = row[0]
        claimed_at = datetime.fromisoformat(row[1])
        agent_name = row[2]
        duration = int((now - claimed_at).total_seconds())

        cursor.execute("""
            UPDATE ticket_sessions 
            SET status = 'resolved', resolved_at = ?, duration_seconds = ?
            WHERE ticket_id = ?
        """, (now.isoformat(), duration, ticket_id))

        # Update agent lifetime totals
        cursor.execute("""
            UPDATE support_agents 
            SET total_time_seconds = total_time_seconds + ?, tickets_resolved = tickets_resolved + 1
            WHERE telegram_id = ?
        """, (duration, str(agent_id)))

    conn.commit()
    conn.close()
    return {"ticket_id": ticket_id, "duration_seconds": duration, "agent_name": agent_name}

def record_csat_rating(ticket_id: int, customer_id: str, agent_id: str, agent_name: str, rating: int):
    """Saves a 1-5 star customer satisfaction rating."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO csat_ratings (ticket_id, customer_id, agent_id, agent_name, rating, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ticket_id, str(customer_id), str(agent_id), agent_name, rating, now))
    conn.commit()
    conn.close()

def get_agent_dashboard_metrics() -> dict:
    """Aggregates performance data for the Web Control Dashboard."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Query all agents with average CSAT rating
    cursor.execute("""
        SELECT a.telegram_id, a.name, a.tickets_resolved, a.total_time_seconds,
               COALESCE(AVG(c.rating), 0) as avg_rating,
               COUNT(c.id) as total_ratings
        FROM support_agents a
        LEFT JOIN csat_ratings c ON a.telegram_id = c.agent_id
        WHERE a.is_active = 1
        GROUP BY a.telegram_id
    """)
    agents = []
    for r in cursor.fetchall():
        avg_time = (r[3] // r[2]) if r[2] > 0 else 0
        agents.append({
            "id": r[0],
            "name": r[1],
            "resolved": r[2],
            "total_time": r[3],
            "avg_time_seconds": avg_time,
            "avg_rating": round(r[4], 1),
            "ratings_count": r[5]
        })

    conn.close()
    return {"agents": agents}

# --- CUSTOMER & AUDIT FUNCTIONS ---

def get_customer(identifier: str) -> dict:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    clean_id = str(identifier).strip().lower()
    cursor.execute("""
        SELECT phone, email, name, city, last_order_id, notes 
        FROM customers 
        WHERE LOWER(phone) = ? OR LOWER(email) = ?
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "found": True,
            "phone": row[0],
            "email": row[1],
            "name": row[2],
            "city": row[3],
            "last_order_id": row[4],
            "notes": row[5]
        }
    return {"found": False, "message": f"No customer profile found for {identifier}."}

def save_or_update_customer(phone: str = None, email: str = None, name: str = None, city: str = None, last_order_id: int = None, notes: str = None) -> dict:
    if not phone and not email:
        return {"error": "Phone or email required"}
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        SELECT phone, email, name, city, last_order_id, notes 
        FROM customers 
        WHERE (phone IS NOT NULL AND phone = ?) OR (email IS NOT NULL AND LOWER(email) = LOWER(?))
    """, (phone or "", email or ""))
    existing = cursor.fetchone()

    if existing:
        pk = existing[0] or phone
        cursor.execute("""
            UPDATE customers 
            SET email = ?, name = ?, city = ?, last_order_id = ?, notes = ?, updated_at = ?
            WHERE phone = ?
        """, (email or existing[1], name or existing[2], city or existing[3], last_order_id or existing[4], notes or existing[5], now, pk))
    else:
        pk = phone if phone else f"email_{email}"
        cursor.execute("""
            INSERT INTO customers (phone, email, name, city, last_order_id, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (pk, email, name, city, last_order_id, notes, now))
    conn.commit()
    conn.close()
    return {"status": "success"}

def log_message(user_id: str, sender: str, text: str, user_name: str = "Unknown"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO chat_audit_logs (user_id, user_name, sender, message, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (str(user_id), user_name, sender, text, now))
    conn.commit()
    conn.close()

init_db()
