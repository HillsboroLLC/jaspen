from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]


class SecretSafeDiagnosticsTests(unittest.TestCase):
    def test_frontend_environment_check_never_displays_values_or_partial_secrets(self):
        source = (REPO_ROOT / "frontend" / "scripts" / "check-env.mjs").read_text(encoding="utf-8")

        self.assertNotIn("function mask", source)
        self.assertNotIn("JSON.stringify(summary", source)
        self.assertNotIn("err.message", source)
        self.assertIn("Configured variable names", source)

    def test_deployment_diagnostics_suppress_library_error_messages(self):
        source = (REPO_ROOT / "frontend" / "scripts" / "deploy.mjs").read_text(encoding="utf-8")

        self.assertNotIn("e.message", source)
        self.assertIn("details suppressed", source)

    def test_admin_scripts_do_not_print_partial_or_inline_credentials(self):
        rehearsal = (REPO_ROOT / "backend" / "scripts" / "rehearse_300k_coupon.py").read_text(encoding="utf-8")
        promotion = (REPO_ROOT / "backend" / "scripts" / "set_homepage_promotion.py").read_text(encoding="utf-8")

        self.assertNotIn('client_secret.split("_secret_")', rehearsal)
        self.assertNotIn("pass it inline", promotion)
        self.assertNotIn('target.split("@")', promotion)

    def test_frontend_sentry_always_uses_privacy_hooks_without_replay(self):
        source = (REPO_ROOT / "frontend" / "src" / "index.js").read_text(encoding="utf-8")

        self.assertIn("beforeSend: scrubSentryEvent", source)
        self.assertIn("beforeBreadcrumb: scrubSentryBreadcrumb", source)
        self.assertNotIn("replayIntegration", source)
        self.assertNotIn("feedbackIntegration", source)

    def test_dependency_audits_are_visible_but_do_not_block_releases_yet(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        dependabot = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

        self.assertIn("security-audit:", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("python -m pip_audit -r backend/requirements.txt", workflow)
        self.assertIn("npm audit --omit=dev --audit-level=high", workflow)
        self.assertEqual(dependabot.count("open-pull-requests-limit: 5"), 3)
        self.assertIn("package-ecosystem: pip", dependabot)
        self.assertIn("package-ecosystem: npm", dependabot)
        self.assertIn("package-ecosystem: github-actions", dependabot)


if __name__ == "__main__":
    unittest.main()
