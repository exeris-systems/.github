"""resolve_release.py: every accepting and refusing path, in-process and as the workflow runs it."""
from __future__ import annotations

import os
import subprocess
import unicodedata
import unittest

import caps_release_helpers as h

SCRIPT = "resolve_release"

BRANCH = dict(target="none", upload="false", version="1.2.3", generated_path="src/main/generated/",
              ref_type="branch", ref_name="feature", ref="refs/heads/feature", default_branch="main",
              repository="o/r", sha="0" * 40, compare_status="")
TAG = dict(BRANCH, ref_type="tag", ref_name="v1.2.3", ref="refs/tags/v1.2.3", version="",
           compare_status="identical")

FIELDS = ["target", "upload", "version", "generated_path", "ref_type", "ref_name", "ref",
          "default_branch", "repository", "sha", "compare_status"]


def argv(base, **over):
    values = dict(base, **over)
    out = []
    for key in FIELDS + ["output"]:
        if key in values and values[key] is not None:
            out += ["--" + key.replace("_", "-"), values[key]]
    return out


def message_class(value):
    """The refusal a value earns: a control character, a non-printing or unassigned one, or a shape that is no tag."""
    for ch in value:
        category = unicodedata.category(ch)
        if category == "Cc":
            return "control character"
        if category in ("Cf", "Zl", "Zp", "Cn"):
            return "non-printing or unassigned character"
    return "release tag"


def c0_c1():
    return [chr(o) for o in list(range(0x20)) + [0x7F] + list(range(0x80, 0xA0))]


class Accepts(h.Case):
    def test_branch_dry_run(self):
        res = self.both(SCRIPT, argv(BRANCH))
        self.accepted(res)
        self.assertNotIn("::warning::", res.out, "a dry run with target none asks for nothing to warn about")
        self.assertEqual(res.out.strip().splitlines()[-1], "resolved: version=1.2.3 target=none publish=false")

    def test_tag_on_default_branch_identical_and_behind(self):
        for status in ("identical", "behind"):
            with self.subTest(status):
                res = self.both(SCRIPT, argv(TAG, compare_status=status))
                self.accepted(res)
                self.assertIn("resolved: version=1.2.3 target=none publish=false", res.out)

    def test_tag_version_input_equal_to_tag_is_accepted(self):
        self.accepted(self.both(SCRIPT, argv(TAG, version="1.2.3")))

    def test_upload_from_default_branch_publishes(self):
        for target in ("github-packages",):
            with self.subTest(target):
                res = self.both(SCRIPT, argv(BRANCH, target=target, upload="true", ref="refs/heads/main"))
                self.accepted(res)
                self.assertIn(f"resolved: version=1.2.3 target={target} publish=true", res.out)

    def test_upload_from_tag_publishes_whatever_the_ref_when_contained(self):
        res = self.both(SCRIPT, argv(TAG, target="github-packages", upload="true"))
        self.accepted(res)
        self.assertIn("publish=true", res.out)

    def test_upload_with_target_none_warns_and_does_not_publish(self):
        out = self.path("out")
        res = self.both(SCRIPT, argv(BRANCH, upload="true", output=out))
        self.accepted(res)
        self.assertIn("::warning::", res.out)
        self.assertIn("publish=false", res.out)
        with open(out) as fh:
            self.assertEqual(fh.read(), "version=1.2.3\npublish=false\n")

    def test_upload_with_target_none_is_never_refused_by_the_ref(self):
        self.accepted(self.both(SCRIPT, argv(BRANCH, upload="true", ref="refs/heads/other")))

    def test_default_branch_with_slash(self):
        self.accepted(self.both(SCRIPT, argv(BRANCH, target="github-packages", upload="true", default_branch="rel/1",
                                             ref="refs/heads/rel/1")))

    def test_generated_path_shapes_the_contract_allows(self):
        for g in ("src/main/generated/", "a b/c", "./x", "a//b", "~", "a\\b", "C:\\x", "x/", ".hidden", "a.b/c",
                  "a..b", "..a", "a..", "...", "a/..b/c", "a/b..", "a:b", "gen:x", "a\\..b"):
            with self.subTest(g):
                self.accepted(self.both(SCRIPT, argv(BRANCH, generated_path=g)))

    def test_generated_path_starting_with_a_dash_is_a_usage_error_not_an_option(self):
        # argparse reads `-x` as an option, so the value never reaches the script; `=` form is a value.
        self.assertEqual(h.run_proc(SCRIPT, argv(BRANCH, generated_path="-x")).rc, 2)
        args = [a for a in argv(BRANCH) if a not in ("--generated-path", "src/main/generated/")]
        self.accepted(self.both(SCRIPT, args + ["--generated-path=-x"]))

    def test_version_shapes_the_contract_allows(self):
        for v in ("0.0.0", "10.20.30", "0.10.0", "9" * 9 + ".0.0", "0." + "9" * 9 + ".0", "0.0." + "9" * 9,
                  "9" * 9 + "." + "9" * 9 + "." + "9" * 9, "1" + "0" * 8 + ".0.0"):
            with self.subTest(v[:12]):
                res = self.both(SCRIPT, argv(BRANCH, version=v))
                self.accepted(res)
                self.assertIn(f"version={v}", res.out)

    def test_comparison_not_asked_when_the_status_is_given(self):
        def never(*_):
            raise AssertionError("compare must not be called when --compare-status is given")
        self.accepted(self.both(SCRIPT, argv(TAG), compare=never))

    def test_comparison_called_with_repository_sha_default_branch(self):
        seen = []

        def compare(repository, sha, default_branch):
            seen.append((repository, sha, default_branch))
            return "behind"
        res = self.both(SCRIPT, argv(TAG, compare_status="", repository="o/r", sha="a" * 40), compare=compare)
        self.accepted(res)
        self.assertEqual(seen, [("o/r", "a" * 40, "main")])

    def test_comparison_not_asked_off_a_tag(self):
        def never(*_):
            raise AssertionError("branch runs do not compare")
        self.accepted(self.both(SCRIPT, argv(BRANCH), compare=never))


