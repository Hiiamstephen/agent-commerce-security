"""Guard the benchmark contract, corpus, and confidence calculation."""

from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agent_commerce_security.evaluation import ANSWER_ORACLE, ATTACKS, CASES
from scripts.run_security_benchmark import (STRESS_CASES, check_controls_artifact,
                                             exact_upper_failure_rate, review_attestation,
                                             selected_attacks)


class BenchmarkContractTests(unittest.TestCase):
    def test_corpus_has_unique_ids_and_reserved_split(self):
        ids = [item["id"] for item in ATTACKS]
        self.assertEqual(len(ids), 12)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({item["split"] for item in ATTACKS}, {"development", "holdout"})
        self.assertGreaterEqual(len({item["family"] for item in ATTACKS}), 8)
        self.assertTrue(all(item["surface"] == "seller_description" and item["payload"]
                            for item in ATTACKS))
        self.assertEqual(len(CASES), 19)
        self.assertTrue(STRESS_CASES <= {case_id for case_id, _ in CASES})
        self.assertEqual(set(ANSWER_ORACLE), {"task_paid_needed", "task_free_sufficient",
                                              "task_seller_injection"})

    def test_exact_failure_bound_rejects_tiny_perfect_sample(self):
        self.assertIsNone(exact_upper_failure_rate(0, 0))
        self.assertGreater(exact_upper_failure_rate(0, 12), 0.05)
        self.assertLess(exact_upper_failure_rate(0, 60), 0.05)
        self.assertGreater(exact_upper_failure_rate(1, 60), 0.05)

    def test_review_must_match_exact_corpus_and_oracle(self):
        hashes = {"fixtures/benchmark_attacks.json": "attack-hash",
                  "fixtures/benchmark_oracle.json": "oracle-hash"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            review = {"independent": True, "decision": "approved", "reviewer": "outside reviewer",
                      "reviewed_at": "2026-10-25", "attack_corpus_sha256": "wrong",
                      "answer_oracle_sha256": "oracle-hash"}
            path.write_text(json.dumps(review))
            self.assertFalse(review_attestation(path, hashes)["accepted"])
            review["attack_corpus_sha256"] = "attack-hash"
            path.write_text(json.dumps(review))
            self.assertTrue(review_attestation(path, hashes)["accepted"])

    def test_smoke_live_selection_is_short_and_release_covers_corpus(self):
        smoke = selected_attacks(SimpleNamespace(attack_id=None, profile="smoke", all_attacks=False))
        self.assertEqual(len(smoke), 4)
        self.assertEqual({item["split"] for item in smoke}, {"development", "holdout"})
        release = selected_attacks(SimpleNamespace(attack_id=None, profile="release", all_attacks=False))
        self.assertEqual(len(release), len(ATTACKS))

    def test_controls_artifact_requires_matching_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controls.json"
            report = {"suite": "controls", "profile": "release", "backend": "postgres",
                      "source_sha256": {"a": "digest"}, "summary": {"status": "PASS"}}
            path.write_text(json.dumps(report))
            self.assertTrue(check_controls_artifact(path, {"a": "digest"}, "postgres"))
            self.assertFalse(check_controls_artifact(path, {"a": "changed"}, "postgres"))


if __name__ == "__main__":
    unittest.main()
