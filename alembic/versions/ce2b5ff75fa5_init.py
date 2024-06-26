"""init

Revision ID: ce2b5ff75fa5
Revises:
Create Date: 2023-02-22 12:55:46.867624

"""
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

from alembic import op
from cosmos.db.check_constraints import create_check_constaints
from cosmos.db.data import load_data

# revision identifiers, used by Alembic.
revision = "ce2b5ff75fa5"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_template_key",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), server_default="", nullable=False),
        sa.Column("description", sa.String(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "fetch_type",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("required_fields", sa.Text(), nullable=True),
        sa.Column("path", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "retailer",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("account_number_prefix", sa.String(length=6), nullable=False),
        sa.Column("account_number_length", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("profile_config", sa.Text(), nullable=False),
        sa.Column("marketing_preference_config", sa.Text(), nullable=False),
        sa.Column("loyalty_name", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("TEST", "ACTIVE", "INACTIVE", "DELETED", "ARCHIVED", name="retailerstatuses"),
            nullable=False,
        ),
        sa.Column("balance_lifespan", sa.Integer(), nullable=True),
        sa.Column("balance_reset_advanced_warning_days", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_retailer_slug"), "retailer", ["slug"], unique=True)
    op.create_table(
        "reward_file_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("file_agent_type", sa.Enum("IMPORT", "UPDATE", name="fileagenttype"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_name", "file_agent_type", name="file_name_file_agent_type_unq"),
    )
    op.create_index(op.f("ix_reward_file_log_file_agent_type"), "reward_file_log", ["file_agent_type"], unique=False)
    op.create_index(op.f("ix_reward_file_log_file_name"), "reward_file_log", ["file_name"], unique=False)
    op.create_table(
        "task_type",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("task_type_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("cleanup_handler_path", sa.String(), nullable=True),
        sa.Column("error_handler_path", sa.String(), nullable=False),
        sa.Column("queue_name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("task_type_id"),
    )
    op.create_index(op.f("ix_task_type_name"), "task_type", ["name"], unique=True)
    op.create_table(
        "account_holder",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column(
            "status", sa.Enum("PENDING", "ACTIVE", "INACTIVE", "FAILED", name="accountholderstatuses"), nullable=False
        ),
        sa.Column("account_number", sa.String(), nullable=True),
        sa.Column("account_holder_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opt_out_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_holder_uuid"),
        sa.UniqueConstraint("email", "retailer_id", name="email_retailer_unq"),
        sa.UniqueConstraint("opt_out_token"),
    )
    op.create_index(op.f("ix_account_holder_account_number"), "account_holder", ["account_number"], unique=True)
    op.create_index(op.f("ix_account_holder_email"), "account_holder", ["email"], unique=False)
    op.create_index(op.f("ix_account_holder_retailer_id"), "account_holder", ["retailer_id"], unique=False)
    op.create_index(
        "ix_retailer_id_email_account_number",
        "account_holder",
        ["retailer_id", "email", "account_number"],
        unique=False,
    )
    op.create_table(
        "campaign",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "DRAFT", "CANCELLED", "ENDED", name="campaignstatuses"),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "loyalty_type",
            sa.Enum("ACCUMULATOR", "STAMPS", name="loyaltytypes"),
            server_default="STAMPS",
            nullable=False,
        ),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaign_retailer_id"), "campaign", ["retailer_id"], unique=False)
    op.create_index(op.f("ix_campaign_slug"), "campaign", ["slug"], unique=True)
    op.create_table(
        "email_template",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("WELCOME_EMAIL", "REWARD_ISSUANCE", "BALANCE_RESET", name="emailtemplatetypes"),
            nullable=False,
        ),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("type", "retailer_id", name="type_retailer_unq"),
    )
    op.create_index(op.f("ix_email_template_retailer_id"), "email_template", ["retailer_id"], unique=False)
    op.create_table(
        "retailer_fetch_type",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.Column("fetch_type_id", sa.BigInteger(), nullable=False),
        sa.Column("agent_config", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fetch_type_id"], ["fetch_type.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("retailer_id", "fetch_type_id"),
    )
    op.create_table(
        "retailer_store",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("store_name", sa.String(), nullable=False),
        sa.Column("mid", sa.String(), nullable=False),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mid"),
    )
    op.create_table(
        "retry_task",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("retry_task_id", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("audit_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("next_attempt_time", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_PROGRESS",
                "RETRYING",
                "FAILED",
                "SUCCESS",
                "WAITING",
                "CANCELLED",
                "REQUEUED",
                "CLEANUP",
                "CLEANUP_FAILED",
                name="retrytaskstatuses",
            ),
            nullable=False,
        ),
        sa.Column("task_type_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_type_id"], ["task_type.task_type_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("retry_task_id"),
    )
    op.create_index(op.f("ix_retry_task_status"), "retry_task", ["status"], unique=False)
    op.create_table(
        "reward_config",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.Column("fetch_type_id", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("required_fields_values", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["fetch_type_id"], ["fetch_type.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", "retailer_id", name="slug_retailer_unq"),
    )
    op.create_index(op.f("ix_reward_config_slug"), "reward_config", ["slug"], unique=False)
    op.create_table(
        "task_type_key",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("task_type_key_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("STRING", "INTEGER", "FLOAT", "BOOLEAN", "DATE", "DATETIME", "JSON", name="taskparamskeytypes"),
            nullable=False,
        ),
        sa.Column("task_type_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["task_type_id"], ["task_type.task_type_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_type_key_id"),
        sa.UniqueConstraint("name", "task_type_id", name="name_task_type_id_unq"),
    )
    op.create_table(
        "account_holder_profile",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("account_holder_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("address_line1", sa.String(), nullable=True),
        sa.Column("address_line2", sa.String(), nullable=True),
        sa.Column("postcode", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("custom", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["account_holder_id"], ["account_holder.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_account_holder_profile_account_holder_id"),
        "account_holder_profile",
        ["account_holder_id"],
        unique=False,
    )
    op.create_table(
        "campaign_balance",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("account_holder_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("reset_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["account_holder_id"], ["account_holder.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_holder_id", "campaign_id", name="account_holder_campaign_unq"),
    )
    op.create_index(
        op.f("ix_campaign_balance_account_holder_id"), "campaign_balance", ["account_holder_id"], unique=False
    )
    op.create_index(op.f("ix_campaign_balance_campaign_id"), "campaign_balance", ["campaign_id"], unique=False)
    op.create_table(
        "earn_rule",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("increment", sa.Integer(), nullable=True),
        sa.Column("increment_multiplier", sa.Numeric(scale=2), nullable=True),
        sa.Column("max_amount", sa.Integer(), server_default="0", nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "email_template_required_key",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("email_template_id", sa.BigInteger(), nullable=False),
        sa.Column("email_template_key_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["email_template_id"], ["email_template.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["email_template_key_id"], ["email_template_key.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("email_template_id", "email_template_key_id"),
    )
    op.create_table(
        "marketing_preference",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("account_holder_id", sa.BigInteger(), nullable=False),
        sa.Column("key_name", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column(
            "value_type",
            sa.Enum(
                "BOOLEAN",
                "INTEGER",
                "FLOAT",
                "STRING",
                "STRING_LIST",
                "DATE",
                "DATETIME",
                name="marketingpreferencevaluetypes",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_holder_id"], ["account_holder.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_marketing_preference_account_holder_id"), "marketing_preference", ["account_holder_id"], unique=False
    )
    op.create_table(
        "pending_reward",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("pending_reward_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_holder_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("created_date", sa.DateTime(), nullable=False),
        sa.Column("conversion_date", sa.DateTime(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("total_cost_to_user", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["account_holder_id"], ["account_holder.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_reward_account_holder_id"), "pending_reward", ["account_holder_id"], unique=False)
    op.create_index(op.f("ix_pending_reward_campaign_id"), "pending_reward", ["campaign_id"], unique=False)
    op.create_table(
        "reward",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("reward_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reward_config_id", sa.BigInteger(), nullable=False),
        sa.Column("account_holder_id", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("issued_date", sa.DateTime(), nullable=True),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.Column("redeemed_date", sa.DateTime(), nullable=True),
        sa.Column("cancelled_date", sa.DateTime(), nullable=True),
        sa.Column("associated_url", sa.String(), server_default="", nullable=False),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("reward_file_log_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["account_holder_id"], ["account_holder.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reward_config_id"],
            ["reward_config.id"],
        ),
        sa.ForeignKeyConstraint(["reward_file_log_id"], ["reward_file_log.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "retailer_id", "reward_config_id", name="code_retailer_reward_config_unq"),
    )
    op.create_index(op.f("ix_reward_account_holder_id"), "reward", ["account_holder_id"], unique=False)
    op.create_index(op.f("ix_reward_code"), "reward", ["code"], unique=False)
    op.create_table(
        "reward_rule",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("reward_goal", sa.Integer(), nullable=False),
        sa.Column("allocation_window", sa.Integer(), nullable=True),
        sa.Column("reward_cap", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("reward_config_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reward_config_id"], ["reward_config.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id"),
    )
    op.create_table(
        "task_type_key_value",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("retry_task_id", sa.Integer(), nullable=False),
        sa.Column("task_type_key_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["retry_task_id"], ["retry_task.retry_task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_type_key_id"], ["task_type_key.task_type_key_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("retry_task_id", "task_type_key_id"),
    )
    op.create_table(
        "transaction",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("account_holder_id", sa.BigInteger(), nullable=False),
        sa.Column("retailer_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("mid", sa.String(length=128), nullable=False),
        sa.Column("datetime", sa.DateTime(), nullable=False),
        sa.Column("payment_transaction_id", sa.String(length=128), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["account_holder_id"], ["account_holder.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", "retailer_id", "processed", name="transaction_retailer_processed_unq"),
    )
    op.create_index(op.f("ix_transaction_account_holder_id"), "transaction", ["account_holder_id"], unique=False)
    op.create_index(op.f("ix_transaction_mid"), "transaction", ["mid"], unique=False)
    op.create_index(
        op.f("ix_transaction_payment_transaction_id"), "transaction", ["payment_transaction_id"], unique=False
    )
    op.create_index(op.f("ix_transaction_processed"), "transaction", ["processed"], unique=False)
    op.create_index(op.f("ix_transaction_transaction_id"), "transaction", ["transaction_id"], unique=False)
    op.create_table(
        "reward_update",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("reward_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("status", sa.Enum("CANCELLED", "REDEEMED", name="rewardupdatestatuses"), nullable=False),
        sa.ForeignKeyConstraint(["reward_id"], ["reward.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transaction_earn",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False
        ),
        sa.Column("transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("loyalty_type", sa.Enum("ACCUMULATOR", "STAMPS", name="loyaltytypes"), nullable=False),
        sa.Column("earn_amount", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # create check constraints
    create_check_constaints()

    # load data into tables
    load_data(op.get_bind(), sa.MetaData())
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_table("transaction_earn")
    op.drop_table("reward_update")
    op.drop_index(op.f("ix_transaction_transaction_id"), table_name="transaction")
    op.drop_index(op.f("ix_transaction_processed"), table_name="transaction")
    op.drop_index(op.f("ix_transaction_payment_transaction_id"), table_name="transaction")
    op.drop_index(op.f("ix_transaction_mid"), table_name="transaction")
    op.drop_index(op.f("ix_transaction_account_holder_id"), table_name="transaction")
    op.drop_table("transaction")
    op.drop_table("task_type_key_value")
    op.drop_table("reward_rule")
    op.drop_index(op.f("ix_reward_code"), table_name="reward")
    op.drop_index(op.f("ix_reward_account_holder_id"), table_name="reward")
    op.drop_table("reward")
    op.drop_index(op.f("ix_pending_reward_campaign_id"), table_name="pending_reward")
    op.drop_index(op.f("ix_pending_reward_account_holder_id"), table_name="pending_reward")
    op.drop_table("pending_reward")
    op.drop_index(op.f("ix_marketing_preference_account_holder_id"), table_name="marketing_preference")
    op.drop_table("marketing_preference")
    op.drop_table("email_template_required_key")
    op.drop_table("earn_rule")
    op.drop_index(op.f("ix_campaign_balance_campaign_id"), table_name="campaign_balance")
    op.drop_index(op.f("ix_campaign_balance_account_holder_id"), table_name="campaign_balance")
    op.drop_table("campaign_balance")
    op.drop_index(op.f("ix_account_holder_profile_account_holder_id"), table_name="account_holder_profile")
    op.drop_table("account_holder_profile")
    op.drop_table("task_type_key")
    op.drop_index(op.f("ix_reward_config_slug"), table_name="reward_config")
    op.drop_table("reward_config")
    op.drop_index(op.f("ix_retry_task_status"), table_name="retry_task")
    op.drop_table("retry_task")
    op.drop_table("retailer_store")
    op.drop_table("retailer_fetch_type")
    op.drop_index(op.f("ix_email_template_retailer_id"), table_name="email_template")
    op.drop_table("email_template")
    op.drop_index(op.f("ix_campaign_slug"), table_name="campaign")
    op.drop_index(op.f("ix_campaign_retailer_id"), table_name="campaign")
    op.drop_table("campaign")
    op.drop_index("ix_retailer_id_email_account_number", table_name="account_holder")
    op.drop_index(op.f("ix_account_holder_retailer_id"), table_name="account_holder")
    op.drop_index(op.f("ix_account_holder_email"), table_name="account_holder")
    op.drop_index(op.f("ix_account_holder_account_number"), table_name="account_holder")
    op.drop_table("account_holder")
    op.drop_index(op.f("ix_task_type_name"), table_name="task_type")
    op.drop_table("task_type")
    op.drop_index(op.f("ix_reward_file_log_file_name"), table_name="reward_file_log")
    op.drop_index(op.f("ix_reward_file_log_file_agent_type"), table_name="reward_file_log")
    op.drop_table("reward_file_log")
    op.drop_index(op.f("ix_retailer_slug"), table_name="retailer")
    op.drop_table("retailer")
    op.drop_table("fetch_type")
    op.drop_table("email_template_key")
