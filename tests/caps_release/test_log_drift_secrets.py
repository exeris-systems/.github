"""check_dry_run_log, check_drift and check_secrets."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest

import caps_release_helpers as h

SKIP = "[INFO] Skipping the upload of the bundle at user's request"
BEGAN = "[INFO] Going to upload /x/central-bundle.zip"


class DryRunLog(h.Case):
    S = "check_dry_run_log"

    def check(self, text, mode="w"):
        return self.both(self.S, ["--log", self.write("log", text, mode)])

    def test_skip_stated_and_no_upload_begun(self):
        res = self.check(f"[INFO] building\n{SKIP}\n[INFO] BUILD SUCCESS\n")
        self.accepted(res)
        self.assertIn("ok - the plugin reported that it skipped the upload", res.out)

    def test_an_upload_began(self):
        for text in (BEGAN, f"{SKIP}\n{BEGAN}\n", f"{BEGAN}\n{SKIP}\n", "Going to upload", f"x{BEGAN}x\n{SKIP}",
                     SKIP + "\n" + "noise\n" * 1000 + "Going to upload\n"):
            with self.subTest(text[:40]):
                self.refused(self.check(text), "began an upload")

    def test_the_skip_is_not_stated(self):
        for text in ("", "\n", "[INFO] BUILD SUCCESS\n", "skipping the upload of the bundle at user's request",
                     "Skipping the upload of the bundle at user’s request", 'Skipping the upload of the bundle at user"s request',
                     "Skipping the upload of the bundle", "Skipping  the upload of the bundle at user's request",
                     "Skipping the upload of the bundle at users request", "SKIPPING THE UPLOAD OF THE BUNDLE AT USER'S REQUEST",
                     "Skipping the upload of the bundle at\nuser's request", "Skipping the upload of the\x00bundle at user's request"):
            with self.subTest(repr(text[:50])):
                self.refused(self.check(text), "did not report")

    def test_unreadable_log(self):
        self.refused(self.both(self.S, ["--log", self.path("absent")]), "cannot be read")
        self.refused(self.both(self.S, ["--log", self.tmp]), "cannot be read")

    def test_binary_bytes_around_the_statement(self):
        data = b"\xff\xfe\x00\x01 junk\n" + SKIP.encode() + b"\n\x80\x81"
        self.accepted(self.check(data, "wb"))
        self.refused(self.check(b"\xff" + BEGAN.encode(), "wb"), "began an upload")
        self.refused(self.check(bytes(range(256)) * 10, "wb"), "did not report")

    def test_huge_log_is_read_whole(self):
        filler = "x" * 99 + "\n"
        self.accepted(self.check(filler * 100_000 + SKIP + "\n" + filler * 100_000))
        self.refused(self.check(filler * 100_000 + SKIP + "\n" + filler * 100_000 + BEGAN), "began an upload")

    def test_usage(self):
        self.assertEqual(h.run_proc(self.S, []).rc, 2)
        self.assertEqual(h.run_main(self.S, ["--bogus"]).rc, 2)


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

    def test_uploaded_flag_changes_the_remedy(self):
        self.put("gen/a.txt", "changed\n")
        res = self.check("gen", "--uploaded")
        self.refused(res, "DROP it")
        self.assertNotIn("two-pass", res.errors()[0])

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


class Secrets(h.Case):
    S = "check_secrets"
    ALL = dict(HAVE_GPG_KEY="true", HAVE_GPG_PASSPHRASE="true", HAVE_CENTRAL_USER="true", HAVE_CENTRAL_PASSWORD="true")
    NAMES = dict(HAVE_GPG_KEY="GPG_PRIVATE_KEY", HAVE_GPG_PASSPHRASE="GPG_PASSPHRASE",
                 HAVE_CENTRAL_USER="CENTRAL_TOKEN_USERNAME", HAVE_CENTRAL_PASSWORD="CENTRAL_TOKEN_PASSWORD")

    def run_check(self, target, **env):
        return self.both(self.S, ["--target", target], env=h.clean_env(**env))

    def test_all_present(self):
        for target in ("central", "github-packages"):
            with self.subTest(target):
                res = self.run_check(target, **self.ALL)
                self.accepted(res)
                self.assertIn(f"target '{target}'", res.out)

    def test_github_packages_ignores_the_central_credentials(self):
        self.accepted(self.run_check("github-packages", HAVE_GPG_KEY="true", HAVE_GPG_PASSPHRASE="true"))
        self.accepted(self.run_check("github-packages", HAVE_GPG_KEY="true", HAVE_GPG_PASSPHRASE="true",
                                     HAVE_CENTRAL_USER="false", HAVE_CENTRAL_PASSWORD=""))

    def test_each_secret_missing_alone_is_named(self):
        for var, secret in self.NAMES.items():
            for target in ("central", "github-packages"):
                if target == "github-packages" and "CENTRAL" in var:
                    continue
                with self.subTest(var, target=target):
                    env = dict(self.ALL)
                    del env[var]
                    res = self.run_check(target, **env)
                    self.refused(res, secret)
                    others = [s for v, s in self.NAMES.items() if v != var]
                    for other in others:
                        self.assertNotIn(other, res.errors()[0])

    def test_values_other_than_exactly_true_are_missing(self):
        for value in ("True", "TRUE", "1", " true", "true ", "true\n", "", "false", "yes", "tru", "truee", "t"):
            for var in self.NAMES:
                with self.subTest(repr(value), var=var):
                    env = dict(self.ALL, **{var: value})
                    self.refused(self.run_check("central", **env), self.NAMES[var])

    def test_nothing_set_names_everything(self):
        res = self.run_check("central")
        self.refused(res)
        for secret in self.NAMES.values():
            self.assertIn(secret, res.errors()[0])
        res = self.run_check("github-packages")
        self.refused(res)
        self.assertNotIn("CENTRAL", res.errors()[0])

    def test_target_none_or_unknown_is_a_usage_error(self):
        for t in ("none", "maven", "Central", ""):
            with self.subTest(repr(t)):
                self.assertEqual(h.run_proc(self.S, ["--target", t], env=h.clean_env(**self.ALL)).rc, 2)
                self.assertEqual(h.run_main(self.S, ["--target", t], env=h.clean_env(**self.ALL)).rc, 2)

    def test_the_secret_values_themselves_never_matter(self):
        self.refused(self.run_check("central", GPG_PRIVATE_KEY="x", GPG_PASSPHRASE="x", CENTRAL_TOKEN_USERNAME="x",
                                    CENTRAL_TOKEN_PASSWORD="x"))


if __name__ == "__main__":
    unittest.main()
