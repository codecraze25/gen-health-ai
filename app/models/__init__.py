"""ORM models. Import every model here so Alembic autogenerate can see it."""

from app.db.base import Base

__all__ = ["Base"]
