"""The suite protects the guards: every mutation of a script is detected by the tests of that script.

The table is `mutation_table.py`: `(script, old, new, selectors)`. `old` must occur in the script exactly once,
so a refactor cannot turn a mutation into a no-op; the script is copied (with its siblings) to a temporary
directory, the single replacement is applied, and the selected tests run against that copy with failfast.
The mutant is KILLED when a test fails or errors. A surviving mutant fails this test and is listed.

Mutants are independent, so they are judged in forked workers, each with a temporary directory of its own.
"""
from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
import os
import shutil
import tempfile
import time
import unittest
from collections import Counter

import caps_release_helpers as h
from mutation_table import EQUIVALENT, M, SECRETS


KILLERS_FILE = os.path.join(h.HERE, "mutation_killers.json")


def key_of(script, old, new):
    return hashlib.sha1(f"{script}\0{old}\0{new}".encode()).hexdigest()[:16]


def load_killers():
    try:
        with open(KILLERS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def source_of(script):
    return os.path.join(h.REPO, "scripts", "caps_release", script + ".py") if not script.startswith("../") else \
        os.path.join(h.REPO, "scripts", script[3:] + ".py")


def killed(script, old, new, selectors):
    """(True, by) when a test notices the mutant, (False, "") when none does, (None, why) when the pattern is broken."""
    with open(source_of(script), encoding="utf-8") as fh:
        text = fh.read()
    if text.count(old) != 1:
        return None, f"pattern occurs {text.count(old)} times, not once"
    work = tempfile.mkdtemp(prefix="caps-mutant-")
    try:
        for name in os.listdir(h.SCRIPT_DIR):
            if name.endswith(".py"):
                shutil.copy(os.path.join(h.SCRIPT_DIR, name), os.path.join(work, name))
        shutil.copy(h.RUNNER, os.path.join(work, "run_caps_release_tests.py"))
        target = os.path.join(work, os.path.basename(source_of(script)))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))
        h.SCRIPT_DIR_OVERRIDE = work
        suite = unittest.defaultTestLoader.loadTestsFromNames(selectors)
        result = unittest.TextTestRunner(stream=io.StringIO(), failfast=True).run(suite)
        found = (result.failures or result.errors)
        if found and "_FailedTest" in found[0][0].id():
            return None, f"a selected test cannot be imported: {found[0][0].id()}"
        return bool(found), (found[0][0].id().split()[0] if found else "")
    finally:
        h.SCRIPT_DIR_OVERRIDE = None
        shutil.rmtree(work, ignore_errors=True)


def judge(entry, private):
    """Runs in a worker: a private temporary directory, so concurrent mutants never see each other's scratch files."""
    tempfile.tempdir = private
    cwd = os.getcwd()
    os.chdir(private)               # a mutant that writes to a relative path writes here, not into the repository
    try:
        script, old, new, selectors = entry
        first = KILLERS.get(key_of(script, old, new))
        # the test that killed this mutant last time goes first, so a mutant is usually judged by one test;
        # a recorded test that no longer exists is not trusted (a missing test would "fail" every mutant)
        if first and not first.endswith("_FailedTest") and loadable(first):
            selectors = [first] + list(selectors)
        return killed(script, old, new, selectors)
    finally:
        os.chdir(cwd)
        tempfile.tempdir = None


TIMEOUT = int(os.environ.get("CAPS_MUTANT_TIMEOUT", "25"))      # a recording pass, which has no recorded killer to run first, needs more
KILLERS = load_killers()


def loadable(name):
    suite = unittest.defaultTestLoader.loadTestsFromName(name)
    return suite.countTestCases() == 1 and "_FailedTest" not in repr(suite)


def _child(entry, private, conn):
    conn.send(judge(entry, private))
    conn.close()


