"""Tests for Alembic migrations running upgrade and downgrade."""
import os
from pathlib import Path
from alembic.config import Config
from alembic import command
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_alembic_upgrade_and_downgrade(tmp_path: Path):
    """Verify that Alembic runs initial migrations to head and successfully downgrades."""
    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Upgrade to head
    command.upgrade(alembic_cfg, "head")
    assert db_file.exists()

    # 2. Downgrade back to base
    command.downgrade(alembic_cfg, "base")
