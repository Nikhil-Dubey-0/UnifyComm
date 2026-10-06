from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import Channel, Consent, ContactKind
from app.models.base import Base, created_at, enum_check, pk, updated_at


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = pk()
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    contacts: Mapped[list["CustomerContact"]] = relationship(
        back_populates="customer", order_by="CustomerContact.id", lazy="raise"
    )


class CustomerContact(Base):
    __tablename__ = "customer_contacts"
    __table_args__ = (
        UniqueConstraint("kind", "value_normalized", name="uq_customer_contacts_kind_value"),
        enum_check("kind", ContactKind),
    )

    id: Mapped[int] = pk()
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = created_at()

    customer: Mapped[Customer] = relationship(back_populates="contacts", lazy="raise")


class ChannelPreference(Base):
    __tablename__ = "channel_preferences"
    __table_args__ = (enum_check("channel", Channel), enum_check("consent", Consent))

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    consent: Mapped[str] = mapped_column(Text, nullable=False, server_default=Consent.unknown)
    dnd: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    updated_at: Mapped[datetime] = updated_at()
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agents.id"))
