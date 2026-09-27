from __future__ import annotations

import os
import json
import re
from typing import Any, Dict, Optional

class LLMClient:
    """Simple LLM client stub for the challenge.
    Uses the environment variable ``LLM_PROVIDER`` but defaults to ``mock``.
    For the mock provider it returns a deterministic JSON payload that satisfies
    the ActionItem schema. Other providers are retained for completeness but are
    not used in the offline test environment.
    """

    def __init__(self) -> None:
        # Default to mock provider for offline testing
        self.provider = os.getenv("LLM_PROVIDER", "mock").lower()
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL", "").strip()
        self.timeout = float(os.getenv("LLM_TIMEOUT", "15.0"))

    def is_available(self) -> bool:
        # Mock provider is always considered available.
        # Mock provider is never considered available for composition; fallback will be used.
        return self.provider != "mock" and (self.provider == "ollama" or bool(self.api_key))

    def generate_json(self, prompt: str, system: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Generate a deterministic mock JSON response.
        The real implementation would call the configured LLM service.
        For the mock provider we return a minimal but valid ActionItem dict.
        """
        if self.provider == "mock":
            # Simple deterministic placeholder
            mock_body = "This is a mock message body with numbers 5 and ₹100."
            return {
                "body": mock_body,
                "cta": "binary_yes_no",
                "send_as": "vera",
                "suppression_key": "mock_key",
                "rationale": "Mock composition for testing."
            }
        # Fallback for non‑mock providers – reuse existing logic.
        if not self.is_available():
            return None
        raw = self._complete(prompt, system)
        if not raw:
            return None
        return self._extract_json(raw)

    # ---------------------------------------------------------------------
    # Private helper methods retained from the original implementation.
    # ---------------------------------------------------------------------
    def _complete(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        try:
            if self.provider == "openai":
                return self._call_openai(prompt, system)
            elif self.provider == "gemini":
                return self._call_gemini(prompt, system)
            elif self.provider == "anthropic":
                return self._call_anthropic(prompt, system)
            elif self.provider == "openrouter":
                return self._call_openrouter(prompt, system)
            elif self.provider == "ollama":
                return self._call_ollama(prompt, system)
            else:
                return self._call_openai(prompt, system)
        except Exception:
            return None

    def _call_openai(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        import urllib.request as urlrequest
        model = self.model or "gpt-4o-mini"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "response_format": {"type": "json_object"} if "gpt-4" in model or "gpt-3.5" in model else None,
            "max_tokens": 800
        }, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )
        with urlrequest.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_gemini(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        import urllib.request as urlrequest
        model = self.model or "gemini-1.5-flash"
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        body = json.dumps({
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 800}
        }, ensure_ascii=False).encode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        req = urlrequest.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlrequest.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def _call_anthropic(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        import urllib.request as urlrequest
        model = self.model or "claude-3-5-sonnet-20241022"
        body_dict = {
            "model": model,
            "max_tokens": 800,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system:
            body_dict["system"] = system
        req = urlrequest.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body_dict).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            }
        )
        with urlrequest.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"]

    def _call_openrouter(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        import urllib.request as urlrequest
        model = self.model or "anthropic/claude-3-haiku"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 800
        }).encode("utf-8")
        req = urlrequest.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://magicpin.com"
            }
        )
        with urlrequest.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_ollama(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        import urllib.request as urlrequest
        url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        model = self.model or "llama3"
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        body = json.dumps({
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0}
        }).encode("utf-8")
        req = urlrequest.Request(f"{url}/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urlrequest.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["response"]

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely parses or repairs JSON substring from text."""
        try:
            return json.loads(text.strip())
        except Exception:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return None

# Instantiate a singleton for the rest of the application.
llm_client = LLMClient()
