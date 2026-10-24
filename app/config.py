"""Application configuration loaded from environment variables / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Every value can be overridden with an env var."""

    app_name: str = "Parivar Kavach"
    use_mocks: bool = True
    use_mock_stt: bool = True
    use_mock_tts: bool = True

    database_url: str = "sqlite:///./data/parivar_kavach.db"
    alert_log_path: str = "./data/alerts.log"

    target_sample_rate: int = 8000
    phone_filter: bool = True
    max_audio_bytes: int = 12_000_000

    max_turns_easy: int = 4
    max_turns_medium: int = 6
    max_turns_hard: int = 8

    family_alert_on_end: bool = True
    family_alert_score_threshold: int = 55

    # Gnani AI credentials. Endpoint/auth/request details must come from the
    # official docs before live mode is enabled.
    gnani_api_key: str = ""
    evon_endpoint: str = ""
    evon_model: str = "evon-v3.3"
    prisma_endpoint: str = "https://api.vachana.ai/stt/v3"
    timbre_endpoint: str = "https://api.vachana.ai/api/v1/tts/inference"
    timbre_model: str = "timbre-v2.5"
    timbre_voice: str = "Poorvi"
    timbre_language: str = "hi-en"
    request_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    def max_turns_for(self, difficulty: str) -> int:
        """Return the turn cap for a difficulty level."""
        return {
            "easy": self.max_turns_easy,
            "medium": self.max_turns_medium,
            "hard": self.max_turns_hard,
        }.get(difficulty, self.max_turns_medium)


settings = Settings()
