"""Repository-only checks for fail-closed production deployment safeguards."""

import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
STAGING_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-staging.yml"
RUNTIME_DATA_PATHS = (
    "backend/data/",
    "backend/connectors_data/",
    "backend/admin_audit_data/",
    "admin_audit_data/",
)


def workflow_text():
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_current_workflow_only_deploys_pushes_to_main():
    workflow = workflow_text()
    assert re.search(r"(?m)^on:\s*$\n\s+push:\s*$\n\s+branches:\s+\[main\]\s*$", workflow)
    assert "pull_request:" not in workflow
    assert "workflow_dispatch:" not in workflow
    assert "workflow_run:" not in workflow
    assert "repository_dispatch:" not in workflow
    assert "schedule:" not in workflow


def test_staging_cannot_deploy_while_it_shares_production_data():
    workflow = STAGING_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "push:" not in workflow
    assert "if: ${{ false }}" in workflow
    assert "secrets." not in workflow
    assert "ssh " not in workflow


def test_current_workflow_sources_connection_values_from_github_secrets():
    workflow = workflow_text()
    assert "SERVER_SSH_KEY: ${{ secrets.SERVER_SSH_KEY }}" in workflow
    assert "SERVER_SSH_KNOWN_HOSTS: ${{ secrets.SERVER_SSH_KNOWN_HOSTS }}" in workflow
    assert "SERVER_USER: ${{ secrets.SERVER_USER }}" in workflow
    assert workflow.count("SERVER_HOST: ${{ secrets.SERVER_HOST }}") == 1
    assert "BEGIN OPENSSH PRIVATE KEY" not in workflow
    assert "BEGIN RSA PRIVATE KEY" not in workflow


def test_current_workflow_preserves_fail_closed_deployment_order():
    workflow = workflow_text()
    required_steps = [
        "git fetch origin",
        'git merge --ff-only "${JASPEN_RELEASE_SHA}"',
        "pip install -q -r backend/requirements.txt",
        "python migrate_production.py",
        "sudo systemctl restart gunicorn-sekki.service",
    ]
    positions = [workflow.index(step) for step in required_steps]
    assert positions == sorted(positions)
    assert "set -euo pipefail" in workflow


def test_current_workflow_protects_and_removes_temporary_ssh_files():
    workflow = workflow_text()
    assert "umask 077" in workflow
    assert "trap cleanup EXIT" in workflow
    assert "rm -f --" in workflow
    assert "echo \"${SERVER_SSH_KEY}\"" not in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    assert "IdentitiesOnly=yes" in workflow


def test_workflow_declares_production_environment_and_read_only_token():
    workflow = workflow_text()
    assert re.search(r"(?m)^permissions:\s*$\n\s+contents:\s+read\s*$", workflow)
    assert re.search(r"(?m)^\s+environment:\s+production\s*$", workflow)


def test_workflow_serializes_production_deployments_with_timeout():
    workflow = workflow_text()
    assert re.search(r"(?m)^concurrency:\s*$", workflow)
    assert re.search(r"(?m)^\s+cancel-in-progress:\s+false\s*$", workflow)
    assert re.search(r"(?m)^\s+timeout-minutes:\s+\d+\s*$", workflow)


def test_workflow_prefers_the_bounded_wrapper_and_validates_exact_revision():
    workflow = workflow_text()

    assert '[[ ! "${RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ]]' in workflow
    check_position = workflow.index("jaspen-deploy --check")
    wrapper_position = workflow.index('jaspen-deploy "${JASPEN_RELEASE_SHA}"')
    compatibility_position = workflow.index("# Compatibility path")
    assert check_position < wrapper_position < compatibility_position
    assert "git pull" not in workflow


