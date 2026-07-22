from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect


def run_alembic(database_url: str, *arguments: str) -> None:
    environment = {
        **os.environ,
        "OPSPILOT_DATABASE_URL": database_url,
        "PYTHONPATH": "src",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_initial_migration_upgrades_and_downgrades(tmp_path) -> None:
    path = tmp_path / "migration.db"
    async_url = f"sqlite+aiosqlite:///{path}"
    sync_url = f"sqlite:///{path}"

    run_alembic(async_url, "upgrade", "head")
    engine = create_engine(sync_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"alembic_version", "incidents", "investigation_runs", "evidence"} <= tables
    columns = {column["name"] for column in inspector.get_columns("investigation_runs")}
    constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("investigation_runs")
    }
    assert "idempotency_key" in columns
    assert "uq_investigation_run_idempotency" in constraints
    engine.dispose()

    run_alembic(async_url, "downgrade", "base")
    engine = create_engine(sync_url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_postgres_offline_downgrade_drops_native_enum_types() -> None:
    environment = {
        **os.environ,
        "OPSPILOT_DATABASE_URL": "postgresql+asyncpg://user:pass@database/opspilot",
        "PYTHONPATH": "src",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "head:base", "--sql"],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert "DROP TYPE investigationstatus" in result.stdout
    assert "DROP TYPE incidentstatus" in result.stdout
    assert "DROP TYPE actionstatus" in result.stdout
