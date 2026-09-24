import json

from maya_mcp import connection


def test_installed_path_is_shared_despite_different_appdata(monkeypatch, tmp_path):
    manifest = tmp_path / "runtime.json"
    shared = tmp_path / "shared" / "connection.json"
    manifest.write_text(json.dumps({"config_path": str(shared)}), encoding="utf-8")
    monkeypatch.setattr(connection, "INSTALLATION_PATH", manifest)
    monkeypatch.delenv("MAYA_MCP_CONFIG", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "external-client"))
    first = connection.ensure_settings()
    monkeypatch.setenv("APPDATA", str(tmp_path / "maya-launcher"))
    second = connection.ensure_settings()
    assert first == second
    assert connection.settings_path() == shared


def test_explicit_override_is_preserved(monkeypatch, tmp_path):
    override = tmp_path / "test-connection.json"
    monkeypatch.setenv("MAYA_MCP_CONFIG", str(override))
    assert connection.settings_path() == override
