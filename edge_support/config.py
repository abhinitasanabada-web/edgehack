"""Runtime settings. Keys and device addresses belong only in an ignored .env."""
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator
from app.config import Thresholds

ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseModel):
    local_llm_base_url: str = "http://127.0.0.1:8000/v1"
    local_llm_model: str = ""
    local_llm_api_key: str = ""
    large_llm_base_url: str = "http://127.0.0.1:8001/v1"
    large_llm_model: str = ""
    large_llm_api_key: str = ""
    cloud_llm_base_url: str = ""
    cloud_llm_model: str = ""
    cloud_llm_api_key: str = ""
    llm_timeout_seconds: float = Field(default=90, gt=0, le=300)
    enable_cloud: bool = False
    enable_large_local: bool = False
    simulation_mode: bool = False
    sample_count: int = Field(default=3, ge=1, le=5)
    sample_temperature: float = Field(default=.4, gt=0, le=1)
    agreement_threshold: float = Field(default=.8, ge=0, le=1)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8502, ge=1024, le=65535)
    action_token: str = ""
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @model_validator(mode="after")
    def distinct_tiers(self):
        if self.enable_large_local and not self.large_llm_model:
            raise ValueError("LARGE_LLM_MODEL is required when the second tier is enabled")
        if self.enable_large_local and (self.local_llm_model, self.local_llm_base_url.rstrip("/")) == (self.large_llm_model, self.large_llm_base_url.rstrip("/")):
            raise ValueError("The second local tier must be a distinct configured deployment")
        return self

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        mapping = {
            "local_llm_base_url": "LOCAL_LLM_BASE_URL", "local_llm_model": "LOCAL_LLM_MODEL",
            "local_llm_api_key": "LOCAL_LLM_API_KEY", "large_llm_base_url": "LARGE_LLM_BASE_URL",
            "large_llm_model": "LARGE_LLM_MODEL", "large_llm_api_key": "LARGE_LLM_API_KEY",
            "cloud_llm_base_url": "CLOUD_LLM_BASE_URL", "cloud_llm_model": "CLOUD_LLM_MODEL",
            "cloud_llm_api_key": "CLOUD_LLM_API_KEY", "llm_timeout_seconds": "LLM_TIMEOUT_SECONDS",
            "enable_cloud": "ENABLE_CLOUD", "enable_large_local": "ENABLE_LARGE_LOCAL",
            "simulation_mode": "SIMULATION_MODE", "sample_count": "LOCAL_SAMPLE_COUNT",
            "sample_temperature": "SAMPLE_TEMPERATURE", "agreement_threshold": "AGREEMENT_THRESHOLD",
            "api_host": "EDGE_SUPPORT_API_HOST", "api_port": "EDGE_SUPPORT_API_PORT",
            "action_token": "EDGE_SUPPORT_ACTION_TOKEN",
        }
        values = {key: os.environ[env] for key,env in mapping.items() if env in os.environ}
        values["thresholds"] = Thresholds.model_validate_json((ROOT / "data/thresholds.json").read_text())
        return cls.model_validate(values)
