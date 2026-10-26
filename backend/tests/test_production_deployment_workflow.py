"""Repository-only checks for fail-closed production deployment safeguards."""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
STAGING_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-staging.yml"


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

    assert "systemctl show" not in wrapper
    assert "printenv" not in wrapper
    assert "EnvironmentFile" not in wrapper
    assert '"$1" =~ ^[0-9a-f]{40}$' in wrapper
    assert 'runuser -u "${DEPLOY_USER}"' in wrapper
    assert "status --porcelain --untracked-files=all" in wrapper
    assert 'systemctl start --wait "${MIGRATION_UNIT}"' in wrapper
    assert wrapper.index('systemctl start --wait "${MIGRATION_UNIT}"') < wrapper.index('systemctl restart "${RUNTIME_UNIT}"')


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
    assert "NoNewPrivileges=true" in unit
    assert "UMask=0077" in unit


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
