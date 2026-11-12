"""Running the tests leaves nothing behind in the temporary directory.

A child interpreter runs a set of the modules with TMPDIR pointing at a private directory; the directory must be empty afterwards.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

import caps_release_helpers as h

MODULES = ["test_release_readiness", "test_readiness_closed_set", "test_release_profile", "test_secrets", "test_drift",
           "test_staging_binding", "test_gate_internals", "test_upload_command", "test_remove_signing_key", "test_workflow", "test_staged_manifest",
           "test_manifest_gate_agreement"]


class Leftovers(h.Case):
    def test_a_run_of_the_modules_leaves_the_private_temporary_directory_empty(self):
        if h.SCRIPT_DIR_OVERRIDE:
            self.skipTest("a mutant is judged by the tests that notice it, not by this one")
        private = self.path("private-tmp")
        os.makedirs(private)
        env = {**os.environ, "TMPDIR": private}
        done = subprocess.run([sys.executable, "-B", "-m", "unittest", *MODULES], cwd=h.HERE, env=env, capture_output=True, text=True,
                              timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(os.listdir(private), [])


if __name__ == "__main__":
    unittest.main()
