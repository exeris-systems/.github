"""check_release_readiness against hostile input: the released set, symlinks, POM binding and staging."""
from __future__ import annotations

import os
import shutil
import stat
import time
import unittest

import caps_release_helpers as h
from readiness_support import Fixture, SUFFIXES, make_zip, pom_xml, sig_of

S = "check_release_readiness"


def _tree(root):
    """Kind, mode and content of everything under root; a link by its text."""
    out = {}
    for base, dirs, files in os.walk(root):
        for name in dirs + files:
            p = os.path.join(base, name)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                out[p] = ("link", os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                out[p] = ("dir", stat.S_IMODE(st.st_mode))
            else:
                with open(p, "rb") as fh:
                    out[p] = ("file", stat.S_IMODE(st.st_mode), fh.read())
    return out


class Gate(Fixture):
    """A refusal is complete: exit 1, the closing line, and nothing in target/ touched."""

    def gate(self, *extra, proc=False):
        before = self.snapshot()
        res = (self.check if proc else (lambda *e: h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, *e])))(*extra)
        self.assertEqual(self.snapshot(), before, "the gate never changes target/")
        return res

    def snapshot(self):
        out = {}
        for root, dirs, files in os.walk(self.target):
            for n in dirs + files:
                p = os.path.join(root, n)
                st = os.lstat(p)
                out[p] = (st.st_mode, st.st_size, os.readlink(p) if stat.S_ISLNK(st.st_mode) else None)
        return out

    def refuse(self, fragment, *extra, proc=False):
        res = self.gate(*extra, proc=proc)
        self.refused(res, fragment)
        self.assertTrue(res.errors()[-1].startswith("::error::release-readiness failed")
                        or "failed unexpectedly" in res.errors()[-1], res)
        return res


