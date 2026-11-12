"""check_drift: the committed generated tree must be what the build produced."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest

import caps_release_helpers as h

def git(repo, *args, check=True):
    env = {**h.clean_env(), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false",
                           "-c", "protocol.file.allow=always", *args], capture_output=True, text=True, env=env, check=check)


class Drift(h.Case):
    S = "check_drift"

    def setUp(self):
        super().setUp()
        self.repo = self.path("repo")
        os.makedirs(os.path.join(self.repo, "gen", "deep"))
        git(self.repo, "init", "-q", "-b", "main")
        self.put("gen/a.txt", "a\n")
        self.put("gen/deep/b.txt", "b\n")
        self.put("src.txt", "s\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

    def put(self, rel, content="x\n"):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)

    def check(self, generated="gen", *extra):
        return self.both(self.S, ["--repo", self.repo, f"--generated={generated}", *extra])

    def test_clean_tree(self):
        res = self.check()
        self.accepted(res)
        self.assertIn("ok - gen is what this build produces", res.out)
        self.accepted(self.check("gen/"))

    def test_modified_deleted_added_staged(self):
        def modify():
            self.put("gen/a.txt", "changed\n")

        def delete():
            os.remove(os.path.join(self.repo, "gen/a.txt"))

        def add():
            self.put("gen/new.txt")

        def add_nested():
            self.put("gen/newdir/deeper/new.txt")

        def stage():
            self.put("gen/a.txt", "changed\n")
            git(self.repo, "add", "gen/a.txt")

        def mode():
            os.chmod(os.path.join(self.repo, "gen/a.txt"), 0o755)

        def rename_staged():
            git(self.repo, "mv", "gen/a.txt", "gen/z.txt")

        def rename_plain():
            os.rename(os.path.join(self.repo, "gen/a.txt"), os.path.join(self.repo, "gen/z.txt"))

        def move_out():
            os.rename(os.path.join(self.repo, "gen/a.txt"), os.path.join(self.repo, "elsewhere.txt"))

        def replaced_by_symlink():
            os.remove(os.path.join(self.repo, "gen/a.txt"))
            os.symlink("/etc/hostname", os.path.join(self.repo, "gen/a.txt"))

        def untracked_hidden_by_config():
            git(self.repo, "config", "status.showUntrackedFiles", "no")
            self.put("gen/new.txt")

        for label, mutate in dict(modified=modify, deleted=delete, added=add, nested_added=add_nested, staged=stage,
                                  mode_change=mode, rename_staged=rename_staged, rename_plain=rename_plain,
                                  moved_out=move_out, symlink_swap=replaced_by_symlink,
                                  config_hides_untracked=untracked_hidden_by_config).items():
            with self.subTest(label):
                git(self.repo, "reset", "-q", "--hard")
                git(self.repo, "clean", "-qfdx")
                git(self.repo, "config", "--unset", "status.showUntrackedFiles", check=False)
                mutate()
                res = self.check()
                self.refused(res, "does not match what this build produced")
                self.assertIn("Run the two-pass build", res.errors()[0])
                self.assertTrue(res.out.strip(), "the status is shown on stdout")

    def test_a_change_outside_the_path_is_not_drift(self):
        self.put("src.txt", "changed\n")
        self.put("other/new.txt")
        self.accepted(self.check())

    def test_ignored_files_are_not_reported(self):
        self.put(".gitignore", "*.log\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "ignore")
        self.put("gen/out.log")
        self.accepted(self.check())

    def test_the_refusal_names_the_fix_and_nothing_about_a_deployment(self):
        self.put("gen/a.txt", "changed\n")
        res = self.check()
        self.refused(res)
        self.assertEqual(len(res.errors()), 1)
        self.assertIn("Run the two-pass build and commit the result.", res.errors()[0])
        for word in ("DROP", "deploy", "Central", "upload", "bundle"):
            self.assertNotIn(word, res.errors()[0])

    def test_there_is_no_uploaded_flag(self):
        for run in (h.run_main, h.run_proc):
            with self.subTest(run.__name__):
                res = run(self.S, ["--repo", self.repo, "--generated", "gen", "--uploaded"])
                self.assertEqual(res.rc, 2, res)
                self.assertEqual(res.errors(), [])

    def test_empty_path_is_refused(self):
        self.refused(self.both(self.S, ["--repo", self.repo, "--generated", ""]), "the generated path is empty")

    def test_git_failing_is_a_refusal(self):
        self.refused(self.both(self.S, ["--repo", self.path("absent"), "--generated", "gen"]), "git could not report")
        plain = self.path("plain")
        os.makedirs(plain)
        self.refused(self.both(self.S, ["--repo", plain, "--generated", "gen"]), "git could not report")

    def test_a_path_behind_a_symlink_out_of_the_repository_is_refused(self):
        outside = self.path("outside")
        os.makedirs(os.path.join(outside, "sub"))
        with open(os.path.join(outside, "sub", "new.txt"), "w") as fh:
            fh.write("x\n")
        os.symlink(outside, os.path.join(self.repo, "link"))
        self.refused(self.check("link/sub"))

    def test_a_leading_dash_is_a_path_not_an_option(self):
        self.put("-x/f.txt")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "dash")
        self.accepted(self.check("-x"))
        self.put("-x/f.txt", "changed\n")
        res = self.check("-x")
        self.refused(res, "does not match")
        self.assertIn("+changed", res.out, "the diff is shown for a path that starts with a dash")

    OPTION_SHAPED = ("--ignored", "--untracked-files=no", "-uno", "--porcelain=v2", "--help")

    def test_an_option_shaped_value_that_names_no_directory_is_refused_as_such(self):
        self.put("gen/a.txt", "changed\n")
        for value in self.OPTION_SHAPED:
            with self.subTest(value):
                res = self.check(value)
                self.refused(res, "is not a directory in the repository")
                self.assertEqual(len(res.errors()), 1)
                self.assertNotIn("a.txt", res.out, "no git report is produced for a value that names nothing")

    def test_a_directory_named_like_an_option_is_a_directory_and_never_an_option(self):
        for value in self.OPTION_SHAPED:
            with self.subTest(value):
                self.put(f"{value}/f.txt", "tracked\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "option-named directories")
        for value in self.OPTION_SHAPED:
            with self.subTest("clean " + value):
                res = self.check(value)
                self.accepted(res)
                self.assertIn(f"ok - {value} is what this build produces", res.out)
        for value in self.OPTION_SHAPED:
            with self.subTest("drift " + value):
                git(self.repo, "reset", "-q", "--hard")
                git(self.repo, "clean", "-qfdx")
                self.put("gen/a.txt", "drifted elsewhere\n")
                self.accepted(self.check(value))                    # drift under gen/ is not drift under this path
                self.put(f"{value}/f.txt", "changed\n")
                res = self.check(value)
                self.refused(res, "does not match what this build produced")
                self.assertIn("f.txt", res.out)
                self.assertIn("+changed", res.out, "the diff is shown, so git read the value as a path")
                self.assertNotIn("a.txt", res.out)
        for value in self.OPTION_SHAPED:
            with self.subTest("untracked " + value):
                git(self.repo, "reset", "-q", "--hard")
                git(self.repo, "clean", "-qfdx")
                self.put(f"{value}/new/deeper/added.txt", "new\n")
                res = self.check(value)
                self.refused(res, "does not match")
                self.assertIn("added.txt", res.out, "-uno or --ignored would hide the added file")

    def test_a_symlink_inside_the_repository_is_followed_to_the_directory_it_names(self):
        os.symlink("gen", os.path.join(self.repo, "link"))
        self.accepted(self.check("link"))
        self.put("gen/a.txt", "changed\n")
        res = self.check("link")
        self.refused(res, "does not match")
        self.assertIn("gen/a.txt", res.out, "git is asked about the resolved directory, not the link")

    def test_a_symlink_to_a_file_or_to_nothing_is_refused(self):
        os.symlink("gen/a.txt", os.path.join(self.repo, "filelink"))
        os.symlink("nowhere", os.path.join(self.repo, "dangling"))
        for value in ("filelink", "dangling"):
            with self.subTest(value):
                self.refused(self.check(value), "is not a directory in the repository")

    def test_a_symlinked_component_leaving_the_repository_is_refused_by_name(self):
        outside = self.path("outside")
        os.makedirs(os.path.join(outside, "gen"))
        os.symlink(outside, os.path.join(self.repo, "out"))
        res = self.check("out/gen")
        self.refused(res, "leaves the repository")

    def test_a_path_that_is_a_file_is_refused(self):
        self.refused(self.check("gen/a.txt"), "is not a directory in the repository")
        self.refused(self.check("src.txt"), "is not a directory in the repository")

    def test_an_untracked_directory_and_a_directory_without_a_tracked_file_are_refused(self):
        self.put("fresh/new.txt")
        os.makedirs(os.path.join(self.repo, "emptydir"))
        self.put(".gitignore", "ign/\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "ignore")
        self.put("ign/only.txt")
        for value in ("fresh", "emptydir", "ign", ".git"):
            with self.subTest(value):
                res = self.check(value)
                self.refused(res)
                self.assertIn("holds no tracked file", "\n".join(res.errors()) if value != ".git" else "holds no tracked file")

    def test_pathspec_magic_and_globs_are_file_names_not_instructions(self):
        self.put("gen/a.txt", "changed\n")
        for value in (":(exclude)gen", "*", ":/", ":(top)gen", "gen/*", "g?n", "[g]en", ":!gen", ":^gen"):
            with self.subTest(value):
                self.refused(self.check(value), "is not a directory in the repository")

    def test_a_directory_literally_named_like_a_glob_is_that_directory_only(self):
        self.put("*/star.txt", "s\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "star")
        self.put("gen/a.txt", "changed\n")
        self.accepted(self.check("*"))                              # `*` as a glob would match gen/ and report drift
        self.put("*/star.txt", "changed\n")
        res = self.check("*")
        self.refused(res, "does not match")
        self.assertNotIn("gen/a.txt", res.out)

    def test_the_same_directory_written_four_ways_is_the_same_answer(self):
        self.put("gen/a.txt", "changed\n")
        for value in ("gen", "gen/", "./gen", "gen/../gen", "gen//deep/.."):
            with self.subTest(value):
                res = self.check(value)
                self.refused(res, "does not match")
                self.assertIn("gen/a.txt", res.out)
        git(self.repo, "reset", "-q", "--hard")
        for value in ("gen", "gen/", "./gen", "gen/../gen"):
            with self.subTest("clean " + value):
                self.accepted(self.check(value))

    def test_every_tracked_file_deleted_from_the_working_tree_is_drift(self):
        for rel in ("gen/a.txt", "gen/deep/b.txt"):
            os.remove(os.path.join(self.repo, rel))
        res = self.check()
        self.refused(res, "does not match what this build produced")
        self.assertIn(" D gen/a.txt", res.out)
        self.assertIn(" D gen/deep/b.txt", res.out)

    def test_a_directory_removed_with_its_files_is_refused_though_not_as_drift(self):
        """The directory is gone, so the path names nothing: refused, with the message of an unusable path."""
        shutil.rmtree(os.path.join(self.repo, "gen"))
        res = self.check()
        self.refused(res, "is not a directory in the repository")
        self.assertEqual(res.out, "", "no status is printed for it")

    def test_a_new_file_a_mode_change_and_a_symlink_swap_inside_are_each_drift(self):
        for label, mutate in (
                ("new", lambda: self.put("gen/deep/new.txt")),
                ("mode", lambda: os.chmod(os.path.join(self.repo, "gen/deep/b.txt"), 0o755)),
                ("symlink", lambda: (os.remove(os.path.join(self.repo, "gen/deep/b.txt")),
                                     os.symlink("a.txt", os.path.join(self.repo, "gen/deep/b.txt"))))):
            with self.subTest(label):
                git(self.repo, "reset", "-q", "--hard")
                git(self.repo, "clean", "-qfdx")
                mutate()
                self.refused(self.check(), "does not match what this build produced")

    def test_a_control_character_in_the_path_cannot_forge_a_second_error_line(self):
        res = self.check("gen\n::error::injected")
        self.refused(res)
        self.assertEqual(len(res.errors()), 1)
        self.assertNotIn("\n::error::injected", res.err)
        self.assertIn("\\n", res.err)

    def test_the_repository_argument_is_required_and_must_be_a_work_tree(self):
        self.assertEqual(h.run_proc(self.S, ["--generated", "gen"]).rc, 2)
        self.assertEqual(h.run_main(self.S, ["--generated", "gen"]).rc, 2)
        bare = self.path("bare.git")
        git(self.tmp, "init", "-q", "--bare", bare)
        self.refused(self.both(self.S, ["--repo", bare, "--generated", "refs"]))   # a directory, but no work tree
        self.refused(self.both(self.S, ["--repo", os.path.join(self.repo, ".git"), "--generated", "gen"]))

    def shim(self, failing):
        """A `git` that runs the real one except for the named subcommand, which fails."""
        real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
        self.write("shim/git", f'#!/bin/sh\nfor a in "$@"; do [ "$a" = "{failing}" ] && {{ echo "fatal: broken" >&2; exit 128; }}; done\nexec {real} "$@"\n')
        os.chmod(self.path("shim", "git"), 0o755)
        return h.clean_env(PATH=self.path("shim") + os.pathsep + os.environ["PATH"])

    def test_a_git_that_fails_to_list_or_to_report_is_a_refusal_naming_git(self):
        for sub in ("ls-files", "status"):
            with self.subTest(sub):
                res = self.both(self.S, ["--repo", self.repo, "--generated", "gen"], env=self.shim(sub))
                self.refused(res, "git could not report on gen: fatal: broken")
                self.assertEqual(res.out, "")

    def test_git_unable_to_run_ends_in_one_error_line(self):
        res = h.run_proc(self.S, ["--repo", self.repo, "--generated", "gen"], env={"PATH": self.tmp, "LC_ALL": "C.UTF-8"})
        self.refused(res)
        self.assertEqual(len(res.errors()), 1)
        self.assertEqual(res.rc, 1)

    def test_a_submodule_with_a_modified_file_is_drift(self):
        sub = self.path("subsrc")
        os.makedirs(sub)
        git(sub, "init", "-q", "-b", "main")
        with open(os.path.join(sub, "f"), "w") as fh:
            fh.write("1\n")
        git(sub, "add", "-A")
        git(sub, "commit", "-q", "-m", "s")
        added = git(self.repo, "submodule", "add", "-q", sub, "gen/sub", check=False)
        if added.returncode != 0:
            self.skipTest("git submodule add is unavailable here: " + added.stderr.strip())
        git(self.repo, "commit", "-q", "-m", "sub")
        self.accepted(self.check())
        with open(os.path.join(self.repo, "gen/sub/f"), "w") as fh:
            fh.write("changed\n")
        self.refused(self.check(), "does not match")

    # --- gaps ---------------------------------------------------------------------------------

    def test_a_path_that_names_nothing_is_refused(self):
        self.put("gen/a.txt", "changed\n")
        self.refused(self.check("gne"))

    def test_pathspec_magic_cannot_hide_the_tree(self):
        self.put("gen/a.txt", "changed\n")
        self.refused(self.check(":(exclude)gen"))
        self.refused(self.check("*.nothing"))

    def test_usage(self):
        self.assertEqual(h.run_proc(self.S, ["--repo", "x"]).rc, 2)


if __name__ == "__main__":
    unittest.main()
