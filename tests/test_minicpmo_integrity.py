import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


path = Path(__file__).resolve().parents[1] / "scripts/minicpmo/verify_download.py"
spec = importlib.util.spec_from_file_location("minicpmo_verify_download", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IntegrityTests(unittest.TestCase):
    def test_inventory_rejects_incomplete_or_corrupt_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.joinpath("weights").write_bytes(b"abcd")
            receipt = {"revision": "fixed", "files": [{"path": "weights", "size": 4,
                       "lfs_sha256": hashlib.sha256(b"abcd").hexdigest()}]}
            self.assertEqual(module.verify(root, receipt)["status"], "pass")
            root.joinpath("weights").write_bytes(b"abce")
            self.assertEqual(module.verify(root, receipt)["errors"][0]["error"], "wrong_sha256")
            root.joinpath("weights").unlink()
            self.assertEqual(module.verify(root, receipt)["errors"][0]["error"], "missing_or_outside_root")


if __name__ == "__main__":
    unittest.main()