class ReleasedSet(Gate):
    def setUp(self):
        super().setUp()
        self.real_coordinate()

    def test_an_unsigned_tests_jar_is_refused_by_name(self):
        make_zip(os.path.join(self.target, "a-1.0.0-tests.jar"), ["T.class"])
        res = self.refuse("a-1.0.0-tests.jar is not part of a release", proc=True)
        self.assertEqual(len(res.errors()), 2)

    def test_a_signed_tests_jar_is_still_not_part_of_the_release(self):
        make_zip(os.path.join(self.target, "a-1.0.0-tests.jar"), ["T.class"])
        with open(os.path.join(self.target, "a-1.0.0-tests.jar.asc"), "w") as fh:
            fh.write(sig_of(os.path.join(self.target, "a-1.0.0-tests.jar")))
        res = self.refuse("a-1.0.0-tests.jar is not part of a release")
        self.assertIn("a-1.0.0-tests.jar.asc is not part of a release", "\n".join(res.errors()))

    def test_any_other_classifier_is_refused(self):
        for classifier in ("shaded", "all", "classes", "javadoc2", "test-sources", "SOURCES"):
            with self.subTest(classifier):
                path = os.path.join(self.target, f"a-1.0.0-{classifier}.jar")
                make_zip(path, ["x"])
                self.refused(self.gate(), None)
                os.remove(path)

    def test_a_shaded_jar_with_its_own_signed_companions_still_has_to_match_its_pom(self):
        self.coordinate("a-1.0.0-shaded", pom_text=pom_xml())
        self.refuse("a-1.0.0-shaded.pom declares a:1.0.0, which the files are not named after")

    def test_a_shaded_jar_alone_is_refused(self):
        make_zip(os.path.join(self.target, "a-1.0.0-shaded.jar"), ["x"])
        res = self.refuse("a-1.0.0-shaded is missing a-1.0.0-shaded-sources.jar")
        self.assertIn("a-1.0.0-shaded.jar has no detached signature", "\n".join(res.errors()))

    def test_a_snapshot_sources_jar_beside_the_main_jar_is_refused_by_name(self):
        make_zip(os.path.join(self.target, "a-1.0.0-SNAPSHOT-sources.jar"), ["x"])
        self.refuse("a-1.0.0-SNAPSHOT-sources.jar is not part of a release")

    def test_a_sources_or_javadoc_jar_without_its_main_jar_is_refused(self):
        make_zip(os.path.join(self.target, "b-2.0.0-sources.jar"), ["x"])
        make_zip(os.path.join(self.target, "c-3.0.0-javadoc.jar"), ["index.html"])
        res = self.refuse("b-2.0.0-sources.jar is not part of a release")
        self.assertIn("c-3.0.0-javadoc.jar is not part of a release", "\n".join(res.errors()))

    def test_an_orphan_signature_is_refused(self):
        for orphan in ("zzz-1.0.asc", "a-1.0.0-tests.jar.asc", "a-1.0.0.jar.asc.asc", "a-1.0.0.module.asc", "a-1.0.1.pom.asc"):
            with self.subTest(orphan):
                path = os.path.join(self.target, orphan)
                with open(path, "w") as fh:
                    fh.write("SIG:00\n")
                self.refuse(f"{orphan} is not part of a release")
                os.remove(path)

    def test_a_signature_whose_file_was_removed_is_reported_as_the_missing_file(self):
        os.remove(os.path.join(self.target, "a-1.0.0.pom"))
        self.refuse("a-1.0.0 is missing a-1.0.0.pom")

    def test_a_pom_without_a_main_jar_is_not_part_of_a_release(self):
        with open(os.path.join(self.target, "zzz-1.0.pom"), "w") as fh:
            fh.write("<project/>")
        self.refuse("zzz-1.0.pom is not part of a release")

    def test_files_that_are_not_jars_poms_or_signatures_are_not_gated(self):
        for name in ("a-1.0.0.module", "notes.txt", "a-1.0.0.jar.md5", "a-1.0.0-cyclonedx.json", "x.zip"):
            with open(os.path.join(self.target, name), "w") as fh:
                fh.write("anything")
        self.accepted(self.gate())

    def test_a_symlink_in_place_of_each_released_file_is_refused(self):
        outside = self.path("outside")
        with open(outside, "w") as fh:
            fh.write("elsewhere")
        for suffix in SUFFIXES:
            for kind in ("", ".asc"):
                for dangling in (False, True):
                    name = f"a-1.0.0{suffix}{kind}"
                    with self.subTest(name, dangling=dangling):
                        path = os.path.join(self.target, name)
                        saved = path + ".keep"
                        os.rename(path, saved)
                        os.symlink(self.path("absent") if dangling else outside, path)
                        res = self.refuse("is a symbolic link")
                        self.assertIn(f"{name} is a symbolic link", "\n".join(res.errors()))
                        os.remove(path)
                        os.rename(saved, path)
        self.accepted(self.gate())

    def test_a_symlink_to_a_directory_named_like_a_jar_is_refused(self):
        os.symlink(self.tmp, os.path.join(self.target, "b-1.0.0.jar"))
        self.refuse("b-1.0.0.jar is a symbolic link")

    def test_a_directory_named_like_a_released_file_is_refused(self):
        for suffix in (".pom", "-sources.jar", ".jar.asc"):
            with self.subTest(suffix):
                path = os.path.join(self.target, f"a-1.0.0{suffix}")
                os.rename(path, path + ".keep")
                os.makedirs(path)
                self.refused(self.gate())
                os.rmdir(path)
                os.rename(path + ".keep", path)

    def test_a_fifo_in_place_of_a_released_file_is_refused_without_blocking(self):
        path = os.path.join(self.target, "a-1.0.0-javadoc.jar")
        os.remove(path)
        os.mkfifo(path)
        start = time.monotonic()
        self.refuse("a-1.0.0-javadoc.jar is not a regular file")
        self.assertLess(time.monotonic() - start, 10)

    def test_a_snapshot_version_in_the_pom_is_refused(self):
        for version in ("1.0.0-SNAPSHOT", "1.0.0-snapshot", "1.0.0-Snapshot", "1.0.0-20260101.120000-1"):
            with self.subTest(version):
                self.real_pom(version=version)
                res = self.refuse(f"declares the SNAPSHOT version {version}")
                self.assertIn("which the files are not named after", "\n".join(res.errors()))

    def test_a_snapshot_inherited_from_the_parent_is_refused(self):
        self.real_pom(text="<project><parent><groupId>g</groupId><artifactId>p</artifactId>"
                           "<version>2.0-SNAPSHOT</version></parent><artifactId>a</artifactId></project>")
        self.refuse("declares the SNAPSHOT version 2.0-SNAPSHOT")

    def test_a_pom_that_disagrees_with_the_file_name_is_refused(self):
        for label, text in (("artifactId", pom_xml(artifact="b")), ("version", pom_xml(version="1.0.1")),
                            ("both", pom_xml(artifact="b", version="2.0.0")),
                            ("case", pom_xml(artifact="A")),
                            ("padded", pom_xml(artifact="a", version="1.0.0").replace("<version>1.0.0", "<version>1.0.0 x"))):
            with self.subTest(label):
                self.real_pom(text=text)
                self.refuse("which the files are not named after")

    def test_whitespace_around_the_pom_values_is_not_a_disagreement(self):
        self.real_pom(text=pom_xml().replace("<artifactId>a<", "<artifactId>\n  a\n<").replace("<version>1.0.0<", "<version> 1.0.0 <"))
        self.accepted(self.gate())

    def test_a_pom_that_cannot_be_read_is_refused(self):
        for body in ("", "<project>", "not xml"):
            with self.subTest(body):
                self.real_pom(text=body)
                self.refuse("cannot be read as a POM")

    def test_a_pom_with_a_doctype_is_refused_before_any_entity_is_read(self):
        for doctype in ("<!DOCTYPE project>", '<!DOCTYPE project [<!ENTITY x "y">]>',
                        '<!DOCTYPE project [<!ENTITY x SYSTEM "file:///etc/hostname">]>'):
            with self.subTest(doctype):
                self.real_pom(text='<?xml version="1.0"?>' + doctype + pom_xml())
                res = self.refuse("cannot be read as a POM")
                self.assertIn("DOCTYPE", "\n".join(res.errors()))

    def test_a_pom_bomb_is_refused_in_bounded_time(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaaaaaaaaaaaa">'
                + "".join(f'<!ENTITY {c} "' + f"&{p};" * 10 + '">' for p, c in zip("abcdefgh", "bcdefghi"))
                + ']><project><version>&i;</version></project>')
        self.real_pom(text=bomb)
        start = time.monotonic()
        self.refuse("cannot be read as a POM")
        self.assertLess(time.monotonic() - start, 10)

    def test_a_file_name_with_a_control_or_undecodable_character_is_refused_and_printed_escaped(self):
        raw = os.fsencode(self.target)
        for label, name in (("newline", b"x\n::error::forged.pom"), ("escape", b"x\x1b[31m.jar"), ("bad utf8", b"x\xff.pom"),
                            ("bidi", "x‮.asc".encode())):
            with self.subTest(label):
                path = raw + b"/" + name
                with open(path, "wb") as fh:
                    fh.write(b"x")
                res = h.run_proc(S, ["--target-dir", self.target, "--gpg", self.gpg])
                self.refused(res, "has a control or unassigned character")
                self.assertNotIn("\n::error::forged", res.err)
                self.assertNotIn("\x1b", res.err)
                os.remove(path)

    def real_pom(self, text=None, version="1.0.0"):
        path = os.path.join(self.target, "a-1.0.0.pom")
        with open(path, "w") as fh:
            fh.write(text if text is not None else pom_xml(version=version))
        with open(path + ".asc", "w") as fh:
            fh.write(sig_of(path))


