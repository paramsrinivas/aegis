
"""Shared isolated test environment."""

import pytest

from app.storage import initialize_db


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Prevent tests from accessing operational telemetry."""

    db_path = tmp_path / "test_aegis.db"

    monkeypatch.setenv(
        "AEGIS_DB_PATH",
        str(db_path),
    )

    initialize_db(db_path)

    return db_path

