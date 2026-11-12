"""What is staged is what was verified: the read point, the private copies and the staging step of the readiness gate.

The live file is attacked after verification and before staging by replacing the module's `stage` (or `copy_gated`) with a
function that first does the damage, so the swap happens at the one point where the gate's guarantee is exercised. The
interpreter-level seams used are the module's own functions; the program is not edited.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import signal
import stat
import tempfile
import zipfile

import caps_release_helpers as h
from readiness_support import GROUP, Fixture, pom_xml, sig_of

S = "check_release_readiness"
NAMES = ["a-1.0.0.jar", "a-1.0.0-sources.jar", "a-1.0.0-javadoc.jar", "a-1.0.0.pom", "a-1.0.0.jar.asc", "a-1.0.0-sources.jar.asc",
         "a-1.0.0-javadoc.jar.asc", "a-1.0.0.pom.asc"]


class Hang(Exception):
    pass


@contextlib.contextmanager
def bounded(seconds):
    def fire(*_):
        raise Hang(f"no result within {seconds} seconds")
    old = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


@contextlib.contextmanager
def patched(module, **attrs):
    saved = {k: getattr(module, k) for k in attrs}
    for k, v in attrs.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(module, k, v)


class Staged(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()
        self.stage = self.path("gated-files")
        self.mod = h.load(S)
        self.tmpdir = self.path("tmp")
        os.mkdir(self.tmpdir)

    @contextlib.contextmanager
    def private_tmp(self):
        """Every temporary directory of the gate is made here, so a leftover is visible and exact."""
        saved = tempfile.tempdir
        tempfile.tempdir = self.tmpdir
        try:
            yield self.tmpdir
        finally:
            tempfile.tempdir = saved

    def run_gate(self, *extra, before_stage=None, env=None, **patches):
        """Run in this process; BEFORE_STAGE(held) runs after every check and before the first byte is staged."""
        original = self.mod.stage

        def stage(dest, t, files, err, held=None):
            if before_stage:
                before_stage(held)
            return original(dest, t, files, err, held)

        argv = ["--target-dir", self.target, "--gpg", self.gpg, *extra, "--stage", self.stage]
        with self.private_tmp(), patched(self.mod, stage=stage, **patches):
            res = h.run_main(S, argv, env=env)
        return res

    def live(self, name):
        return os.path.join(self.target, name)

    def staged_files(self):
        out = {}
        for root, _, files in os.walk(self.stage):
            for n in files:
                with open(os.path.join(root, n), "rb") as fh:
                    out[os.path.relpath(os.path.join(root, n), self.stage)] = fh.read()
        return out

    def assert_nothing_left(self, res):
        self.assertEqual(res.rc, 1, res)
        self.assertFalse(os.path.lexists(self.stage), "a refused run leaves no staging directory")
        self.assertEqual(os.listdir(self.tmpdir), [], "the gate's private directory is removed")

    def assert_not_staged(self, res, name):
        self.assert_nothing_left(res)
        errors = "\n".join(res.errors())
        self.assertIn(f"{os.path.join(self.target, name)} cannot be staged", errors)
        self.assertIn("the gated files could not be staged", errors)


class Swaps(Staged):
    def swap_all(self, make):
        for name in NAMES:
            with self.subTest(name):
                shutil.rmtree(self.stage, ignore_errors=True)
                self.reset()
                res = self.run_gate(before_stage=lambda held, n=name: make(n))
                self.assert_not_staged(res, name)

    def reset(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.real_coordinate()

    def test_a_file_replaced_by_same_size_different_bytes_is_not_staged(self):
        def make(name):
            data = bytearray(self.read_target(name))
            data[-1] ^= 0x01
            with open(self.live(name), "wb") as fh:
                fh.write(data)
        self.swap_all(make)

    def test_a_file_replaced_by_a_symbolic_link_to_identical_bytes_is_not_staged(self):
        def make(name):
            elsewhere = self.path("elsewhere-" + name)
            shutil.copy(self.live(name), elsewhere)
            os.remove(self.live(name))
            os.symlink(elsewhere, self.live(name))
        self.swap_all(make)

    def test_a_file_replaced_by_a_fifo_does_not_hang_the_gate(self):
        def make(name):
            os.remove(self.live(name))
            os.mkfifo(self.live(name))
        with bounded(30):
            self.swap_all(make)

    def test_a_file_that_is_deleted_is_not_staged(self):
        self.swap_all(lambda name: os.remove(self.live(name)))

    def test_a_file_replaced_by_a_directory_is_not_staged(self):
        def make(name):
            os.remove(self.live(name))
            os.mkdir(self.live(name))
        self.swap_all(make)

    def test_a_file_replaced_by_a_device_is_not_staged(self):
        if not os.path.exists("/dev/null"):
            self.skipTest("no /dev/null")

        def make(name):
            os.remove(self.live(name))
            os.symlink("/dev/null", self.live(name))
        self.swap_all(make)

    def test_a_file_swapped_and_swapped_back_is_the_verified_file(self):
        """A swap that is undone before staging changes nothing a release could contain."""
        def make(name):
            original = self.read_target(name)
            with open(self.live(name), "wb") as fh:
                fh.write(b"evil")
            with open(self.live(name), "wb") as fh:
                fh.write(original)
        res = self.run_gate(before_stage=lambda held: make("a-1.0.0.jar"))
        self.accepted(res)

    def test_the_bytes_staged_are_the_bytes_verified_even_when_the_live_file_changes_after_it_was_re_hashed(self):
        """The copy comes from the private read, so a change made after the live file was hashed cannot reach the stage."""
        original = self.mod.digest_of_file
        live = self.live("a-1.0.0.jar")
        want = self.read_target("a-1.0.0.jar")

        def digest_of_file(path):
            digest = original(path)
            if path == live:
                with open(live, "wb") as fh:
                    fh.write(b"evil" + want[4:])
            return digest

        res = self.run_gate(digest_of_file=digest_of_file)
        self.accepted(res)
        self.assertEqual(self.staged_files()["a-1.0.0.jar"], want)
        self.assertNotEqual(self.read_target("a-1.0.0.jar"), want, "the swap really happened")

    @staticmethod
    def overwrite_first_byte(path):
        with open(path, "r+b") as fh:
            fh.write(b"\xff")

    def test_a_private_copy_changed_after_it_was_verified_is_not_staged(self):
        for label, tamper in (("same-size bytes", self.overwrite_first_byte),
                              ("symbolic link", lambda p: (os.remove(p), os.symlink(self.live("a-1.0.0.jar"), p))),
                              ("deleted", os.remove), ("fifo", lambda p: (os.remove(p), os.mkfifo(p)))):
            with self.subTest(label):
                shutil.rmtree(self.stage, ignore_errors=True)
                with bounded(30):
                    res = self.run_gate(before_stage=lambda held: tamper(held["a-1.0.0.jar"][0]))
                self.assert_not_staged(res, "a-1.0.0.jar")

    def test_a_private_copy_that_changes_while_it_is_copied_is_unlinked_from_the_stage(self):
        """The digest of the bytes written is compared with the digest taken when the file was read."""
        original = self.mod.open_regular

        def open_regular(path):
            fd = original(path)
            if os.path.basename(path) == "a-1.0.0.jar" and path != self.live("a-1.0.0.jar"):
                self.overwrite_first_byte(path)
            return fd

        # the digest of the live file is checked first, so tampering with the private copy is caught after the copy
        res = self.run_gate(open_regular=open_regular)
        self.assertEqual(res.rc, 1, res)
        self.assertFalse(os.path.lexists(self.stage))
        self.assertIn("the verified copy changed", "\n".join(res.errors()))


class WhenItStages(Staged):
    @staticmethod
    def put(path, content):
        with open(path, "wb" if isinstance(content, bytes) else "w") as fh:
            fh.write(content)

    def recorder(self):
        calls = []
        original = self.mod.stage

        def stage(*a, **k):
            calls.append(a[0])
            return original(*a, **k)
        return calls, stage

    def test_a_run_with_any_finding_never_reaches_staging(self):
        problems = {
            "a missing sources jar": lambda: os.remove(self.live("a-1.0.0-sources.jar")),
            "a missing signature": lambda: os.remove(self.live("a-1.0.0.pom.asc")),
            "a bad signature": lambda: self.put(self.live("a-1.0.0.jar.asc"), "SIG:0\n"),
            "a javadoc jar without index.html": lambda: zipfile.ZipFile(self.live("a-1.0.0-javadoc.jar"), "w").close(),
            "a classifier jar": lambda: self.put(self.live("a-1.0.0-tests.jar"), b"x"),
            "a symbolic link": lambda: (os.remove(self.live("a-1.0.0.pom")), os.symlink(self.live("a-1.0.0.jar"), self.live("a-1.0.0.pom"))),
            "an unreadable pom": lambda: self.put(self.live("a-1.0.0.pom"), "<project"),
        }
        for label, damage in problems.items():
            with self.subTest(label):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.real_coordinate()
                damage()
                if label == "an unreadable pom":
                    self.put(self.live("a-1.0.0.pom.asc"), sig_of(self.live("a-1.0.0.pom")))
                calls, stage = self.recorder()
                with self.private_tmp(), patched(self.mod, stage=stage):
                    res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
                self.assertEqual(res.rc, 1, res)
                self.assertEqual(calls, [], "staging is not attempted")
                self.assertFalse(os.path.lexists(self.stage))

    def test_a_clean_run_stages_once(self):
        calls, stage = self.recorder()
        with self.private_tmp(), patched(self.mod, stage=stage):
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
        self.accepted(res)
        self.assertEqual(calls, [self.stage])

    def test_a_stage_that_fails_part_way_is_removed(self):
        for failing_call in range(1, 6):
            with self.subTest(failing_call):
                calls = []
                original = self.mod.copy_gated

                def copy_gated(src, dst, gated, n=failing_call):
                    calls.append(dst)
                    if len(calls) == n:
                        raise OSError("disk full")
                    return original(src, dst, gated)
                shutil.rmtree(self.stage, ignore_errors=True)
                with self.private_tmp(), patched(self.mod, copy_gated=copy_gated):
                    res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
                self.assertEqual(res.rc, 1, res)
                self.assertGreaterEqual(len(calls), failing_call)
                self.assertFalse(os.path.lexists(self.stage), "the partial stage is removed")
                self.assertIn("disk full", "\n".join(res.errors()))
                self.assertEqual(os.listdir(self.tmpdir), [])

    def test_an_empty_destination_that_was_handed_in_is_used_and_removed_with_a_failed_stage(self):
        os.mkdir(self.stage)

        def copy_gated(src, dst, gated):
            raise OSError("disk full")
        with self.private_tmp(), patched(self.mod, copy_gated=copy_gated):
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
        self.assertEqual(res.rc, 1)
        self.assertFalse(os.path.lexists(self.stage))

    def test_a_destination_that_holds_anything_is_refused_and_left_byte_for_byte_alone(self):
        for label, populate in (("a file", lambda d: self.put(os.path.join(d, "keep"), "old")),
                                ("a hidden file", lambda d: self.put(os.path.join(d, ".keep"), "old")),
                                ("an empty subdirectory", lambda d: os.mkdir(os.path.join(d, "sub"))),
                                ("a dangling link", lambda d: os.symlink("nowhere", os.path.join(d, "l")))):
            for clean in (True, False):
                with self.subTest(f"{label}, {'clean' if clean else 'failing'} run"):
                    shutil.rmtree(self.stage, ignore_errors=True)
                    os.mkdir(self.stage)
                    populate(self.stage)
                    before = sorted(os.listdir(self.stage))
                    if not clean:
                        os.remove(self.live("a-1.0.0-sources.jar"))
                    with self.private_tmp():
                        res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
                    self.assertEqual(res.rc, 1, res)
                    self.assertEqual(sorted(os.listdir(self.stage)), before, "nothing in the destination is touched")
                    if clean:
                        self.assertIn("is not an empty directory", "\n".join(res.errors()))
                    if not clean:
                        self.reset_target()
                    shutil.rmtree(self.stage, ignore_errors=True)

    def reset_target(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.real_coordinate()

    def test_a_destination_whose_parent_does_not_exist_is_created_with_it(self):
        deep = self.path("a", "b", "gated-files")
        with self.private_tmp():
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", deep])
        self.accepted(res)
        self.assertTrue(os.path.isdir(deep))
        self.assertEqual(stat.S_IMODE(os.stat(deep).st_mode), 0o700)

    def test_a_stage_that_is_interrupted_part_way_is_removed(self):
        original = self.mod.copy_gated
        calls = []

        def copy_gated(src, dst, gated):
            calls.append(dst)
            if len(calls) == 3:
                raise KeyboardInterrupt()
            return original(src, dst, gated)
        with self.private_tmp(), patched(self.mod, copy_gated=copy_gated):
            with self.assertRaises(KeyboardInterrupt):
                h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
        self.assertFalse(os.path.lexists(self.stage))

    def test_an_interrupted_stage_still_removes_the_private_directory(self):
        def copy_gated(src, dst, gated):
            raise KeyboardInterrupt()
        with self.private_tmp(), patched(self.mod, copy_gated=copy_gated):
            with self.assertRaises(KeyboardInterrupt):
                h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
        self.assertEqual(os.listdir(self.tmpdir), [])


class PrivateCopies(Staged):
    def test_the_private_directory_is_removed_on_every_way_out(self):
        argv = ["--target-dir", self.target, "--gpg", self.gpg]

        def explode(*_a, **_k):
            raise RuntimeError("boom")

        def interrupt(*_a, **_k):
            raise KeyboardInterrupt()

        cases = {
            "success": ({}, 0), "refusal": ({}, 1), "unexpected exception": ({"gate": explode}, 1),
            "interrupt": ({"gate": interrupt}, KeyboardInterrupt), "an exception while reading": ({"take": explode}, 1),
        }
        for label, (patches, outcome) in cases.items():
            with self.subTest(label):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.real_coordinate()
                if label == "refusal":
                    os.remove(self.live("a-1.0.0.pom.asc"))
                with self.private_tmp(), patched(self.mod, **patches):
                    if outcome is KeyboardInterrupt:
                        with self.assertRaises(KeyboardInterrupt):
                            h.run_main(S, argv)
                    else:
                        res = h.run_main(S, argv)
                        self.assertEqual(res.rc, outcome, res)
                        if "exception" in label:
                            self.assertEqual(len(res.errors()), 1, res)
                            self.assertIn("failed unexpectedly", res.err)
                self.assertEqual(os.listdir(self.tmpdir), [])

    def test_the_program_removes_it_too(self):
        os.remove(self.live("a-1.0.0.pom.asc"))
        env = h.clean_env(TMPDIR=self.tmpdir)
        self.assertEqual(h.run_proc(S, ["--target-dir", self.target, "--gpg", self.gpg], env=env).rc, 1)
        self.assertEqual(os.listdir(self.tmpdir), [])
        self.real_coordinate()
        self.accepted(h.run_proc(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage], env=env))
        self.assertEqual(os.listdir(self.tmpdir), [])
        self.assertTrue(os.path.isdir(self.stage))

    def test_the_private_directory_and_every_copy_are_unpredictable_and_closed_to_others(self):
        self.use_py_gpg()
        with self.private_tmp():
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(PYGPG_LOG=self.log))
        self.accepted(res)
        calls = self.gpg_calls()
        self.assertEqual(len(calls), 4, "the four built files, each against its signature")
        for call in calls:
            self.assertEqual(call["argv"][0], "--verify")
            for path in call["argv"][1:]:
                self.assertTrue(os.path.isabs(path))
                self.assertTrue(path.startswith(self.tmpdir + os.sep), path)
            self.assertEqual(set(call["dir_modes"]), {0o700}, "each file sits in a directory of its own, closed to others")
            self.assertEqual(set(call["scratch_modes"]), {0o700})
        tops = {os.path.relpath(p, self.tmpdir).split(os.sep)[0] for c in calls for p in c["argv"][1:]}
        self.assertEqual(len(tops), 1, "one scratch directory, from mkdtemp")
        for top in tops:
            self.assertRegex(top, r"^release-verify-[A-Za-z0-9_]{8}$")

    def test_a_name_that_is_already_taken_is_never_used_or_removed(self):
        """The scratch directory is made by mkdtemp: a directory or a link that holds the first name it tries is skipped over."""
        if not hasattr(tempfile, "_get_candidate_names"):
            self.skipTest("tempfile does not expose its name sequence here")
        victim = self.path("victim")
        os.mkdir(victim)
        with open(os.path.join(victim, "sentinel"), "w") as fh:
            fh.write("keep")
        os.mkdir(os.path.join(self.tmpdir, "release-verify-aaaaaaaa"))
        with open(os.path.join(self.tmpdir, "release-verify-aaaaaaaa", "attacker"), "w") as fh:
            fh.write("x")
        os.symlink(victim, os.path.join(self.tmpdir, "release-verify-bbbbbbbb"))
        names = iter(["aaaaaaaa", "bbbbbbbb", "cccccccc"] + [f"{i:08x}" for i in range(1, 400)])
        self.use_py_gpg()
        with self.private_tmp(), patched(tempfile, _get_candidate_names=lambda: _Fixed(names)):
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(PYGPG_LOG=self.log))
        self.accepted(res)
        self.assertEqual(os.listdir(victim), ["sentinel"], "nothing was written through the link")
        self.assertEqual(os.listdir(os.path.join(self.tmpdir, "release-verify-aaaaaaaa")), ["attacker"])
        used = {os.path.dirname(os.path.dirname(c["argv"][1])) for c in self.gpg_calls()}
        self.assertEqual({os.path.basename(u) for u in used}, {"release-verify-cccccccc"}, "the first free name is used")

    def test_a_private_copy_is_created_exclusively(self):
        """`take` refuses to write over a file that is already there, so a planted link is not followed."""
        victim = self.path("victim.bin")
        with open(victim, "wb") as fh:
            fh.write(b"keep")
        plant = self.path("plant")
        os.mkdir(plant)
        os.symlink(victim, os.path.join(plant, "a-1.0.0.jar"))
        with patched(tempfile, mkdtemp=lambda dir=None, **k: plant):
            with self.assertRaises(FileExistsError):
                self.mod.take(self.live("a-1.0.0.jar"), self.tmpdir)
        with open(victim, "rb") as fh:
            self.assertEqual(fh.read(), b"keep")

    def test_the_read_point_refuses_links_and_special_files_without_blocking(self):
        elsewhere = self.path("elsewhere")
        shutil.copy(self.live("a-1.0.0.jar"), elsewhere)
        os.symlink(elsewhere, self.path("link.jar"))
        os.mkfifo(self.path("fifo.jar"))
        os.mkdir(self.path("dir.jar"))
        with bounded(30):
            for name in ("link.jar", "fifo.jar", "dir.jar", "absent.jar"):
                with self.subTest(name):
                    with self.assertRaises(OSError):
                        self.mod.take(self.path(name), self.tmpdir)
            private, digest = self.mod.take(self.live("a-1.0.0.jar"), self.tmpdir)
        self.assertEqual(digest, hashlib.sha256(self.read_target("a-1.0.0.jar")).hexdigest())
        with open(private, "rb") as fh:
            self.assertEqual(fh.read(), self.read_target("a-1.0.0.jar"))
        self.assertEqual(os.path.basename(private), "a-1.0.0.jar", "the base name is kept")

    def test_the_read_opens_without_following_blocking_or_leaking_the_descriptor(self):
        seen = []
        real = os.open

        def spy(path, flags, *a, **k):
            if str(path).endswith("a-1.0.0.jar"):
                seen.append(flags)
            return real(path, flags, *a, **k)
        with patched(os, open=spy):
            self.mod.take(self.live("a-1.0.0.jar"), self.tmpdir)
        want = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        self.assertTrue(seen and all(f & want == want for f in seen), seen)

    def test_a_file_name_cannot_become_a_gpg_option_or_break_the_argument_list(self):
        names = {"leading dash": "-x", "leading double dash": "--version", "option with value": "--keyring=x", "homedir option": "--homedir=.",
                 "space": "a b", "quote": "a'b", "glob": "a*b", "newline": "a\nb", "semicolon": "a;b"}
        for label, artifact in names.items():
            with self.subTest(label):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                os.remove(self.log) if os.path.exists(self.log) else None
                self.use_py_gpg()
                self.coordinate(f"{artifact}-1.0.0", pom_text=pom_xml(GROUP, artifact, "1.0.0"))
                with self.private_tmp():
                    res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(PYGPG_LOG=self.log))
                self.assertEqual(os.listdir(self.tmpdir), [])
                if label == "newline":
                    self.assertEqual(res.rc, 1)
                    self.assertIn("control or unassigned character", res.err)
                else:
                    self.accepted(res)
                calls = self.gpg_calls()
                self.assertEqual(len(calls), 4, calls)
                for call in calls:
                    self.assertEqual(len(call["argv"]), 3, "exactly --verify, the signature and the file")
                    self.assertEqual(call["argv"][0], "--verify")
                    for path in call["argv"][1:]:
                        self.assertTrue(path.startswith(self.tmpdir + os.sep), path)
                        self.assertFalse(os.path.basename(os.path.dirname(path)).startswith("-"))


class _Fixed:
    """An iterator standing in for tempfile's name sequence (it is created once per mkdtemp call)."""

    def __init__(self, names):
        self.names = names

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.names)
