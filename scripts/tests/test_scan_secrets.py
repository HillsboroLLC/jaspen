import contextlib
import io
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import scan_secrets


class SecretScannerTests(unittest.TestCase):
    def test_detects_high_confidence_secret_without_storing_it_in_summary(self):
        secret = "sk_live_" + "A" * 24
        findings = scan_secrets.scan_text("config.py", f"STRIPE_SECRET_KEY='{secret}'")

        self.assertTrue(findings)
        self.assertTrue(any(item.rule == "stripe-live-key" for item in findings))
        self.assertTrue(all(secret not in item.safe_summary() for item in findings))

    def test_allows_documented_placeholders_and_github_secret_references(self):
        text = "\n".join(
            (
                "API_KEY=replace_me",
                "SERVER_SSH_KEY: ${{ secrets.SERVER_SSH_KEY }}",
                "DATABASE_URL=postgresql://user:password@example.test/jaspen",
            )
        )
        self.assertEqual(scan_secrets.scan_text("backend/.env.example", text), [])

    def test_detects_unquoted_generic_secret_in_environment_file(self):
        value = "production-credential-value-123456"
        findings = scan_secrets.scan_text("backend/.env.production", f"JWT_SECRET_KEY={value}")

        self.assertTrue(any(item.rule == "hardcoded-secret-assignment" for item in findings))
        self.assertTrue(all(value not in item.safe_summary() for item in findings))

    def test_main_never_prints_detected_value(self):
        secret = "ghp_" + "Z" * 36
        finding = scan_secrets.Finding("unsafe.txt", 7, "github-token")
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(scan_secrets, "scan_tracked_tree", return_value=[finding]):
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                result = scan_secrets.main([])

        self.assertEqual(result, 1)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertNotIn(secret, stdout.getvalue())
        self.assertIn("unsafe.txt:7: github-token", stderr.getvalue())

    def test_rejects_shell_metacharacters_in_history_range(self):
        with self.assertRaises(ValueError):
            scan_secrets.scan_history_range("HEAD;printenv")


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _credential_line():
    # Assembled at runtime so this file never contains a credential-shaped line.
    return "url = " + "postgresql" + "://svc:" + "q7Rz" + "Lm9Xw2" + "@db.internal/app"


class ReviewedHistoryExemptionTests(unittest.TestCase):
    """The reviewed exemption matches one exact (commit, file, line, rule)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "scanner-test@example.test")
        _git(self.repo, "config", "user.name", "Scanner Test")
        (self.repo / "README.md").write_text("start\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "base")
        self.base = _git(self.repo, "rev-parse", "HEAD")
        (self.repo / "app.cfg").write_text("first = 1\n" + _credential_line() + "\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "add config")
        self.commit = _git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self._tmp.cleanup()

    def _scan(self, reviewed, exempted=None):
        head = _git(self.repo, "rev-parse", "HEAD")
        return scan_secrets.scan_history_range(
            f"{self.base}..{head}", repo_root=self.repo, reviewed=frozenset(reviewed), exempted=exempted,
        )

    def test_unreviewed_history_finding_fails(self):
        findings = self._scan(set())
        self.assertEqual([(f.line, f.rule) for f in findings], [(2, "credentialed-url")])

    def test_exact_reviewed_entry_is_exempted_and_reported(self):
        exempted = []
        findings = self._scan({(self.commit, "app.cfg", 2, "credentialed-url")}, exempted)
        self.assertEqual(findings, [])
        self.assertEqual([f.safe_summary() for f in exempted], [f"{self.commit[:12]}:app.cfg:2: credentialed-url"])

    def test_wrong_line_rule_file_or_short_commit_never_exempts(self):
        for entry in (
            (self.commit, "app.cfg", 1, "credentialed-url"),
            (self.commit, "app.cfg", 2, "hardcoded-secret-assignment"),
            (self.commit, "other.cfg", 2, "credentialed-url"),
            (self.commit[:12], "app.cfg", 2, "credentialed-url"),
        ):
            with self.subTest(entry=entry):
                self.assertEqual(len(self._scan({entry})), 1)

    def test_a_new_commit_with_the_same_finding_still_fails(self):
        (self.repo / "app.cfg").write_text("first = 2\n" + _credential_line() + "\nnew = 1\n")
        (self.repo / "copy.cfg").write_text(_credential_line() + "\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "reuse")
        findings = self._scan({(self.commit, "app.cfg", 2, "credentialed-url")})
        self.assertEqual(sorted(f.path.split(":", 1)[1] for f in findings), ["copy.cfg"])

    def test_an_amended_commit_loses_its_exemption(self):
        (self.repo / "app.cfg").write_text("first = 1\n" + _credential_line() + "\nmore = 1\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "--amend", "-m", "add config, amended")
        findings = self._scan({(self.commit, "app.cfg", 2, "credentialed-url")})
        self.assertEqual([(f.line, f.rule) for f in findings], [(2, "credentialed-url")])

    def test_current_tracked_files_are_never_exempted(self):
        findings = scan_secrets.scan_tracked_tree(self.repo)
        self.assertEqual([(f.path, f.line, f.rule) for f in findings], [("app.cfg", 2, "credentialed-url")])

    def test_reviewed_registry_holds_only_the_five_verified_findings(self):
        rules = {name for name, _pattern in scan_secrets.CONTENT_RULES} | {"hardcoded-secret-assignment"}
        self.assertEqual(len(scan_secrets.REVIEWED_HISTORY_FALSE_POSITIVES), 5)
        for commit, path, line, rule in scan_secrets.REVIEWED_HISTORY_FALSE_POSITIVES:
            self.assertRegex(commit, r"^[0-9a-f]{40}$")
            self.assertTrue(path and not path.startswith("/"))
            self.assertIsInstance(line, int)
            self.assertIn(rule, rules)

    def test_main_reports_exemptions_location_only_and_passes(self):
        finding = scan_secrets.Finding("7fbb4e903596:.github/workflows/ci.yml", 80, "hardcoded-secret-assignment")

        def fake_history(_range, exempted=None, **_kwargs):
            exempted.append(finding)
            return []

        stdout = io.StringIO()
        with patch.object(scan_secrets, "scan_tracked_tree", return_value=[]), \
                patch.object(scan_secrets, "scan_history_range", side_effect=fake_history):
            with contextlib.redirect_stdout(stdout):
                result = scan_secrets.main(["--history-range", "a" * 40 + ".." + "b" * 40])
        self.assertEqual(result, 0)
        self.assertIn("Reviewed history exemption: 7fbb4e903596:.github/workflows/ci.yml:80: hardcoded-secret-assignment", stdout.getvalue())
        self.assertNotRegex(stdout.getvalue(), r"://[^\s]*:[^\s]*@")


if __name__ == "__main__":
    unittest.main()
