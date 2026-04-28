"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("messages", sa.Text, nullable=False),
        sa.Column("pinned", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "shares",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("messages", sa.Text, nullable=False),
    )
    op.create_table(
        "memory",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("tags", sa.Text, nullable=False),
    )
    op.create_table(
        "user_prefs",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.create_table(
        "usage_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.Float, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("in_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("out_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("task_type", sa.Text, nullable=False, server_default="chat"),
    )
    op.create_table(
        "users",
        sa.Column("username", sa.Text, primary_key=True),
        sa.Column("password", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text),
        sa.Column("role", sa.Text, nullable=False, server_default="user"),
        sa.Column("email", sa.Text),
        sa.Column("email_verified", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.Text, nullable=False),
        sa.Column("message_idx", sa.Integer, nullable=False),
        sa.Column("reaction", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False, server_default=""),
        sa.Column("model", sa.Text, nullable=False, server_default=""),
        sa.Column("ts", sa.Float, nullable=False),
        sa.UniqueConstraint("chat_id", "message_idx"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("instructions", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("color", sa.Text, nullable=False, server_default="#7c6af7"),
    )
    op.create_table(
        "project_chats",
        sa.Column("project_id", sa.Text, sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chat_id", sa.Text, sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "auth_api_keys",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("key_hash", sa.Text, nullable=False, unique=True),
        sa.Column("key_prefix", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("scopes", sa.Text, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("last_used_at", sa.Float),
        sa.Column("revoked_at", sa.Float),
    )
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_id", sa.Text, nullable=False),
        sa.UniqueConstraint("provider", "provider_id"),
    )


def downgrade() -> None:
    op.drop_table("oauth_accounts")
    op.drop_table("auth_api_keys")
    op.drop_table("project_chats")
    op.drop_table("projects")
    op.drop_table("message_feedback")
    op.drop_table("users")
    op.drop_table("usage_log")
    op.drop_table("user_prefs")
    op.drop_table("memory")
    op.drop_table("shares")
    op.drop_table("chats")
