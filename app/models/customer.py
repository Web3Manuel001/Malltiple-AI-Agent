from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.core.database import Base

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String, unique=True, index=True, nullable=True)
    whatsapp_phone = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    city = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
