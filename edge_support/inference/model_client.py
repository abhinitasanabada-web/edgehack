from __future__ import annotations

import json
import re

import httpx

from edge_support.config import Settings
from edge_support.inference.output_schema import Diagnosis


SYSTEM_PROMPT = """You are EdgeSupport, an IT triage agent running locally on an edge GPU.
Return JSON only. Never return shell commands. Select one action ID from this list:
flush_dns, restart_dns_client, close_demo_process, clear_temp, collect_more_telemetry,
no_action_escalate.
Use the telemetry and retrieved runbook evidence. Set escalate=true when confidence is
low, the issue is unfamiliar, or the action is high-risk. Keep the answer concise.
Required JSON keys: diagnosis, evidence, confidence, severity, recommended_action,
requires_confirmation, escalate, rationale.
"""


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


class LocalModelClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()

    def diagnose(self, complaint: str, telemetry: dict, knowledge: list[dict]) -> Diagnosis:
        if not self.settings.local_llm_model:
            raise ValueError("LOCAL_LLM_MODEL is not configured")
        body = {
            "model": self.settings.local_llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"complaint": complaint, "telemetry": telemetry, "runbooks": knowledge})},
            ],
            "temperature": 0,
            "max_tokens": 700,
        }
        headers = {"Authorization": f"Bearer {self.settings.local_llm_api_key}"} if self.settings.local_llm_api_key else {}
        with httpx.Client(timeout=self.settings.llm_timeout_seconds, trust_env=False) as client:
            response = client.post(f"{self.settings.local_llm_base_url}/chat/completions", json=body, headers=headers)
            response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        # Models sometimes return semantically correct values in the wrong JSON types.
        # Normalize those common cases before strict Pydantic validation.
        raw = _extract_json(content)

        if isinstance(raw.get("evidence"), dict):
            raw["evidence"] = [
                f"{key}: {value}" for key, value in raw["evidence"].items()
            ]
        elif isinstance(raw.get("evidence"), str):
            raw["evidence"] = [raw["evidence"]]

        if isinstance(raw.get("confidence"), str):
            confidence_map = {
                "low": 0.30,
                "medium": 0.60,
                "moderate": 0.60,
                "high": 0.85,
                "very high": 0.95,
            }
            raw["confidence"] = confidence_map.get(
                raw["confidence"].lower(), 0.50
            )

        if raw.get("severity") == "moderate":
            raw["severity"] = "medium"

        return Diagnosis.model_validate(raw)