def test_wrapper_never_reads_or_prints_credentials():
    wrapper = (REPO_ROOT / "deploy" / "production" / "jaspen-deploy").read_text(encoding="utf-8")

    assert "--property=Environment" not in wrapper
    assert "printenv" not in wrapper
    assert "EnvironmentFile" not in wrapper
    assert '"$1" =~ ^[0-9a-f]{40}$' in wrapper
    assert 'runuser -u "${DEPLOY_USER}"' in wrapper
    assert "status --porcelain --untracked-files=all" in wrapper
    assert 'systemctl start --wait "${MIGRATION_UNIT}"' in wrapper
    assert wrapper.index('systemctl start --wait "${MIGRATION_UNIT}"') < wrapper.index('systemctl restart "${RUNTIME_UNIT}"')


def test_wrapper_check_validates_cutover_permissions_without_reading_values():
    wrapper = (REPO_ROOT / "deploy" / "production" / "jaspen-deploy").read_text(encoding="utf-8")

    assert "load_config" in wrapper
    assert "stat -c '%U' \"${DEPLOY_ROOT}\"" in wrapper
    assert 'runuser -u "${APP_USER}" -- test -x "${DEPLOY_ROOT}"' in wrapper
    assert 'runuser -u "${APP_USER}" -- test -x "${DEPLOY_ROOT}/backend/venv/bin/python"' in wrapper
    assert 'runuser -u "${MIGRATION_USER}" -- test -r "${DEPLOY_ROOT}"' in wrapper
    assert 'runuser -u "${MIGRATION_USER}" -- test -x "${DEPLOY_ROOT}"' in wrapper
    assert 'runuser -u "${MIGRATION_USER}" -- test -r "${DEPLOY_ROOT}/backend/migrate_production.py"' in wrapper
    assert 'runuser -u "${APP_USER}" -- test -w "${path}"' in wrapper
    assert 'check_protected_environment_file "${RUNTIME_ENV_FILE}" "${APP_USER}"' in wrapper
    assert 'check_protected_environment_file "${MIGRATION_ENV_FILE}" "${MIGRATION_USER}"' in wrapper
    assert 'systemctl cat "${MIGRATION_UNIT}"' in wrapper
    assert 'systemctl cat "${RUNTIME_UNIT}"' in wrapper
    assert 'systemctl show "${RUNTIME_UNIT}" --property=WorkingDirectory --value' in wrapper
    assert '== "${DEPLOY_ROOT}/backend"' in wrapper
    assert wrapper.count("systemctl show") == 1
    assert "read_text" not in wrapper


def test_cutover_verifies_identity_switch_before_ssh_lockdown_without_reading_environment():
    cutover = (REPO_ROOT / "docs" / "production-security-cutover.md").read_text(encoding="utf-8")
    verification = cutover[cutover.index("## Fail-closed verification") : cutover.index("## Rollback")]

    assert "systemctl show" not in cutover
    assert "/usr/local/sbin/jaspen-env-check" in verification
    assert "prints `PASS`" in verification

    env_check = cutover.index("Run `/usr/local/sbin/jaspen-env-check`")
    functional_check = cutover.index("a chat file upload")
    ssh_lockdown = cutover.index("Only after every identity-switch and functional check passes")
    assert env_check < functional_check < ssh_lockdown


def test_migration_unit_has_a_dedicated_identity_and_hardening():
    unit = (REPO_ROOT / "deploy" / "production" / "jaspen-migrate.service").read_text(encoding="utf-8")

    assert "User=jaspen-migrate" in unit
    assert "Group=jaspen-migrate" in unit
    assert "EnvironmentFile=/etc/jaspen/migration.env" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit


def test_runtime_drop_in_separates_identity_and_protected_environment():
    unit = (REPO_ROOT / "deploy" / "production" / "gunicorn-sekki-security.conf").read_text(encoding="utf-8")

    assert "User=jaspen-app" in unit
    assert "Group=jaspen-app" in unit
    assert "EnvironmentFile=/etc/jaspen/runtime.env" in unit
    assert re.search(r"(?m)^Environment=$", unit)
    assert "NoNewPrivileges=true" in unit
    assert "UMask=0077" in unit
    for path in (
        "backend/data/user_uploads",
        "backend/data/reports",
        "backend/connectors_data",
        "backend/admin_audit_data",
    ):
        assert f"ReadWritePaths=@DEPLOY_ROOT@/{path}" in unit


