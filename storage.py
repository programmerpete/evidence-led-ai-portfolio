"""SQLAlchemy transactions and Alembic upgrades for SQLite or PostgreSQL."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def open_database(database: str):
    url = database if "://" in database else f"sqlite:///{database}"
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        # Serialize startup migrations on PostgreSQL.
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(481901)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return engine
