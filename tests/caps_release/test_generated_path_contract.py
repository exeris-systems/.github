"""The generated-tree path is checked by two scripts with different rules. These tests characterise each rule as it is;
they are not a statement that the two ought to agree.

resolve_release.py refuses an absolute --generated-path and never passes the value on: its output file carries the
version and the publish decision only. check_drift.py takes its own --generated and accepts an absolute path that
resolves inside the repository. So an absolute path is stopped at the first script that sees it, and is accepted by
the second only if the second is given it directly.
"""
from __future__ import annotations

import os

import caps_release_helpers as h
from test_drift import git

RESOLVE = "resolve_release"
DRIFT = "check_drift"


class GeneratedPath(h.Case):
    def setUp(self):
        super().setUp()
        self.repo = self.path("repo")
        os.makedirs(os.path.join(self.repo, "gen"))
        git(self.repo, "init", "-q", "-b", "main")
        self.write("repo/gen/a.txt", "a\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

    def resolve(self, generated, out=None):
        argv = ["--target", "none", "--upload", "false", "--version", "1.2.3", "--generated-path", generated]
        return h.run_main(RESOLVE, argv + (["--output", out] if out else []))

    def test_characterisation_check_drift_accepts_an_absolute_path_inside_the_repository(self):
        inside = os.path.join(self.repo, "gen")
        res = self.both(DRIFT, ["--repo", self.repo, f"--generated={inside}"])
        self.accepted(res)
        self.assertIn(f"ok - {inside} is what this build produces", res.out)

    def test_characterisation_check_drift_refuses_an_absolute_path_outside_the_repository(self):
        outside = self.path("elsewhere")
        os.makedirs(outside)
        self.refused(self.both(DRIFT, ["--repo", self.repo, f"--generated={outside}"]), "leaves the repository")

    def test_characterisation_resolve_release_refuses_an_absolute_path_even_inside_the_repository(self):
        for g in (os.path.join(self.repo, "gen"), "/", "/gen"):
            with self.subTest(g):
                self.refused(self.both(RESOLVE, ["--target", "none", "--upload", "false", "--version", "1.2.3",
                                                 "--generated-path", g]), "generated-path must be a non-empty path inside the repository")

    def test_the_resolved_output_never_carries_the_generated_path(self):
        out = self.path("out")
        res = self.resolve("gen", out)
        self.accepted(res)
        with open(out) as fh:
            self.assertEqual(fh.read(), "version=1.2.3\npublish=false\n")
        self.assertNotIn("gen", res.out.replace("generated", ""), "the path is not echoed either")

    def test_a_relative_path_is_accepted_by_both(self):
        self.accepted(self.resolve("gen"))
        self.accepted(self.both(DRIFT, ["--repo", self.repo, "--generated=gen"]))


if __name__ == "__main__":
    import unittest
    unittest.main()
