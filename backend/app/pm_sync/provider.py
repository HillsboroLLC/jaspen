"""Provider boundary for execution-plan synchronization.

The reconciliation engine deals only in Jaspen's canonical task fields. A
provider translates those fields to its remote API and returns canonical
snapshots plus field-level change times.
"""
from abc import ABC, abstractmethod


class ProjectToolProvider(ABC):
    connector_id = ""

    @abstractmethod
    def assert_connected(self, user_id, container_id=None):
        raise NotImplementedError

    @abstractmethod
    def list_containers(self, user_id):
        raise NotImplementedError

    @abstractmethod
    def create_container(self, user_id, payload):
        raise NotImplementedError

    @abstractmethod
    def get_item(self, config, binding, external_id):
        """Return {deleted, values, changed_at, version, url}."""
        raise NotImplementedError

    @abstractmethod
    def update_item(self, config, binding, external_id, changes, task=None):
        raise NotImplementedError

    @abstractmethod
    def create_items(self, config, binding, items):
        raise NotImplementedError

    @abstractmethod
    def recover_item(self, config, binding, entity_id):
        raise NotImplementedError

    @abstractmethod
    def set_identity(self, config, binding, external_id, entity_type, jaspen_id):
        raise NotImplementedError

    @abstractmethod
    def ensure_recovery_identity(self, config, binding, external_id, jaspen_id):
        """Ensure the provider-side identity used to recover a missing link."""
        raise NotImplementedError

    @abstractmethod
    def create_dependency(self, config, binding, prerequisite_id, dependent_id):
        raise NotImplementedError


def get_provider(connector_id):
    key = str(connector_id or "").strip().lower()
    if key == "jira_sync":
        from app.pm_sync.jira_adapter import JiraProvider
        return JiraProvider()
    raise ValueError(f"Unsupported project tool: {key or 'unknown'}")
