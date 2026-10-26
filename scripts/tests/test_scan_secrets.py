import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
