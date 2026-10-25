"""Cross-platform Quality Gate and Floor Guard Automation Script.

Usage:
    python scripts/check.py [--fast | --task | --full]

Flags:
    --fast : Scans Floor Guard (zero suppressions), runs ruff check, and mypy --strict (budget <= 5s).
    --task : Runs --fast plus full pytest suite with coverage verification (>= 80%) (budget <= 90s).
    --full : Runs --task plus security and secrets heuristic checks.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import time

FORBIDDEN_PATTERNS = [
    (re.compile(r"#\s*noqa"), "# noqa"),
    (re.compile(r"#\s*type:\s*ignore"), "# type: ignore"),
    (re.compile(r"//\s*@ts-ignore"), "@ts-ignore"),
    (re.compile(r"//\s*@ts-nocheck"), "@ts-nocheck"),
    (re.compile(r"//\s*@ts-expect-error"), "@ts-expect-error"),
]

SECRET_PATTERNS = [
    (re.compile(r"(?i)api_key\s*=\s*['\"][A-Za-z0-9_\-]{20,}['\"]"), "Potential hardcoded API key"),
    (re.compile(r"(?i)secret\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]"), "Potential hardcoded secret"),
    (re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"), "Hardcoded private key block"),
]

IGNORE_DIRS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
}


def log(msg: str) -> None:
    """Print standard formatted message."""
    print(f"[InkShift Check] {msg}")


def log_step(name: str) -> None:
    """Print step announcement."""
    print(f"\n===> RUNNING: {name}")


def run_cmd(cmd: list[str], cwd: Path) -> int:
    """Execute a subprocess command, streaming output to terminal."""
    log(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def check_floor_guard(repo_root: Path) -> bool:
    """Scan codebases for forbidden suppression comments violating CONSTRAINTS.md."""
    log_step("Floor Guard: Scanning for forbidden suppressions (#noqa, #type:ignore, @ts-ignore)")
    violations: list[str] = []

    scan_targets = [repo_root / "src", repo_root / "tests"]
    allowed_extensions = {".py", ".ts", ".tsx", ".js"}

    for target in scan_targets:
        if not target.exists():
            continue
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix not in allowed_extensions:
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue

                for line_no, line in enumerate(content.splitlines(), start=1):
                    for pattern, label in FORBIDDEN_PATTERNS:
                        if pattern.search(line):
                            violations.append(
                                f"  - {file_path.relative_to(repo_root)}:{line_no} contains forbidden '{label}'"
                            )

    if violations:
        print("\n[FAIL] Floor Guard Violation! Suppressions forbidden by CONSTRAINTS.md found:")
        for v in violations:
            print(v)
        return False

    print("[PASS] Floor Guard: Zero suppressions detected across all source and test files.")
    return True


def check_security_secrets(repo_root: Path) -> bool:
    """Scan source files for accidental hardcoded credentials or keys."""
    log_step("Security Scan: Heuristic credential and secret detection")
    findings: list[str] = []
    scan_targets = [repo_root / "src", repo_root / "tests"]

    for target in scan_targets:
        if not target.exists():
            continue
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix not in {".py", ".ts", ".json"}:
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue

                for line_no, line in enumerate(content.splitlines(), start=1):
                    for pattern, label in SECRET_PATTERNS:
                        if pattern.search(line):
                            findings.append(
                                f"  - {file_path.relative_to(repo_root)}:{line_no}: {label}"
                            )

    if findings:
        print("\n[FAIL] Security finding! Potential secrets detected:")
        for f in findings:
            print(f)
        return False

    print("[PASS] Security Scan: No hardcoded secrets detected.")
    return True


def main() -> int:
    """Parse CLI flags and run staged quality verification suites."""
    parser = argparse.ArgumentParser(description="InkShift Quality Gate Verification Runner")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--fast",
        action="store_true",
        default=False,
        help="Run fast gate: Floor Guard, ruff linter, and mypy strict (default)",
    )
    group.add_argument(
        "--task",
        action="store_true",
        default=False,
        help="Run task gate: --fast + full test suite with >= 80% coverage check",
    )
    group.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Run full gate: --task + security secret heuristic scanner",
    )

    args = parser.parse_args()
    mode = "full" if args.full else ("task" if args.task else "fast")

    start_time = time.perf_counter()
    repo_root = Path(__file__).resolve().parent.parent

    print(f"==================================================")
    print(f"   InkShift Quality Gate: Mode [{mode.upper()}]")
    print(f"==================================================")

    # 1. Floor Guard Scan (always executed)
    if not check_floor_guard(repo_root):
        return 1

    # 2. Ruff Linter
    log_step("Linter: Ruff Check")
    rc = run_cmd([sys.executable, "-m", "ruff", "check", "src", "tests"], cwd=repo_root)
    if rc != 0:
        print("\n[FAIL] Ruff linting check failed.")
        return 1
    print("[PASS] Ruff linting passed.")

    # 3. Mypy Strict Type Check
    log_step("Type Checker: Mypy Strict")
    rc = run_cmd([sys.executable, "-m", "mypy", "src", "--strict"], cwd=repo_root)
    if rc != 0:
        print("\n[FAIL] Mypy strict type checking failed.")
        return 1
    print("[PASS] Mypy strict type checking passed.")

    # If --fast only, exit now
    if mode == "fast":
        elapsed = time.perf_counter() - start_time
        print(f"\n[ALL CHECKS PASSED] Fast gate succeeded in {elapsed:.2f}s (Budget: <= 5s)")
        return 0

    # 4. Pytest Suite with Coverage (for --task and --full)
    log_step("Test Suite: Pytest with Coverage Gate (>= 80%)")
    pytest_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "--cov=src.backend",
        "--cov-fail-under=80",
        "--cov-report=term-missing",
    ]
    rc = run_cmd(pytest_cmd, cwd=repo_root)
    if rc != 0:
        print("\n[FAIL] Test suite or coverage threshold failed.")
        return 1
    print("[PASS] Test suite and coverage threshold (>= 80%) passed.")

    # 5. Security Checks (for --full)
    if mode == "full":
        if not check_security_secrets(repo_root):
            return 1

    elapsed = time.perf_counter() - start_time
    print(f"\n[ALL CHECKS PASSED] {mode.upper()} gate succeeded in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
