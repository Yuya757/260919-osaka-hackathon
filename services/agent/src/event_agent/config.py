from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gcp_project_id: str | None = None
    gcp_region: str = "asia-northeast1"
    gemini_model: str = "gemini-2.0-flash"
    agent_demo_mode: bool = True
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "https://osaka-hackathon-260919.web.app"
    )
    port: int = 8080
    max_search_queries: int = 8
    max_candidates: int = 30
    max_model_calls: int = 15
    verified_confidence_threshold: float = 0.8
    prompt_version: str = "chat-1.0.0"
    validation_rule_version: str = "1.0.0"
    ekispert_api_key: str | None = None

    @property
    def use_vertex(self) -> bool:
        if self.agent_demo_mode:
            return False
        return bool(self.gcp_project_id and self.gcp_project_id.strip())

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
