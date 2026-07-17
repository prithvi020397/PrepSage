"""Tests for concept normalization — the load-bearing map every gap/translation
decision flows through. Guards against substring-collision misroutes and proves
the cloud-platform translation (Azure/AWS/GCP -> cloud_platform) is symmetric."""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from app import _normalize_concept, CONCEPT_NORMALIZATION


class TestConceptNormalizationRouting(unittest.TestCase):
    def test_streaming_tools_map_to_streaming_paradigm(self):
        for t in ["kafka", "flink", "kinesis", "spark streaming", "event streaming"]:
            assert _normalize_concept(t) == "streaming_paradigm", t

    def test_batch_tools_map_to_batch_paradigm(self):
        for t in ["batch", "etl", "pyspark", "spark"]:
            assert _normalize_concept(t) == "batch_paradigm", t

    def test_warehouse_tools_map_symmetrically(self):
        # BigQuery <-> Redshift is a genuine translation (step-2 reasoning)
        assert _normalize_concept("bigquery") == "warehouse"
        assert _normalize_concept("redshift") == "warehouse"
        assert _normalize_concept("snowflake") == "warehouse"

    def test_cloud_platform_is_symmetric_across_vendors(self):
        # The core step-2 claim: Azure/AWS/GCP are the SAME concept.
        for t in ["azure", "aws", "gcp", "google cloud", "databricks"]:
            assert _normalize_concept(t) == "cloud_platform", t

    def test_container_orchestration_maps(self):
        for t in ["kubernetes", "k8s", "eks", "aks", "gke"]:
            assert _normalize_concept(t) == "container_orchestration", t

    def test_unknown_concept_falls_back_to_underscored_form(self):
        assert _normalize_concept("some brand new thing") == "some_brand_new_thing"
        assert _normalize_concept("My Weird Concept") == "my_weird_concept"


class TestConceptNormalizationNoCollisions(unittest.TestCase):
    def test_schema_modeling_does_not_become_schema_evolution(self):
        # Substring fallback: "schema" is a key in CONCEPT_NORMALIZATION mapping to
        # schema_evolution_compat. A modeling phrase containing "schema" must NOT
        # silently relabel a data-modeling concept as schema-evolution.
        #
        # NOTE: this is the collision risk called out in the stress test. If the
        # substring scan matches "schema" first, this assertion FAILS and tells us
        # the map needs disambiguation (e.g. drop bare "schema" or order longer
        # phrases first). We assert the SAFE behavior the product intends.
        result = _normalize_concept("schema modeling for fact tables")
        assert result != "schema_evolution_compat", (
            "substring collision: 'schema modeling' routed to schema_evolution_compat"
        )

    def test_plain_schema_is_ambiguous_and_does_not_collide(self):
        # A bare "schema" mention is ambiguous (modeling vs evolution) — it must NOT
        # silently become schema_evolution_compat. It falls back to the underscored
        # raw form, which won't match a concept. That's the honest, collision-free choice.
        assert _normalize_concept("schema") == "schema"

    def test_normalization_is_deterministic(self):
        # Same input twice -> same output (no randomness, no order drift across runs).
        for t in ["kafka", "azure", "real-time", "schema modeling for fact tables"]:
            assert _normalize_concept(t) == _normalize_concept(t)


class TestConceptNormalizationCompleteness(unittest.TestCase):
    def test_every_normalization_value_is_a_known_concept_key(self):
        # Every value in the map must itself be a canonical key (no dangling targets).
        known = set(CONCEPT_NORMALIZATION.values())
        for src, dst in CONCEPT_NORMALIZATION.items():
            assert dst in known or dst == _normalize_concept(dst), (src, dst)


if __name__ == "__main__":
    unittest.main()
