"""Repository-only checks for the production deployment workflow.

The current-state tests protect the approved deployment behavior without
claiming that the workflow already has the Phase 2 safeguards. Future-state
requirements are executable specifications marked xfail until Phase 2 is
approved and implemented; remove the marker when each safeguard is added.
"""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"


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


def test_current_workflow_sources_connection_values_from_github_secrets():
    workflow = workflow_text()
    assert "SERVER_SSH_KEY: ${{ secrets.SERVER_SSH_KEY }}" in workflow
    assert "SERVER_USER: ${{ secrets.SERVER_USER }}" in workflow
    assert workflow.count("SERVER_HOST: ${{ secrets.SERVER_HOST }}") == 2
    assert "BEGIN OPENSSH PRIVATE KEY" not in workflow
    assert "BEGIN RSA PRIVATE KEY" not in workflow


def test_current_workflow_preserves_fail_closed_deployment_order():
    workflow = workflow_text()
    required_steps = [
        "git fetch origin",
        "git pull --ff-only origin main",
        "pip install -q -r backend/requirements.txt",
        "python migrate_production.py",
        "sudo systemctl restart gunicorn-sekki.service",
    ]
    positions = [workflow.index(step) for step in required_steps]
    assert positions == sorted(positions)
    deploy_line = next(line for line in workflow.splitlines() if "python migrate_production.py" in line)
    assert "python migrate_production.py && sudo systemctl restart gunicorn-sekki.service" in deploy_line


def test_current_workflow_protects_the_temporary_ssh_private_key_file():
    workflow = workflow_text()
    write_position = workflow.index('echo "${SERVER_SSH_KEY}" > ~/.ssh/id_ed25519')
    chmod_position = workflow.index("chmod 600 ~/.ssh/id_ed25519")
    ssh_position = workflow.index('ssh "${SERVER_USER}@${SERVER_HOST}"')
    assert write_position < chmod_position < ssh_position


@pytest.mark.xfail(strict=True, reason="Future-state Phase 2 requirement: protected environment and bounded Actions permissions")
def test_future_workflow_declares_production_environment_and_read_only_token():
    workflow = workflow_text()
    assert re.search(r"(?m)^permissions:\s*$\n\s+contents:\s+read\s*$", workflow)
    assert re.search(r"(?m)^\s+environment:\s+production\s*$", workflow)


@pytest.mark.xfail(strict=True, reason="Future-state Phase 2 requirement: serialized deployments and a finite timeout")
def test_future_workflow_serializes_production_deployments_with_timeout():
    workflow = workflow_text()
    assert re.search(r"(?m)^concurrency:\s*$", workflow)
    assert re.search(r"(?m)^\s+cancel-in-progress:\s+false\s*$", workflow)
    assert re.search(r"(?m)^\s+timeout-minutes:\s+\d+\s*$", workflow)


@pytest.mark.xfail(strict=True, reason="Future-state Phase 2 requirement: administrator-verified pinned SSH host key")
def test_future_workflow_does_not_trust_runtime_ssh_keyscan():
    workflow = workflow_text()
    assert "ssh-keyscan" not in workflow
    assert "known_hosts" in workflow
    assert "${{ secrets." in workflow or "${{ vars." in workflow
