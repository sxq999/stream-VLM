"""A requested revision is resolved once and the immutable commit is downloaded."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / "scripts/minicpmo/download_model.py"
spec = importlib.util.spec_from_file_location("download_model", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DownloadRevisionTests(unittest.TestCase):
    def test_resolves_requested_revision_and_downloads_its_commit(self):
        calls = {}
        class FakeApi:
            def __init__(self, **kwargs):
                pass
            def model_info(self, repo_id, **kwargs):
                calls["metadata"] = kwargs
                return SimpleNamespace(sha="immutable-commit", siblings=[
                    SimpleNamespace(rfilename="weights", size=4, lfs=None)])
        def snapshot_download(**kwargs):
            calls["download"] = kwargs
            Path(kwargs["local_dir"]).joinpath("weights").write_bytes(b"abcd")
        fake = SimpleNamespace(HfApi=FakeApi, snapshot_download=snapshot_download)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            argv = ["download_model.py", "--revision", "explicit-tag", "--out", str(root / "model"),
                    "--cache", str(root / "cache")]
            with patch.object(sys, "argv", argv), patch.dict(sys.modules, {"huggingface_hub": fake}), redirect_stdout(io.StringIO()):
                module.main()
            self.assertEqual(calls["metadata"]["revision"], "explicit-tag")
            self.assertEqual(calls["download"]["revision"], "immutable-commit")
            receipt = json.loads((root / "model-download.json").read_text())
            self.assertEqual(receipt["revision"], "immutable-commit")
            self.assertEqual(receipt["status"], "files_present_size_verified")

    def test_revision_cannot_be_omitted(self):
        errors = io.StringIO()
        with patch.object(sys, "argv", ["download_model.py", "--out", "unused", "--cache", "unused"]), redirect_stderr(errors):
            with self.assertRaises(SystemExit) as error:
                module.main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("--revision", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
