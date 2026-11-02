"""Frozen investigation runs and their attributed review decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "investigation_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("case_id", sa.Text, sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("snapshot", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("reviewer", sa.Text),
        sa.Column("review_decision", sa.Text),
        sa.Column("review_rationale", sa.Text),
        sa.Column("reviewed_at", sa.Text),
        sa.CheckConstraint("status IN ('awaiting_review', 'review_pending', 'reviewed')"),
    )
    op.create_index("ix_runs_case", "investigation_runs", ["case_id", "created_at"])


def downgrade():
    raise NotImplementedError("Run history must not be discarded; restore a tested backup.")
