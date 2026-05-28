from __future__ import annotations

from lecture_reconstructor import settings


def test_save_settings_does_not_write_api_key(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "APP_DIR", tmp_path)
    monkeypatch.setattr(settings, "SETTINGS_PATH", settings_path)

    settings.save_settings(
        {
            "provider": "Qwen",
            "api_key": "secret-value",
            "max_tokens": 180000,
            "remember_api_key": True,
        }
    )

    content = settings_path.read_text(encoding="utf-8")
    assert "secret-value" not in content
    loaded = settings.load_settings()
    assert loaded["provider"] == "Qwen"
    assert loaded["max_tokens"] == 180000
    assert loaded["remember_api_key"] is True
