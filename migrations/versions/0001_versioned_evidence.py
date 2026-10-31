"""Versioned evidence, including upgrade of the original SQLite portfolio database."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    connection = op.get_bind()
    existing = sa.inspect(connection).get_table_names()
    if "cases" not in existing:
        op.create_table(
            "cases",
            sa.Column("id", sa.Text, primary_key=True),
            sa.Column("owner", sa.Text, nullable=False),
        )
    if "audit" not in existing:
        op.create_table(
            "audit",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("case_id", sa.Text, nullable=False),
            sa.Column("actor", sa.Text, nullable=False),
            sa.Column("action", sa.Text, nullable=False),
            sa.Column("payload", sa.Text, nullable=False),
            sa.Column("recorded_at", sa.Text, nullable=False),
        )
    op.create_table(
        "evidence_versions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("case_id", sa.Text, sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("relationship", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("event_time", sa.Text, nullable=False),
        sa.Column("known_at", sa.Text, nullable=False),
        sa.Column("restricted", sa.Integer, nullable=False),
        sa.Column("source_system", sa.Text, nullable=False),
        sa.Column("batch_id", sa.Text, nullable=False),
        sa.Column("correction_reason", sa.Text, nullable=True),
        sa.CheckConstraint("version >= 1"),
        sa.CheckConstraint("restricted IN (0, 1)"),
        sa.CheckConstraint("relationship IN ('used_device', 'transferred_to', 'profile')"),
    )
    op.create_index("ix_evidence_case", "evidence_versions", ["case_id", "id", "version"])
    if "evidence" in existing:
        connection.execute(
            sa.text("""
            INSERT INTO evidence_versions
              (id, version, case_id, source, target, relationship, description,
               event_time, known_at, restricted, source_system, batch_id)
            SELECT id, 1, case_id, source, target,
              CASE WHEN restricted = 1 THEN 'profile'
                   WHEN source LIKE 'device-%' OR target LIKE 'device-%' THEN 'used_device'
                   ELSE 'transferred_to' END,
              description, event_time, known_at, restricted, 'synthetic-fixture', 'legacy-import'
            FROM evidence
        """)
        )
        op.drop_table("evidence")


def downgrade():
    raise NotImplementedError("Evidence history must not be discarded; restore a tested backup.")
