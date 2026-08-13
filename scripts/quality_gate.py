"""The quality gate.

    python scripts/quality_gate.py     # or: make gate

Runs the test suite **once**, then derives one scorecard line per product claim
from the per-test results. Every number is measured — nothing here is asserted
by the script itself, and a claim whose tests did not run reads ERROR rather
than PASS, because "we could not check" and "it is fine" are different answers.

Exit status is 0 only when every line passes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "var" / "quality-gate" / "report.jsonl"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass(frozen=True)
class Claim:
    """One scorecard line, and the tests that stand behind it."""

    label: str
    #: Matched against the pytest node id (``path::test_name``).
    pattern: str
    #: When true the line reports a count of escapes rather than PASS/FAIL.
    counts_escapes: bool = False
    #: Guard against a filter that silently matches nothing.
    min_tests: int = 1


CLAIMS: tuple[Claim, ...] = (
    Claim("Unit/integration tests", r".", min_tests=150),
    Claim("Fact lifecycle invariants", r"invariants/test_fact_lifecycle\.py", min_tests=15),
    Claim(
        "Unverified fact escapes",
        r"(unverified|proposed_fact|_proposed|not_verified|only_verified)",
        counts_escapes=True,
        min_tests=5,
    ),
    Claim(
        "Arithmetic delegated to LLM",
        r"(arithmetic|calculator|decimal|pending_bill|tampered_total|totals_come_from)",
        counts_escapes=True,
        min_tests=5,
    ),
    Claim(
        "Unsupported claims",
        r"(unsupported|invented|permanence|prognosis|contradic|escalat|grounding)",
        counts_escapes=True,
        min_tests=10,
    ),
    Claim(
        "Prompt injection escapes",
        r"adversarial/test_prompt_injection\.py",
        counts_escapes=True,
        min_tests=10,
    ),
    Claim(
        "Template mutations",
        r"(invariants/test_template_invariants\.py|test_template_fidelity\.py)",
        counts_escapes=True,
        min_tests=20,
    ),
    Claim(
        "Blocking issues at approval",
        r"(approve|approval|blocking)",
        counts_escapes=True,
        min_tests=8,
    ),
    Claim("Template fidelity (golden doc)", r"test_golden_document\.py", min_tests=4),
    Claim("Migrations match the models", r"test_migrations\.py", min_tests=4),
)


@dataclass
class Result:
    claim: Claim
    passed: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def ran(self) -> bool:
        return self.total >= self.claim.min_tests

    @property
    def ok(self) -> bool:
        return self.ran and self.failed == 0

    def render(self) -> str:
        if not self.ran:
            return f"{RED}ERROR{RESET}"
        if self.claim.counts_escapes:
            colour = GREEN if self.failed == 0 else RED
            return f"{colour}{self.failed}{RESET}"
        return f"{GREEN}PASS{RESET}" if self.ok else f"{RED}FAIL{RESET}"


def run_suite() -> tuple[int, float]:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    if REPORT.exists():
        REPORT.unlink()

    started = time.monotonic()
    completed = subprocess.run(
        [
            sys.executable, "-m", "pytest", "apps/api/tests",
            "-q", "--no-header", "-p", "no:cacheprovider",
            f"--report-log={REPORT}",
        ],
        cwd=REPO_ROOT,
    )
    return completed.returncode, time.monotonic() - started


def read_outcomes() -> list[tuple[str, str]]:
    """``(node id, outcome)`` for every test that actually executed."""
    if not REPORT.exists():
        return []
    outcomes: list[tuple[str, str]] = []
    for line in REPORT.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("$report_type") != "TestReport":
            continue
        node = entry.get("nodeid", "")
        outcome = entry.get("outcome")
        when = entry.get("when")
        # A setup or teardown error is a failure of that test, not a silence.
        if when == "call" or (when in ("setup", "teardown") and outcome == "failed"):
            outcomes.append((node.replace("\\", "/"), outcome))
    return outcomes


def score(outcomes: list[tuple[str, str]]) -> list[Result]:
    results: list[Result] = []
    for claim in CLAIMS:
        pattern = re.compile(claim.pattern, re.I)
        result = Result(claim=claim)
        for node, outcome in outcomes:
            if not pattern.search(node):
                continue
            if outcome == "passed":
                result.passed += 1
            elif outcome == "failed":
                result.failed += 1
                result.failures.append(node)
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--no-run", action="store_true", help="score the last report instead of re-running"
    )
    arguments = parser.parse_args()

    duration = 0.0
    if not arguments.no_run:
        _, duration = run_suite()

    outcomes = read_outcomes()
    results = score(outcomes)
    ok = all(result.ok for result in results)

    if arguments.json:
        print(json.dumps(
            {
                "ok": ok,
                "tests_executed": len(outcomes),
                "duration_seconds": round(duration, 1),
                "claims": [
                    {
                        "label": r.claim.label,
                        "tests": r.total,
                        "passed": r.passed,
                        "failed": r.failed,
                        "ran": r.ran,
                        "ok": r.ok,
                        "failures": r.failures[:10],
                    }
                    for r in results
                ],
            },
            indent=2,
        ))
        return 0 if ok else 1

    width = max(len(claim.label) for claim in CLAIMS) + 2
    print()
    print("Demand Letter Quality Gate")
    print()
    for result in results:
        detail = (
            f"{DIM}({result.total} tests){RESET}"
            if result.ran
            else f"{RED}(only {result.total} tests matched; expected >= "
                 f"{result.claim.min_tests}){RESET}"
        )
        print(f"  {result.claim.label.ljust(width)} {result.render():<20} {detail}")
    print()
    print(f"  {DIM}{len(outcomes)} tests executed in {duration:.0f}s{RESET}")
    print()

    if ok:
        print(f"  {GREEN}All gates passed.{RESET}")
        print()
        return 0

    for result in results:
        if result.ok:
            continue
        print(f"  {RED}{result.claim.label}{RESET}")
        for failure in result.failures[:5]:
            print(f"    {YELLOW}{failure}{RESET}")
        if not result.ran:
            print(f"    {YELLOW}no tests matched — the filter or the suite has moved{RESET}")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
