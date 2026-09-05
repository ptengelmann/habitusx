from __future__ import annotations

from pathlib import Path

import pytest

from habitusx.config import Settings, get_settings
from habitusx.errors import ConfigurationError


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings(_env_file=None)
        assert s.environment == "dev"
        assert s.log_level == "INFO"
        assert s.effective_log_format == "console"
        assert s.registry_path.name == "agents.yaml"

    def test_prod_defaults_to_json_logs(self) -> None:
        assert Settings(_env_file=None, environment="prod").effective_log_format == "json"

    def test_explicit_log_format_wins(self) -> None:
        s = Settings(_env_file=None, environment="prod", log_format="console")
        assert s.effective_log_format == "console"

    def test_log_level_is_normalised(self) -> None:
        assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"

    def test_unknown_log_level_rejected(self) -> None:
        with pytest.raises(ValueError, match="standard level name"):
            Settings(_env_file=None, log_level="loud")

    def test_unknown_key_in_dotenv_rejected(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("HABITUSX_NOT_A_SETTING=1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="extra"):
            Settings(_env_file=env_file)

    def test_dotenv_values_are_read(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "HABITUSX_ENVIRONMENT=test\nHABITUSX_LOG_LEVEL=warning\n", encoding="utf-8"
        )
        s = Settings(_env_file=env_file)
        assert s.environment == "test"
        assert s.log_level == "WARNING"


def test_get_settings_wraps_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("HABITUSX_ENVIRONMENT", "staging")
    try:
        with pytest.raises(ConfigurationError):
            get_settings()
    finally:
        get_settings.cache_clear()
