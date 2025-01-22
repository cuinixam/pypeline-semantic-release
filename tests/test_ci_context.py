from pathlib import Path
from unittest.mock import patch

import pytest
from pypeline.domain.execution_context import ExecutionContext

from pypeline_semantic_release.steps import CheckCIContext, CIContext, CISystem
from tests.utils import assert_element_of_type


@pytest.fixture
def execution_context(tmp_path: Path) -> ExecutionContext:
    """Fixture for the ExecutionContext."""
    return ExecutionContext(tmp_path)


@pytest.fixture
def check_ci_context(execution_context: ExecutionContext) -> CheckCIContext:
    """Fixture for the CheckCIContext step."""
    return CheckCIContext(execution_context)


def test_jenkins_pull_request(check_ci_context: CheckCIContext) -> None:
    """Test Jenkins CI environment with a pull request."""
    with patch.object(CheckCIContext, "get_env_variable") as mock_get_env:
        mock_get_env.side_effect = lambda var, default=None: {
            "JENKINS_HOME": "/jenkins/home",
            "CHANGE_ID": "123",
            "CHANGE_TARGET": "main",
            "CHANGE_BRANCH": "feature-branch",
        }.get(var, default)

        check_ci_context.update_execution_context()

        ci_context = assert_element_of_type(check_ci_context.execution_context.data_registry.find_data(CIContext), CIContext)
        assert ci_context.ci_system == CISystem.JENKINS
        assert ci_context.is_pull_request
        assert ci_context.target_branch == "main"
        assert ci_context.current_branch == "feature-branch"


def test_non_jenkins_environment(check_ci_context: CheckCIContext) -> None:
    """Test non-Jenkins CI environment."""
    with patch.object(CheckCIContext, "get_env_variable") as mock_get_env:
        mock_get_env.side_effect = lambda var, default=None: {}.get(var, default)

        check_ci_context.update_execution_context()

        ci_context = assert_element_of_type(check_ci_context.execution_context.data_registry.find_data(CIContext), CIContext)
        assert ci_context is not None
        assert ci_context.ci_system == CISystem.UNKNOWN
        assert not ci_context.is_pull_request
        assert ci_context.target_branch is None
        assert ci_context.current_branch is None


def test_missing_branch_names(check_ci_context: CheckCIContext) -> None:
    """Test CI environment with missing branch names."""
    with patch.object(CheckCIContext, "get_env_variable") as mock_get_env:
        mock_get_env.side_effect = lambda var, default=None: {
            "JENKINS_HOME": "/jenkins/home",
        }.get(var, default)

        check_ci_context.update_execution_context()

        ci_context = assert_element_of_type(check_ci_context.execution_context.data_registry.find_data(CIContext), CIContext)
        assert ci_context is not None
        assert ci_context.ci_system == CISystem.JENKINS
        assert not ci_context.is_pull_request
        assert ci_context.target_branch is None
        assert ci_context.current_branch is None
