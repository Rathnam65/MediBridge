from alembic import context

from backend.database import _get_engine, _postgres_url


config = context.config


def run_migrations_offline():
    url = _postgres_url()
    if not url:
        raise RuntimeError("DATABASE_URL must be set to run PostgreSQL migrations.")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = _get_engine()
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
