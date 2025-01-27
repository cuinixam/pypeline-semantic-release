from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pypeline.domain.execution_context import ExecutionContext
from semantic_release.version.version import Version

from pypeline_semantic_release.steps import CIContext, CISystem, PublishPackage, PublishPackageConfig, ReleaseCommit


@pytest.fixture
def mock_execution_context() -> Mock:
    execution_context = Mock(spec=ExecutionContext)
    execution_context.data_registry = Mock()
    execution_context.data_registry.find_data.side_effect = lambda data_type: {
        ReleaseCommit: [ReleaseCommit(version=Version.parse("0.1.0"))],
        CIContext: [CIContext(ci_system=CISystem.JENKINS, is_pull_request=False, target_branch="main", current_branch="main")],
    }.get(data_type, [])
    execution_context.project_root_dir = Path("/mock/project/root")
    process_executor = Mock()
    process_executor.execute.return_value = 0
    execution_context.create_process_executor.return_value = process_executor

    return execution_context


def test_publish_package_success(mock_execution_context: Mock) -> None:
    iut_step = PublishPackage(mock_execution_context)
    mock_executor = mock_execution_context.create_process_executor.return_value

    # Execute the step
    iut_step.run()

    # Expect that publish command is called
    mock_executor.execute.assert_called_once()
    mock_execution_context.create_process_executor.assert_called_once_with([*PublishPackage.get_poetry_command(), "publish", "--build"])


def test_publish_package_with_credentials(mock_execution_context: Mock) -> None:
    iut_step = PublishPackage(
        mock_execution_context,
        config=PublishPackageConfig(pypi_repository_name="test-repo", pypi_user_env="MY_PYPI_USER", pypi_password_env="MY_PYPI_PASSWD").to_dict(),  # noqa: S106
    )
    mock_executor = mock_execution_context.create_process_executor.return_value

    # Set environment variables to simulate credentials
    with patch.dict("os.environ", {"MY_PYPI_USER": "user", "MY_PYPI_PASSWD": "password"}):
        # Execute the step
        iut_step.run()

    # Expect that publish command is called with credentials
    mock_executor.execute.assert_called_once()
    mock_execution_context.create_process_executor.assert_called_once_with(
        [*PublishPackage.get_poetry_command(), "publish", "--build", "--username", "user", "--password", "password", "--repository", "test-repo"]
    )


def test_publish_package_missing_credentials(mock_execution_context: Mock) -> None:
    iut_step = PublishPackage(
        mock_execution_context,
        config=PublishPackageConfig(pypi_repository_name="test-repo", pypi_user_env="MY_PYPI_USER", pypi_password_env="MY_PYPI_PASSWD").to_dict(),  # noqa: S106
    )

    # Set environment variables to simulate missing credentials. Password is empty.
    with patch.dict("os.environ", {"MY_PYPI_USER": "user", "MY_PYPI_PASSWD": ""}):
        # Execute the step
        iut_step.run()

    # Should not attempt to publish package with empty credentials
    mock_execution_context.create_process_executor.assert_not_called()


def test_publish_package_no_release_commit(mock_execution_context: Mock) -> None:
    mock_execution_context.data_registry.find_data.side_effect = lambda data_type: {
        CIContext: [CIContext(ci_system=CISystem.JENKINS, is_pull_request=False, target_branch="main", current_branch="main")],
    }.get(data_type, [])

    iut_step = PublishPackage(mock_execution_context)

    # Execute the step
    iut_step.run()

    # Verify that create_process_executor was not called
    mock_execution_context.create_process_executor.assert_not_called()


def test_publish_package_no_ci_context(mock_execution_context: Mock) -> None:
    """Test that the PublishPackage step skips publishing when no CI context is found."""
    # Modify execution context to return no CI context
    mock_execution_context.data_registry.find_data.side_effect = lambda data_type: {
        ReleaseCommit: [ReleaseCommit(version=Version.parse("0.1.0"))],
    }.get(data_type, [])

    iut_step = PublishPackage(mock_execution_context)

    # Execute the step
    iut_step.run()

    # Verify that create_process_executor was not called
    mock_execution_context.create_process_executor.assert_not_called()


def test_publish_package_not_on_ci(mock_execution_context: Mock) -> None:
    """Test that the PublishPackage step skips publishing when not on a CI system."""
    # Modify execution context to simulate a non-CI environment
    mock_execution_context.data_registry.find_data.side_effect = lambda data_type: {
        ReleaseCommit: [ReleaseCommit(version=Version.parse("0.1.0"))],
        CIContext: [CIContext(ci_system=CISystem.UNKNOWN, is_pull_request=False, target_branch="main", current_branch="main")],
    }.get(data_type, [])

    iut_step = PublishPackage(mock_execution_context)

    # Execute the step
    iut_step.run()

    # Verify that create_process_executor was not called
    mock_execution_context.create_process_executor.assert_not_called()