class UnboundGroup(Gate):
    """A POM that does not yield a full coordinate cannot bind the release to one, and is refused."""

    def setUp(self):
        super().setUp()
        self.coordinate("a-1.0.0", pom_text=pom_xml(group=None))

    def test_a_group_less_pom_is_refused(self):
        res = self.gate()
        self.refused(res, "a-1.0.0.pom does not yield a groupId, an artifactId and a version")
        self.assertNotIn("unexpectedly", res.err)

    def test_a_pom_naming_neither_artifact_nor_version_must_not_pass(self):
        with open(os.path.join(self.target, "a-1.0.0.pom"), "w") as fh:
            fh.write("<project><groupId>g</groupId></project>")
        with open(os.path.join(self.target, "a-1.0.0.pom.asc"), "w") as fh:
            fh.write(sig_of(os.path.join(self.target, "a-1.0.0.pom")))
        self.assertNotEqual(self.gate().rc, 0)

    def test_a_parent_supplies_the_group_and_the_version(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.coordinate("a-1.0.0", pom_text=pom_xml(group=None, parent_group="org.parent"))
        self.accepted(self.gate())

    def test_a_parent_never_supplies_the_artifact_id(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.coordinate("a-1.0.0", pom_text="<project><parent><groupId>g</groupId><artifactId>a</artifactId>"
                                            "<version>1.0.0</version></parent></project>")
        self.refused(self.gate(), "a-1.0.0.pom does not yield a groupId, an artifactId and a version")


class Staging(Gate):
    def setUp(self):
        super().setUp()
        self.real_coordinate()
        self.stage = self.path("gated-files")

    def stage_run(self, *extra, stage=None, prepare=None):
        """Run in this process and as the workflow does, each from the same starting stage; the two must agree."""
        stage = stage or self.stage
        argv = ["--target-dir", self.target, "--gpg", self.gpg, *extra, "--stage", stage]
        outcome = []
        for run in (h.run_main, h.run_proc):
            if os.path.islink(stage) or os.path.isfile(stage):
                os.remove(stage)
            else:
                shutil.rmtree(stage, ignore_errors=True)
            if prepare:
                prepare()
            res = run(S, argv)
            outcome.append((res, self.staged(stage) if os.path.isdir(stage) and not os.path.islink(stage) else None))
        (a, first), (b, second) = outcome
        self.assertEqual((a.rc, a.errors()), (b.rc, b.errors()))
        self.assertEqual(first, second, "main() and the subprocess stage the same bytes")
        return a

    def staged(self, root=None):
        root = root or self.stage
        out = {}
        for r, _, files in os.walk(root):
            for n in files:
                p = os.path.join(r, n)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, root)] = fh.read()
        return out

    def gated_names(self):
        return {f"a-1.0.0{s}{k}" for s in SUFFIXES for k in ("", ".asc")}

    def test_only_the_gated_set_is_copied_and_the_bytes_are_equal(self):
        for name in ("notes.txt", "a-1.0.0.module", "a-1.0.0.jar.md5", "x.zip", "other.dat"):
            with open(os.path.join(self.target, name), "w") as fh:
                fh.write("not gated")
        os.makedirs(os.path.join(self.target, "classes"))
        with open(os.path.join(self.target, "classes", "A.class"), "w") as fh:
            fh.write("x")
        res = self.stage_run()
        self.accepted(res)
        got = self.staged()
        self.assertEqual(set(got), self.gated_names())
        for name, data in got.items():
            self.assertEqual(data, self.read_target(name), name)

    def test_a_stage_directory_that_exists_and_is_empty_is_accepted(self):
        self.accepted(self.stage_run(prepare=lambda: os.makedirs(self.stage)))
        self.assertEqual(set(self.staged()), self.gated_names())

    def test_a_non_empty_stage_directory_is_refused_and_left_as_it_was(self):
        def leftover():
            os.makedirs(self.stage)
            with open(os.path.join(self.stage, "leftover"), "w") as fh:
                fh.write("old")
        res = self.stage_run(prepare=leftover)
        self.refused(res, "is not an empty directory")
        self.assertEqual(os.listdir(self.stage), ["leftover"])

    def test_a_symlinked_stage_directory_is_refused_and_not_written_through(self):
        real = self.path("real-stage")

        def link():
            shutil.rmtree(real, ignore_errors=True)
            os.makedirs(real)
            os.symlink(real, self.stage)
        res = self.stage_run(prepare=link)
        self.refused(res, "is not an empty directory")
        self.assertEqual(os.listdir(real), [])

    def test_a_stage_path_that_is_a_file_or_a_dangling_link_is_refused(self):
        def a_file():
            with open(self.stage, "w") as fh:
                fh.write("file")
        self.refused(self.stage_run(prepare=a_file), "is not an empty directory")
        self.refused(self.stage_run(prepare=lambda: os.symlink(self.path("absent"), self.stage)), "is not an empty directory")
        self.assertFalse(os.path.exists(self.path("absent")))

    def stage_cases(self):
        """Every shape of --stage that is not absent and not an empty directory, each built fresh by its prepare."""
        def into(target_name, files):
            def prepare():
                target = self.path(target_name)
                shutil.rmtree(target, ignore_errors=True)
                os.makedirs(target)
                for f in files:
                    with open(os.path.join(target, f), "w") as fh:
                        fh.write("old")
                os.symlink(target, self.stage)
            return prepare

        def directory(files):
            def prepare():
                os.makedirs(self.stage)
                for f in files:
                    with open(os.path.join(self.stage, f), "w") as fh:
                        fh.write("old")
            return prepare

        def a_file():
            with open(self.stage, "w") as fh:
                fh.write("old")
        return {"link to an empty directory": into("elsewhere", []), "link to a directory with content": into("elsewhere", ["keep"]),
                "dangling link": lambda: os.symlink(self.path("absent"), self.stage), "file": a_file,
                "directory with content": directory(["keep"]), "directory holding only a hidden file": directory([".hidden"])}

    def test_every_shape_of_stage_that_is_not_absent_or_empty_is_refused_and_left_exactly_as_it_was(self):
        for label, prepare in self.stage_cases().items():
            with self.subTest(label):
                if os.path.lexists(self.stage):
                    os.remove(self.stage) if os.path.islink(self.stage) or os.path.isfile(self.stage) else shutil.rmtree(self.stage)
                prepare()
                before = _tree(self.tmp)
                res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
                self.refused(res, "is not an empty directory")
                self.assertEqual(_tree(self.tmp), before, "nothing is created, written or removed, through the path or beside it")

    def test_an_existing_empty_stage_directory_is_left_in_place_when_the_gate_has_a_finding(self):
        os.makedirs(self.stage)
        os.chmod(self.stage, 0o755)
        inode = os.stat(self.stage).st_ino
        os.remove(os.path.join(self.target, "a-1.0.0.jar"))
        res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.stage])
        self.refused(res)
        self.assertTrue(os.path.isdir(self.stage) and not os.path.islink(self.stage))
        self.assertEqual(os.listdir(self.stage), [], "an existing empty directory is not filled by a run with a finding")
        self.assertEqual(os.stat(self.stage).st_ino, inode, "and it is the same directory")

    def test_the_stage_directory_and_its_files_are_not_world_accessible(self):
        self.accepted(self.stage_run())
        self.assertEqual(stat.S_IMODE(os.stat(self.stage).st_mode), 0o700)

    def test_a_refusal_that_stops_before_staging_creates_nothing(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        res = self.stage_run()
        self.refused(res, "no main jar")
        self.assertFalse(os.path.exists(self.stage))

    def test_a_failing_run_does_not_stage_a_file_that_is_not_part_of_a_release(self):
        make_zip(os.path.join(self.target, "a-1.0.0-tests.jar"), ["x"])
        with open(os.path.join(self.target, "orphan.asc"), "w") as fh:
            fh.write("x")
        os.symlink(self.path("absent"), os.path.join(self.target, "dangling.jar"))
        os.symlink(self.tmp, os.path.join(self.target, "dirlink.pom"))
        res = self.stage_run()
        self.refused(res)
        got = set(self.staged()) if os.path.exists(self.stage) else set()
        self.assertEqual(got - self.gated_names(), set(), "only released regular files can be staged")

    def test_a_failing_run_attempts_to_stage_only_what_exists(self):
        os.remove(os.path.join(self.target, "a-1.0.0-sources.jar"))
        res = self.stage_run()
        self.refused(res, "a-1.0.0 is missing a-1.0.0-sources.jar")
        self.assertNotIn("cannot be staged", "\n".join(res.errors()))

    def test_a_failing_run_stages_no_symlinked_file(self):
        outside = self.path("outside")
        with open(outside, "w") as fh:
            fh.write("elsewhere")
        path = os.path.join(self.target, "a-1.0.0-sources.jar")
        os.remove(path)
        os.symlink(outside, path)
        res = self.stage_run()
        self.refused(res, "a-1.0.0-sources.jar is a symbolic link")
        self.assertNotIn("a-1.0.0-sources.jar", self.staged() if os.path.exists(self.stage) else {})

    def test_a_failing_run_does_not_stage_a_file_with_a_bad_signature(self):
        with open(os.path.join(self.target, "a-1.0.0.jar.asc"), "w") as fh:
            fh.write("garbage\n")
        res = self.stage_run()
        self.refused(res, "a-1.0.0.jar.asc is not a good signature")
        staged = self.staged() if os.path.exists(self.stage) else {}
        self.assertNotIn("a-1.0.0.jar", staged)
        self.assertNotIn("a-1.0.0.jar.asc", staged)

    def test_a_failing_run_does_not_stage_an_unsigned_file(self):
        os.remove(os.path.join(self.target, "a-1.0.0-javadoc.jar.asc"))
        self.refused(self.stage_run(), "has no detached signature")
        staged = self.staged() if os.path.exists(self.stage) else {}
        self.assertNotIn("a-1.0.0-javadoc.jar", staged)

    def swapping_gpg(self, mode, trigger, victim, replacement):
        """A gpg double that verifies correctly and then, as its last act, replaces `victim` (after it was gated)."""
        script = self.write("swap-gpg", f'''#!/bin/sh
[ $# -eq 3 ] && [ "$1" = "--verify" ] || exit 2
want="SIG:$(sha256sum "$3" | cut -d' ' -f1)"
if [ "$(cat "$2")" = "$want" ]; then rc=0; else rc=1; fi
if [ "$(basename "$3")" = "{trigger}" ]; then
  rm -f "{victim}"
  if [ "{mode}" = "link" ]; then ln -s "{replacement}" "{victim}"; else cp "{replacement}" "{victim}"; fi
fi
exit $rc
''')
        os.chmod(script, 0o755)
        return script

    def swapped_for_a_link(self):
        evil = self.path("evil.jar")
        with open(evil, "wb") as fh:
            fh.write(b"EVIL BYTES")
        victim = os.path.join(self.target, "a-1.0.0.jar")
        gpg = self.swapping_gpg("link", "a-1.0.0.pom", victim, evil)
        res = h.run_main(S, ["--target-dir", self.target, "--gpg", gpg, "--stage", self.stage])
        self.assertTrue(os.path.islink(victim), "the race was forced: the link is in place at staging time")
        return res

    def test_a_file_swapped_for_a_symlink_between_gating_and_staging_is_not_followed(self):
        self.swapped_for_a_link()
        self.assertNotIn(b"EVIL BYTES", b"".join(self.staged().values()))

    def test_a_gated_file_that_cannot_be_staged_fails_the_gate(self):
        res = self.swapped_for_a_link()
        self.refused(res)

    def test_staging_never_follows_a_symlink_that_is_present_at_staging_time(self):
        module = h.load(S)
        outside = self.path("outside.jar")
        with open(outside, "wb") as fh:
            fh.write(b"EVIL BYTES")
        os.symlink(outside, os.path.join(self.target, "link.jar"))
        os.mkdir(os.path.join(self.target, "dir.jar"))
        found = []
        module.stage(self.stage, self.target, ["a-1.0.0.pom", "link.jar", "dir.jar", "/dev/null"], found.append)
        self.assertEqual(sorted(os.listdir(self.stage)), ["a-1.0.0.pom"])
        self.assertEqual(len(found), 3)
        self.assertTrue(all("cannot be staged" in f for f in found), found)
        self.assertTrue(any("not a regular file" in f for f in found if "/dev/null" in f), found)

    def test_staging_never_overwrites_a_file_it_already_wrote(self):
        module = h.load(S)
        found = []
        module.stage(self.stage, self.target, ["a-1.0.0.pom", "a-1.0.0.pom"], found.append)
        self.assertEqual(len(found), 1)
        self.assertIn("cannot be staged", found[0])

    def test_staging_refuses_a_stage_that_is_not_empty_when_called_directly(self):
        module = h.load(S)
        os.makedirs(self.stage)
        with open(os.path.join(self.stage, "x"), "w") as fh:
            fh.write("x")
        found = []
        module.stage(self.stage, self.target, ["a-1.0.0.pom"], found.append)
        self.assertEqual(os.listdir(self.stage), ["x"])
        self.assertEqual(len(found), 1)

    def test_a_file_replaced_by_other_bytes_between_gating_and_staging_is_not_staged_as_gated(self):
        evil = self.path("evil.jar")
        with open(evil, "wb") as fh:
            fh.write(b"EVIL BYTES")
        victim = os.path.join(self.target, "a-1.0.0.jar")
        gated = self.read_target("a-1.0.0.jar")
        gpg = self.swapping_gpg("copy", "a-1.0.0.pom", victim, evil)
        res = h.run_main(S, ["--target-dir", self.target, "--gpg", gpg, "--stage", self.stage])
        staged = self.staged() if os.path.exists(self.stage) else {}
        self.assertTrue(res.rc != 0 or staged.get("a-1.0.0.jar") == gated, f"staged {staged.get('a-1.0.0.jar')!r}, gated {gated!r}")

    def test_an_unreadable_stage_destination_ends_in_one_error_line(self):
        res = self.stage_run(stage=os.path.join("/proc", "no-such", "stage"))
        self.refused(res)
        self.assertTrue(res.errors())


if __name__ == "__main__":
    unittest.main()
