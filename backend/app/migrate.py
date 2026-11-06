"""Tiny additive migrations: add columns introduced after a database was first created.

``create_all`` creates new tables but never alters existing ones, so columns added in later
versions are added here.  Only additive, nullable/defaulted columns are handled.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "contacts": [("external_source", "VARCHAR(30) DEFAULT '' NOT NULL"), ("external_id", "VARCHAR(120) DEFAULT '' NOT NULL")],
    "deals": [("external_source", "VARCHAR(30) DEFAULT '' NOT NULL"), ("external_id", "VARCHAR(120) DEFAULT '' NOT NULL")],
    "posts": [("external_source", "VARCHAR(30) DEFAULT '' NOT NULL"), ("external_id", "VARCHAR(120) DEFAULT '' NOT NULL")],
}


def run_migrations(engine: Engine) -> list[str]:
    applied = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{name} ON {table} ({name})"))
                    applied.append(f"{table}.{name}")
    return applied
