from pathlib import Path

import pytest
from git import Repo
from pypeline.domain.execution_context import ExecutionContext

from pypeline_semantic_release.steps import CIContext, CISystem


class PyPackageRepo:
    def __init__(self, repo: Repo):
        self.repo = repo

    def new_feature(self) -> "PyPackageRepo":
        """Create a new feature commit."""
        # Touch a new file
        feature_file = Path(self.repo.working_dir) / "feature.txt"
        feature_file.touch()
        self.repo.index.add([str(feature_file)])
        self.repo.index.commit("feat: some new feature")
        return self

    def new_tag(self, tag: str) -> "PyPackageRepo":
        """Create a new tag."""
        self.repo.create_tag(tag)
        return self

    def create_ci_execution_context(self) -> ExecutionContext:
        execution_context = ExecutionContext(Path(self.repo.working_dir))
        execution_context.data_registry.insert(CIContext(is_pull_request=False, ci_system=CISystem.JENKINS, target_branch="develop", current_branch="develop"), "ci_context")
        return execution_context

    def create_local_execution_context(self) -> ExecutionContext:
        return ExecutionContext(Path(self.repo.working_dir))

    def checkout_branch(self, branch: str) -> None:
        """Create and checkout a new branch."""
        self.repo.git.checkout("-b", branch)


@pytest.fixture
def py_package_tmp(tmp_path: Path) -> PyPackageRepo:
    """Fixture to create a temporary Git repository."""
    # Set up the repository directory
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize the Git repository
    repo = Repo.init(repo_path, initial_branch="develop")

    # Create pyproject.toml file
    pyproject_file = repo_path / "pyproject.toml"
    pyproject_content = """
    [tool.poetry]
    name = "example-project"
    version = "0.1.0"
    description = "An example project"
    authors = ["Your Name <your.email@example.com>"]

    [tool.coverage.run]
    branch = true

    [tool.semantic_release.branches.main]
    match = "develop"

    [tool.semantic_release.branches.noop]
    match = "(?!develop$)"
    prerelease = true
    """
    pyproject_file.write_text(pyproject_content)

    repo_path.joinpath("CHANGELOG.md").touch()

    # Create initial commit
    repo.index.add([str(pyproject_file), "CHANGELOG.md"])
    repo.index.commit("chore: initial commit")

    # Add origin remote
    repo.create_remote("origin", "git@github.com:user/repo.git")

    return PyPackageRepo(repo)
