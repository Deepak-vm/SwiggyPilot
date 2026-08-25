"""
models.py — SQLAlchemy ORM models for SwiggyPilot.

Tables
------
conversations   Tracks each chat session (one per user turn or thread).
orders          Tracks every order placement attempt across all three verticals
                (Food, Instamart, Dineout) with full lifecycle status.

Design notes
------------
- UUIDs are used as primary keys (string-encoded) so IDs can be generated
  client-side or by the LangGraph checkpoint layer without DB round-trips.
- `created_at` / `updated_at` use server-side defaults so timestamps are
  consistent even if the application layer clock drifts.
- `cart_snapshot` stores a JSON blob of the cart at time-of-placement for
  audit purposes — especially important because Swiggy order placement is
  non-idempotent and irreversible.
- `vertical` is an enum-like string constrained to ("food", "instamart", "dineout")
  via a SQLAlchemy CheckConstraint.
- `status` mirrors the lifecycle: pending_approval → approved / declined →
  placing → placed → tracking → delivered / failed.
"""

import uuid
from datetime import datetime, timezone


# pyrefly: ignore [missing-import]
from sqlalchemy import (
    String,
    Text,
    DateTime,
    Numeric,
    CheckConstraint,
    ForeignKey,
    JSON,
    func,
)
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base


# ── helpers ───────────────────────────────────────────────────────────────────

def _new_uuid() -> str:
    """Generate a new UUID4 string (used as default for pk columns)."""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


# ── Conversations ─────────────────────────────────────────────────────────────

class Conversation(Base):
    """
    One row per chat session / LangGraph thread.

    The `thread_id` maps directly to the LangGraph `config["configurable"]["thread_id"]`
    used by PostgresSaver for checkpointing, so we can JOIN conversation history
    to graph checkpoint state later.
    """
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        comment="UUID primary key",
    )
    # Optional user identifier.  
    user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Opaque user identifier (phone hash, Firebase UID, etc.)",
    )
    # Matches LangGraph thread_id for checkpoint lookup.
    thread_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        comment="LangGraph thread_id used by PostgresSaver",
    )
    # Detected intent for the session.
    intent: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Classified intent: food | instamart | dineout | combined | unclear",
    )
    # Full conversation transcript stored as JSON array of {role, content} dicts.
    messages: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
        comment="Ordered list of {role, content} message objects",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Row creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Row last-update timestamp (UTC)",
    )

    # ── relationships ─────────────────────────────────────────────────────────
    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation id={self.id!r} thread_id={self.thread_id!r} "
            f"intent={self.intent!r}>"
        )


# ── Orders ────────────────────────────────────────────────────────────────────

class Order(Base):
    """
    One row per order placement attempt (or Dineout booking attempt).

    Key design decisions
    --------------------
    - `swiggy_order_id` is the external ID returned by Swiggy MCP after a
      successful `place_food_order` / `confirm_order` / `book_table` call.
      It is nullable because we create the row *before* placement (at the
      human-approval interrupt) so the retry-guard logic can query this table
      to detect a previous successful placement without calling `get_food_orders`
      every time.
    - `cart_snapshot` freezes the exact cart payload we sent to the placement
      tool.  This is your audit log.
    - `cart_total` is denormalized for quick reporting without parsing the JSON.
    - `status` lifecycle:
        pending_approval  → user has been shown the order summary, awaiting yes/no
        approved          → user said yes, placement in progress
        declined          → user said no, row kept for analytics
        placing           → placement tool call in flight
        placed            → Swiggy returned an order_id
        tracking          → order is live and being tracked
        delivered         → final success state
        failed            → placement failed after retries
        cancelled         → order was cancelled post-placement (future feature)
    """
    __tablename__ = "orders"

    __table_args__ = (
        CheckConstraint(
            "vertical IN ('food', 'instamart', 'dineout')",
            name="ck_orders_vertical",
        ),
        CheckConstraint(
            "status IN ("
            "'pending_approval', 'approved', 'declined', 'placing', "
            "'placed', 'tracking', 'delivered', 'failed', 'cancelled'"
            ")",
            name="ck_orders_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_new_uuid,
        comment="UUID primary key",
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → conversations.id",
    )
    vertical: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Swiggy vertical: food | instamart | dineout",
    )
    # External order ID returned by Swiggy MCP after successful placement.
    swiggy_order_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Swiggy-assigned order ID (null until placement succeeds)",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending_approval",
        comment="Order lifecycle status",
    )
    # Snapshot of the cart payload at approval time (JSON blob).
    cart_snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Full cart payload frozen at human-approval checkpoint",
    )
    # Denormalized total for quick queries.
    cart_total: Mapped[float | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Cart total in INR (denormalized from cart_snapshot)",
    )
    # Address used for this order (food/instamart only).
    address_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Swiggy address_id used for delivery",
    )
    # Any coupon applied.
    coupon_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Coupon code applied to this order (if any)",
    )
    # Last error message for the failed status.
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error detail if status=failed",
    )
    # Dineout-specific fields.
    restaurant_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Restaurant ID (Dineout bookings)",
    )
    booking_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Requested booking time (Dineout only)",
    )
    party_size: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Number of guests (Dineout only)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Row creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Row last-update timestamp (UTC)",
    )

    # ── relationships ─────────────────────────────────────────────────────────
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="orders",
    )

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id!r} vertical={self.vertical!r} "
            f"status={self.status!r} swiggy_order_id={self.swiggy_order_id!r}>"
        )
