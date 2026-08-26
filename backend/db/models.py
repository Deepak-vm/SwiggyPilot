import uuid
from datetime import datetime
# pyrefly: ignore [missing-import]
from sqlalchemy import String, Text, DateTime, Numeric, CheckConstraint, ForeignKey, JSON, func
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Conversation(Base):
    __tablename__ = "conversations"

    id:         Mapped[str]      = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id:  Mapped[str]      = mapped_column(String(36), unique=True, index=True)
    intent:     Mapped[str|None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="conversation", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"

    id:              Mapped[str]       = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str]       = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"))
    vertical:        Mapped[str]       = mapped_column(String(20))
    swiggy_order_id: Mapped[str|None]  = mapped_column(String(255), nullable=True)
    status:          Mapped[str]       = mapped_column(String(30), default="pending")
    cart_snapshot:   Mapped[dict|None] = mapped_column(JSON, nullable=True)
    created_at:      Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="orders")
