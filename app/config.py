from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8080
    database_url: str = "postgresql+psycopg://finance:finance@127.0.0.1:5432/finance"
    redis_url: str = "redis://127.0.0.1:6379/0"
    upload_dir: Path = ROOT / "runtime" / "uploads"

    jwt_secret_key: str = "development-only-change-me"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    refresh_cookie_name: str = "finance_refresh"
    cookie_secure: bool = False
    frontend_origin: str = "http://127.0.0.1:18081"
    production_origin: str = "https://finance.chiraliumai.cn"

    sms_access_key: str = ""
    sms_secret_key: str = ""
    sms_sign_name: str = ""
    sms_template_code: str = ""
    sms_template_code_login: str = ""
    sms_remote_enabled: bool = False
    sms_dev_force_local: bool = True
    sms_dev_expose_code: bool = False
    sms_test_code: str = ""
    sms_code_expire_seconds: int = 300
    sms_cooldown_seconds: int = 60
    sms_phone_hour_limit: int = 5
    sms_phone_day_limit: int = 10
    sms_ip_hour_limit: int = 20
    sms_global_day_limit: int = 500
    sms_verify_attempt_limit: int = 5
    sms_code_pepper: str = "development-only-sms-pepper"

    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""
    turnstile_enforce_after_phone_hourly: int = 3

    demo_seed_new_users: bool = True
    ai_provider: str = "demo"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("app_env")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def allowed_origins(self) -> set[str]:
        return {
            self.frontend_origin.rstrip("/"),
            self.production_origin.rstrip("/"),
        }

    def validate_runtime(self) -> None:
        if not self.is_production:
            return
        if len(self.jwt_secret_key) < 32 or self.jwt_secret_key == "development-only-change-me":
            raise RuntimeError("JWT_SECRET_KEY must be a unique production secret of at least 32 characters")
        if not self.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production")
        if self.sms_dev_force_local or not self.sms_remote_enabled:
            raise RuntimeError("Production requires remote SMS verification")
        missing = [
            name
            for name, value in {
                "SMS_ACCESS_KEY": self.sms_access_key,
                "SMS_SECRET_KEY": self.sms_secret_key,
                "SMS_SIGN_NAME": self.sms_sign_name,
                "SMS_TEMPLATE_CODE_LOGIN": self.sms_template_code_login or self.sms_template_code,
                "TURNSTILE_SITE_KEY": self.turnstile_site_key,
                "TURNSTILE_SECRET_KEY": self.turnstile_secret_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing production SMS configuration: {', '.join(missing)}")
        if self.sms_dev_expose_code or self.sms_test_code:
            raise RuntimeError("Development SMS code exposure is forbidden in production")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