class Refuses(h.Case):
    def check(self, base, fragment=None, **over):
        res = self.both(SCRIPT, argv(base, **over))
        self.refused(res, fragment)
        return res

    def test_target_outside_its_set(self):
        for t in ("", "central", "Central", "CENTRAL", "central ", " central", "maven", "github_packages", "none\n", "all",
                  "github-packages ", " github-packages", "github-packages\n", "GitHub-Packages", "github-package", "None", "NONE",
                  "none ", "github-packages,none", "github-packages\u200b"):
            with self.subTest(repr(t)):
                res = self.check(BRANCH, target=t)
                self.assertEqual(len(res.errors()), 1, res)
                self.assertEqual(res.out, "", "nothing is resolved")

    def test_upload_outside_its_set(self):
        for u in ("", "True", "TRUE", "1", "yes", "true ", " false", "no"):
            with self.subTest(repr(u)):
                self.check(BRANCH, upload=u)

    def test_generated_path(self):
        for g in ("", "/abs", "/", "..", "../x", "a/../b", "a/..", "x/..\\y", "a/../../b", "..\\x", "a\\..\\b", "a\\..",
                  "*", "?", "[", "]", "gen/*", "gen/?.java", "gen/[ab]", "a]", ":", ":/", ":(exclude)gen", ":!gen", ":^gen",
                  ":(top)gen", "*.java"):
            with self.subTest(repr(g)):
                self.check(BRANCH, "generated-path", generated_path=g)

    def test_tag_shape(self):
        bad = ["v1.2", "v1.2.3.4", "V1.2.3", "1.2.3", "v1.2.3-rc1", "v1.2.3 ", " v1.2.3", "v1.2.3\n", "vv1.2.3",
               "refs/tags/v1.2.3", "v1.2.3-SNAPSHOT", "v", "", "v1..3", "v1.2.x", "v+1.2.3", "v-1.2.3",
               "v\uff11.\uff12.\uff13", "v\u0661.\u0662.\u0663", "v1.2.3\u2028", "v1.2.3\u202e"]
        for t in bad:
            with self.subTest(repr(t)):
                self.check(TAG, message_class(t), ref_name=t)

    def test_tag_and_version_must_agree(self):
        for v in ("1.2.4", "v1.2.3", "1.2.3 ", "1.2", "0.0.0"):
            with self.subTest(v):
                self.check(TAG, "disagree", version=v)

    def test_tag_compare_status_other_than_identical_or_behind(self):
        for s in ("ahead", "diverged", "IDENTICAL", "Behind", "identical ", "bogus", "404", "not found"):
            with self.subTest(s):
                self.check(TAG, "NOT on", compare_status=s)

    def test_tag_without_default_branch(self):
        self.check(TAG, "default branch", default_branch="")

    def test_tag_without_a_status_and_nothing_to_ask_with(self):
        self.check(TAG, "--repository", compare_status="", repository="")
        self.check(TAG, "--repository", compare_status="", sha="")

    def test_failed_comparison_is_a_refusal(self):
        for exc in (subprocess.CalledProcessError(1, "gh"), FileNotFoundError("gh"), PermissionError("gh")):
            with self.subTest(type(exc).__name__):
                res = self.both(SCRIPT, argv(TAG, compare_status=""), compare=lambda *_a, e=exc: (_ for _ in ()).throw(e))
                self.refused(res, "comparison")

    def test_comparison_answering_ahead_or_with_a_control_character_is_refused(self):
        self.refused(self.both(SCRIPT, argv(TAG, compare_status=""), compare=lambda *_: "ahead"), "NOT on")
        self.refused(self.both(SCRIPT, argv(TAG, compare_status=""), compare=lambda *_: "identical\n"),
                     "control character")
        self.refused(self.both(SCRIPT, argv(TAG, compare_status=""), compare=lambda *_: ""), "NOT on")

    def test_real_comparison_without_gh_is_a_refusal_in_a_subprocess(self):
        env = h.clean_env(PATH=self.tmp)       # no `gh` reachable
        res = h.run_proc(SCRIPT, argv(TAG, compare_status=""), env=env)
        self.refused(res, "comparison")

    def test_branch_version(self):
        bad = ["", "v1.2.3", "1.2", "1.2.3 ", " 1.2.3", "+1.2.3", "-1.2.3", "1.2.3-SNAPSHOT", "1.2.3.4", "1.2.3\n",
               "a.b.c", "\uff11.\uff12.\uff13", "\u0661.\u0662.\u0663", "1.2.3\u2028", "1.2.3\u2029", "1.2.3\u0085",
               "1.2.3\u202e", "1\u200b.2.3", "1. 2.3", "1.2.3-rc.1", "1,2,3", "1_0.2.3", "\u00b2.0.0", "1.2.3\x00"]
        for v in bad:
            with self.subTest(repr(v)):
                res = h.run_main(SCRIPT, argv(BRANCH, version=v))
                self.refused(res)
        # the subprocess cannot be handed NUL, so it is checked on everything else
        for v in bad[:-1]:
            with self.subTest("proc " + repr(v)):
                self.refused(h.run_proc(SCRIPT, argv(BRANCH, version=v)))

    def test_upload_off_a_tag_from_anywhere_but_the_default_branch(self):
        refs = ["refs/heads/feature", "refs/heads/main-evil", "refs/heads/main/../x", "refs/heads/main/",
                "refs/heads/Main", "refs/heads/main ", "refs/tags/v1.2.3", "refs/pull/1/merge", "main", "", "heads/main",
                "refs/heads/mainx", "refs/heads//main"]
        for target in ("github-packages",):
            for r in refs:
                with self.subTest(target + " " + repr(r)):
                    self.check(BRANCH, "allowed on main only", target=target, upload="true", ref=r)

    def test_upload_off_a_tag_without_a_known_default_branch(self):
        self.check(BRANCH, "unknown default branch", target="github-packages", upload="true", ref="refs/heads/", default_branch="")

    def test_a_ref_type_that_only_looks_like_tag_is_a_branch_that_needs_its_version(self):
        for rt in ("Tag", "TAG", "tAg"):
            with self.subTest(rt):
                self.check(TAG, "A dry run needs one", ref_type=rt, version="")

    def test_ref_type_other_than_tag_is_a_branch(self):
        for rt in ("Tag", "TAG", "tag ", "", "release"):
            with self.subTest(repr(rt)):
                self.check(BRANCH, "MAJOR.MINOR.PATCH", ref_type=rt, version="v1.2.3")

    def test_version_numbers_with_a_leading_zero_or_more_than_nine_digits_are_refused(self):
        bad = ["01.02.03", "1.02.3", "1.2.03", "00.0.0", "0.00.0", "0.0.00", "9" * 400 + ".0.0",
               "1" + "0" * 9 + ".0.0", "0." + "1" + "0" * 9 + ".0", "0.0." + "1" + "0" * 9, "0" * 10 + ".0.0", "000.0.0"]
        for v in bad:
            with self.subTest(v[:14]):
                res = self.check(BRANCH, "MAJOR.MINOR.PATCH", version=v)
                self.assertNotIn("resolved", res.out)

    def test_a_tag_with_a_leading_zero_or_ten_digits_is_no_release_tag(self):
        for t in ("v01.2.3", "v1.02.3", "v1.2.03", "v" + "1" + "0" * 9 + ".0.0", "v0.0." + "9" * 10, "v" + "9" * 400 + ".0.0"):
            with self.subTest(t[:16]):
                self.check(TAG, "release tag", ref_name=t)

    def test_the_boundaries_of_a_tag(self):
        self.accepted(self.both(SCRIPT, argv(TAG, ref_name="v0.0.0")))
        self.accepted(self.both(SCRIPT, argv(TAG, ref_name="v" + ".".join(["9" * 9] * 3))))
        self.check(TAG, "release tag", ref_name="v" + "1" + "0" * 9 + ".0.0")

    def test_dot_dot_is_a_segment_not_a_substring(self):
        for g in ("a/..", "../a", "a/../b", "a\\..\\b", "a/..\\b"):
            with self.subTest(g):
                self.check(BRANCH, "generated-path", generated_path=g)
        for g in ("a..b", "..a", "a..", "a/..b", "a/b..c/d"):
            with self.subTest(g):
                self.accepted(self.both(SCRIPT, argv(BRANCH, generated_path=g)))

    def test_a_comparison_that_raises_is_a_refusal_naming_the_comparison(self):
        for exc in (RuntimeError("boom"), ValueError("x"), TimeoutError("slow"), OSError(5, "io"), Exception("plain")):
            with self.subTest(type(exc).__name__):
                out = self.path("out-" + type(exc).__name__)
                res = self.both(SCRIPT, argv(TAG, compare_status="", output=out), compare=lambda *_a, e=exc: (_ for _ in ()).throw(e))
                self.refused(res, "comparison")
                self.assertEqual(len(res.errors()), 1)
                self.assertFalse(os.path.exists(out))

    def test_an_interrupt_during_the_comparison_is_not_turned_into_an_answer(self):
        """KeyboardInterrupt is not an Exception: it leaves main() and is neither a refusal nor a pass."""
        out = self.path("out")

        def interrupted(*_a):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            h.run_main(SCRIPT, argv(TAG, compare_status="", output=out), compare=interrupted)
        self.assertFalse(os.path.exists(out), "an interrupted run writes nothing")

    def test_a_comparison_returning_something_that_is_not_identical_or_behind_is_refused(self):
        for value, fragment in (("ahead", "NOT on"), ("diverged", "NOT on"), ("", "NOT on"), ("identical ", "NOT on"),
                                (" behind", "NOT on"), ("identical\n", "control character"), ("behind\r", "control character"),
                                ("identical\u200b", "non-printing"), ("Identical", "NOT on"), ("identical\x00", "control character")):
            with self.subTest(repr(value)):
                out = self.path("out")
                res = self.both(SCRIPT, argv(TAG, compare_status="", output=out), compare=lambda *_a, v=value: v)
                self.refused(res, fragment)
                self.assertEqual(len(res.errors()), 1)
                self.assertFalse(os.path.exists(out))

    def test_a_comparison_returning_a_non_string_ends_in_one_error_line(self):
        for value in (None, 0, b"identical", ["identical"], True):
            with self.subTest(repr(value)):
                res = self.both(SCRIPT, argv(TAG, compare_status=""), compare=lambda *_a, v=value: v)
                self.refused(res)
                self.assertEqual(len(res.errors()), 1)
                self.assertNotIn("resolved", res.out)

    def test_an_unwritable_output_ends_in_one_error_line_and_exit_one(self):
        for bad in (self.path("absent-dir", "out"), self.tmp):
            for run in (h.run_main, h.run_proc):
                with self.subTest(bad, run=run.__name__):
                    res = run(SCRIPT, argv(BRANCH, output=bad))
                    self.refused(res, "failed unexpectedly")
                    self.assertEqual(len(res.errors()), 1)
                    self.assertNotIn("resolved:", res.out)



