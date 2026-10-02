"""OpenAI-compatible chat client shared by summaries and translation (stdlib only)."""
import json
import os
import re
import urllib.request


def chat(profile, system, user, max_tokens=None):
    body = {"model": profile["model"], "messages": [{"role": "system", "content": system},
                                                    {"role": "user", "content": user}],
            "temperature": 0.2, "max_tokens": max_tokens or profile.get("max_tokens", 4096),
            **profile.get("extra_body", {})}
    req = urllib.request.Request(profile["base_url"].rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    key = os.environ.get(profile["api_key_env"]) if profile.get("api_key_env") else profile.get("api_key")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=profile.get("timeout", 900)) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
    return msg.get("content") or ""


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0))


def ask(profile, system, user, required, tries=3, max_tokens=None):
    """Ask for one JSON object with the `required` keys; re-ask on invalid replies."""
    last = None
    for _ in range(tries):
        try:
            d = parse_json(chat(profile, system, user, max_tokens))
            missing = [k for k in required if k not in d]
            if not missing:
                return d
            last = f"missing keys {missing}"
        except (ValueError, json.JSONDecodeError) as e:
            last = str(e)
        user += f"\n\n(Your previous reply was invalid: {last}. Reply with the JSON object only.)"
    raise RuntimeError(f"LLM did not return valid JSON after {tries} tries: {last}")


def reachable(profile, timeout=3):
    try:
        urllib.request.urlopen(profile["base_url"].rstrip("/") + "/models", timeout=timeout)
        return True
    except Exception:
        return False
