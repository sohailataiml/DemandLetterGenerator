"""The migration history builds the schema the models describe.

A migration that has drifted from the models is worse than no migration: the
service boots, and then fails on the first query that touches the missing
column. This checks the two together.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _alembic(command: list[str], database_url: str) -> subprocess.CompletedProcess:
    environment = {**os.environ, "DLG_DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *command],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture
def migrated(tmp_path) -> str:
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    result = _alembic(["upgrade", "head"], url)
    assert result.returncode == 0, result.stderr
    return url


def test_the_migration_history_is_linear():
    result = _alembic(["heads"], "sqlite:///:memory:")
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"expected one head, found: {heads}"


def test_migrations_build_every_table_the_models_declare(migrated):
    from app.db import Base

    tables = set(inspect(create_engine(migrated)).get_table_names())
    missing = sorted(set(Base.metadata.tables) - tables)
    assert not missing, f"migrations do not create: {missing}"


def test_migrations_build_every_column_the_models_declare(migrated):
    from app.db import Base

    inspector = inspect(create_engine(migrated))
    problems: list[str] = []
    for name, table in Base.metadata.tables.items():
        actual = {column["name"] for column in inspector.get_columns(name)}
        for column in table.columns:
            if column.name not in actual:
                problems.append(f"{name}.{column.name}")
    assert not problems, f"migrations do not create: {sorted(problems)}"


def test_the_migration_can_be_rolled_back(migrated):
    result = _alembic(["downgrade", "base"], migrated)
    assert result.returncode == 0, result.stderr

    tables = set(inspect(create_engine(migrated)).get_table_names())
    assert tables <= {"alembic_version"}


def test_autogenerate_finds_no_drift_between_models_and_migrations(migrated, tmp_path):
    """If this fails, someone changed a model without adding a migration."""
    from alembic.autogenerate import produce_migrations
    from alembic.migration import MigrationContext

    from app.db import Base

    engine = create_engine(migrated)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "target_metadata": Base.metadata}
        )
        script = produce_migrations(context, Base.metadata)

    changes = [op for op in script.upgrade_ops.ops]
    described = [getattr(op, "table_name", type(op).__name__) for op in changes]
    assert not changes, f"models and migrations have drifted: {described}"
