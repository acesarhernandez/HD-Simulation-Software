from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_prefix="SIM_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8079

    db_path: Path = Field(default=Path("./data/simulator.db"))
    templates_dir: Path = Field(default=Path("./src/helpdesk_sim/templates"))

    poll_interval_seconds: int = 30
    scheduler_interval_seconds: int = 30

    zammad_url: str = "http://localhost"
    zammad_token: str = ""
    zammad_verify_tls: bool = True
    zammad_group_tier1: str = "Service Desk"
    zammad_group_tier2: str = "Tier 2"
    zammad_group_sysadmin: str = "Systems"
    zammad_customer_fallback_email: str = ""
    use_dry_run: bool = True

    response_engine: str = "rule_based"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_fallback_to_rule_based: bool = True
    ollama_rewrite_opening_tickets: bool = True
    engine_control_url: str = ""
    engine_control_api_key: str = ""
    engine_auto_wake: bool = True
    engine_auto_wake_timeout_seconds: int = 90
    llm_host_label: str = "LLM PC"
    llm_host_wol_enabled: bool = False
    llm_host_mac: str = ""
    llm_host_wol_broadcast_ip: str = "255.255.255.255"
    llm_host_wol_port: int = 9

    god_mode_enabled: bool = False
    god_mode_access_key: str = ""
    god_mode_default_attempt_first: bool = True
    god_mode_reveal_mode: str = "guided"
    god_mode_separate_reports: bool = True

    kb_enabled: bool = False
    kb_provider: str = "zammad"
    kb_review_required: bool = True
    kb_min_score: int = 60
    kb_sync_on_start: bool = True
    kb_sync_interval_seconds: int = 900
    kb_zammad_kb_id: int = 0
    kb_zammad_locale_id: int = 0
    kb_zammad_default_category_id: int = 0
    kb_zammad_publish_mode: str = "internal"

    def resolve_db_path(self, cwd: Path) -> Path:
        return self.db_path if self.db_path.is_absolute() else (cwd / self.db_path).resolve()

    def resolve_templates_dir(self, cwd: Path) -> Path:
        return (
            self.templates_dir
            if self.templates_dir.is_absolute()
            else (cwd / self.templates_dir).resolve()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
