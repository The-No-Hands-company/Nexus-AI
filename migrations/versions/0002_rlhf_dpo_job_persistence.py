"""add persistent dpo and rlhf job tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dpo_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("base_model", sa.Text, nullable=False),
        sa.Column("adapter_name", sa.Text, nullable=False),
        sa.Column("dataset_path", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("metrics", sa.Text, nullable=False, server_default="{}"),
        sa.Column("adapter_path", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("completed_at", sa.Text),
    )
    op.create_index("idx_dpo_jobs_status", "dpo_jobs", ["status"])
    op.create_index("idx_dpo_jobs_created_at", "dpo_jobs", ["created_at"])

    op.create_table(
        "rlhf_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("base_model", sa.Text, nullable=False),
        sa.Column("adapter_name", sa.Text, nullable=False),
        sa.Column("dataset_path", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("rounds_completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reward_model_path", sa.Text),
        sa.Column("metrics", sa.Text, nullable=False, server_default="{}"),
        sa.Column("adapter_path", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("completed_at", sa.Text),
    )
    op.create_index("idx_rlhf_jobs_status", "rlhf_jobs", ["status"])
    op.create_index("idx_rlhf_jobs_created_at", "rlhf_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_rlhf_jobs_created_at", table_name="rlhf_jobs")
    op.drop_index("idx_rlhf_jobs_status", table_name="rlhf_jobs")
    op.drop_table("rlhf_jobs")

    op.drop_index("idx_dpo_jobs_created_at", table_name="dpo_jobs")
    op.drop_index("idx_dpo_jobs_status", table_name="dpo_jobs")
    op.drop_table("dpo_jobs")
