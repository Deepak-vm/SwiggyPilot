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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    messages: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="conversation", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("vertical IN ('food', 'instamart', 'dineout')", name="ck_orders_vertical"),
        CheckConstraint("status IN ('pending_approval','approved','declined','placing','placed','tracking','delivered','failed','cancelled')", name="ck_orders_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    vertical: Mapped[str] = mapped_column(String(20))
    swiggy_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_approval")
    cart_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cart_total: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    address_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    coupon_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    restaurant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    booking_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    party_size: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="orders")
