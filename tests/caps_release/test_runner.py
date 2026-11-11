"""scripts/run_caps_release_tests.py: an empty suite fails, a passing one passes, a failing one fails."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

import caps_release_helpers as h

PASSING = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
FAILING = "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n        self.assertTrue(False)\n"
ERRORING = "import unittest\nclass T(unittest.TestCase):\n    def test_err(self):\n        raise RuntimeError('x')\n"
UNEXPECTED = ("import unittest\nclass T(unittest.TestCase):\n    @unittest.expectedFailure\n"
              "    def test_fixed(self):\n        pass\n")


class Runner(h.Case):
    def run_root(self, files: dict | None, make_dir=True):
        root = self.path("root")
        d = os.path.join(root, "tests", "caps_release")
        if make_dir:
            os.makedirs(d)
        for name, body in (files or {}).items():
            with open(os.path.join(d, name), "w") as fh:
                fh.write(body)
        return subprocess.run([sys.executable, "-I", "-B", h.runner_path(), "--root", root], capture_output=True, text=True,
                              env=h.clean_env(), timeout=60)

    def test_an_empty_directory_fails(self):
        res = self.run_root({})
        self.assertEqual(res.returncode, 1, res)
        self.assertIn("::error::no test was collected", res.stderr)

    def test_a_directory_with_files_that_are_not_tests_fails(self):
        res = self.run_root({"helper.py": PASSING, "notes.txt": "x", "test_empty.py": "x = 1\n"})
        self.assertEqual(res.returncode, 1, res)
        self.assertIn("::error::no test was collected", res.stderr)

    def test_one_passing_test_passes(self):
        res = self.run_root({"test_a.py": PASSING})
        self.assertEqual(res.returncode, 0, res)
        self.assertIn("Ran 1 test", res.stderr)

    def test_a_failing_test_fails(self):
        for body in (FAILING, ERRORING, UNEXPECTED):
            with self.subTest(body[-40:]):
                self.tearDown_dirs()
                res = self.run_root({"test_a.py": PASSING, "test_b.py": body})
                self.assertEqual(res.returncode, 1, res)

    def test_a_test_module_that_cannot_be_imported_fails(self):
        res = self.run_root({"test_broken.py": "import no_such_module_anywhere\n"})
        self.assertEqual(res.returncode, 1, res)

    def test_a_syntax_error_fails(self):
        res = self.run_root({"test_syntax.py": "def (:\n"})
        self.assertEqual(res.returncode, 1, res)

    def test_a_missing_tests_directory_does_not_pass(self):
        res = self.run_root(None, make_dir=False)
        self.assertNotEqual(res.returncode, 0, res)

    def test_skipped_tests_are_counted_as_collected(self):
        res = self.run_root({"test_s.py": "import unittest\nclass T(unittest.TestCase):\n    @unittest.skip('x')\n"
                                          "    def test_s(self):\n        pass\n"})
        self.assertEqual(res.returncode, 0, res)

    def tearDown_dirs(self):
        import shutil
        shutil.rmtree(self.path("root"), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