class ControlCharacters(h.Case):
    """Any C0, DEL or C1 character, in any field, in any position, is refused before a pattern is tried."""

    def test_every_control_character_in_every_field_in_process(self):
        for field in FIELDS:
            for ch in c0_c1():
                for shape in ("{c}", "x{c}", "{c}x", "x{c}x"):
                    value = shape.format(c=ch)
                    with self.subTest(field=field, char=hex(ord(ch)), shape=shape):
                        base = TAG if field in ("ref_name", "compare_status") else BRANCH
                        res = h.run_main(SCRIPT, argv(base, **{field: value}))
                        self.refused(res, "control character")

    def test_every_control_character_as_a_subprocess_argument(self):
        for field in ("version", "ref_name", "generated_path"):
            for ch in c0_c1():
                if ch == "\x00" or (field == "generated_path" and ord(ch) not in (0x01, 0x0A, 0x1B, 0x7F, 0x85, 0x9F)):
                    continue
                with self.subTest(field=field, char=hex(ord(ch))):
                    base = TAG if field == "ref_name" else BRANCH
                    res = h.run_proc(SCRIPT, argv(base, **{field: f"x{ch}x"}))
                    self.refused(res, "control character")

    def test_nul_cannot_reach_a_subprocess_argument(self):
        with self.assertRaises(ValueError):
            h.run_proc(SCRIPT, argv(BRANCH, version="1.2.3\x00"))

    def test_undecodable_byte_is_refused_by_the_subprocess_and_in_process(self):
        for field in ("version", "generated_path", "ref", "repository"):
            with self.subTest(field):
                args = argv(BRANCH, **{field: "x\udcffx"})
                self.refused(h.run_main(SCRIPT, args), "undecodable")
                raw = [a.encode("utf-8", "surrogateescape") for a in args]
                proc = subprocess.run([h.sys.executable.encode(), b"-I", b"-B", h.script_path(SCRIPT).encode(), *raw],
                                      capture_output=True, env=h.clean_env())
                self.assertEqual(proc.returncode, 1, proc)
                self.assertIn(b"::error::", proc.stderr)
                self.assertIn(b"undecodable", proc.stderr)

    def test_two_key_value_lines_cannot_be_smuggled_through_the_output_file(self):
        out = self.path("out")
        for v in ("1.2.3\npublish=true", "1.2.3\r\npublish=true", "1.2.3\rpublish=true", "1.2.3\x0bpublish=true",
                  "1.2.3\x0cpublish=true", "1.2.3\x85publish=true"):
            with self.subTest(repr(v)):
                self.refused(self.both(SCRIPT, argv(BRANCH, version=v, output=out)))
        self.assertFalse(os.path.exists(out), "a refusal must not touch the output file")

    def test_unicode_separators_and_bidi_cannot_become_a_version(self):
        for ch in ("\u2028", "\u2029", "\u0085", "\u202e", "\u202d", "\u2066", "\u200f", "\ufeff"):
            for v in (f"1.2.3{ch}", f"{ch}1.2.3", f"1.2{ch}.3"):
                with self.subTest(repr(v)):
                    self.refused(self.both(SCRIPT, argv(BRANCH, version=v)))
                    self.refused(self.both(SCRIPT, argv(TAG, ref_name="v" + v)))


