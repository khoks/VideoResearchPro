from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
from app.utils.json_logging import configure_logging
# Wildcard re-import of every model so `--autogenerate` sees the full
# schema. ``app.models.__init__`` is the single source of truth; if a
# model isn't listed there it isn't in `Base.metadata` and won't be
# diffed. Keep this import even though the names are unused — the
# side effect (registering tables on `Base.metadata`) is what matters.
from app.models import *  # noqa: F401,F403

config = context.config
if config.config_file_name is not None:
    # `disable_existing_loggers` defaults to True, which sets `.disabled`
    # on every logger that already exists and is not named in alembic.ini —
    # i.e. all of `app.*`. Those loggers then drop records silently while
    # still reporting `propagate=True` and a sane level, so nothing looks
    # wrong anywhere.
    #
    # It only bites when a migration runs IN-PROCESS with the app already
    # imported: the test suite (`test_schema_init.py`), and any startup path
    # that migrates before serving. A standalone `alembic upgrade` is
    # unaffected, which is why this survived unnoticed.
    #
    # Found via a caplog assertion that passed alone and captured zero
    # records in the full suite — see docs/testing.md §3.5.
    fileConfig(config.config_file_name, disable_existing_loggers=False)
    # fileConfig replaces the root logger's handlers, in the app's process too
    # when it migrates at startup, so LOG_FORMAT=json has to be put back. A
    # no-op under the default, text.
    configure_logging()

target_metadata = Base.metadata


def _database_url() -> str:
    """The database to migrate: the one the caller named, else the app's own.

    A caller's URL has to win. The app's startup (`schema_init_service`) and
    every migration test put one on the Config, and a test's throwaway file
    must never turn into the live database: some of them downgrade to base.
    Without one, `alembic` on the command line reads `DATABASE_URL`, like the
    app. alembic.ini used to repeat the value, so after the database moved a
    manual `alembic upgrade head` built an empty file at the old path and
    reported success (T-2.6.7).
    """
    return config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
