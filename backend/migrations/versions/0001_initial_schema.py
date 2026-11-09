"""Create the existing MediBridge SQLite-equivalent application schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("assigned_at", sa.Text()),
        sa.Column("deadline_at", sa.Text()),
        sa.Column("document_name", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("overall_confidence", sa.Float(), nullable=False),
        sa.Column("extracted_json", sa.Text(), nullable=False),
        sa.Column("recommendations_json", sa.Text(), nullable=False),
        sa.Column("gaps_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "source_locations_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("workflow_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "activity",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
    )
    op.create_table(
        "settings",
        sa.Column(
            "user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )
    op.create_index("idx_sessions_expiry", "auth_sessions", ["expires_at"])
    op.create_index("idx_cases_user_created", "cases", ["user_id", "created_at"])
    op.create_index("idx_cases_user_assigned", "cases", ["user_id", "assigned_at"])
    op.create_index("idx_activity_user_id", "activity", ["user_id", "id"])


def downgrade():
    op.drop_index("idx_activity_user_id", table_name="activity")
    op.drop_index("idx_cases_user_assigned", table_name="cases")
    op.drop_index("idx_cases_user_created", table_name="cases")
    op.drop_index("idx_sessions_expiry", table_name="auth_sessions")
    op.drop_table("settings")
    op.drop_table("activity")
    op.drop_table("cases")
    op.drop_table("auth_sessions")
    op.drop_table("users")
