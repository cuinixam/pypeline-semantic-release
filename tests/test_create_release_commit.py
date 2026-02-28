from pathlib import Path
from unittest.mock import Mock

import pytest
from pypeline.domain.execution_context import ExecutionContext
from semantic_release.cli.config import BranchConfig, RemoteConfig

from pypeline_semantic_release.steps import CreateReleaseCommit, CreateReleaseCommitConfig, ReleaseCommit
from tests.conftest import PyPackageRepo
from tests.utils import assert_element_of_type


@pytest.fixture
def repo_with_feature_branch(py_package_tmp: PyPackageRepo) -> PyPackageRepo:
    """Fixture to prepare a repository with no commits."""
    assert py_package_tmp
    assert py_package_tmp.repo.active_branch.name == "develop"
    iut_step = CreateReleaseCommit(py_package_tmp.create_ci_execution_context(), config=CreateReleaseCommitConfig(push=False).to_dict())
    # Execute step
    iut_step.run()
    iut_step.update_execution_context()
    # Check release commit
    release_commit = assert_element_of_type(iut_step.execution_context.data_registry.find_data(ReleaseCommit), ReleaseCommit)
    assert release_commit
    assert release_commit.version.as_tag() == "v0.0.0"
    assert release_commit.previous_version is None
    # Create a new feature commit
    py_package_tmp.new_feature()
    # Create and execute step again
    iut_step = CreateReleaseCommit(py_package_tmp.create_ci_execution_context(), config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.run()
    iut_step.update_execution_context()
    # Check release commit
    release_commit = assert_element_of_type(iut_step.execution_context.data_registry.find_data(ReleaseCommit), ReleaseCommit)
    assert release_commit.version.as_tag() == "v0.1.0"
    # Checkout a feature branch and push commit
    py_package_tmp.checkout_branch("feature/feature1")
    assert py_package_tmp.repo.active_branch.name == "feature/feature1"
    # Create a new feature commit
    py_package_tmp.new_feature()
    return py_package_tmp


def test_create_release_commit(py_package_tmp: PyPackageRepo) -> None:
    assert py_package_tmp
    assert py_package_tmp.repo.active_branch.name == "develop"
    iut_step = CreateReleaseCommit(py_package_tmp.create_ci_execution_context(), config=CreateReleaseCommitConfig(push=False).to_dict())
    # Execute step
    iut_step.run()
    iut_step.update_execution_context()
    # Check release commit
    release_commit = assert_element_of_type(iut_step.execution_context.data_registry.find_data(ReleaseCommit), ReleaseCommit)
    assert release_commit
    assert release_commit.version.as_tag() == "v0.0.0"
    assert release_commit.previous_version is None
    # Create a new feature commit
    py_package_tmp.new_feature()
    # Create and execute step again
    iut_step = CreateReleaseCommit(py_package_tmp.create_ci_execution_context(), config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.run()
    iut_step.update_execution_context()
    # Check release commit
    release_commit = assert_element_of_type(iut_step.execution_context.data_registry.find_data(ReleaseCommit), ReleaseCommit)
    assert release_commit.version.as_tag() == "v0.1.0"
    assert release_commit.previous_version and release_commit.previous_version.as_tag() == "v0.0.0"
    # Execute again and there shall be no new release commit
    iut_step = CreateReleaseCommit(py_package_tmp.create_ci_execution_context(), config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.run()
    iut_step.update_execution_context()
    # No release commit shall be created because there are no new commits
    assert iut_step.execution_context.data_registry.find_data(ReleaseCommit) == []


def test_create_release_commit_with_release_candidates(py_package_tmp: PyPackageRepo) -> None:
    assert py_package_tmp
    assert py_package_tmp.repo.active_branch.name == "develop"
    iut_step = CreateReleaseCommit(py_package_tmp.create_ci_execution_context(), config=CreateReleaseCommitConfig(push=False).to_dict())
    # Create a new release tag
    py_package_tmp.new_tag("v0.1.0")
    # Execute step
    # Create a new feature commit
    py_package_tmp.new_feature()
    # Create a new release candidate tag
    py_package_tmp.new_tag("v0.3.0-rc.1")
    # Execute step
    iut_step.run()
    iut_step.update_execution_context()
    # Check release commit
    release_commit = assert_element_of_type(iut_step.execution_context.data_registry.find_data(ReleaseCommit), ReleaseCommit)
    assert release_commit
    assert release_commit.version.as_tag() == "v0.2.0"
    assert release_commit.previous_version
    assert release_commit.previous_version.as_tag() == "v0.3.0-rc.1"


def test_update_prerelease_token(py_package_tmp: PyPackageRepo) -> None:
    assert py_package_tmp
    branches = {
        "main": BranchConfig(match="main", prerelease_token="rc", prerelease=True),  # noqa: S106
        "develop": BranchConfig(match="develop", prerelease_token="", prerelease=False),
        "feature": BranchConfig(match="feature", prerelease_token="", prerelease=True),
    }

    # Create the step and set the input for prerelease_token
    iut_step = CreateReleaseCommit(py_package_tmp.create_ci_execution_context(), config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.execution_context.inputs = {"prerelease_token": "alpha"}

    # Call the method to update prerelease tokens
    iut_step.update_prerelease_token(branches)

    # Assert that the prerelease tokens have been updated
    assert branches["main"].prerelease_token == "alpha"  # noqa: S105
    assert branches["develop"].prerelease_token == ""
    assert branches["feature"].prerelease_token == "alpha"  # noqa: S105


def test_create_release_commit_with_prerelease_token(repo_with_feature_branch: PyPackageRepo) -> None:
    # Enable prerelease
    repo = repo_with_feature_branch
    execution_context = repo.create_ci_execution_context({"prerelease_token": "rc1.dev", "do_prerelease": True})
    # Create and execute step again
    iut_step = CreateReleaseCommit(execution_context, config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.run()
    iut_step.update_execution_context()
    # Check release commit
    release_commit = assert_element_of_type(iut_step.execution_context.data_registry.find_data(ReleaseCommit), ReleaseCommit)
    assert release_commit
    assert release_commit.version.as_tag() == "v0.2.0-rc1.dev.1"
    assert release_commit.previous_version
    assert release_commit.previous_version.as_tag() == "v0.1.0"
    # Create a new feature commit
    repo.new_feature()
    # Enable prerelease
    execution_context = repo.create_ci_execution_context({"prerelease_token": "rc1.dev", "do_prerelease": True})
    # Create and execute step again
    iut_step = CreateReleaseCommit(execution_context, config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.run()
    iut_step.update_execution_context()
    # Check release commit
    release_commit = assert_element_of_type(iut_step.execution_context.data_registry.find_data(ReleaseCommit), ReleaseCommit)
    assert release_commit
    assert release_commit.version.as_tag() == "v0.2.0-rc1.dev.2"
    assert release_commit.previous_version
    assert release_commit.previous_version.as_tag() == "v0.2.0-rc1.dev.1"


def test_prerelease_not_created_automatically(repo_with_feature_branch: PyPackageRepo) -> None:
    repo = repo_with_feature_branch
    execution_context = repo.create_ci_execution_context({"prerelease_token": "rc1.dev"})
    # Create and execute step again
    iut_step = CreateReleaseCommit(execution_context, config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.run()
    iut_step.update_execution_context()
    # Expect no release commit
    assert not iut_step.execution_context.data_registry.find_data(ReleaseCommit)
    # Enable prerelease to create a release commit
    execution_context = repo.create_ci_execution_context({"do_prerelease": True})
    # Create and execute step again
    iut_step = CreateReleaseCommit(execution_context, config=CreateReleaseCommitConfig(push=False).to_dict())
    iut_step.run()
    iut_step.update_execution_context()
    # Expect no release commit
    assert iut_step.execution_context.data_registry.find_data(ReleaseCommit)


# --- Unit tests for do_release() CLI flag generation ---


@pytest.fixture
def mock_execution_context() -> Mock:
    execution_context = Mock(spec=ExecutionContext)
    execution_context.project_root_dir = Path("/mock/project")
    execution_context.get_input.return_value = None
    process_executor = Mock()
    process_executor.execute.return_value = None
    execution_context.create_process_executor.return_value = process_executor
    return execution_context


def _get_semantic_release_args(mock_execution_context: Mock) -> list[str]:
    """Extract the arguments passed to create_process_executor."""
    return mock_execution_context.create_process_executor.call_args[0][0]


@pytest.mark.parametrize(
    ("config", "expected_flags", "unexpected_flags"),
    [
        pytest.param(
            CreateReleaseCommitConfig(push=False),
            ["--skip-build", "--no-vcs-release", "--no-push"],
            [],
            id="defaults-skip-build-and-no-vcs-release",
        ),
        pytest.param(
            CreateReleaseCommitConfig(push=False, build=True),
            ["--no-vcs-release", "--no-push"],
            ["--skip-build"],
            id="build-enabled-removes-skip-build",
        ),
        pytest.param(
            CreateReleaseCommitConfig(push=False, vcs_release=True),
            ["--skip-build", "--no-push"],
            ["--no-vcs-release"],
            id="vcs-release-enabled-removes-no-vcs-release",
        ),
        pytest.param(
            CreateReleaseCommitConfig(push=False, build=True, vcs_release=True),
            ["--no-push"],
            ["--skip-build", "--no-vcs-release"],
            id="build-and-vcs-release-enabled",
        ),
        pytest.param(
            CreateReleaseCommitConfig(push=True, build=True, vcs_release=True),
            ["--push"],
            ["--skip-build", "--no-vcs-release", "--no-push"],
            id="all-enabled-with-push",
        ),
    ],
)
def test_do_release_cli_flags(
    mock_execution_context: Mock,
    config: CreateReleaseCommitConfig,
    expected_flags: list[str],
    unexpected_flags: list[str],
) -> None:
    step = CreateReleaseCommit(mock_execution_context, config=config.to_dict())
    remote_config = Mock(spec=RemoteConfig)
    remote_config.type = "github"

    step.do_release(remote_config)

    args = _get_semantic_release_args(mock_execution_context)
    for flag in expected_flags:
        assert flag in args, f"Expected {flag} in {args}"
    for flag in unexpected_flags:
        assert flag not in args, f"Did not expect {flag} in {args}"


def test_do_release_includes_prerelease_token(mock_execution_context: Mock) -> None:
    mock_execution_context.get_input.return_value = "beta"
    step = CreateReleaseCommit(mock_execution_context, config=CreateReleaseCommitConfig(push=False).to_dict())
    remote_config = Mock(spec=RemoteConfig)
    remote_config.type = "github"

    step.do_release(remote_config)

    args = _get_semantic_release_args(mock_execution_context)
    token_idx = args.index("--prerelease-token")
    assert args[token_idx + 1] == "beta"
