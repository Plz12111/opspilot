"""investigation idempotency

Revision ID: 2f69600ac7b9
Revises: 1ae0937d3650
Create Date: 2026-07-22 15:06:37.339567
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2f69600ac7b9"
down_revision: str | None = "1ae0937d3650"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("investigation_runs") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint("uq_investigation_run_idempotency", ["idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("investigation_runs") as batch_op:
        batch_op.drop_constraint("uq_investigation_run_idempotency", type_="unique")
        batch_op.drop_column("idempotency_key")
