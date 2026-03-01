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
    llm_host_label: str = "LLM PC"
    llm_host_wol_enabled: bool = False
    llm_host_mac: str = ""
    llm_host_wol_broadcast_ip: str = "255.255.255.255"
    llm_host_wol_port: int = 9

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