NON_PRINTING = {
    "zero width space": "\u200b", "zero width joiner": "\u200d", "word joiner": "\u2060", "byte order mark": "\ufeff",
    "right-to-left override": "\u202e", "left-to-right isolate": "\u2066", "soft hyphen": "\u00ad",
    "line separator": "\u2028", "paragraph separator": "\u2029", "unassigned": "\u0378", "noncharacter": "\U0010ffff",
}


class NonPrinting(h.Case):
    """Cf, Zl, Zp, Cn and an undecodable byte are refused in every input, --output included, before any pattern."""

    ALL = FIELDS + ["output"]

    def base_for(self, field):
        return TAG if field in ("ref_name", "compare_status") else BRANCH

    def test_every_category_in_every_input_names_the_input(self):
        for field in self.ALL:
            for label, ch in NON_PRINTING.items():
                for shape in ("{c}", "x{c}", "x{c}x"):
                    value = shape.format(c=ch)
                    with self.subTest(field=field, char=label, shape=shape):
                        out = self.path("o") if field != "output" else value
                        extra = {} if field == "output" else {"output": out}
                        res = h.run_main(SCRIPT, argv(self.base_for(field), **{field: value}, **extra))
                        self.refused(res, field.replace("_", "-") + " holds a non-printing or unassigned character")
                        self.assertEqual(len(res.errors()), 1)
                        self.assertNotIn("resolved", res.out)
                        self.assertFalse(os.path.exists(out), "a refusal writes no output")

    def test_a_lone_surrogate_in_every_input(self):
        for field in self.ALL:
            for value in ("x\udc80x", "x\ud800x", "x\udbffx", "x\udfffx", "\ud800"):
                with self.subTest(field=field, value=value):
                    res = h.run_main(SCRIPT, argv(self.base_for(field), **{field: value}))
                    self.refused(res, field.replace("_", "-") + " holds an undecodable byte")
                    self.assertEqual(len(res.errors()), 1)

    def test_the_subprocess_refuses_the_same_characters_in_every_input(self):
        for field in self.ALL:
            for ch in ("\u200b", "\u202e", "\u2028", "\u0378"):
                with self.subTest(field=field, char=hex(ord(ch))):
                    value = f"x{ch}x"
                    res = h.run_proc(SCRIPT, argv(self.base_for(field), **{field: value}))
                    self.refused(res, field.replace("_", "-") + " holds a non-printing or unassigned character")
                    self.assertEqual(len(res.errors()), 1)
                    self.assertEqual(res.rc, 1)

    def test_a_character_that_only_looks_empty_in_the_tag_is_refused_before_the_shape(self):
        for ch in ("\u200b", "\u2028", "\u202e", "\u0378"):
            with self.subTest(hex(ord(ch))):
                self.refused(self.both(SCRIPT, argv(TAG, ref_name="v1.2.3" + ch)), "non-printing or unassigned character")

    def test_printable_non_ascii_is_not_a_control_character(self):
        """The class is Cc, Cf, Zl, Zp, Cn: a printable letter or a space-like Zs is judged by the pattern."""
        for ch in ("\u00e9", "\u00a0", "\u3000", "\u0661"):
            with self.subTest(hex(ord(ch))):
                res = h.run_main(SCRIPT, argv(BRANCH, repository="o/r" + ch))
                self.accepted(res)


