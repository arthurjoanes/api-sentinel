from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY

metadata = MetaData()

tenants = Table(
    "tenants",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("is_probe", Boolean, nullable=False, default=False),
    Column("quota_per_second", Integer, nullable=False),
    CheckConstraint("quota_per_second > 0", name="ck_tenant_quota"),
)

stores = Table(
    "stores",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("tenant_id", ForeignKey("tenants.id"), nullable=False),
    Column("name", String(100), nullable=False),
    Column("coverage_starts_on", Date, nullable=False),
    Column("coverage_ends_on", Date, nullable=False),
    UniqueConstraint("tenant_id", "id", name="uq_stores_tenant_id"),
    CheckConstraint("coverage_starts_on <= coverage_ends_on", name="ck_store_coverage"),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sku", String(32), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
)

sale_items = Table(
    "sale_items",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("tenant_id", Integer, nullable=False),
    Column("store_id", Integer, nullable=False),
    Column("order_id", BigInteger, nullable=False),
    Column("sold_at", DateTime(timezone=True), nullable=False),
    Column("product_id", ForeignKey("products.id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price_cents", BigInteger, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "store_id"], ["stores.tenant_id", "stores.id"], name="fk_item_store"
    ),
    CheckConstraint("quantity > 0 AND quantity <= 1000", name="ck_item_quantity"),
    CheckConstraint("unit_price_cents >= 0", name="ck_item_price"),
)
Index(
    "ix_sales_tenant_store_sold_id",
    sale_items.c.tenant_id,
    sale_items.c.store_id,
    sale_items.c.sold_at.desc(),
    sale_items.c.id.desc(),
    postgresql_include=["order_id", "quantity", "unit_price_cents"],
)

datasets = Table(
    "datasets",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("version", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("starts_on", Date, nullable=False),
    Column("ends_on", Date, nullable=False),
    Column("seed_orders_per_day", Integer, nullable=False),
    Column("seed_digest", String(64), nullable=False),
    CheckConstraint("id = 1", name="ck_dataset_singleton"),
)

credentials = Table(
    "credentials",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(100), nullable=False, unique=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("tenant_id", ForeignKey("tenants.id"), nullable=False),
    Column("store_ids", ARRAY(Integer), nullable=False),
    Column("scopes", ARRAY(String(32)), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
