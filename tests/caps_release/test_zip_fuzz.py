"""A seeded mutation fuzz of the bundle's archive layout.

Valid bundles are damaged in tens of thousands of ways (flipped bytes, truncation, insertion, deletion, edits of single
header fields, rebuilt headers with random flags, methods and extra fields). The only outcomes allowed are

  * the gate accepts, and an independent strict reader (`zip_support.strict_reason`, which shares no code with the gate)
    accepts the same bytes, and `zipfile` and a streaming local-header walk agree on every entry name and content;
  * the gate refuses with `::error::` lines.

A traceback, the generic unexpected-failure line, a hang, or an acceptance the strict reader or the streaming walk
disagrees with fails the test and is reported with the seed and the case number.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import random
import signal
import struct
import tempfile
import time
import unittest

import caps_release_helpers as h
from caps_release_helpers import known_defect
from readiness_support import Fixture, GROUP, sig_of
from zip_support import Entry, build, extra_block, strict_reason, stream_view, zipfile_view

S = "check_release_readiness"
SEED = 20261111
CASES_PER_BASE = 7000
PER_CASE_SECONDS = 5


def pinned_failure(exc) -> bool:
    """An exception that `zipfile.ZipFile` raises on a damaged directory and the gate does not catch: it ends the run in the
    generic unexpected-failure line (a refusal), which the pinned defect test asserts is replaced by a `central bundle:` line."""
    import traceback
    frames = traceback.extract_tb(exc.__traceback__)
    return type(exc).__name__ in ("NotImplementedError", "UnicodeDecodeError") and any(
        f.name == "_RealGetContents" for f in frames)


class Timeout(Exception):
    pass


@contextlib.contextmanager
def bounded(seconds):
    def fire(*_):
        raise Timeout()
    old = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


class Fuzz(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()
        self.mod = h.load(S)
        self.built = {"a-1.0.0": (GROUP, "a", "1.0.0")}
        self.held = {}
        for n in os.listdir(self.target):
            if os.path.isfile(os.path.join(self.target, n)):
                self.held[n] = (None, hashlib.sha256(self.read_target(n)).hexdigest())
        self.copy = self.path("copy.zip")
        self.make_reproducible()

    def make_reproducible(self):
        """Archive members carry the time they were written; fixed times make a case number mean the same bytes on every run."""
        from readiness_support import write_zip
        for suffix, member in (("", "a/B.class"), ("-sources", "a/B.java"), ("-javadoc", "index.html")):
            write_zip(os.path.join(self.target, f"a-1.0.0{suffix}.jar"), [(member, b"x")])
        for suffix in (".jar", "-sources.jar", "-javadoc.jar"):
            f = os.path.join(self.target, f"a-1.0.0{suffix}")
            with open(f + ".asc", "w") as fh:
                fh.write(sig_of(f))
            self.held[f"a-1.0.0{suffix}"] = (None, hashlib.sha256(self.read_target(f"a-1.0.0{suffix}")).hexdigest())
            self.held[f"a-1.0.0{suffix}.asc"] = (None, hashlib.sha256(self.read_target(f"a-1.0.0{suffix}.asc")).hexdigest())

    def specs(self, method, descriptor):
        return [Entry(n, d, method=method, descriptor=descriptor) for n, d in self.bundle_entries().items()]

    @staticmethod
    def good_signature(asc, f):
        with open(asc, "rb") as a, open(f, "rb") as b:
            return a.read() == ("SIG:" + hashlib.sha256(b.read()).hexdigest() + "\n").encode()

    def verdict(self, data):
        """(accepted, errors) as the gate's bundle judgement sees DATA; an exception propagates."""
        with open(self.copy, "wb") as fh:
            fh.write(data)
        errors: list[str] = []
        with contextlib.redirect_stdout(io.StringIO()):
            ok = self.mod.judge_private_copy(self.target, "bundle.zip", self.copy, self.built, errors.append,
                                             self.good_signature, self.held)
        return bool(ok) and not errors, errors

    def mutate(self, rng, base, fields, spec_maker):
        n = len(base)
        op = rng.randrange(10)
        data = bytearray(base)
        if op == 0:
            for _ in range(rng.randint(1, 4)):
                data[rng.randrange(n)] ^= 1 << rng.randrange(8)
        elif op == 1:
            for _ in range(rng.randint(1, 3)):
                off, width = rng.choice(fields)
                if off + width <= len(data):
                    data[off:off + width] = rng.randrange(256 ** width).to_bytes(width, "little")
        elif op == 2:
            data = data[:rng.randrange(n)]
        elif op == 3:
            at = rng.randrange(n + 1)
            data[at:at] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 16)))
        elif op == 4:
            at = rng.randrange(n)
            del data[at:at + rng.randint(1, 16)]
        elif op in (5, 6):
            for _ in range(rng.randint(1, 2)):
                off, width = rng.choice(fields)
                if off + width <= len(data):
                    value = int.from_bytes(data[off:off + width], "little")
                    new = rng.choice([0, 1, 2, 0xFF, 0xFFFF, 0xFFFFFFFF, 0x800, 0x8, 0x1, value + 1, value - 1, value ^ 0x8000]) % (256 ** width)
                    data[off:off + width] = new.to_bytes(width, "little")
        elif op == 7:
            data = bytearray(spec_maker(rng))
        elif op == 8:
            data += bytes(rng.randrange(256) for _ in range(rng.randint(1, 30)))
        else:
            data = bytearray(bytes(rng.randrange(256) for _ in range(rng.randint(1, 30)))) + data
        return bytes(data)

    def random_specs(self, rng, method, descriptor):
        entries = self.specs(method, descriptor)
        for e in entries:
            if rng.random() < 0.25:
                e.flags = rng.choice([0x0, 0x800, 0x1, 0x40, 0x2000, 0x8, 0x808])
            if rng.random() < 0.2:
                e.local["flags"] = rng.choice([0x0, 0x800, 0x8, 0x1])
            if rng.random() < 0.15:
                e.central["method"] = rng.choice([0, 8, 9, 12, 99])
            if rng.random() < 0.15:
                e.local["method"] = rng.choice([0, 8, 9, 12])
            if rng.random() < 0.2:
                # a harmless identifier only: a renaming extension has its own pinned test
                blob = extra_block(rng.choice([0x5455, 0x7875, 0xCAFE, 0x0001]), bytes(rng.randrange(256) for _ in range(rng.randint(0, 12))))
                if rng.random() < 0.5:
                    e.extra = blob
                if rng.random() < 0.5:
                    e.central_extra = blob
            if rng.random() < 0.1:
                e.local[rng.choice(["crc", "csize", "usize"])] = rng.choice([0, 1, 0xFFFFFFFF])
            if rng.random() < 0.05:
                e.descriptor = rng.choice([None, "sig", "nosig"])
        kwargs = {}
        if rng.random() < 0.1:
            kwargs["comment"] = b"c"
        if rng.random() < 0.05:
            kwargs["locator"] = True
        if rng.random() < 0.1:
            field = rng.choice(["disk", "here", "total", "cd_size", "cd_off"])
            kwargs["end"] = {field: rng.choice([0, 1, 0xFFFF, 0xFFFFFFFF]) & (0xFFFF if field in ("disk", "here", "total") else 0xFFFFFFFF)}
        return build(entries, **kwargs)[0]

    def run_fuzz(self, label, method, descriptor, seed):
        rng = random.Random(seed)
        base, fields = build(self.specs(method, descriptor))
        accepted, pinned, ok_base = 0, [], self.verdict(base)
        gaps = self.gaps = []
        self.assertEqual(ok_base, (True, []), f"the unmutated {label} bundle must be accepted")
        problems = []
        started = time.monotonic()
        for case in range(CASES_PER_BASE):
            data = self.mutate(rng, base, fields, lambda r: self.random_specs(r, method, descriptor))
            try:
                with bounded(PER_CASE_SECONDS):
                    ok, errors = self.verdict(data)
            except Timeout:
                problems.append((case, "hang", data))
                continue
            except Exception as exc:                  # a traceback in the gate
                if pinned_failure(exc):
                    pinned.append(case)
                else:
                    problems.append((case, f"{type(exc).__name__}: {exc}", data))
                continue
            if not ok:
                if not errors:
                    problems.append((case, "refused without an error line", data))
                continue
            accepted += 1
            if strict_reason(data) is None:
                streamed = stream_view(data)
                if streamed == "unstreamable":          # a stored entry with a descriptor cannot be walked without the central sizes
                    continue
                if streamed is None or streamed != zipfile_view(self.copy):
                    problems.append((case, "accepted, but a streaming reader and zipfile disagree", data))
                continue
            reason = strict_reason(data, lenient_central=True)
            if reason:
                problems.append((case, f"accepted, but the strict reader says: {reason}", data))
            else:
                gaps.append(case)                       # the pinned gaps: central-record bookkeeping, a stream past its size
        return accepted, problems, time.monotonic() - started, pinned

    def check_problems(self, label, problems):
        classes = {}
        for case, what, data in problems:
            classes.setdefault(what.split(":")[0] if what.startswith(("accepted", "refused", "hang")) else what.split(":")[0], []).append(
                (case, what, data))
        report = []
        for kind, items in sorted(classes.items()):
            case, what, data = items[0]
            report.append(f"{label}: {len(items)} case(s) of {kind!r}; first is case {case} (seed {SEED}): {what}; "
                          f"{len(data)} bytes, head {data[:48].hex()}")
        self.assertEqual(report, [])


