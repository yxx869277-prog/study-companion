"""Local model traffic: literal loopback only, no environment proxies or redirects."""
import ipaddress
from urllib.parse import urlsplit

import requests

import config


def request(method, url, **kwargs):
    parsed = urlsplit(url)
    try:
        local = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    if (parsed.scheme != "http" or not local or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise ValueError("Only a literal loopback HTTP address is permitted")
    with requests.Session() as session:
        session.trust_env = False  # no HTTP_PROXY, ALL_PROXY, or .netrc
        response = session.request(method, url, allow_redirects=False, **kwargs)
    if 300 <= response.status_code < 400:
        raise ValueError("Local model redirects are not permitted")
    response.raise_for_status()
    return response


def require_local_ollama_model(model):
    """Check model metadata before sending any screen, audio-derived, or report text."""
    if not isinstance(model, str) or not model.strip() or "cloud" in model.lower():
        raise ValueError("Choose a downloaded local model, not a cloud model")
    info = request("POST", config.OLLAMA_BASE + "/api/show",
                   json={"model": model}, timeout=10).json()
    # Ollama's ShowResponse exposes these fields for remote models.
    if info.get("remote_host") or info.get("remote_model"):
        raise ValueError("The selected Ollama model is hosted remotely")
    if not isinstance(info.get("model_info"), dict) or not info["model_info"]:
        raise ValueError("Could not verify local model metadata; no content was sent")


def ollama_chat(payload, timeout):
    require_local_ollama_model(payload["model"])
    options = {"num_ctx": config.OLLAMA_CTX, "num_batch": 32,
               **payload.get("options", {})}
    if config.OLLAMA_CPU_ONLY:
        options["num_gpu"] = 0
    # Apply settings to this request only, and release model memory afterwards.
    payload = {"keep_alive": 0, **payload, "options": options}
    return request("POST", config.OLLAMA_URL, json=payload, timeout=timeout).json()


def text_chat(prompt, model, timeout=45, max_tokens=256):
    if config.VISION_BACKEND == "llama":
        data = request("POST", config.LLAMA_URL + "/v1/chat/completions",
                       json={"messages": [{"role": "user", "content": prompt}],
                             "max_tokens": max_tokens, "temperature": 0.3},
                       timeout=timeout).json()
        return data["choices"][0]["message"]["content"].strip()
    data = ollama_chat({"model": model, "stream": False,
                       "options": {"num_predict": max_tokens},
                       "messages": [{"role": "user", "content": prompt}]}, timeout)
    return data["message"]["content"].strip()
