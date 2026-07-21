import asyncio
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add current path to sys.path so shared framework can be imported
sys.path.insert(0, ".")

# Import Pydantic settings and SQLAlchemy Base
from shared.config.settings import settings
from shared.database.base import Base
import shared.database.models  # Ensures all models are registered on Base.metadata

# this is the Alembic Config object, which provides access to the values within the .ini file.
config = context.config

# Overwrite the database URL from settings dynamically (using asyncpg driver).
# Replace container hostname 'postgres' with '127.0.0.1' for host-side CLI migrations.
db_url = settings.database_url
if "@postgres:" in db_url:
    db_url = db_url.replace("@postgres:", "@127.0.0.1:")
elif "@postgres/" in db_url:
    db_url = db_url.replace("@postgres/", "@127.0.0.1/")

config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DB API to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
