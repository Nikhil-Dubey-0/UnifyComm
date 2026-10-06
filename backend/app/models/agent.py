from datetime import datetime

from sqlalchemy import Boolean, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import AgentRole
from app.models.base import Base, created_at, enum_check, pk


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (enum_check("role", AgentRole),)

    id: Mapped[int] = pk()
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = created_at()
