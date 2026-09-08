from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, func


class Base(DeclarativeBase):
    """
    Clase base declarativa centralizada para todos los modelos ORM de SQLAlchemy 2.0.
    """
    pass


class TimestampMixin:
    """
    Mixin reutilizable para marcas de auditoría temporal (created_at, updated_at).
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

