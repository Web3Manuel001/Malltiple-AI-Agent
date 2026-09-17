from datetime import datetime
import requests
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.customer import Customer

def get_or_create_customer(telegram_id: str = None, fallback_name: str = "Customer") -> dict:
    """Retrieves customer profile or creates an initial record."""
    db = SessionLocal()
    cust = db.query(Customer).filter(Customer.telegram_id == str(telegram_id)).first()

    if not cust:
        cust = Customer(
            telegram_id=str(telegram_id),
            name=fallback_name if fallback_name != "Customer" else None
        )
        db.add(cust)
        db.commit()
        db.refresh(cust)

    res = {
        "id": cust.id,
        "name": cust.name or "Valued Customer",
        "phone": cust.phone or "",
        "email": cust.email or "",
        "city": cust.city or "",
        "has_profile": bool(cust.phone or cust.email)
    }
    db.close()
    return res

def link_customer_identity(telegram_id: str, name: str = None, phone: str = None, email: str = None, city: str = None) -> dict:
    """Saves verified identity so the bot remembers the user forever."""
    db = SessionLocal()
    cust = db.query(Customer).filter(Customer.telegram_id == str(telegram_id)).first()

    if not cust:
        cust = Customer(telegram_id=str(telegram_id))
        db.add(cust)

    if name: cust.name = name
    if phone: cust.phone = phone
    if email: cust.email = email.strip().lower()
    if city: cust.city = city
    cust.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(cust)

    res = {
        "success": True,
        "name": cust.name,
        "phone": cust.phone,
        "email": cust.email,
        "city": cust.city
    }
    db.close()
    return res
