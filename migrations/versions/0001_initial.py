"""Dados comerciais imutáveis e credenciais de leitura."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_probe", sa.Boolean(), nullable=False),
        sa.Column("quota_per_second", sa.Integer(), nullable=False),
        sa.CheckConstraint("quota_per_second > 0", name="ck_tenant_quota"),
    )
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("coverage_starts_on", sa.Date(), nullable=False),
        sa.Column("coverage_ends_on", sa.Date(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_stores_tenant_id"),
        sa.CheckConstraint("coverage_starts_on <= coverage_ends_on", name="ck_store_coverage"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
    )
    op.create_table(
        "sale_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "store_id"], ["stores.tenant_id", "stores.id"], name="fk_item_store"
        ),
        sa.CheckConstraint("quantity > 0 AND quantity <= 1000", name="ck_item_quantity"),
        sa.CheckConstraint("unit_price_cents >= 0", name="ck_item_price"),
    )
    op.create_index(
        "ix_sales_tenant_store_sold_id",
        "sale_items",
        ["tenant_id", "store_id", sa.text("sold_at DESC"), sa.text("id DESC")],
        postgresql_include=["order_id", "quantity", "unit_price_cents"],
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("seed_orders_per_day", sa.Integer(), nullable=False),
        sa.Column("seed_digest", sa.String(64), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_dataset_singleton"),
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("credentials")
    op.drop_table("datasets")
    op.drop_index("ix_sales_tenant_store_sold_id", table_name="sale_items")
    op.drop_table("sale_items")
    op.drop_table("products")
    op.drop_table("stores")
    op.drop_table("tenants")
