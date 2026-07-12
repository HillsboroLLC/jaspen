import os
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from flask import current_app

# point Alembic at the root-level alembic.ini
root_ini = os.path.join(os.getcwd(), 'alembic.ini')
if os.path.isfile(root_ini):
    context.config.config_file_name = root_ini

# this is the Alembic Config object, loaded from that file
config = context.config

# set up Python logging according to alembic.ini
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

# fetch DB URL from Flask app and override the ini
def get_engine():
    try:
        return current_app.extensions['migrate'].db.get_engine()
    except (KeyError, TypeError, AttributeError):
        return db.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace('%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')

# load your MetaData from Flask app
from app import create_app, db
app = create_app()
with app.app_context():
    # override in-memory config so engine_from_config sees it
    config.set_main_option('sqlalchemy.url', get_engine_url())
    target_metadata = db.metadata


def run_migrations_offline():
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    cfg_section = config.get_section(config.config_ini_section)
    connectable = engine_from_config(
        cfg_section,
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
