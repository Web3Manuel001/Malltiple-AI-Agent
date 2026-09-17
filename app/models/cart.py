from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.core.database import Base

class CustomerCart(Base):
    __tablename__ = "customer_carts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String, unique=True, index=True) # Phone, Email, or Telegram ID
    items_json = Column(Text, default="[]")
    updated_at = Column(DateTime, default=datetime.utcnow)