def judge_all(entries, workers=None):
    """Judge every entry in its own forked process, at most `workers` at a time.

    A mutant that makes the suite hang (a refusal turned into a blocking read) is killed after TIMEOUT seconds
    and counts as detected: the run did not finish with the guard intact.
    """
    workers = workers or max(1, min(8, os.cpu_count() or 1))
    ctx = multiprocessing.get_context("fork")
    results, running, pending = [None] * len(entries), {}, list(range(len(entries)))
    while pending or running:
        while pending and len(running) < workers:
            i = pending.pop(0)
            recv, send = ctx.Pipe(duplex=False)
            private = tempfile.mkdtemp(prefix="caps-worker-")       # removed here, so a killed worker leaves nothing
            proc = ctx.Process(target=_child, args=(entries[i], private, send))
            proc.start()
            send.close()
            running[i] = (proc, recv, time.monotonic(), private)
        for i, (proc, recv, started, private) in list(running.items()):
            if recv.poll(0.02):
                try:
                    results[i] = recv.recv()
                except EOFError:
                    results[i] = (True, "the worker died")
            elif not proc.is_alive():
                results[i] = (True, "the worker died") if not recv.poll(0) else recv.recv()
            elif time.monotonic() - started > TIMEOUT:
                proc.kill()
                results[i] = (True, "timed out")
            else:
                continue
            proc.join()
            recv.close()
            shutil.rmtree(private, ignore_errors=True)
            del running[i]
    return results


class Mutants(unittest.TestCase):
    def test_every_mutation_is_killed(self):
        survivors, broken = [], []
        for (script, old, new, _), (was_killed, why) in zip(M, judge_all(M)):
            if was_killed is None:
                broken.append(f"{script}: {old[:60]!r}: {why}")
            elif not was_killed:
                survivors.append(f"{script}: {old[:70]!r} -> {new[:60]!r}")
        self.assertEqual(broken, [], "mutations whose pattern no longer applies exactly once")
        self.assertEqual(survivors, [], "SURVIVING MUTANTS: the tests do not notice these changes to a guard")

    def test_the_harness_reports_a_mutant_the_tests_cannot_see(self):
        """A replacement that changes nothing must survive, and a pattern that does not apply once is reported."""
        self.assertIs(killed("check_secrets", "if missing:", "if missing:", SECRETS)[0], False)
        self.assertIsNone(killed("check_secrets", "a.target", "a.target", SECRETS)[0])
        self.assertIsNone(killed("check_secrets", "no such text anywhere", "x", SECRETS)[0])

    def test_every_recorded_killer_is_a_test_that_exists(self):
        for key, name in load_killers().items():
            self.assertTrue(loadable(name), name)

    def test_there_is_a_mutation_for_every_script(self):
        scripts = Counter(s for s, *_ in M)
        on_disk = {n[:-3] for n in os.listdir(h.SCRIPT_DIR) if n.endswith(".py")}
        self.assertEqual(on_disk - set(scripts), set())
        for script in on_disk:
            self.assertGreaterEqual(scripts[script], 6, script)
        self.assertGreaterEqual(len(M), 400)

    def test_every_equivalent_mutant_is_justified_and_still_applies_once(self):
        self.assertGreaterEqual(len(EQUIVALENT), 5)
        seen = set()
        for script, old, new, why in EQUIVALENT:
            with open(source_of(script), encoding="utf-8") as fh:
                self.assertEqual(fh.read().count(old), 1, f"{script}: {old[:70]!r} no longer applies; review the mutant")
            self.assertGreater(len(why.split()), 5, f"{script}: {old[:70]!r} needs a reason it cannot be told from the script")
            self.assertNotIn((script, old, new), seen)
            self.assertNotIn((script, old, new), {(a, b, c) for a, b, c, _ in M}, "a mutant is either judged or equivalent")
            seen.add((script, old, new))

    def test_every_pattern_is_unique_in_its_script(self):
        texts, seen = {}, set()
        for script, old, new, _ in M:
            if script not in texts:
                with open(source_of(script), encoding="utf-8") as fh:
                    texts[script] = fh.read()
            self.assertEqual(texts[script].count(old), 1, f"{script}: {old[:70]!r}")
            self.assertNotEqual(old, new, f"{script}: {old[:70]!r} is a no-op")
            self.assertNotIn((script, old, new), seen, f"{script}: {old[:70]!r} is listed twice")
            seen.add((script, old, new))


def record():
    """Rewrite mutation_killers.json: for every mutant, the test that kills it when all its selectors run."""
    global KILLERS
    KILLERS = {}
    results = judge_all(M)
    killers = {}
    for (script, old, new, _), (was_killed, by) in zip(M, results):
        if was_killed and by and "timed out" not in by and "worker died" not in by:
            killers[key_of(script, old, new)] = by
    with open(KILLERS_FILE, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(killers.items())), fh, indent=0, sort_keys=True)
        fh.write("\n")
    print(f"recorded {len(killers)} of {len(M)} mutants")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--record"]:
        record()
    else:
        unittest.main()