class Targets(h.Case):
    """Two targets exist: `none` uploads nothing and `github-packages` uploads; `publish` needs both an upload and a target."""

    def test_the_two_targets_resolve_and_name_themselves(self):
        for target in ("none", "github-packages"):
            with self.subTest(target):
                res = self.both(SCRIPT, argv(BRANCH, target=target))
                self.accepted(res)
                self.assertIn(f"target={target} publish=false", res.out)

    def test_a_refused_target_is_exactly_one_error_line_whose_text_names_both_targets(self):
        for t in ("central", "Central", "github-packages ", ""):
            for run in (h.run_main, h.run_proc):
                with self.subTest(repr(t), run=run.__name__):
                    res = run(SCRIPT, argv(BRANCH, target=t))
                    self.assertEqual(res.rc, 1, res)
                    self.assertEqual(len(res.errors()), 1, res)
                    self.assertEqual(len(res.err.splitlines()), 1, res)
                    self.assertIn("target must be 'none' or 'github-packages'", res.err)

    def test_publish_is_true_only_for_an_upload_to_github_packages(self):
        matrix = {("none", "false"): "false", ("none", "true"): "false", ("github-packages", "false"): "false",
                  ("github-packages", "true"): "true"}
        for (target, upload), want in matrix.items():
            with self.subTest(target=target, upload=upload):
                out = self.path(f"out-{target}-{upload}")
                res = self.both(SCRIPT, argv(BRANCH, target=target, upload=upload, ref="refs/heads/main", output=out))
                self.accepted(res)
                with open(out) as fh:
                    self.assertEqual(fh.read(), f"version=1.2.3\npublish={want}\n")
                self.assertIn(f"publish={want}", res.out)

    def test_an_upload_with_target_none_is_one_warning_and_no_publish(self):
        for ref in ("refs/heads/main", "refs/heads/feature"):
            for run in (h.run_main, h.run_proc):
                with self.subTest(ref, run=run.__name__):
                    res = run(SCRIPT, argv(BRANCH, upload="true", ref=ref))
                    self.assertEqual(res.rc, 0, res)
                    self.assertEqual(res.errors(), [])
                    warnings = [ln for ln in res.out.splitlines() if ln.startswith("::warning::")]
                    self.assertEqual(len(warnings), 1, res)
                    self.assertIn("target 'none'", warnings[0])
                    self.assertIn("publish=false", res.out)

    def test_a_dispatch_uploads_from_the_default_branch_only(self):
        self.accepted(self.both(SCRIPT, argv(BRANCH, target="github-packages", upload="true", ref="refs/heads/main")))
        for ref in ("refs/heads/feature", "refs/pull/1/merge", "refs/tags/v1.2.3", "refs/heads/main-evil", ""):
            with self.subTest(repr(ref)):
                res = self.both(SCRIPT, argv(BRANCH, target="github-packages", upload="true", ref=ref))
                self.refused(res, "allowed on main only")
                self.assertEqual(len(res.errors()), 1)
        res = self.both(SCRIPT, argv(BRANCH, target="github-packages", upload="true", ref="refs/heads/main",
                                     default_branch="trunk"))
        self.refused(res, "allowed on trunk only")

    def test_a_tag_upload_needs_no_particular_ref_but_a_contained_commit(self):
        self.accepted(self.both(SCRIPT, argv(TAG, target="github-packages", upload="true")))
        self.refused(self.both(SCRIPT, argv(TAG, target="github-packages", upload="true", compare_status="ahead")), "NOT on main")
        self.refused(self.both(SCRIPT, argv(TAG, target="github-packages", upload="true", compare_status="diverged")), "NOT on main")

    def test_a_refusal_resolves_nothing_whatever_the_target(self):
        out = self.path("out")
        for target in ("none", "github-packages"):
            for bad in (dict(version="1.2"), dict(generated_path="../x")):
                with self.subTest(target=target, bad=bad):
                    self.refused(self.both(SCRIPT, argv(BRANCH, target=target, output=out, **bad)))
        self.assertFalse(os.path.exists(out))


