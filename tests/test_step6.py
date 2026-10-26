"""Check that the public-file gate catches real leak shapes without a real secret."""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_public import check_paths


class PublicFileCheckTests(unittest.TestCase):
    def test_rejects_private_key_marker_and_local_database(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            folder = Path(directory)
            secret = folder / "example.txt"
            secret.write_text("-----BEGIN " + "PRIVATE KEY-----\nsynthetic fixture\n")
            database = folder / "demo.sqlite3"
            database.write_bytes(b"synthetic")
            problems = check_paths([secret, database])
            self.assertEqual(len(problems), 2)
            self.assertEqual({reason for _, reason in problems},
                             {"possible credential material", "local secret or runtime-data path"})


if __name__ == "__main__":
    unittest.main()