def test_env_check_is_executable_and_never_discloses_synthetic_values(tmp_path):
    checker = REPO_ROOT / "deploy" / "production" / "jaspen-env-check"
    assert checker.stat().st_mode & stat.S_IXUSR

    protected_value = "synthetic-" + "protected-value"
    inline = tmp_path / "inline"
    runtime = tmp_path / "runtime"
    migration = tmp_path / "migration"
    inline.write_text(f"COPIED_SETTING={protected_value} API_TOKEN=synthetic-inline\n", encoding="utf-8")
    runtime.write_text(f"RUNTIME_REFERENCE={protected_value}\n", encoding="utf-8")
    migration.write_text("MIGRATION_SETTING=synthetic-metadata\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(checker),
            "--inline-file",
            str(inline),
            "--runtime-file",
            str(runtime),
            "--migration-file",
            str(migration),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout.strip() == "FAIL: 2 secret-named variable(s) still inline"
    assert protected_value not in result.stdout
    assert protected_value not in result.stderr
    assert "synthetic-inline" not in result.stdout
    assert "synthetic-inline" not in result.stderr


def test_env_check_passes_when_only_non_secret_settings_are_inline(tmp_path):
    checker = REPO_ROOT / "deploy" / "production" / "jaspen-env-check"
    inline = tmp_path / "inline"
    runtime = tmp_path / "runtime"
    migration = tmp_path / "migration"
    inline.write_text("SAFE_SETTING=enabled\n", encoding="utf-8")
    runtime.write_text("DATABASE_URL=synthetic-runtime\n", encoding="utf-8")
    migration.write_text("DATABASE_URL=synthetic-migration\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(checker),
            "--inline-file",
            str(inline),
            "--runtime-file",
            str(runtime),
            "--migration-file",
            str(migration),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "PASS"


def test_runtime_customer_data_is_ignored_but_not_tracked_or_committed():
    samples = [f"{path}synthetic-check" for path in RUNTIME_DATA_PATHS]
    ignored = subprocess.run(
        ["git", "check-ignore", "--", *samples],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(ignored.stdout.splitlines()) == set(samples)

    tracked = subprocess.run(
        ["git", "ls-files", "--", *RUNTIME_DATA_PATHS],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout == ""

    tracked_ignored = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard", "--", *RUNTIME_DATA_PATHS],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked_ignored.stdout == ""

    branch_changes = subprocess.run(
        ["git", "diff", "--name-only", "origin/main..HEAD", "--", *RUNTIME_DATA_PATHS],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert branch_changes.stdout == ""


def test_deployment_artifacts_never_remove_runtime_customer_data():
    texts = [
        (REPO_ROOT / "deploy" / "production" / "jaspen-deploy").read_text(encoding="utf-8"),
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        (REPO_ROOT / "docs" / "production-security-cutover.md").read_text(encoding="utf-8"),
    ]
    for text in texts:
        assert not re.search(r"\bgit\s+(?:clean|rm)\b", text)


def test_ssh_dispatcher_accepts_only_a_release_sha_and_fixed_wrapper():
    dispatcher = (REPO_ROOT / "deploy" / "production" / "jaspen-ssh-dispatch").read_text(encoding="utf-8")

    assert "SSH_ORIGINAL_COMMAND" in dispatcher
    assert "([0-9a-f]{40})" in dispatcher
    assert 'exec sudo -n /usr/local/sbin/jaspen-deploy "${BASH_REMATCH[1]}"' in dispatcher
    assert "SSH command refused." in dispatcher


@pytest.mark.xfail(strict=True, reason="Future-state Phase 2 requirement: administrator-verified pinned SSH host key")
def test_future_workflow_does_not_trust_runtime_ssh_keyscan():
    workflow = workflow_text()
    assert "ssh-keyscan" not in workflow
    assert "known_hosts" in workflow
    assert "${{ secrets." in workflow or "${{ vars." in workflow
