"""Behaviour that hosted deployments (Docker / Render) rely on."""
import os

import pytest

from backend.utils import account_utils


def _symlink_or_skip(target, link):
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks is not permitted on this system")


def test_root_folder_on_mounted_volume_is_accessible(tmp_path, monkeypatch):
    """docker/entrypoint.sh swaps root folders for links into STORAGE_DIR; paths inside must stay usable."""
    project, volume = tmp_path / "app", tmp_path / "volume"
    project.mkdir()
    (volume / "logs").mkdir(parents=True)
    _symlink_or_skip(volume / "logs", project / "logs")
    monkeypatch.setattr(account_utils, "PROJECT_ROOT", str(project))

    path = account_utils.get_user_path(None, "logs/batch_x.log")

    assert path.endswith("logs/batch_x.log")
    assert account_utils.is_path_accessible(path, None)


def test_root_workspace_paths_cannot_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(account_utils, "PROJECT_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        account_utils.get_user_path(None, "../outside.txt")


@pytest.fixture
def empty_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.database.mysql import Base
    import backend.database.models  # noqa: F401  registers the tables

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seeded_admin(db):
    from backend.database.models import User
    from backend.core.security import DEFAULT_ADMIN_EMAIL
    return db.query(User).filter(User.email == DEFAULT_ADMIN_EMAIL).first()


@pytest.mark.parametrize("password", [None, "admin", "short-pass"])
def test_production_never_seeds_a_weak_admin_password(empty_db, monkeypatch, password):
    from backend.api.auth import seed_default_admin
    monkeypatch.setenv("ENV", "production")
    if password is None:
        monkeypatch.delenv("DEFAULT_ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", password)

    seed_default_admin(empty_db)

    assert _seeded_admin(empty_db) is None


def test_production_seeds_admin_with_a_strong_password(empty_db, monkeypatch):
    from backend.api.auth import seed_default_admin
    from backend.core.security import verify_password
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "a-long-unique-passphrase")

    seed_default_admin(empty_db)

    admin = _seeded_admin(empty_db)
    assert admin is not None and verify_password("a-long-unique-passphrase", admin.password)


def test_development_keeps_the_admin_default(empty_db, monkeypatch):
    from backend.api.auth import seed_default_admin
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("DEFAULT_ADMIN_PASSWORD", raising=False)

    seed_default_admin(empty_db)

    assert _seeded_admin(empty_db) is not None
