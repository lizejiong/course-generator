"""verify business tables exist

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-11
"""

from alembic import op
from sqlalchemy import inspect

from app.db import models  # noqa: F401
from app.db.base import Base

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_REQUIRED_TABLES = {"courses", "runs", "jobs", "artifacts", "review_events"}


def upgrade() -> None:
    bind = op.get_bind()
    if not _REQUIRED_TABLES.issubset(inspect(bind).get_table_names()):
        Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # This verification migration deliberately owns no schema objects.
    pass
