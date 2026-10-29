"""Resource preparation tests that never execute an installer."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("prepare", HERE / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class Resources(unittest.TestCase):
    def test_ui_is_self_contained_and_uses_app_branding(self):
        page = prepare.render_ui("1.0.1")
        self.assertIn("#b4bbc8", page)
        self.assertIn("XYNLEVEL", page)
        self.assertIn("data:image/png;base64,", page)
        self.assertIn("data:font/woff2;base64,", page)
        self.assertNotIn("XynClaim", page)
        self.assertNotIn("__LOGO__", page)
        self.assertNotIn("licenceButton", page)

    def test_backend_metadata_and_digest(self):
        source = HERE.parent / "src-tauri/target/release/bundle/nsis/XynLevel_1.0.1_x64-setup.exe"
        receipt = prepare.check_backend(source, "1.0.1")
        self.assertEqual(len(receipt["sha256"]), 64)
        self.assertEqual(receipt["backend"], source.name)
        self.assertNotIn(str(HERE.parent), str(receipt))

    def test_mismatched_backend_version_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare.check_backend(Path("wrong.exe"), "99.0.0")

    def test_output_outside_work_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            prepare.prepare(HERE.parent / "dist", None, "1.0.1")

    def test_invalid_resource_versions_are_rejected_before_writing(self):
        for version in ["0.1", "1.0.0/extra", "65536.0.0", "1.2.-1"]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                prepare.prepare(HERE / "work/test-invalid", None, version)


if __name__ == "__main__":
    unittest.main()
