"""Minimal OpenAI-compatible endpoint client: health check and model list."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class EndpointStatus:
    reachable: bool
    model_ids: list[str]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.reachable


def _get(url: str, api_key: str, timeout: int = 10):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_endpoint(base_url: str, api_key: str, timeout: int = 10) -> EndpointStatus:
    url = base_url.rstrip("/") + "/models"
    try:
        raw = _get(url, api_key, timeout)
        data = json.loads(raw)
        model_ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return EndpointStatus(reachable=True, model_ids=model_ids)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return EndpointStatus(reachable=False, model_ids=[], error=str(exc))


def resolve_model_id(base_url: str, api_key: str, want: str) -> str | None:
    """Return the model id to send in requests for `want`.

    If `want` exactly matches an exposed model id, use it as-is. Otherwise try
    a fuzzy match (substring), because harnesses often get a short alias.
    """
    st = check_endpoint(base_url, api_key)
    if not st.reachable:
        return want or None
    if want and want in st.model_ids:
        return want
    if want:
        for mid in st.model_ids:
            if want in mid:
                return mid
    # fall back to a reasonable default if none configured
    if st.model_ids:
        return st.model_ids[0]
    return want or None
