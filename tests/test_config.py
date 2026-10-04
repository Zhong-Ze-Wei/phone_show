import pytest

from phone_assistant import config


def test_env_overrides_dotenv_and_key_not_in_repr(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AIPING_API_KEY=file-key\nAIPING_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("AIPING_API_KEY", "env-key")
    monkeypatch.setenv("AIPING_MODEL", "env-model")
    settings = config.Settings.from_env()
    assert settings.api_key == "env-key"
    assert settings.model == "env-model"
    assert "env-key" not in repr(settings)


@pytest.mark.parametrize("key", ["", "your-api-key"])
def test_missing_key_has_actionable_error(key):
    with pytest.raises(ValueError, match="AIPING_API_KEY"):
        config.create_client(config.Settings(key))
