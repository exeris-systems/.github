"""`literal()` of the key removal: the last component of a path, named by the text alone, and what the removals do with it.

Trailing separators and trailing `.` components are removed from the text; nothing else is: a `..` component stays, the
root and the empty string stay what they are. The removals then act on that name with sentinels on every side.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import unittest

import caps_release_helpers as h
from test_staging_binding import patched

S = "remove_signing_key"


class Literal(unittest.TestCase):
    def setUp(self):
        self.mod = h.load(S)

    def test_trailing_separators_and_dot_components_are_removed_from_the_text(self):
        cases = {"LINK": "LINK", "LINK/": "LINK", "LINK//": "LINK", "LINK///": "LINK", "LINK/.": "LINK", "LINK/./": "LINK",
                 "LINK/./.": "LINK", "LINK/.//.": "LINK", "LINK//.//": "LINK", "a/b/": "a/b", "a/b/.": "a/b", "/a/b/.": "/a/b",
                 "./a/": "./a"}
        for text, want in cases.items():
            with self.subTest(text):
                self.assertEqual(self.mod.literal(text), want)

    def test_a_parent_component_is_never_resolved_or_dropped(self):
        for text in ("LINK/..", "LINK/../", "LINK/../.", "a/b/..", "..", "../..", "LINK/.hidden", "LINK/..x"):
            with self.subTest(text):
                want = text.rstrip("/")
                while want.endswith("/."):
                    want = want[:-2]
                self.assertEqual(self.mod.literal(text), want)
                self.assertTrue(self.mod.literal(text).endswith(("..", ".hidden", "..x")), "a name that ends in `..` stays")

    def test_the_root_the_dot_and_the_empty_string_are_themselves(self):
        for text, want in (("/", "/"), ("//", "/"), ("///", "/"), ("/.", "/"), ("//.", "/"), ("/./", "/"), (".", "."), ("./", "."),
                           ("./.", "."), ("", ""), ("././", ".")):
            with self.subTest(text):
                self.assertEqual(self.mod.literal(text), want)

    def test_the_result_is_a_fixed_point(self):
        for text in ("LINK/", "LINK/.", "/", ".", "", "a//./b/./", "///", "/.//"):
            once = self.mod.literal(text)
            self.assertEqual(self.mod.literal(once), once, text)

    def test_nothing_is_looked_up(self):
        calls = []
        real = os.path.realpath
        with patched(os.path, realpath=lambda *a, **k: calls.append(a) or real(*a, **k)):
            self.mod.literal("LINK/./")
        self.assertEqual(calls, [])


class Sandbox(h.Case):
    """A working directory with `LINK -> outside/inner` and a sentinel on every side of it."""

    def setUp(self):
        super().setUp()
        self.mod = h.load(S)
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)
        self.root = self.path("root")
        os.makedirs(os.path.join(self.root, "work", "inner"))
        os.makedirs(os.path.join(self.root, "outside", "inner"))
        for p in ("parent-sentinel", "work/before", "work/after", "work/inner/deep", "outside/sentinel", "outside/inner/deep"):
            self.write(os.path.join("root", p), "s")
        os.symlink(os.path.join("..", "outside", "inner"), os.path.join(self.root, "work", "LINK"))
        os.chdir(os.path.join(self.root, "work"))

    def listing(self):
        out = set()
        for d, dirs, files in os.walk(self.root):
            out.update(os.path.relpath(os.path.join(d, n), self.root) for n in dirs + files)
        return out

    def untouched(self, *gone):
        before = self.baseline
        self.assertEqual(before - self.listing(), set(gone))
        self.assertEqual(self.listing() - before, set())


class RemovalWithSentinels(Sandbox):
    def setUp(self):
        super().setUp()
        self.baseline = self.listing()

    def test_a_link_spelled_with_trailing_separators_or_dots_is_the_link_and_only_that(self):
        for spelling in ("LINK/", "LINK//", "LINK/.", "LINK/./", "LINK/.//."):
            with self.subTest(spelling):
                self.mod.remove_tree(spelling)
                self.untouched("work/LINK")
                os.symlink(os.path.join("..", "outside", "inner"), "LINK")

    def test_a_link_spelled_with_trailing_separators_or_dots_survives_a_tree_removal_of_a_secret_home(self):
        """`remove_literally(tree=True)` reports a link nowhere and deletes through none: the link and its target stay."""
        for spelling in ("LINK", "LINK/", "LINK//", "LINK/.", "LINK/./"):
            with self.subTest(spelling):
                self.mod.remove_literally(spelling, tree=True)
                self.untouched()

    def test_a_file_spelling_is_removed_as_a_file_only_when_it_is_not_a_tree_removal(self):
        for spelling in ("before", "before/", "before/."):
            with self.subTest(spelling):
                self.mod.remove_literally(spelling, tree=True)
                self.untouched()
        self.mod.remove_literally("before", tree=False)
        self.untouched("work/before")

    def test_a_link_with_a_parent_component_is_not_normalised_to_the_parent_of_the_link(self):
        """`LINK/..` names the directory above the link's TARGET, as the system resolves it; it is not turned into the
        directory that holds the link. The directory that holds the link, and everything beside it, is untouched."""
        for remove in (lambda s: self.mod.remove_tree(s), lambda s: self.mod.remove_literally(s, tree=True)):
            for spelling in ("LINK/..", "LINK/../"):
                with self.subTest(spelling):
                    remove(spelling)
                    after = self.listing()
                    for kept in ("parent-sentinel", "work", "work/before", "work/after", "work/inner/deep", "work/LINK"):
                        self.assertIn(kept, after)
                    self.assertTrue(os.path.islink("LINK"))
                    self.assertEqual(sorted(os.listdir(os.path.join(self.root, "outside"))), [],
                                     "the directory the path resolves to is emptied: a `..` after a link is followed by the system")
                    shutil.rmtree(os.path.join(self.root, "outside"), ignore_errors=True)
                    os.makedirs(os.path.join(self.root, "outside", "inner"))
                    self.write("root/outside/sentinel", "s")
                    self.write("root/outside/inner/deep", "s")
                    self.baseline = self.listing()

    def test_the_empty_string_removes_nothing(self):
        for remove in (lambda: self.mod.remove_tree(""), lambda: self.mod.remove_literally("", tree=True),
                       lambda: self.mod.remove_literally("", tree=False)):
            remove()
            self.untouched()

    def test_a_missing_name_removes_nothing_and_is_not_an_error(self):
        for spelling in ("missing", "missing/", "missing/.", "LINK/missing", "before/missing"):
            self.mod.remove_tree(spelling)
            self.mod.remove_literally(spelling, tree=True)
            self.mod.remove_literally(spelling, tree=False)
            self.untouched()

    def test_dot_names_the_working_directory_and_empties_it_and_nothing_above_it(self):
        """The text `.` is the directory itself: its contents go, the directory above it and its siblings stay."""
        self.mod.remove_literally(".", tree=True)
        after = self.listing()
        self.assertEqual({p for p in after if p.startswith("work/")}, set(), "the contents of the directory are gone")
        for kept in ("parent-sentinel", "outside/sentinel", "outside/inner/deep"):
            self.assertIn(kept, after)

    def test_dot_and_its_spellings_leave_a_file_removal_alone(self):
        for spelling in (".", "./", "./."):
            self.mod.remove_literally(spelling, tree=False)
            self.untouched()


class RootPaths(h.Case):
    """`/` is never given to a real removal here: the operations are recorded, not performed."""

    def setUp(self):
        super().setUp()
        self.mod = h.load(S)

    @contextlib.contextmanager
    def recorded(self):
        calls = []
        with patched(shutil, rmtree=lambda p, *a, **k: calls.append(("rmtree", p)),
                     ), patched(os, unlink=lambda p, *a, **k: calls.append(("unlink", p))):
            yield calls

    def test_separators_alone_are_the_root_and_a_tree_removal_names_exactly_the_root(self):
        for spelling in ("/", "//", "///", "/.", "/./", "//.//"):
            with self.subTest(spelling), self.recorded() as calls:
                self.mod.remove_literally(spelling, tree=True)
                self.assertEqual(calls, [("rmtree", "/")])

    def test_a_file_removal_never_touches_the_root(self):
        for spelling in ("/", "///", "/."):
            with self.subTest(spelling), self.recorded() as calls:
                self.mod.remove_literally(spelling, tree=False)
                self.assertEqual(calls, [])

    def test_remove_tree_of_the_root_unlinks_nothing(self):
        with self.recorded() as calls:
            self.mod.remove_tree("///")
        self.assertEqual([c for c in calls if c[0] == "unlink"], [])


if __name__ == "__main__":
    unittest.main()
