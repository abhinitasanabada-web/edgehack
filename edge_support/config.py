"""Runtime settings. Keys and device addresses belong only in an ignored .env."""
import os
from pathlib import Path
from typing import Literal
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
    batch_samples: bool = True
    sample_temperature: float = Field(default=.4, gt=0, le=1)
    agreement_threshold: float = Field(default=.8, ge=0, le=1)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8502, ge=1024, le=65535)
    action_token: str = ""
    thresholds: Thresholds = Field(default_factory=Thresholds)
    # Enhancement switches. Every default reproduces the pre-v2 behaviour, so one Nano session can A/B them.
    strict_schema: bool = False          # enum category/action IDs + required evidence in the enforced JSON schema
    compact_prompt: bool = False         # omit the schema text from the prompt when the server enforces it
    gate_mode: Literal["any", "majority"] = "any"   # "majority": one hedging/malformed sample no longer vetoes
    lenient_parse: bool = False          # tolerate <think>, fences, prose and common type slips in model JSON
    retrieval: Literal["legacy", "bm25"] = "legacy"   # "bm25": one ranked index over both corpora, unique kb IDs
    local_redaction: Literal["full", "keep_network"] = "full"   # keep IPs for the on-site model; egress stays full
    max_output_tokens: int | None = Field(default=None, ge=64, le=4096)   # None = 700 batched / 1500 sequential
    kb_top_k: int = Field(default=4, ge=1, le=10)                          # bm25 retrieval depth
    force_offline: bool = False          # demo switch: behave as if the site uplink were down
    cloud_price_in_per_mtok: float | None = Field(default=None, ge=0)     # optional, for cost reporting only
    cloud_price_out_per_mtok: float | None = Field(default=None, ge=0)

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
            "sample_temperature": "SAMPLE_TEMPERATURE", "batch_samples": "BATCH_SAMPLES", "agreement_threshold": "AGREEMENT_THRESHOLD",
            "api_host": "EDGE_SUPPORT_API_HOST", "api_port": "EDGE_SUPPORT_API_PORT",
            "action_token": "EDGE_SUPPORT_ACTION_TOKEN",
            "strict_schema": "STRICT_SCHEMA", "compact_prompt": "COMPACT_PROMPT", "gate_mode": "GATE_MODE",
            "lenient_parse": "LENIENT_PARSE", "retrieval": "RETRIEVAL", "local_redaction": "LOCAL_REDACTION",
            "max_output_tokens": "MAX_OUTPUT_TOKENS", "kb_top_k": "KB_TOP_K", "force_offline": "FORCE_OFFLINE",
            "cloud_price_in_per_mtok": "CLOUD_PRICE_IN_PER_MTOK", "cloud_price_out_per_mtok": "CLOUD_PRICE_OUT_PER_MTOK",
        }
        values = {key: os.environ[env] for key,env in mapping.items() if env in os.environ and os.environ[env] != ""}
        values["thresholds"] = Thresholds.model_validate_json((ROOT / "data/thresholds.json").read_text())
        return cls.model_validate(values)
