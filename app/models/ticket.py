from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.core.database import Base

class TicketSession(Base):
    __tablename__ = "ticket_sessions"
    ticket_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String, index=True)
    customer_name = Column(String)
    assigned_agent_id = Column(String)
    assigned_agent_name = Column(String)
    status = Column(String, default="open") # open, claimed, resolved
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
