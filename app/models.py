from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text
from app.database import Base

class Agent(Base):
    __tablename__ = "support_agents"
    telegram_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    total_time_seconds = Column(Integer, default=0)
    tickets_resolved = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class TicketSession(Base):
    __tablename__ = "ticket_sessions"
    ticket_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String, index=True)
    customer_name = Column(String)
    assigned_agent_id = Column(String)
    assigned_agent_name = Column(String)
    status = Column(String, default="open")
    claimed_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)

class CSATRating(Base):
    __tablename__ = "csat_ratings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer)
    customer_id = Column(String)
    agent_id = Column(String)
    agent_name = Column(String)
    rating = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class CartInquiry(Base):
    __tablename__ = "cart_inquiries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String)
    items_summary = Column(Text)
    total_naira = Column(Float)
    cart_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "chat_audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    user_name = Column(String)
    sender = Column(String)
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
