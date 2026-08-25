"""Tests for Smart Checklist for Jira operations."""

from unittest.mock import Mock

import pytest
from requests.exceptions import HTTPError

from mcp_atlassian.jira import JiraFetcher
from mcp_atlassian.jira.smart_checklist import SMART_CHECKLIST_PROPERTY_KEY


class TestSmartChecklistMixin:
    """Tests for the SmartChecklistMixin class."""

    @pytest.fixture
    def smart_checklist_fetcher(self, jira_fetcher: JiraFetcher) -> JiraFetcher:
        """Create a JiraFetcher with Smart Checklist configuration."""
        jira_fetcher.config.smart_checklist_field_id = "customfield_10001"
        return jira_fetcher

    def test_get_smart_checklist_property_success(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test reading the legacy Smart Checklist issue property."""
        smart_checklist_fetcher.jira.get.return_value = {
            "key": SMART_CHECKLIST_PROPERTY_KEY,
            "value": [{"name": "Legacy item", "checked": False}],
        }

        result = smart_checklist_fetcher.get_smart_checklist_property("TEST-123")

        assert result == {
            "issue_key": "TEST-123",
            "property_key": SMART_CHECKLIST_PROPERTY_KEY,
            "value": [{"name": "Legacy item", "checked": False}],
        }
        smart_checklist_fetcher.jira.get.assert_called_once_with(
            "rest/api/2/issue/TEST-123/properties/"
            f"{SMART_CHECKLIST_PROPERTY_KEY}"
        )

    def test_get_smart_checklist_property_missing_returns_none(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test missing legacy property returns an empty value response."""
        smart_checklist_fetcher.jira.get.side_effect = HTTPError(
            response=Mock(status_code=404)
        )

        result = smart_checklist_fetcher.get_smart_checklist_property("TEST-123")

        assert result == {
            "issue_key": "TEST-123",
            "property_key": SMART_CHECKLIST_PROPERTY_KEY,
            "value": None,
        }

    def test_get_smart_checklist_reads_value_field_id(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test reading uses configured field ID + 1, where the value lives."""
        smart_checklist_fetcher.jira.get_issue.return_value = {
            "key": "TEST-123",
            "fields": {
                "customfield_10002": "- ToDo List\n+ Checked\n",
            },
        }

        result = smart_checklist_fetcher.get_smart_checklist("TEST-123")

        assert result == {
            "issue_key": "TEST-123",
            "field_id": "customfield_10002",
            "value": "- ToDo List\n+ Checked\n",
        }
        smart_checklist_fetcher.jira.get_issue.assert_called_once_with(
            "TEST-123",
            expand=None,
            fields="customfield_10002",
            properties=None,
            update_history=False,
        )

    def test_get_smart_checklist_rejects_underivable_field_id(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test non-numeric field IDs cannot be used to derive the value field."""
        smart_checklist_fetcher.config.smart_checklist_field_id = "not_a_field"

        with pytest.raises(
            ValueError, match="Cannot derive Smart Checklist value field"
        ):
            smart_checklist_fetcher.get_smart_checklist("TEST-123")

    def test_set_smart_checklist_replaces_via_railsware_api(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test replacing the checklist via the Railsware REST API."""
        smart_checklist_fetcher.jira.get_issue.return_value = {
            "key": "TEST-123",
            "fields": {"customfield_10001": {"checklistId": 6755062}},
        }

        result = smart_checklist_fetcher.set_smart_checklist(
            "TEST-123",
            "- ToDo List\n+ Checked\nx Skipped\n~ In Progress\n",
        )

        assert result == {
            "success": True,
            "message": "Smart Checklist replaced for issue TEST-123",
            "issue_key": "TEST-123",
            "checklist_id": 6755062,
            "field_id": "customfield_10001",
        }
        smart_checklist_fetcher.jira.get_issue.assert_called_once_with(
            "TEST-123",
            expand=None,
            fields="customfield_10001",
            properties=None,
            update_history=False,
        )
        smart_checklist_fetcher.jira.put.assert_called_once_with(
            "rest/railsware/1.0/checklist/6755062/item",
            data={
                "isReplace": True,
                "stringValue": (
                    "- ToDo List\n+ Checked\nx Skipped\n~ In Progress\n"
                ),
            },
        )
        smart_checklist_fetcher.jira.update_issue.assert_not_called()

    def test_set_smart_checklist_extracts_id_from_string_field(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test checklist ID extraction from a JSON string field value."""
        smart_checklist_fetcher.jira.get_issue.return_value = {
            "key": "TEST-123",
            "fields": {"customfield_10001": '{"checklistId": 6755062, "x": 1}'},
        }

        result = smart_checklist_fetcher.set_smart_checklist("TEST-123", "- AC 1\n")

        assert result["checklist_id"] == 6755062
        smart_checklist_fetcher.jira.put.assert_called_once_with(
            "rest/railsware/1.0/checklist/6755062/item",
            data={"isReplace": True, "stringValue": "- AC 1\n"},
        )

    def test_set_smart_checklist_fails_without_checklist_id(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test a clear error is raised when no checklist ID can be found."""
        smart_checklist_fetcher.jira.get_issue.return_value = {
            "key": "TEST-123",
            "fields": {"customfield_10001": None},
        }

        with pytest.raises(
            ValueError, match="Could not extract Smart Checklist ID"
        ):
            smart_checklist_fetcher.set_smart_checklist("TEST-123", "- AC 1\n")
        smart_checklist_fetcher.jira.put.assert_not_called()

    def test_set_smart_checklist_requires_string(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test that checklist updates require the documented string payload."""
        with pytest.raises(ValueError, match="Checklist value must be a string"):
            smart_checklist_fetcher.set_smart_checklist(
                "TEST-123",
                ["not", "a", "string"],  # type: ignore[arg-type]
            )

    def test_get_smart_checklist_requires_env_field_id(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test Smart Checklist custom field ID must be configured."""
        smart_checklist_fetcher.config.smart_checklist_field_id = None

        with pytest.raises(
            ValueError, match="JIRA_SMART_CHECKLIST_FIELD_ID is required"
        ):
            smart_checklist_fetcher.get_smart_checklist("TEST-123")

    def test_smart_checklist_respects_project_filter(
        self, smart_checklist_fetcher: JiraFetcher
    ):
        """Test Smart Checklist operations respect configured project filters."""
        smart_checklist_fetcher.config.projects_filter = "DEV"

        with pytest.raises(ValueError, match="restricted by configuration"):
            smart_checklist_fetcher.get_smart_checklist("TEST-123")
