#!/usr/bin/env python3
"""Cases for `javadoc_trivial_members.py`, one per rule the filter is meant to hold.

Each case names the member shape, the policy, and whether the finding SURVIVES. A
filter is only worth having if it can be shown to keep what it must keep, so the
negative controls outnumber the positive ones: the risk here is not failing to
exempt a getter, it is exempting a contract.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import javadoc_trivial_members as filt  # noqa: E402

SOURCE = """package probe;

public final class Probe {

    private String name;
    private java.time.Instant start;
    private java.time.Duration ttl;
    private int order;
    private Probe delegate;

    public String name() { return name; }

    public String nameThis() { return this.name; }

    public void setName(String v) { this.name = v; }

    public Probe name(String v) { this.name = v; return this; }

    public Probe nameNoThis(String v) { name = v; return this; }

    public java.time.Instant deadline() { return start.plus(ttl); }

    public boolean isBefore(Probe other) { return this.order < other.order; }

    public int priority() { return 0; }

    public String delegated() { return delegate.name(); }

    public String identity(String x) { return x; }

    public void setChecked(String v) { this.name = java.util.Objects.requireNonNull(v); }

    public String commented() {
        // the field is not the contract
        return name;
    }

    @SafeVarargs
    @SuppressWarnings({"unchecked", "rawtypes"})
    public final String annotated() { return name; }

    public void selfAssign(String name) { name = name; }
}

interface Contract {

    String open(String name, int mode);

    default int priorityDefault() { return 0; }
}

abstract class Base {

    public abstract void close();

    public abstract String render(
            String prefix,
            int width);
}
"""

# line -> (label, shape expected under `exempt`; None means the finding SURVIVES)
CASES = {
    11: ("getter returning a field", "GETTER"),
    13: ("getter returning this.field", "GETTER"),
    15: ("void setter", "SETTER"),
    17: ("fluent setter with this.", "FLUENT_SETTER"),
    19: ("fluent setter without this.", "FLUENT_SETTER"),
    21: ("one-line computation -- the deadline() class", None),
    23: ("one-line comparison with a contract", None),
    25: ("constant return -- the priority() convention", None),
    27: ("delegation to another object", None),
    29: ("passthrough with a parameter, not a getter", None),
    31: ("setter that validates", None),
    33: ("body carrying a comment", None),
    38: ("getter behind annotations, one carrying braces", "GETTER"),
    42: ("parameter assigned to itself", None),
    47: ("abstract interface method -- the contract surface", None),
    49: ("default method with a constant body", None),
    54: ("public abstract method in an abstract class", None),
    56: ("abstract method declared across three lines", None),
}


def run_case(source: Path, line: int, policy: str, check: str = "MissingJavadocMethod", severity: str = "ERROR"):
    """Return (surviving_count, printed_lines) for a one-finding report."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(f"[{severity}] {source}:{line}:5: Missing a Javadoc comment. [{check}]\n")
        report = Path(fh.name)
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = filt.main(["--policy", policy, "--report", str(report)])
    report.unlink()
    return code, buf.getvalue()


def main() -> int:
    failures: list[str] = []
    checked = 0
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "Probe.java"
        source.write_text(SOURCE, encoding="utf-8")

        declared = source.read_text(encoding="utf-8").splitlines()
        for line, (label, expected) in CASES.items():
            checked += 1
            # The fixture must say what the case claims it says.
            if not declared[line - 1].strip():
                failures.append(f"line {line} ({label}) is blank -- the fixture drifted")
                continue

            code, _ = run_case(source, line, "exempt")
            if expected is None and code != 1:
                failures.append(f"EXEMPTED a member that must keep its finding: line {line} -- {label}")
            if expected is not None and code != 0:
                failures.append(f"KEPT a finding on a mechanical member: line {line} -- {label}")

            shape = filt.classify(source, line)
            if shape != expected:
                failures.append(f"line {line} ({label}): classified {shape!r}, expected {expected!r}")

            # Under the default policy nothing is ever exempted.
            code, _ = run_case(source, line, "documented")
            if code != 1:
                failures.append(f"policy=documented dropped a finding: line {line} -- {label}")

        # The filter touches one check and one severity, and nothing else.
        checked += 1
        code, _ = run_case(source, 11, "exempt", check="MissingJavadocType")
        if code != 1:
            failures.append("a finding from another check was dropped -- the filter is not a general silencer")
        checked += 1
        code, out = run_case(source, 11, "exempt", severity="WARN")
        if "WARN" not in out:
            failures.append("a warning was dropped; only ERROR findings are in scope")

        # A file the filter cannot read keeps its finding.
        checked += 1
        code, _ = run_case(Path(tmp) / "Absent.java", 11, "exempt")
        if code != 1:
            failures.append("an unreadable file exempted its member -- the filter must fail closed")

        # A surviving count that is a multiple of 256 must not exit 0: a process exit
        # status is eight bits, so a returned count truncates -- 909 survivors read as
        # 141, and exactly 256 read as clean.
        checked += 1
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            for _ in range(256):
                fh.write(f"[ERROR] {source}:21:5: Missing a Javadoc comment. [MissingJavadocMethod]\n")
            many = Path(fh.name)
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = filt.main(["--policy", "exempt", "--report", str(many)])
        many.unlink()
        if code == 0:
            failures.append("256 surviving findings exited 0 -- the exit status is eight bits, it may not carry a count")

        # A line past the end of the file keeps its finding.
        checked += 1
        code, _ = run_case(source, 9999, "exempt")
        if code != 1:
            failures.append("a line outside the file exempted its member -- the filter must fail closed")

    if failures:
        print(f"javadoc_trivial_members: {len(failures)} of {checked} cases FAILED")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(f"javadoc_trivial_members: {checked} cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
