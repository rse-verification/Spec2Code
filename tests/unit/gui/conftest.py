import pytest

from spec2code.gui import run_server
from spec2code.gui.settings_store import SettingsStore


class NoKeyring:
    priority = 0


@pytest.fixture(autouse=True)
def isolated_gui_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(run_server, "SETTINGS_STORE", SettingsStore(
        tmp_path / "settings.json", environment={}, keyring_backend=NoKeyring(),
    ))
    monkeypatch.setattr(run_server, "_MODELS_CACHE", {"by_key": {}})
    monkeypatch.setattr(run_server, "MODELS_CACHE_FILE", tmp_path / "models-cache.json")
