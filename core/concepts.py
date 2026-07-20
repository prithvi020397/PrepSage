# Phase 3 refactor — pure concept-normalization helpers, verbatim from app.py.
from core.constants import CONCEPT_NORMALIZATION


def _normalize_concept(concept):
    """Map a JD concept (taxonomy key OR plain-English phrase) to a canonical key.
    Falls back to the lowercased, underscored form so unknown concepts still flow through."""
    if not concept:
        return ""
    c = concept.strip().lower()
    if c in CONCEPT_NORMALIZATION:
        return CONCEPT_NORMALIZATION[c]
    # try the underscored version (e.g. 'streaming_paradigm' passes through untouched)
    underscored = c.replace(" ", "_")
    if underscored in CONCEPT_NORMALIZATION:
        return CONCEPT_NORMALIZATION[underscored]
    # try substring match against known phrases (handles 'real-time processing' etc.)
    for phrase, key in CONCEPT_NORMALIZATION.items():
        if phrase in c:
            return key
    return underscored


def _concept_is_present(concept, evidence_text, evidence_skills):
    """Heuristic: is this JD concept evidenced in the resume?
    Returns (present: bool, confidence: 'high'|'medium'|'low').
    Conservative by design: requires STRONG signals for easy-to-false-positive concepts
    (streaming must show streaming tooling, not just the word 'event' in a batch context)."""
    concept_l = concept.lower().replace("_", " ")
    hay = evidence_text.lower()

    # STRONG (tool-level) signals — high confidence when present
    strong = {
        "streaming_paradigm": ["kafka", "flink", "kinesis", "spark streaming", "pub/sub",
                               "streaming pipeline", "real-time pipeline", "stream processor"],
        "batch_paradigm": ["batch", "pyspark", "spark", "java", "etl", "dataproc", "scheduled job",
                           "daily job", "hourly job", "airflow"],
        "cloud_platform": ["azure", "aws", "gcp", "databricks", "s3", "blob", "cloud"],
        "idempotency_dedup": ["idempot", "dedup", "exactly-once", "exactly once", "deduplicate"],
        "backfill_reprocessing": ["backfill", "reprocess", "replay", "recompute"],
        "late_data_watermarks": ["watermark", "late arrival", "late data", "event time", "windowed"],
        "schema_evolution_compat": ["schema evolution", "schema contract", "avro", "versioned schema"],
        "partitioning_hot_key_skew": ["partition skew", "hot key", "data skew", "repartition"],
        "replication_consistency": ["replication", "failover", "leader", "replica"],
        "storage_format_choice": ["parquet", "iceberg", "delta lake", "orc", "columnar"],
        "data_quality_observability": ["data quality", "data validation", "monitoring", "observability"],
        "orchestration": ["airflow", "dagster", "luigi", "orchestrat"],
        "iac": ["terraform", "pulumi", "cloudformation"],
        "warehouse": ["snowflake", "bigquery", "redshift"],
        "sql_database": ["postgres", "mysql", "t-sql", "sql server", "relational"],
        "container_orchestration": ["kubernetes", "k8s", "eks", "aks", "gke"],
        "containers": ["docker", "container", "podman"],
        "grain_awareness": ["grain", "star schema", "fact table"],
        "scd_strategy": ["scd", "slowly changing", "type 2"],
        "entity_enumeration": ["dimension", "fact table", "entity model"],
        "missing_dimension_audit": ["dimension", "data mart", "modeling audit"],
        "feature_store": ["feature store", "feature serving", "low-latency serving", "ml platform",
                          "feature development", "feature reuse"],
    }
    # WEAK (fuzzy) signals — medium/low confidence, prone to false positives, so gated
    weak = {
        "streaming_paradigm": [("real-time", "low"), ("realtime", "low"), ("event stream", "medium")],
        "batch_vs_stream_choice": [("batch", "medium"), ("stream", "low"), ("latency", "low"), ("sla", "low")],
        "late_data_watermarks": [("window", "low"), ("event time", "low")],
        "domain_alignment": [("stakeholder", "medium"), ("requirements", "medium"), ("business", "low"), ("alignment", "low")],
        "clarifying_requirements": [("requirement", "medium"), ("scope", "low"), ("clarif", "low")],
        "data_modeling": [("modeling", "low"), ("warehouse", "low")],
    }

    for s in strong.get(concept, []):
        if s and s in hay:
            return True, "high"
    # weak signals only count if no strong signal matched, and they're explicitly lower confidence
    for w, conf in weak.get(concept, []):
        if w and w in hay:
            return True, conf
    return False, "none"

def _translation_source(concept, jd_tool_set):
    """Given a concept, return the JD tool keyword that implies it (for the sidebar)."""
    concept_to_tool = {
        "streaming_paradigm": ["kafka", "flink", "kinesis", "spark streaming"],
        "cloud_platform": ["aws", "azure", "gcp", "google cloud"],
        "batch_paradigm": ["spark", "pyspark", "databricks"],
        "orchestration": ["airflow", "dagster", "luigi"],
        "iac": ["terraform", "pulumi", "cloudformation"],
        "warehouse": ["snowflake", "bigquery", "redshift"],
        "sql_database": ["postgres", "mysql", "sql server", "t-sql"],
        "container_orchestration": ["kubernetes", "k8s", "eks", "aks"],
        "containers": ["docker"],
        "storage_format": ["iceberg", "delta lake", "parquet", "hive"],
    }
    for t in concept_to_tool.get(concept, []):
        if t in jd_tool_set:
            return t
    return None


def _find_translation_sibling(concept, resume_tool_set):
    """Given a concept and the resume's tool set, find a sibling tool in the same family."""
    families = {
        "streaming_paradigm": ["kafka", "flink", "kinesis", "spark streaming", "pubsub"],
        "cloud_platform": ["aws", "azure", "gcp", "google cloud", "databricks"],
        "batch_paradigm": ["spark", "pyspark", "databricks", "hadoop", "java"],
        "orchestration": ["airflow", "dagster", "luigi", "prefect"],
        "iac": ["terraform", "pulumi", "cloudformation"],
        "warehouse": ["snowflake", "bigquery", "redshift", "databricks"],
        "sql_database": ["postgres", "mysql", "sql server", "t-sql", "oracle"],
        "container_orchestration": ["kubernetes", "k8s", "eks", "aks", "gke"],
        "containers": ["docker", "podman", "containerd"],
        "storage_format": ["iceberg", "delta lake", "parquet", "hive", "orc"],
    }
    fam = families.get(concept, [])
    for t in fam:
        if t in resume_tool_set:
            return t
    return None

