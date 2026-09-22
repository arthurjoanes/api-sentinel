import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "review.py"
SPEC = importlib.util.spec_from_file_location("sentinel_review", SCRIPT)
assert SPEC and SPEC.loader
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class EvidenceSourceIdentity(unittest.TestCase):
    def test_changing_financial_oracle_invalidates_source_identity(self) -> None:
        source_paths = REVIEW.fingerprint()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in source_paths:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"")
            oracle = root / "data/fixtures/manual-sales.json"
            oracle.parent.mkdir(parents=True, exist_ok=True)
            oracle.write_text('{"revenue_cents":12500}', encoding="utf-8")
            with patch.object(REVIEW, "ROOT", root):
                before = REVIEW.fingerprint()
                oracle.write_text('{"revenue_cents":12501}', encoding="utf-8")
                after = REVIEW.fingerprint()
            self.assertIn("data/fixtures/manual-sales.json", before)
            self.assertNotEqual(before, after)
            self.assertEqual(
                {name for name in before if before[name] != after[name]},
                {"data/fixtures/manual-sales.json"},
            )


class CleanupRecording(unittest.TestCase):
    def test_success_is_not_published_until_cleanup_finishes(self) -> None:
        record = {"status": "passed"}
        snapshots = []
        with REVIEW.record_cleanup_outcome(
            record, lambda: snapshots.append(json.loads(json.dumps(record)))
        ):
            self.assertEqual(record["status"], "cleanup_pending")
        self.assertEqual([item["status"] for item in snapshots], ["cleanup_pending", "passed"])
        self.assertIn("finished_at", snapshots[-1])

    def test_transport_failures_are_recorded_and_propagated(self) -> None:
        for error in (OSError("docker unavailable"), subprocess.TimeoutExpired("docker", 1)):
            with self.subTest(error=type(error).__name__):
                record = {"status": "passed"}
                with self.assertRaises(type(error)):
                    with REVIEW.record_cleanup_outcome(record, lambda: None):
                        raise error
                self.assertEqual(record["status"], "failed")
                self.assertEqual(record["cleanup_failure"]["type"], type(error).__name__)
                self.assertIn("finished_at", record)

    def test_cleanup_failure_preserves_original_measurement_failure(self) -> None:
        failure = {"type": "AssertionError", "message": "incorrect financial result"}
        record = {"status": "failed", "failure": failure, "failed_command": "load-mixed"}
        with self.assertRaises(OSError):
            with REVIEW.record_cleanup_outcome(record, lambda: None):
                raise OSError("docker unavailable")
        self.assertEqual(record["failure"], failure)
        self.assertEqual(record["failed_command"], "load-mixed")
        self.assertEqual(record["status"], "failed")


if __name__ == "__main__":
    unittest.main()
