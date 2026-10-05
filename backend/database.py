from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from backend.config import get_settings


def get_connection():
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to connect to PostgreSQL")
    return psycopg.connect(database_url, row_factory=dict_row)


def initialize_database():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        connection.execute("SELECT pg_advisory_xact_lock(hashtext('lumora_schema_migrations'))")
        applied_versions = {
            row["version"]
            for row in connection.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        for migration_path in sorted(migrations_dir.glob("*.sql")):
            if migration_path.name in applied_versions:
                continue
            with connection.transaction():
                connection.execute(migration_path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (migration_path.name,),
                )
