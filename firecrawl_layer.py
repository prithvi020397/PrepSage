"""Optional Firecrawl-powered "fresh angle" layer for The Loop.

This is the HYBRID piece: the precomputed question bank (questions.json + traces/solutions/
contexts) remains the always-available floor. Firecrawl is a bonus layer on top that pulls search
result snippets (title + description) from across the web for a concept, then synthesizes a short
real-world framing via the same OpenRouter LLM the tutor uses.

Design:
- NO SCRAPING — individual pages are slow and most interview-content sites block bots. Instead
  we use Firecrawl's web search API and feed the result titles + snippets directly to the LLM.
  This is fast (2-5s), reliable, and gives the LLM enough context to produce a vivid anchor.
- Every function here is designed to FAIL SILENTLY — if there's no API key, the network is down,
  or the snippets are unhelpful, it returns None and the caller falls back to the precomputed bank.
- Nothing in here ever touches the graded solve/submit path; it only flavors the tutor conversation
  (hints, curveballs, a standalone "fresh angle" panel).

Env:
  FIRECRAWL_API_KEY   required to use Firecrawl (optional overall — absence => all fns return None)
  FIRECRAWL_ENABLED   set to "0"/"false"/"no" to hard-disable even if a key is present

Caching: results are written to research_cache.json (gitignored) keyed by concept so repeat calls
are free and the feature still works offline after the first successful scrape.
"""
import json
import os
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")
FIRECRAWL_ENABLED = os.environ.get("FIRECRAWL_ENABLED", "true").lower() not in ("0", "false", "no")
FIRECRAWL_BASE = "https://api.firecrawl.dev/v2"

CACHE_FILE = "research_cache.json"
CACHE_TTL = 60 * 60 * 24 * 30  # 30 days — a "fresh angle" stays fresh for a month

# ponytail: reuse the same OpenRouter client/model the rest of the app uses, so a fresh angle is
# synthesized in the same voice as the precomputed framing. Imported LAZILY inside functions to
# avoid a circular import (app.py imports this module, so importing app at module top would recurse).


def _available():
    return FIRECRAWL_ENABLED and bool(FIRECRAWL_API_KEY)


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        return json.load(open(CACHE_FILE))
    except Exception:
        return {}


def _save_cache(cache):
    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass


def _cache_get(concept):
    cache = _load_cache()
    entry = cache.get(concept)
    if not entry:
        return None
    import time
    if time.time() - entry.get("ts", 0) > CACHE_TTL:
        return None
    return entry.get("angle")


def _cache_put(concept, angle):
    cache = _load_cache()
    import time
    cache[concept] = {"angle": angle, "ts": time.time()}
    _save_cache(cache)


def scrape_markdown(url, timeout=15):
    """Scrape one URL into cleaned markdown via the free Jina Reader API (r.jina.ai).

    No API key needed, works on most sites (blogs, docs, tutorials, GitHub READMEs).
    Falls back to Firecrawl scraping if Jina fails and a FIRECRAWL_API_KEY is available.
    """
    # Jina is fast, free, and works on most sites — try it first.
    jina_url = f"https://r.jina.ai/{url}"
    req = urllib.request.Request(jina_url, headers={"Accept": "text/markdown"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            if len(text) > 500:
                return text
    except Exception:
        pass
    # Firecrawl scrape as fallback (requires FIRECRAWL_API_KEY)
    if not _available():
        return None
    payload = json.dumps({
        "url": url, "formats": ["markdown"],
        "onlyMainContent": True, "onlyCleanContent": True, "blockAds": True,
        "timeout": 10000,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{FIRECRAWL_BASE}/scrape", data=payload,
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("success"):
            md = (body.get("data") or {}).get("markdown")
            if md:
                return md
    except Exception:
        pass
    return None


def search(query, limit=4):
    """Firecrawl v2 web search. Returns a list of {url, title, description}, or [] on failure.

    Search is far more robust than fixed seed URLs — it always returns concept-relevant sources
    rather than a generic Wikipedia page that may not even mention the concept.
    """
    if not _available():
        return []
    payload = json.dumps({"query": query, "limit": limit}).encode("utf-8")
    req = urllib.request.Request(
        f"{FIRECRAWL_BASE}/search",
        data=payload,
        headers={
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("success"):
            return []
        results = (body.get("data") or {}).get("web") or []
        return [
            {"url": r.get("url"), "title": r.get("title"), "description": r.get("description")}
            for r in results if r.get("url")
        ]
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, Exception):
        return []


def fresh_angle(concept, lang="", max_sources=2):
    """Return a short real-world / current-event framing for a concept, or None if unavailable.

    Flow: check cache -> scrape a couple of seed sources -> ask the LLM to synthesize one tight
    paragraph that grounds the concept in a recognizable real system or recent trend. Any failure
    returns None so the caller keeps using the precomputed framing.
    """
    if not concept:
        return None
    cached = _cache_get(concept)
    if cached:
        return cached

    # Search for concept-relevant sources. Scraping individual pages is slow and unreliable
    # (most real sites block bots), so we use the search result snippets (title + description)
    # themselves as the source text — they're concise, on-topic, and the LLM only needs a tiny
    # real-world anchor to synthesize a framing. Fast and reliable.
    query = f"{concept} {'system design' if lang == 'design' else lang} interview real-world example"
    results = search(query, limit=6)
    if not results:
        return None

    snippets = []
    seen = set()
    for r in results:
        # skip generic or empty descriptions
        d = (r.get("description") or "").strip()
        t = (r.get("title") or "").strip()
        text = f"{t}. {d}" if d else t
        if text and text not in seen and len(text) > 20:
            snippets.append(text[:400])
            seen.add(text)

    if not snippets:
        return None

    corpus = "\n".join(snippets)
    # lazy import to dodge the app.py <-> firecrawl_layer import cycle
    try:
        from app import client, MODEL
    except Exception:
        return None
    prompt = f"""You are framing an interview-prep question for a candidate. Concept: "{concept}".

Below are web search result titles and snippets for the concept. Write ONE tight paragraph (2-3
sentences, under 60 words) that grounds this concept in a recognizable real system, company, or
recent industry trend the candidate would know. Make it concrete and interview-relevant. Do NOT
explain the concept — assume they know it; just give a vivid real-world anchor. If the snippets are
unhelpful, return exactly the word NONE.

Snippets:
{corpus[:5000]}"""

    # ponytail: the model intermittently returns empty content (None). Retry once.
    angle = None
    for _ in range(2):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=160,
                temperature=0.4,
                extra_body={"reasoning": {"enabled": False}},
            )
            angle = chat_content_safe(resp)
        except Exception:
            angle = None
        if angle and angle.strip().upper() != "NONE":
            break

    if not angle or angle.strip().upper() == "NONE":
        return None
    _cache_put(concept, angle)
    return angle


def chat_content_safe(resp):
    """Local copy of app.chat_content to avoid a second import resolution round-trip."""
    try:
        text = resp.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return None
    return text.strip() if text else None
