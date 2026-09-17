from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "chat_audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    user_name = Column(String)
    sender = Column(String)
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
