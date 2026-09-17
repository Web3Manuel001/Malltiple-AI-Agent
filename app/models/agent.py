from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.core.database import Base

class Agent(Base):
    __tablename__ = "support_agents"
    telegram_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    total_time_seconds = Column(Integer, default=0)
    tickets_resolved = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
