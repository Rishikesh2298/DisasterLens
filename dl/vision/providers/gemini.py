"""
dl/vision/providers/gemini.py
-----------------------------
Official Google Gemini Vision AI adapter for DisasterLens.

Uses the official google-genai SDK to interact with multimodal Gemini models:
- gemini-1.5-pro (default in registry)
- gemini-1.5-flash
- gemini-2.0-flash / gemini-3.8-flash (via VISION_MODEL configuration)

SECURITY & INTEGRITY RULES:
1. Credentials are read strictly from the GEMINI_API_KEY environment variable.
2. API keys are never printed, logged, hardcoded, or exposed in error messages.
3. scene.ground_truth is NEVER accessed or forwarded to Gemini (strict integrity rule).
4. Raw model outputs are validated through dl.vision.parse.parse_scene_analysis.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from dl.contracts.enums import Verdict
from dl.contracts.scene import Box, Scene
from dl.contracts.vision import SceneAnalysis
from dl.vision.base import VisionAdapter, ZoneComparisonResult
from dl.vision.parse import extract_json_string, parse_scene_analysis
from dl.vision.registry import register_adapter

logger = logging.getLogger(__name__)

# Base directory for prompt versions: dl/vision/prompts
_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _sanitize_error(msg: str, secret: str | None = None) -> str:
    """Ensure API keys or secrets are completely masked in error messages."""
    sanitized = str(msg)
    if secret and secret in sanitized:
        sanitized = sanitized.replace(secret, "[REDACTED_API_KEY]")
    # Mask query parameter key=... or api_key=...
    sanitized = re.sub(r"(?:api_?key|key)=([A-Za-z0-9_\-]+)", r"key=[REDACTED]", sanitized)
    return sanitized


@register_adapter("gemini")
class GeminiVisionAdapter(VisionAdapter):
    """
    VisionAdapter implementation backed by Google Gemini multimodal API.

    Registered under provider name 'gemini'.
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        image_variant: str = "plain",
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Gemini vision adapter.

        Model selection hierarchy:
        1. Explicit `model` parameter.
        2. `VISION_MODEL` environment variable.
        3. Default fallback `"gemini-1.5-pro"` (matching registry.py).

        Args:
            model: Model identifier string (e.g. 'gemini-1.5-pro', 'gemini-3.8-flash').
            api_key: Optional explicit API key (defaults to GEMINI_API_KEY env var).
            image_variant: 'plain' or 'labelled' (determines prompt template).
            client: Optional injected genai.Client instance (useful for mocking/testing).
            **kwargs: Extra parameters ignored or forwarded.
        """
        self.model_id = (model or os.getenv("VISION_MODEL") or "gemini-1.5-pro").strip()
        self.image_variant = image_variant.strip().lower()

        # Resolve credentials securely
        raw_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self._api_key = raw_key.strip() if raw_key else None

        # Initialize SDK client
        if client is not None:
            self._client = client
        elif self._api_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                clean_err = _sanitize_error(str(exc), self._api_key)
                raise RuntimeError(f"Failed to initialize google-genai Client: {clean_err}") from None
        else:
            self._client = None

    def _require_client(self) -> Any:
        """Verify client is initialized or raise clear, non-exposing error."""
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError(
                "GEMINI_API_KEY environment variable is not configured. "
                "Please configure GEMINI_API_KEY to execute live Gemini requests."
            )
        try:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
            return self._client
        except Exception as exc:
            clean_err = _sanitize_error(str(exc), self._api_key)
            raise RuntimeError(f"Failed to initialize google-genai Client: {clean_err}") from None

    def _load_prompt(self, prompt_version: str = "v1") -> str:
        """Load the versioned prompt template for the configured image variant."""
        prompt_file = f"{self.image_variant}.txt"
        prompt_path = _PROMPTS_DIR / prompt_version / prompt_file

        if not prompt_path.exists():
            # Fallback to plain.txt if labelled is not available
            fallback = _PROMPTS_DIR / prompt_version / "plain.txt"
            if fallback.exists():
                prompt_path = fallback
            else:
                raise FileNotFoundError(
                    f"Prompt file not found at {prompt_path}. "
                    f"Available versions: {[p.name for p in _PROMPTS_DIR.iterdir() if p.is_dir()]}"
                )

        return prompt_path.read_text(encoding="utf-8")

    def analyze_scene(
        self,
        image_bytes: bytes,
        scene: Scene,
        prompt_version: str = "v1",
    ) -> SceneAnalysis:
        """
        Analyze an aerial disaster scene image with Gemini.

        CRITICAL DATA-LEAKAGE RULE:
        Does NOT access or expose scene.ground_truth. Only image_bytes and
        unprivileged segment IDs are provided to the model.
        """
        client = self._require_client()
        base_prompt = self._load_prompt(prompt_version)

        # For plain images, supply the known segment IDs so the model evaluates them
        if self.image_variant == "plain" and scene.segments:
            seg_ids = [s.segment_id for s in scene.segments]
            full_prompt = (
                f"{base_prompt}\n\n"
                f"Accompanying Road Geometry Context:\n"
                f"Road segment IDs to evaluate in this scene: {seg_ids}\n"
            )
        else:
            full_prompt = base_prompt

        from google.genai import types

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

        t0 = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=self.model_id,
                contents=[image_part, full_prompt],
            )
            latency_ms = max(0, int((time.perf_counter() - t0) * 1000))
        except Exception as exc:
            latency_ms = max(0, int((time.perf_counter() - t0) * 1000))
            clean_err = _sanitize_error(str(exc), self._api_key)
            logger.error("Gemini API call failed after %dms: %s", latency_ms, clean_err)
            raise RuntimeError(f"Gemini API request failed: {clean_err}") from None

        raw_text = getattr(response, "text", "") or ""

        # Parse and validate response using existing parse_scene_analysis
        return parse_scene_analysis(
            raw_text=raw_text,
            scene_id=scene.scene_id,
            model_id=self.model_id,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
            repair_callback=None,
        )

    def answer_route_questions(
        self,
        image_bytes: bytes,
        questions: dict[str, str],
        scene: Scene,
        prompt_version: str = "v1",
    ) -> dict[str, Verdict]:
        """
        Determine whether specific routes are obstructed using Gemini multimodal QA.
        """
        if not questions:
            return {}

        client = self._require_client()
        from google.genai import types

        questions_text = "\n".join([f"- {qid}: {text}" for qid, text in questions.items()])
        prompt = (
            "You are evaluating whether routes in an aerial disaster image are obstructed.\n"
            "For each question, determine if the route is 'obstructed' or 'clear'.\n"
            f"Questions to evaluate:\n{questions_text}\n\n"
            "Output ONLY a raw JSON object mapping each question ID to 'obstructed' or 'clear'.\n"
            'Example: {"Q-001": "obstructed", "Q-002": "clear"}\n'
            "Output only the JSON object, no other text."
        )

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

        try:
            response = client.models.generate_content(
                model=self.model_id,
                contents=[image_part, prompt],
            )
            raw_text = getattr(response, "text", "") or ""
            json_str = extract_json_string(raw_text)
            import json

            data = json.loads(json_str)
        except Exception as exc:
            clean_err = _sanitize_error(str(exc), self._api_key)
            logger.warning("Route question answering fallback due to: %s", clean_err)
            data = {}

        results: dict[str, Verdict] = {}
        for qid in questions:
            ans_str = str(data.get(qid, "clear")).strip().lower()
            if "obstruct" in ans_str:
                results[qid] = Verdict.OBSTRUCTED
            else:
                results[qid] = Verdict.CLEAR

        return results

    def compare_zones(
        self,
        image_bytes: bytes,
        zone_a: Box,
        zone_b: Box,
        scene: Scene,
        comparison_id: str = "",
        prompt_version: str = "v1",
    ) -> ZoneComparisonResult:
        """
        Compare two geographic zones in the aerial image to determine which has more visible hazards.
        """
        client = self._require_client()
        from google.genai import types

        prompt = (
            "You are comparing two geographic zones in an aerial disaster image to determine which has more hazards.\n"
            f"Zone A bounding box [x1, y1, x2, y2]: {list(zone_a.root)}\n"
            f"Zone B bounding box [x1, y1, x2, y2]: {list(zone_b.root)}\n\n"
            "Which zone has more visible disaster hazard area (debris, flooding, damage)?\n"
            "Output ONLY a raw JSON object: {\"zone_with_more\": \"zone_a\" | \"zone_b\" | \"equal\"}\n"
            "Output only the JSON object."
        )

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

        try:
            response = client.models.generate_content(
                model=self.model_id,
                contents=[image_part, prompt],
            )
            raw_text = getattr(response, "text", "") or ""
            json_str = extract_json_string(raw_text)
            import json

            data = json.loads(json_str)
            winner = str(data.get("zone_with_more", "equal")).strip().lower()
        except Exception as exc:
            clean_err = _sanitize_error(str(exc), self._api_key)
            logger.warning("Zone comparison fallback to 'equal': %s", clean_err)
            winner = "equal"

        if "zone_a" in winner or winner == "a":
            return "zone_a"
        if "zone_b" in winner or winner == "b":
            return "zone_b"
        return "equal"
