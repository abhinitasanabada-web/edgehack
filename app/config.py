import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

class Thresholds(BaseModel):
    cpu_percent: float = 90
    memory_percent: float = 90
    disk_percent: float = 90
    temperature_c: float = 85
    battery_health_percent: float = 70
    wifi_signal_percent: float = 35

class Settings(BaseModel):
    local_url: str = "http://localhost:8000/v1"
    local_model: str = ""
    local_key: str = ""
    cloud_url: str = ""
    cloud_model: str = ""
    cloud_key: str = ""
    enable_cloud: bool = False
    simulation: bool = False
    timeout: float = Field(default=90, gt=0, le=600)
    confidence_threshold: float = Field(default=.65, ge=0, le=1)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @classmethod
    def from_env(cls):
        return cls(local_url=os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1"),
                   local_model=os.getenv("LOCAL_LLM_MODEL", ""), local_key=os.getenv("LOCAL_LLM_API_KEY", ""),
                   cloud_url=os.getenv("CLOUD_LLM_BASE_URL", ""), cloud_model=os.getenv("CLOUD_LLM_MODEL", ""),
                   cloud_key=os.getenv("CLOUD_LLM_API_KEY", ""), enable_cloud=os.getenv("ENABLE_CLOUD", "false").lower()=="true",
                   simulation=os.getenv("SIMULATION_MODE", "false").lower()=="true",
                   timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
                   confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", ".65")),
                   thresholds=Thresholds.model_validate_json((ROOT / "data/thresholds.json").read_text()))
