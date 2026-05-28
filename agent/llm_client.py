"""Small OpenAI-compatible LLM client used by online and offline agents."""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request


DEFAULT_LLM_URL = "https://api.deepseek.com/chat/completions"


def normalize_chat_url(value: str | None) -> str:
    url = str(value or "").strip() or DEFAULT_LLM_URL
    if "://" not in url:
        url = f"https://{url}"
    if url.endswith("/"):
        url = url[:-1]
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    return url


class LLMClient:
    """Call an OpenAI-compatible chat-completion endpoint and parse JSON decisions."""

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key = (
            str(config.get("api_key") or "").strip()
            or os.environ.get("AUTOSOLVER_LLM_API_KEY", "").strip()
            or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        )
        self.model = (
            str(config.get("model") or "").strip()
            or os.environ.get("AUTOSOLVER_LLM_MODEL", "").strip()
            or "deepseek-chat"
        )
        self.url = normalize_chat_url(
            str(config.get("base_url") or "").strip()
            or os.environ.get("AUTOSOLVER_LLM_BASE_URL", "").strip()
            or os.environ.get("DEEPSEEK_API_URL", "").strip()
            or DEFAULT_LLM_URL
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def ask_json(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: dict,
        timeout: float = 6.0,
    ) -> dict:
        if not self.configured:
            return {
                "used_llm": False,
                "status": "not_configured",
                "model": self.model,
                "decision": fallback,
                "raw_text": "",
                "error": None,
            }
        request_body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.15,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(1.0, timeout)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            choices = payload.get("choices") or []
            raw_text = choices[0].get("message", {}).get("content", "") if choices else ""
            return {
                "used_llm": True,
                "status": "ok",
                "model": payload.get("model", self.model),
                "decision": _parse_json_object(raw_text, fallback),
                "raw_text": raw_text,
                "error": None,
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
            return {
                "used_llm": True,
                "status": "error",
                "model": self.model,
                "decision": fallback,
                "raw_text": "",
                "error": f"{type(exc).__name__}: {exc}",
            }


def _parse_json_object(text: str, fallback: dict) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else fallback
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return fallback
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return fallback
        return parsed if isinstance(parsed, dict) else fallback
