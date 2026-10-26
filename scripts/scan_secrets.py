#!/usr/bin/env python3
"""Fail when tracked files or new commits contain likely credentials.

Findings intentionally contain only location and rule metadata. The matched
value is never printed, including in verbose/error paths.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
INTENTIONAL_FIXTURE_PATHS = {
    "scripts/scan_secrets.py",
    "scripts/tests/test_scan_secrets.py",
}
ALLOWED_SECRET_METADATA_FILES = {
    "backend/.env.example",
    "frontend/.env.example",
    "frontend/.env.development",
}
SENSITIVE_FILE_NAMES = re.compile(
    r"(^|/)(?:\.env(?:\..+)?|id_(?:rsa|dsa|ecdsa|ed25519)|credentials(?:\..+)?)$",
    re.IGNORECASE,
)
SENSITIVE_FILE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    rule: str

    def safe_summary(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


def _joined(*parts: str) -> str:
    """Keep detector source from looking like a credential to itself."""
    return "".join(parts)


CONTENT_RULES = (
    ("private-key", re.compile(_joined("-----BEGIN ", "(?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"))),
    ("aws-access-key", re.compile(_joined(r"\b(?:AKIA|ASIA)", r"[A-Z0-9]{16}\b"))),
    ("github-token", re.compile(_joined(r"\bgh[pousr]_", r"[A-Za-z0-9]{30,}\b"))),
    ("openai-api-key", re.compile(_joined(r"\bsk-(?:proj-)?", r"[A-Za-z0-9_-]{20,}\b"))),
    ("anthropic-api-key", re.compile(_joined(r"\bsk-ant-", r"[A-Za-z0-9_-]{20,}\b"))),
    ("stripe-live-key", re.compile(_joined(r"\b(?:sk|rk)_live_", r"[A-Za-z0-9]{16,}\b"))),
    ("stripe-webhook-secret", re.compile(_joined(r"\bwhsec_", r"[A-Za-z0-9]{16,}\b"))),
    ("slack-token", re.compile(_joined(r"\bxox[baprs]-", r"[A-Za-z0-9-]{16,}\b"))),
    ("google-api-key", re.compile(_joined(r"\bAIza", r"[A-Za-z0-9_-]{30,}\b"))),
    ("google-oauth-secret", re.compile(_joined(r"\bGOCSPX-", r"[A-Za-z0-9_-]{16,}\b"))),
    ("digitalocean-token", re.compile(_joined(r"\bdop_v1_", r"[A-Fa-f0-9]{32,}\b"))),
    ("sendgrid-api-key", re.compile(_joined(r"\bSG\.", r"[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"))),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b")),
    (
        "credentialed-url",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]{1,128}:[^\s/@]{8,128}@", re.IGNORECASE),
    ),
)

GENERIC_QUOTED_ASSIGNMENT = re.compile(
    r"\b(?:[A-Z0-9_]*(?:API_KEY|CLIENT_SECRET|SECRET_KEY|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_TOKEN|REFRESH_TOKEN|DATABASE_URL))\b"
    r"\s*(?:=|:)\s*([\"'])([^\r\n\"']{8,})\1"
)
GENERIC_UNQUOTED_ASSIGNMENT = re.compile(
    r"\b(?:[A-Z0-9_]*(?:API_KEY|CLIENT_SECRET|SECRET_KEY|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_TOKEN|REFRESH_TOKEN|DATABASE_URL))\b"
    r"\s*(?:=|:)\s*([^\s,;#]{8,})"
)
CONFIG_SUFFIXES = {".conf", ".config", ".ini", ".json", ".properties", ".toml", ".yaml", ".yml"}

PLACEHOLDER_MARKERS = (
    "${{",
    "process.env",
    "os.getenv",
    "getenv(",
    "config.get",
    "example",
    "placeholder",
    "changeme",
    "change-me",
    "replace_me",
    "replace-with",
    "not_used",
    "not-used",
    "dummy",
    "synthetic",
    "test-only",
    "dev-",
    "local-",
    "sqlite:",
    "validpass",
    "redacted",
    "your_",
    "your-",
    "<",
)


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def scan_text(path: str, text: str) -> list[Finding]:
    normalized_path = path.replace("\\", "/")
    if normalized_path in INTENTIONAL_FIXTURE_PATHS:
        return []

    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in CONTENT_RULES:
            match = pattern.search(line)
            is_example_url = rule == "credentialed-url" and (
                "example.test" in line.lower()
                or "example.com" in line.lower()
                or re.search(r"://user:password@host(?::|/)", line, re.IGNORECASE)
            )
            if match and not is_example_url and not _looks_like_placeholder(match.group(0)):
                findings.append(Finding(normalized_path, line_number, rule))
        generic = GENERIC_QUOTED_ASSIGNMENT.search(line)
        is_test_fixture = "/tests/" in f"/{normalized_path}" and "test" in generic.group(2).lower() if generic else False
        is_metadata_default = (
            generic
            and normalized_path in ALLOWED_SECRET_METADATA_FILES
            and (
                generic.group(2).lower().startswith(("dev", "test", "local"))
                or any(marker in generic.group(2).lower() for marker in ("change", "replace", "placeholder", "dummy"))
            )
        )
        if generic and not is_test_fixture and not is_metadata_default and not _looks_like_placeholder(generic.group(2)):
            findings.append(Finding(normalized_path, line_number, "hardcoded-secret-assignment"))
        is_config = Path(normalized_path).suffix.lower() in CONFIG_SUFFIXES or Path(normalized_path).name.startswith(".env")
        unquoted = GENERIC_UNQUOTED_ASSIGNMENT.search(line) if is_config else None
        metadata_default = (
            unquoted
            and normalized_path in ALLOWED_SECRET_METADATA_FILES
            and (
                unquoted.group(1).lstrip("\"'").lower().startswith(("dev", "test", "local"))
                or any(marker in unquoted.group(1).lower() for marker in ("change", "replace", "placeholder", "dummy"))
            )
        )
        if unquoted and not metadata_default and not _looks_like_placeholder(unquoted.group(1)):
            findings.append(Finding(normalized_path, line_number, "hardcoded-secret-assignment"))
    return findings


def _tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def scan_tracked_tree(repo_root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in _tracked_paths(repo_root):
        normalized = relative_path.replace("\\", "/")
        suffix = Path(normalized).suffix.lower()
        if normalized not in ALLOWED_SECRET_METADATA_FILES and (
            SENSITIVE_FILE_NAMES.search(normalized) or suffix in SENSITIVE_FILE_SUFFIXES
        ):
            findings.append(Finding(normalized, 1, "sensitive-file-name"))

        path = repo_root / relative_path
        try:
            data = path.read_bytes()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if b"\0" in data or len(data) > 5 * 1024 * 1024:
            continue
        findings.extend(scan_text(normalized, data.decode("utf-8", errors="replace")))
    return sorted(set(findings))


def _scan_patch(commit_label: str, patch: str) -> list[Finding]:
    findings: list[Finding] = []
    path = "unknown"
    new_line = 0
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            new_line = int(match.group(1)) - 1 if match else 0
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_line += 1
            findings.extend(
                Finding(f"{commit_label}:{item.path}", new_line, item.rule)
                for item in scan_text(path, line[1:])
            )
        elif not line.startswith("-"):
            new_line += 1
    return findings


def scan_history_range(revision_range: str, repo_root: Path = REPO_ROOT) -> list[Finding]:
    if not re.fullmatch(r"[0-9a-fA-F^~.]+", revision_range):
        raise ValueError("History range must contain only Git revision characters")
    commits = subprocess.run(
        ["git", "rev-list", "--reverse", revision_range],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    findings: list[Finding] = []
    for commit in commits:
        patch = subprocess.run(
            ["git", "show", "--format=", "--no-ext-diff", "--unified=0", commit],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout
        findings.extend(_scan_patch(commit[:12], patch))
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-range", help="also scan every added line in this Git revision range")
    args = parser.parse_args(argv)

    try:
        findings = scan_tracked_tree()
        if args.history_range:
            findings.extend(scan_history_range(args.history_range))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"Secret scan could not run ({type(exc).__name__}); no credential data was printed.", file=sys.stderr)
        return 2

    findings = sorted(set(findings))
    if findings:
        print("Secret scan failed. Findings are location-only; matched values are suppressed.", file=sys.stderr)
        for finding in findings:
            print(finding.safe_summary(), file=sys.stderr)
        return 1
    print("Secret scan passed: no likely credentials found in tracked content.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
