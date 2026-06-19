"""Module for Smart Checklist for Jira operations."""

import logging
from typing import Any

from requests.exceptions import HTTPError

from ..utils.decorators import handle_auth_errors
from .client import JiraClient

logger = logging.getLogger("mcp-jira")

SMART_CHECKLIST_PROPERTY_KEY = "com.railsware.SmartChecklist.checklist"
SMART_CHECKLIST_FIELD_ID_ENV = "JIRA_SMART_CHECKLIST_FIELD_ID"


class SmartChecklistMixin(JiraClient):
    """Mixin for Smart Checklist for Jira operations."""

    @handle_auth_errors("Jira API")
    def get_smart_checklist_property(self, issue_key: str) -> dict[str, Any]:
        """Get the legacy Smart Checklist issue property for an issue.

        Args:
            issue_key: The Jira issue key or ID.

        Returns:
            Dictionary containing the issue key, property key, and value.
        """
        self._validate_issue_access(issue_key)

        try:
            response = self.jira.get(
                f"rest/api/2/issue/{issue_key}/properties/"
                f"{SMART_CHECKLIST_PROPERTY_KEY}"
            )
            if not isinstance(response, dict):
                msg = f"Unexpected response type from Jira API: {type(response)}"
                logger.error(msg)
                raise TypeError(msg)

            return {
                "issue_key": issue_key,
                "property_key": response.get("key", SMART_CHECKLIST_PROPERTY_KEY),
                "value": response.get("value"),
            }
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return {
                    "issue_key": issue_key,
                    "property_key": SMART_CHECKLIST_PROPERTY_KEY,
                    "value": None,
                }
            raise

    def get_smart_checklist(self, issue_key: str) -> dict[str, Any]:
        """Get the Smart Checklist custom field value for an issue.

        Args:
            issue_key: The Jira issue key or ID.

        Returns:
            Dictionary containing the issue key, field ID, and checklist value.
        """
        self._validate_issue_access(issue_key)
        checklist_field_id = self._get_smart_checklist_field_id()

        issue = self.jira.get_issue(
            issue_key,
            expand=None,
            fields=checklist_field_id,
            properties=None,
            update_history=False,
        )
        if not isinstance(issue, dict):
            msg = f"Unexpected return value type from `jira.get_issue`: {type(issue)}"
            logger.error(msg)
            raise TypeError(msg)

        fields = issue.get("fields", {}) or {}
        return {
            "issue_key": issue.get("key", issue_key),
            "field_id": checklist_field_id,
            "value": fields.get(checklist_field_id),
        }

    def set_smart_checklist(
        self,
        issue_key: str,
        checklist: str,
    ) -> dict[str, Any]:
        """Set the Smart Checklist custom field value for an issue.

        Args:
            issue_key: The Jira issue key or ID.
            checklist: Checklist markdown accepted by Smart Checklist, e.g.
                ``- ToDo\n+ Done\nx Skipped\n~ In Progress\n``.

        Returns:
            Dictionary describing the successful update.
        """
        self._validate_issue_access(issue_key)
        if not isinstance(checklist, str):
            raise ValueError("Checklist value must be a string.")

        checklist_field_id = self._get_smart_checklist_field_id()
        self.jira.update_issue(
            issue_key=issue_key,
            update={"fields": {checklist_field_id: checklist}},
        )

        return {
            "success": True,
            "message": f"Smart Checklist updated for issue {issue_key}",
            "issue_key": issue_key,
            "field_id": checklist_field_id,
        }

    def _get_smart_checklist_field_id(self) -> str:
        """Get the configured Smart Checklist custom field ID."""
        field_id = self.config.smart_checklist_field_id
        if field_id:
            return field_id
        raise ValueError(
            f"{SMART_CHECKLIST_FIELD_ID_ENV} is required to use Smart Checklist "
            "tools. Set it to your Jira Checklists custom field ID, "
            "for example 'customfield_10001'."
        )

    def _validate_issue_access(self, issue_key: str) -> None:
        """Apply the configured project filter to issue-key based operations."""
        if not issue_key:
            raise ValueError("Issue key is required.")

        filter_to_use = self.config.projects_filter
        if not filter_to_use or "-" not in issue_key:
            return

        allowed_projects = [p.strip() for p in filter_to_use.split(",")]
        issue_project = issue_key.split("-", 1)[0]
        if issue_project not in allowed_projects:
            raise ValueError(
                "Issue with project prefix "
                f"'{issue_project}' are restricted by configuration"
            )
