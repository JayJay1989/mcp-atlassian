"""Module for Smart Checklist for Jira operations."""

import json
import logging
import re
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

        Note:
            The checklist value is exposed by the Smart Checklist plugin in the
            custom field directly after the configured one (configured field ID
            + 1), e.g. ``customfield_18600`` -> ``customfield_18601``.
        """
        self._validate_issue_access(issue_key)
        checklist_field_id = self._get_smart_checklist_value_field_id()

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
        """Replace the Smart Checklist of an issue via the Railsware REST API.

        Smart Checklist updates are NOT done through the Jira custom field.
        The ``checklistId`` is extracted from the configured custom field
        (e.g. ``customfield_18600``), then the full checklist is replaced via
        ``PUT rest/railsware/1.0/checklist/{checklistId}/item`` with
        ``isReplace: true``.

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

        base_field_id = self._get_smart_checklist_field_id()
        issue = self.jira.get_issue(
            issue_key,
            expand=None,
            fields=base_field_id,
            properties=None,
            update_history=False,
        )
        if not isinstance(issue, dict):
            msg = f"Unexpected return value type from `jira.get_issue`: {type(issue)}"
            logger.error(msg)
            raise TypeError(msg)

        fields = issue.get("fields", {}) or {}
        checklist_id = self._extract_checklist_id(
            fields.get(base_field_id), issue_key, base_field_id
        )

        self.jira.put(
            f"rest/railsware/1.0/checklist/{checklist_id}/item",
            data={"isReplace": True, "stringValue": checklist},
        )

        return {
            "success": True,
            "message": f"Smart Checklist replaced for issue {issue_key}",
            "issue_key": issue_key,
            "checklist_id": checklist_id,
            "field_id": base_field_id,
        }

    @staticmethod
    def _extract_checklist_id(
        value: Any, issue_key: str, checklist_field_id: str
    ) -> int:
        """Extract the ``checklistId`` from the configured custom field value.

        The configured custom field (e.g. ``customfield_18600``) contains the
        checklist data, including its unique ``checklistId``
        (e.g. ``6755062``). Handles dicts, JSON strings, and plain numeric
        IDs.
        """
        if value is not None:
            if isinstance(value, dict):
                checklist_id = value.get("checklistId") or value.get("id")
                if checklist_id is not None:
                    return int(checklist_id)
                text = json.dumps(value)
            elif isinstance(value, (int, str)):
                text = str(value)
                if text.isdigit():
                    return int(text)
            else:
                text = json.dumps(value, default=str)
            match = re.search(r'"?(?:checklistId|id)"?\s*[:=]\s*"?(\d+)', text)
            if match:
                return int(match.group(1))

        raise ValueError(
            f"Could not extract Smart Checklist ID from field "
            f"'{checklist_field_id}' of issue {issue_key}. "
            "Verify the Smart Checklist plugin is enabled for this issue."
        )

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

    def _get_smart_checklist_value_field_id(self) -> str:
        """Get the field ID that holds the readable Smart Checklist value.

        The Smart Checklist plugin stores the readable checklist value in the
        custom field directly after the configured one (configured field ID
        + 1), e.g. ``customfield_18600`` -> ``customfield_18601``.
        """
        field_id = self._get_smart_checklist_field_id()
        prefix, _, number = field_id.rpartition("_")
        if not prefix or not number.isdigit():
            raise ValueError(
                f"Cannot derive Smart Checklist value field from '{field_id}'. "
                "Expected a custom field ID like 'customfield_18600'."
            )
        return f"{prefix}_{int(number) + 1}"

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
