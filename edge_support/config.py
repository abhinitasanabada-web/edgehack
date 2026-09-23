from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = lambda: None


@dataclass(frozen=True)
class Settings:
    local_llm_base_url: str = "http://127.0.0.1:8000/v1"
    local_llm_model: str = ""
    local_llm_api_key: str = ""
    llm_timeout_seconds: float = 90.0
    enable_cloud: bool = False
    simulation_mode: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8502
    action_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            local_llm_base_url=os.getenv("LOCAL_LLM_BASE_URL", cls.local_llm_base_url).rstrip("/"),
            local_llm_model=os.getenv("LOCAL_LLM_MODEL", "").strip(),
            local_llm_api_key=os.getenv("LOCAL_LLM_API_KEY", "").strip(),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
            enable_cloud=os.getenv("ENABLE_CLOUD", "false").lower() == "true",
            simulation_mode=os.getenv("SIMULATION_MODE", "false").lower() == "true",
            api_host=os.getenv("EDGE_SUPPORT_API_HOST", cls.api_host),
            api_port=int(os.getenv("EDGE_SUPPORT_API_PORT", str(cls.api_port))),
            action_token=os.getenv("EDGE_SUPPORT_ACTION_TOKEN", "").strip(),
        )