class Output(h.Case):
    def test_success_appends_two_lines_and_keeps_existing_content(self):
        out = self.write("out", "keep=1\n")
        self.accepted(self.both(SCRIPT, argv(BRANCH, output=out)))
        with open(out) as fh:
            self.assertEqual(fh.read(), "keep=1\nversion=1.2.3\npublish=false\n")
        self.accepted(self.both(SCRIPT, argv(BRANCH, target="github-packages", upload="true", ref="refs/heads/main", output=out)))
        with open(out) as fh:
            self.assertEqual(fh.read().splitlines()[-2:], ["version=1.2.3", "publish=true"])

    def test_no_output_flag_writes_nothing(self):
        self.accepted(self.both(SCRIPT, argv(BRANCH)))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_every_refusal_leaves_the_output_file_untouched(self):
        out = self.write("out", "keep=1\n")
        cases = [argv(BRANCH, target="x"), argv(BRANCH, upload="x"), argv(BRANCH, generated_path="../x"),
                 argv(BRANCH, version="1.2"), argv(TAG, ref_name="v1"), argv(TAG, version="9.9.9"),
                 argv(TAG, compare_status="ahead"),
                 argv(BRANCH, target="github-packages", upload="true", ref="refs/heads/other"),
                 argv(BRANCH, version="1.2.3\n")]
        for args in cases:
            with self.subTest(args):
                self.refused(self.both(SCRIPT, args + ["--output", out]))
        with open(out) as fh:
            self.assertEqual(fh.read(), "keep=1\n")

    def test_output_is_written_for_a_tag_with_the_tag_version(self):
        out = self.path("out")
        self.accepted(self.both(SCRIPT, argv(TAG, ref_name="v10.0.7", output=out)))
        with open(out) as fh:
            self.assertEqual(fh.read(), "version=10.0.7\npublish=false\n")


