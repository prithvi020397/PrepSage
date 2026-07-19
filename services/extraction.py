# Phase 4 refactor — document parsing/extraction (verbatim from app.py).
import re
import json
import os
from io import BytesIO
from services.llm import _call_json_extract


def _ocr_with_stirling(file_bytes, filename):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Fallback OCR via a self-hosted Stirling-PDF instance (default http://localhost:8080).
    Activates only when STIRLING_PDF_URL is set (or default local instance is reachable) and
    pdfplumber returned no text (e.g. a scanned/image PDF). Returns extracted text or None.
    Fails silently — caller keeps using whatever it already had."""
    base = os.environ.get("STIRLING_PDF_URL", "http://localhost:8080").rstrip("/")
    if not base:
        return None
    try:
        resp = urllib.request.urlopen(
            f"{base}/api/v1/convert/pdf/ocr",
            data=file_bytes, timeout=60,
            headers={"Content-Type": "application/pdf"},
        )
        out = resp.read()
        # OCR endpoint returns a PDF; re-run pdfplumber on it to get text
        if pdfplumber and out:
            with pdfplumber.open(BytesIO(out)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            return text or None
    except Exception:
        return None
    return None



def _extract_text_from_resume(file_bytes, filename):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Extract plain text from a PDF or DOCX file. Falls back to Stirling-PDF OCR
    for scanned/image PDFs that pdfplumber can't read."""
    lower = filename.lower()
    if lower.endswith(".pdf") and pdfplumber:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        # empty => likely a scanned PDF; try OCR before giving up
        if not text.strip() and os.environ.get("STIRLING_PDF_URL", "http://localhost:8080"):
            ocr = _ocr_with_stirling(file_bytes, filename)
            if ocr:
                return ocr
        return text
    elif lower.endswith((".docx", ".doc")) and docx:
        doc = docx.Document(BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    elif lower.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="replace")
    return None



def _clean_pdf_artifacts(text):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Strip PostScript character names (cid:xxx), ligature codes, and Unicode garbage
    that leak from PDF text extraction (e.g. '(cid:136)' for ⚠️)."""
    text = re.sub(r"\(cid:\d+\)", "", text)
    text = re.sub(r"\(cid\d+\)", "", text)
    text = re.sub(r"\(U\+[0-9A-Fa-f]{4,6}\)", "", text)
    text = re.sub(r"\(0x[0-9A-Fa-f]{2,4}\)", "", text)
    return text


_NON_TECH_SKILL_BLACKLIST = {
    "sam", "designed", "power", "questease", "programming", "compliance",
    "automated", "computer", "bachelor", "master", "university", "college",
    "school", "institute", "team", "leader", "leadership", "communication",
    "collaboration", "problem", "solving", "analytical", "detail", "oriented",
    "self", "motivated", "experience", "years", "year", "role", "position",
    "technologies", "tools", "systems", "solutions", "services", "platform",
    "platforms", "infrastructure", "environment", "environments",
    "development", "management", "operations", "production", "process",
    "processes", "projects", "project", "product", "products", "business",
    "stakeholders", "clients", "customers", "requirements", "specifications",
    "documentation", "standards", "methodologies", "approach", "data",
}



def _is_technical_skill(name):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Check if a skill name looks like a genuine technical skill, not a random word."""
    n = name.lower().strip()
    if len(n) <= 2:
        return False
    if n in _NON_TECH_SKILL_BLACKLIST:
        return False
    return True



def _extract_skills_from_resume(text):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Use LLM to extract structured skills, projects, and domain from resume text.
    Returns rich data including depth signals, project specificity, and skill context."""
    prompt = f"""Analyze this resume like a technical interviewer would. Extract structured information. Respond ONLY with a JSON object — no markdown, no commentary.

Resume text (truncated):
{text[:4000]}

Return exactly this JSON shape:
{{
  "target_role": "inferred target role e.g. 'data engineer', 'backend engineer', 'ML engineer' — be specific",
  "years_experience": "estimated years or null",
  "skills": [
    {{
      "name": "skill name — ONLY extract TECHNICAL skills: programming languages, frameworks, tools, platforms, databases, cloud services, libraries. IGNORE: soft skills, university names, company names, locations, personal names, degree names, generic terms like 'Engineering' or 'Bachelor'.",
      "depth": "deep | moderate | shallow — based on how it was used (built production system = deep, listed in skills section only = shallow)",
      "context": "where/how it was used (e.g. 'used in AdTech pipeline for 3B daily events') — be specific"
    }}
  ],
  "projects": [
    {{
      "name": "project name",
      "description": "what it does — be specific about scale, impact, technical choices",
      "tech": ["technologies used"],
      "specificity": "high | low — are the numbers/concrete details provided or is it vague?"
    }}
  ],
  "domains": ["application domains e.g. 'ad tech', 'healthcare', 'payments', 'distributed systems'"],
  "strongest_skills": ["top 3-5 technical skills based on depth and context"],
  "weakest_signals": ["skills with no project context — likely shallow"]
}}

Note: do NOT include interview questions/probes — those are generated on demand later.
Be strict about depth: "familiar with X" or just listing X = shallow. "Built Y using X processing Z events/day" = deep.
CRITICAL: ONLY extract genuine technical skills. Do not include company names, person names, university names, cities, or generic English words.
DO NOT extract these as skills: Sam, Designed, Power, Programming, Compliance, Automated, Computer, Data, Engineer, Team, Business, Systems, Solutions, Platforms, Infrastructure, Environment, Development, Management, Operations, Production, Process, Projects, Products, Services, Solutions.
DO extract these as skills: Apache Spark, Python, SQL, Docker, Kubernetes, Snowflake, dbt, Airflow, Terraform, AWS, GCP, Azure, Git, React, Node.js, Java, Scala, Go, Rust, MongoDB, PostgreSQL, Kafka, Spark Streaming."""

    raw = _call_json_extract(prompt, max_tokens=1800)
    if not raw:
        return None
    try:
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        skills = obj.get("skills", [])
        filtered = []
        for s in skills:
            name = s.get("name", "") if isinstance(s, dict) else str(s)
            if _is_technical_skill(name):
                filtered.append(s)
        projects = []
        for p in obj.get("projects", []):
            if isinstance(p, dict):
                p["name"] = _clean_pdf_artifacts(p.get("name", ""))
                p["description"] = _clean_pdf_artifacts(p.get("description", ""))
            projects.append(p)
        domains = [_clean_pdf_artifacts(d) for d in obj.get("domains", [])]
        return {
            "skills": filtered,
            "projects": projects,
            "domains": domains,
            "years_experience": obj.get("years_experience"),
            "target_role": obj.get("target_role"),
            "strongest_skills": obj.get("strongest_skills", []),
            "weakest_signals": obj.get("weakest_signals", []),
        }
    except Exception:
        return None



def _extract_concepts_from_jd(text):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Use LLM to extract the JD at the CONCEPT level, not the tool-keyword level.
    Returns concepts (mapped to our taxonomy where possible), required capabilities,
    and the raw tool keywords (for the translation sidebar)."""
    concept_list = ", ".join(CONCEPT_TAXONOMY)
    prompt = f"""You are analyzing a job description for a technical interview coach. Extract what the role ACTUALLY requires at the CONCEPT level — not the literal tool names.

Job description (truncated):
{text[:4000]}

Our coaching taxonomy of data-engineering concepts (use these exact keys where they fit):
{concept_list}

Return ONLY this JSON — no markdown, no commentary:
{{
  "role_title": "the job title, be specific",
  "seniority": "junior | mid | senior | staff | principal",
  "domain": "the application domain (e.g. 'real-time recommendation', 'payments', 'adtech', 'healthcare')",
  "concepts_required": [
    {{
      "concept": "a concept key from the taxonomy above if it fits, else a short concept phrase (e.g. 'streaming_paradigm', 'batch_vs_stream_choice', 'partitioning_hot_key_skew', 'cloud_platform', 'ic_across_teams')",
      "evidence": "the JD phrase that implies this concept",
      "importance": "must_have | nice_to_have"
    }}
  ],
  "capabilities_required": [
    "broader capabilities the role needs that aren't single taxonomy concepts, e.g. 'design a real-time system from scratch', 'own a data platform end to end', 'translate batch experience to streaming' — 3 to 6 items"
  ],
  "tool_keywords": ["literal tools/services named in the JD, e.g. 'Kafka', 'AWS', 'Flink', 'Terraform' — preserved for the translation sidebar"],
  "signal_framing": "1-2 sentences on what kind of candidate this JD is really looking for (beyond the bullet list)"
}}

Critical: if the JD says 'Kafka' or 'Flink', the concept is 'streaming_paradigm' (not 'Kafka'). If it says 'AWS' or 'GCP', the concept is 'cloud_platform'. Batch tools (Spark, PySpark) map to 'batch_paradigm'. Think in paradigms and concepts, not brand names."""

    raw = _call_json_extract(prompt, max_tokens=1500)
    if not raw:
        return None
    try:
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        return {
            "role_title": obj.get("role_title", ""),
            "seniority": obj.get("seniority", ""),
            "domain": obj.get("domain", ""),
            "concepts_required": obj.get("concepts_required", []),
            "capabilities_required": obj.get("capabilities_required", []),
            "tool_keywords": obj.get("tool_keywords", []),
            "signal_framing": obj.get("signal_framing", ""),
        }
    except Exception:
        return None



def _fallback_extract_jd(text):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Basic regex-based JD extraction when the LLM is unavailable.
    Extracts role title, tool keywords, and concept-level guesses from raw text."""
    title = ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for l in lines[:15]:
        l_clean = l.strip()
        if l_clean and len(l_clean) < 120 and not l_clean.startswith(("http", "About", "Job", "Location", "Salary", "Type", "Posted")):
            # likely a job title — first substantive short line
            if any(w in l_clean.lower() for w in ("engineer", "scientist", "architect", "developer", "manager", "intern", "analyst")):
                title = l_clean
                break
            elif "|" not in l_clean and "@" not in l_clean:
                title = l_clean
                break
    known_tools = set(JD_CONCEPT_TRANSLATIONS.keys())
    tool_keywords = []
    text_lower = text.lower()
    for tool in sorted(known_tools, key=len, reverse=True):
        if tool in text_lower and tool not in tool_keywords:
            tool_keywords.append(tool)
    concept_matches = {}
    for tool, concept in JD_CONCEPT_TRANSLATIONS.items():
        if tool in text_lower:
            concept_matches.setdefault(concept, []).append(tool)
    concepts_required = []
    for concept, tools in concept_matches.items():
        concepts_required.append({
            "concept": concept,
            "evidence": f"Mentions: {', '.join(tools[:3])}",
            "importance": "must_have",
        })
    return {
        "role_title": title or "Unknown Role",
        "seniority": "mid",
        "domain": "",
        "concepts_required": concepts_required,
        "capabilities_required": [],
        "tool_keywords": tool_keywords[:20],
        "signal_framing": "Extracted by fallback (no LLM available). Concepts are based on tool-name matching — less precise than AI extraction.",
    }



def _fallback_extract_resume(text):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Basic regex-based resume extraction when the LLM is unavailable.
    Extracts skill candidates, project-like paragraphs, and domain guesses."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # collect capitalized terms as skill candidates
    words = re.findall(r'\b[A-Z][a-z++#.]{1,}\b', text)
    skip = {"The", "This", "That", "With", "From", "They", "What", "When", "Where",
            "Also", "Have", "Has", "Had", "Our", "Your", "You", "We", "I", "It", "Its",
            "Not", "All", "Each", "Every", "Some", "Most", "Few", "Many", "Much",
            "More", "Less", "And", "But", "Or", "For", "Nor", "Yet", "So", "Both",
            "Either", "Neither", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
            "Email", "Phone", "Address", "City", "State"}
    skill_set = set()
    for w in words:
        wl = w.lower()
        if w in skip or len(w) < 3:
            continue
        if wl in skill_set:
            continue
        skill_set.add(wl)
    skills = [{"name": s.title(), "depth": "moderate", "context": ""} for s in list(skill_set)[:30]]
    projects = []
    for l in lines[10:40]:
        if len(l) > 60 and any(c in l for c in (".", ":", "—")):
            projects.append({
                "name": l.split("—")[0].split(":")[0].strip()[:60] or "Project",
                "description": l[:150],
                "tech": [],
                "specificity": "low",
            })
    return {
        "target_role": "Unknown",
        "years_experience": None,
        "skills": skills,
        "projects": projects[:5],
        "domains": [],
        "strongest_skills": [s["name"] for s in skills[:5]],
        "weakest_signals": [],
    }



def _extraction_fallback_chain(extract_fn, fallback_fn, text, label):
    from app import client, MODEL, log, pdfplumber, docx  # lazy: breaks app<->service import cycle
    """Try LLM extraction first, fall back to deterministic extraction on failure.
    Returns (data: dict | None, method: str)."""
    data = extract_fn(text)
    if data:
        return data, "llm"
    log.debug("[%s] LLM extraction failed — using fallback", label)
    fb = fallback_fn(text)
    if fb:
        return fb, "fallback"
    log.debug("[%s] Fallback also failed — returning None", label)
    return None, "none"