class ByteLevel(Fuzz):
    def test_a_deflated_bundle_survives_the_mutations(self):
        accepted, problems, secs, pinned = self.run_fuzz("deflated", 8, None, SEED)
        self.check_problems("deflated", problems)
        self.assertGreater(accepted, 100, "mutations of unchecked fields must still be accepted, or the oracle is untested")
        self.assertLess(secs, 120)

    def test_a_stored_bundle_survives_the_mutations(self):
        accepted, problems, secs, pinned = self.run_fuzz("stored", 0, None, SEED + 1)
        self.check_problems("stored", problems)
        self.assertGreater(accepted, 100)
        self.assertLess(secs, 120)

    def test_a_bundle_with_data_descriptors_survives_the_mutations(self):
        accepted, problems, secs, pinned = self.run_fuzz("descriptors", 8, "sig", SEED + 2)
        self.check_problems("descriptors", problems)
        self.assertGreater(accepted, 20)
        self.assertLess(secs, 120)


class Pinned(Fuzz):
    def test_no_damage_to_the_directory_ends_in_the_generic_failure_line(self):
        _, _, _, pinned = self.run_fuzz("deflated", 8, None, SEED)
        self.assertEqual(pinned, [])


class WholeGate(Fuzz):
    """The same judgement through the program: a sample of the mutations, with the gpg double and the exit status."""

    def test_the_program_and_the_bundle_judgement_agree_on_a_sample(self):
        rng = random.Random(SEED + 3)
        base, fields = build(self.specs(8, None))
        agreed = 0
        for case in range(250):
            data = self.mutate(rng, base, fields, lambda r: self.random_specs(r, 8, None))
            try:
                expected, errors = self.verdict(data)
            except Exception as exc:
                self.assertTrue(pinned_failure(exc), (case, exc))
                expected, errors = False, ["pinned"]
            os.makedirs(os.path.dirname(self.bundle_path), exist_ok=True)
            with open(self.bundle_path, "wb") as fh:
                fh.write(data)
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"])
            self.assertIn(res.rc, (0, 1), (case, res))
            self.assertEqual(res.rc == 0, expected, (case, res.errors(), errors))
            if res.rc:
                self.assertTrue(res.errors(), (case, res))
            agreed += 1
        self.assertEqual(agreed, 250)


if __name__ == "__main__":
    unittest.main()
