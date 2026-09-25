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
