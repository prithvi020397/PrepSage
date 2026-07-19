# Phase 4 refactor — LLM client helpers (verbatim from app.py).


import re
def chat_content(resp):
    from app import client, MODEL, log  # lazy: breaks app<->service import cycle
    """Safely pull text out of an OpenAI chat-completions response.

    The model intermittently returns an empty `content` (None), which used to crash every
    route that did `resp.choices[0].message.content.strip()` with a 502 + leaked exception
    ('NoneType' object has no attribute 'strip'). Centralizing this means each route can just
    check `if not text:` and return a clean retry error instead of 500ing. Returns the stripped
    string, or None if the response was empty/malformed.
    """
    try:
        text = resp.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return None
    return text.strip() if text else None


def _call_json_extract(prompt, max_tokens=1800):
    from app import client, MODEL, log  # lazy: breaks app<->service import cycle
    """Call the LLM for a JSON-only extraction, with a truncation-safe retry.
    If the first response is cut off (finish_reason 'length'), retries once with a
    larger cap. Returns the cleaned response text, or None if both attempts fail."""
    def _clean(raw):
        if not raw:
            return None
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw).strip()
        if "{" not in raw or "}" not in raw:
            return None
        return raw

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.1,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = _clean(chat_content(resp))
        if raw:
            return raw
        # truncated or empty — retry once with a larger cap if it was length-limited
        if getattr(resp.choices[0], "finish_reason", None) == "length":
            resp2 = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens * 2,
                temperature=0.1,
                extra_body={"reasoning": {"enabled": False}},
            )
            raw2 = _clean(chat_content(resp2))
            if raw2:
                return raw2
        return None
    except Exception as e:
        log.exception("_clean: unhandled exception")
        log.debug("[_call_json_extract] LLM error: %s: %s", type(e).__name__, e)
        return None




