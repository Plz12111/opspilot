from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPSPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "OpsPilot"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./opspilot.db"
    redis_url: str = "redis://localhost:6379/0"
    db_auto_create: bool = False
    readiness_check_external: bool = False
    readiness_timeout_seconds: float = 1.0
    evaluation_report_path: str = "evals/reports/incident-comparison.json"

    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    jaeger_url: str = "http://localhost:16686"
    tool_timeout_seconds: float = 8.0
    tool_max_evidence_chars: int = 20_000
    remediation_approvers: str = "demo-approver"

    feishu_base_url: str = "https://open.feishu.cn"
    feishu_app_id: str = ""
    feishu_app_secret: str = Field(default="", repr=False)
    feishu_verification_token: str = Field(default="", repr=False)
    feishu_encrypt_key: str = Field(default="", repr=False)
    feishu_default_chat_id: str = ""
    feishu_callback_max_age_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