class RealComparison(h.Case):
    """The default comparison asks `gh api`; a stand-in `gh` on PATH shows what is asked and what is made of the answer."""

    def setUp(self):
        super().setUp()
        self.bin = self.path("bin")
        self.args_log = self.path("gh-args")

    def gh(self, stdout="", rc=0):
        self.write("bin/gh", f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{self.args_log}'\nprintf '%s' '{stdout}'\nexit {rc}\n")
        os.chmod(os.path.join(self.bin, "gh"), 0o755)
        return h.clean_env(PATH=self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin"))

    def run_tag(self, env, **over):
        return h.run_proc(SCRIPT, argv(TAG, compare_status="", sha="a" * 40, **over), env=env)

    def test_the_question_asked_is_the_commit_against_the_default_branch(self):
        res = self.run_tag(self.gh("behind"))
        self.accepted(res)
        with open(self.args_log) as fh:
            self.assertEqual(fh.read().strip(), f"api repos/o/r/compare/main...{'a' * 40} --jq .status")

    def test_the_answer_is_trimmed_and_judged(self):
        self.accepted(self.run_tag(self.gh("identical")))
        for answer in ("ahead", "diverged", "", "IDENTICAL"):
            with self.subTest(answer):
                self.refused(self.run_tag(self.gh(answer)), "NOT on")

    def test_a_gh_that_fails_is_a_refused_comparison_whatever_it_printed(self):
        for out in ("", "behind", "identical"):
            with self.subTest(out):
                self.refused(self.run_tag(self.gh(out, rc=1)), "comparison")

    def test_gh_is_not_run_off_a_tag_or_when_the_status_is_given(self):
        env = self.gh("behind")
        self.accepted(h.run_proc(SCRIPT, argv(BRANCH), env=env))
        self.accepted(h.run_proc(SCRIPT, argv(TAG), env=env))
        self.assertFalse(os.path.exists(self.args_log))


class JavaInputs(h.Case):
    """`--java-distribution` and `--java-version`: validated when given, written to the output exactly as given, absent when not given."""

    DISTRIBUTIONS_OK = ["temurin", "graalvm"]
    DISTRIBUTIONS_BAD = ["Temurin", "TEMURIN", "GraalVM", "zulu", "jdkfile", "temurin ", " temurin", "$(x)", "temurin;x", "temurin\n", "", "oracle", "temurin,graalvm",
                         "temurın"]
    VERSIONS_OK = ["25", "21.x", "25.0.2", "8", "17", "99", "25.0", "11.0.21", "17.999.999", "21.0", "9.x"]
    VERSIONS_BAD = ["0", "025", "25.x.1", "1000", "25.0.2.1", "25.", " 25", "25 ", "\u0662\u0665", "", "x", "21.X", "25.00", "25.0.02", "25.1000", "25.0.1000",
                    "25.0.x", "25ax", "25-x", "25_x", "25x", "25 x", "25/x", "25-ea", "25+36", "v25", "-25", "$(x)", "25\n", "100", ".x", "25.x ", "25..2", "08", "25.０"]

    def test_the_two_distributions_are_accepted_and_written(self):
        for value in self.DISTRIBUTIONS_OK:
            with self.subTest(value):
                out = self.path(f"out-{value}")
                self.accepted(self.both(SCRIPT, argv(BRANCH, output=out) + ["--java-distribution", value]))
                with open(out) as fh:
                    self.assertEqual(fh.read(), f"version=1.2.3\npublish=false\njava-distribution={value}\n")

    def test_every_other_distribution_is_one_refusal_that_writes_nothing(self):
        for value in self.DISTRIBUTIONS_BAD:
            with self.subTest(repr(value)):
                out = self.write("out", "keep=1\n")
                res = self.both(SCRIPT, argv(BRANCH, output=out) + ["--java-distribution", value])
                self.refused(res)
                self.assertEqual(len(res.errors()), 1, res)
                self.assertEqual(res.out, "")
                with open(out) as fh:
                    self.assertEqual(fh.read(), "keep=1\n")

    def test_the_refusal_names_the_input_and_the_allowed_values(self):
        res = self.both(SCRIPT, argv(BRANCH) + ["--java-distribution", "zulu"])
        self.refused(res, "java-distribution must be one of temurin, graalvm, got 'zulu'")

    def test_the_versions_the_form_allows_are_accepted_and_written(self):
        for value in self.VERSIONS_OK:
            with self.subTest(value):
                out = self.path(f"out-{value}")
                self.accepted(self.both(SCRIPT, argv(BRANCH, output=out) + ["--java-version", value]))
                with open(out) as fh:
                    self.assertEqual(fh.read(), f"version=1.2.3\npublish=false\njava-version={value}\n")

    def test_every_other_version_is_one_refusal_that_writes_nothing(self):
        for value in self.VERSIONS_BAD:
            with self.subTest(repr(value)):
                out = self.write("out", "keep=1\n")
                res = self.both(SCRIPT, argv(BRANCH, output=out) + ["--java-version", value])
                self.refused(res)
                self.assertEqual(len(res.errors()), 1, res)
                self.assertEqual(res.out, "")
                with open(out) as fh:
                    self.assertEqual(fh.read(), "keep=1\n")

    def test_the_refusal_names_the_input_and_the_form(self):
        self.refused(self.both(SCRIPT, argv(BRANCH) + ["--java-version", "0"]), "java-version must be NN, NN.x or NN.N.N (for example 25, 21.x or 25.0.2), got '0'")

    def test_both_are_written_after_the_version_and_the_publish_line_in_a_fixed_order(self):
        out = self.path("out")
        self.accepted(self.both(SCRIPT, argv(BRANCH, output=out) + ["--java-version", "21.x", "--java-distribution", "graalvm"]))
        with open(out) as fh:
            self.assertEqual(fh.read(), "version=1.2.3\npublish=false\njava-distribution=graalvm\njava-version=21.x\n")

    def test_a_flag_that_is_not_passed_is_neither_validated_nor_written(self):
        """The resolver does not make the JDK a required input: the workflow passes both flags (see `test_workflow`), and without them the
        output holds no `java-*` line, so a step that reads one gets the empty string."""
        out = self.path("out")
        self.accepted(self.both(SCRIPT, argv(BRANCH, output=out)))
        with open(out) as fh:
            self.assertEqual(fh.read(), "version=1.2.3\npublish=false\n")
        for only, line in (("--java-distribution", "java-distribution=temurin"), ("--java-version", "java-version=25")):
            with self.subTest(only):
                out = self.path(f"out-{only}")
                self.accepted(self.both(SCRIPT, argv(BRANCH, output=out) + [only, line.split("=")[1]]))
                with open(out) as fh:
                    lines = fh.read().splitlines()
                self.assertEqual([ln for ln in lines if ln.startswith("java-")], [line])

    def test_an_empty_value_is_given_and_therefore_refused_unlike_an_absent_flag(self):
        self.refused(self.both(SCRIPT, argv(BRANCH) + ["--java-version", ""]))
        self.refused(self.both(SCRIPT, argv(BRANCH) + ["--java-distribution", ""]))

    def test_a_control_character_in_either_is_refused_as_one(self):
        for flag in ("--java-distribution", "--java-version"):
            for c in c0_c1():
                with self.subTest(flag=flag, char=repr(c)):
                    res = h.run_main(SCRIPT, argv(BRANCH) + [flag, "temurin" + c if "dist" in flag else "25" + c])
                    self.refused(res, f"::error::{flag[2:]} holds a control character")
                    self.assertEqual(len(res.errors()), 1, res)

    def test_a_refusal_elsewhere_still_writes_no_java_line(self):
        out = self.write("out", "")
        self.refused(self.both(SCRIPT, argv(BRANCH, version="1.2", output=out) + ["--java-distribution", "temurin", "--java-version", "25"]))
        with open(out) as fh:
            self.assertEqual(fh.read(), "")


class Usage(h.Case):
    def test_unknown_flag_is_a_usage_error(self):
        self.assertEqual(h.run_proc(SCRIPT, ["--nope", "x"]).rc, 2)
        self.assertEqual(h.run_main(SCRIPT, ["--nope", "x"]).rc, 2)

    def test_no_arguments_is_a_refusal_not_a_pass(self):
        self.refused(self.both(SCRIPT, []))


if __name__ == "__main__":
    unittest.main()
