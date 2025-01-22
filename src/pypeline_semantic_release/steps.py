import os
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Type, TypeVar
from unittest.mock import Mock
from urllib.parse import quote_plus

from git import Repo
from mashumaro.mixins.dict import DataClassDictMixin
from py_app_dev.core.exceptions import UserNotificationException
from py_app_dev.core.logging import logger
from pypeline.domain.execution_context import ExecutionContext
from pypeline.domain.pipeline import PipelineStep
from semantic_release.cli.cli_context import CliContextObj
from semantic_release.cli.commands.version import last_released
from semantic_release.cli.config import GlobalCommandLineOptions, RuntimeContext
from semantic_release.errors import NotAReleaseBranch
from semantic_release.version.algorithm import next_version
from semantic_release.version.version import Version


@contextmanager
def change_directory(path: Path) -> Iterator[None]:
    """Temporarily change the working directory to the given path and revert to the original directory when done."""
    original_path = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(original_path)


class BaseStep(PipelineStep[ExecutionContext]):
    """Base step defining all required methods."""

    def __init__(self, execution_context: ExecutionContext, group_name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(execution_context, group_name, config)
        self.logger = logger.bind()

    def run(self) -> None:
        pass

    def get_inputs(self) -> List[Path]:
        return []

    def get_outputs(self) -> List[Path]:
        return []

    def get_name(self) -> str:
        return self.__class__.__name__

    def update_execution_context(self) -> None:
        pass

    def get_needs_dependency_management(self) -> bool:
        """It shall always run, independent off any dependencies."""
        return False

    def execute_process(self, command: List[str | Path], error_msg: str) -> None:
        proc_executor = self.execution_context.create_process_executor(command)
        proc_executor.shell = False
        process = proc_executor.execute(handle_errors=False)
        if process and process.returncode != 0:
            raise UserNotificationException(f"{error_msg} Return code: {process.returncode}")


# Create ENUM for the CI system
class CISystem(Enum):
    UNKNOWN = auto()
    JENKINS = auto()


@dataclass
class CIContext:
    #: CI system where the build is running
    ci_system: CISystem
    #: Whether the build is for a pull request
    is_pull_request: bool
    #: The branch being build or the branch from the PR to merge into (e.g. main)
    target_branch: Optional[str]
    #: Branch being built or the branch from the PR that needs to be merged (e.g. feature/branch)
    current_branch: Optional[str]

    @property
    def is_ci(self) -> bool:
        """Whether the build is running on a CI system."""
        return self.ci_system != CISystem.UNKNOWN


class CheckCIContext(BaseStep):
    """Provide the CI context for the current build."""

    def get_env_variable(self, var_name: str, default: Optional[str] = None) -> Optional[str]:
        """Fetch environment variables to make testing easier."""
        return os.getenv(var_name, default)

    def update_execution_context(self) -> None:
        """Check if the current build runs on Jenkins and then determine the CI context."""
        ci_system = CISystem.JENKINS if self.get_env_variable("JENKINS_HOME") is not None else CISystem.UNKNOWN
        is_pull_request = self.get_env_variable("CHANGE_ID") is not None

        if is_pull_request:
            target_branch = self.get_env_variable("CHANGE_TARGET")
            current_branch = self.get_env_variable("CHANGE_BRANCH")
        else:
            target_branch = self.get_env_variable("BRANCH_NAME")
            current_branch = target_branch

        if not target_branch or not current_branch:
            if ci_system != CISystem.UNKNOWN:
                self.logger.warning("Detected CI Build but branch names not found.")

        self.execution_context.data_registry.insert(
            CIContext(
                ci_system=ci_system,
                is_pull_request=is_pull_request,
                target_branch=target_branch,
                current_branch=current_branch,
            ),
            self.get_name(),
        )


@dataclass
class ReleaseCommit:
    version: Version
    previous_version: Optional[Version] = None


@dataclass
class CreateReleaseCommitConfig(DataClassDictMixin):
    """Configuration for the CreateReleaseCommit step."""

    #: Whether or not to push the new commit and tag to the remote
    push: bool = False


class CreateReleaseCommit(BaseStep):
    """Create new commit using semantic release."""

    def __init__(self, execution_context: ExecutionContext, group_name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(execution_context, group_name, config)
        self.release_commit: Optional[ReleaseCommit] = None

    def run(self) -> None:
        with change_directory(self.execution_context.project_root_dir):
            self.logger.info(f"Running {self.get_name()} step.")
            ci_contexts = self.execution_context.data_registry.find_data(CIContext)
            if len(ci_contexts) > 0:
                ci_context = ci_contexts[0]
                self.logger.info(f"CI context: {ci_context}")
                self.run_semantic_release(ci_context)
            else:
                self.logger.info("CI context Unknown. Skip releasing the package.")

    def update_execution_context(self) -> None:
        """Update the execution context with the release commit."""
        if self.release_commit:
            self.execution_context.data_registry.insert(self.release_commit, self.get_name())

    def run_semantic_release(self, ci_context: CIContext) -> None:
        # (!) Using mocks for the ctx and logger objects is working as long as the semantic-release options are provided in the pyproject.toml file.
        context = CliContextObj(Mock(), Mock(), GlobalCommandLineOptions())
        config = context.raw_config
        # TODO: Do not print the raw config in production code.
        self.logger.debug(f"Semantic release raw config: {config}")
        last_release = self.last_released_version(config.repo_dir, tag_format=config.tag_format)
        self.logger.debug(f"Last released version: {last_release}")
        next_version = self.next_version(context)
        if next_version:
            self.logger.info(f"Next version: {next_version}")
            self.logger.info(f"Next version tag: {next_version.as_tag()}")
            if ci_context.is_ci and not ci_context.is_pull_request:
                if not last_release or next_version > last_release:
                    self.logger.info("Running semantic release.")
                    self.do_release()
                    # Store the release commit to be updated in the data registry
                    self.release_commit = ReleaseCommit(version=next_version, previous_version=last_release)
                else:
                    self.logger.info("No release needed.")
        else:
            if ci_context:
                self.logger.warning(f"Current branch {ci_context.current_branch} is not configured to be released.")
            else:
                self.logger.warning("No CI context, assuming local run. Skip releasing the package.")

    def last_released_version(self, repo_dir: Path, tag_format: str) -> Optional[Version]:
        last_release_str = last_released(repo_dir, tag_format)
        return last_release_str[1] if last_release_str else None

    def next_version(self, context: CliContextObj) -> Optional[Version]:
        try:
            runtime = RuntimeContext.from_raw_config(
                context.raw_config,
                global_cli_options=context.global_opts,
            )
        except NotAReleaseBranch:
            # If the current branch is not configured to be released, just return None.
            return None
        # For all other exception raise UserNotification
        except Exception as exc:
            raise UserNotificationException(f"Failed to determine next version. Exception: {exc}") from exc

        self.logger.debug(f"Semantic release runtime context: {runtime}")
        with Repo(str(runtime.repo_dir)) as git_repo:
            new_version = next_version(
                repo=git_repo,
                translator=runtime.version_translator,
                commit_parser=runtime.commit_parser,
                prerelease=runtime.prerelease,
                major_on_zero=runtime.major_on_zero,
                allow_zero_version=runtime.allow_zero_version,
            )
        return new_version

    def do_release(self) -> None:
        config = CreateReleaseCommitConfig.from_dict(self.config) if self.config else CreateReleaseCommitConfig()
        # We have to update the BITBUCKET_TOKEN environment variable because it will be used in the push URL and requires all special characters to be URL encoded.
        os.environ["BITBUCKET_TOKEN"] = quote_plus(os.getenv("BITBUCKET_TOKEN", ""))
        semantic_release_args = ["--skip-build", "--no-vcs-release"]
        semantic_release_args.append("--push" if config.push else "--no-push")
        # For Windows call the semantic-release executable
        semantic_release_cmd = ["semantic-release"] if os.name == "nt" else ["python", "-m", "semantic_release"]
        self.execute_process(
            [
                *semantic_release_cmd,
                "version",
                *semantic_release_args,
            ],
            "Failed to create release commit.",
        )
        self.logger.info("[OK] New release commit created and pushed to remote.")


@dataclass
class PublishPackageConfig(DataClassDictMixin):
    """Configuration for the PublishPackage step."""

    #: PyPi repository name for releasing the package. If not set, the package will be released to the python-semantic-release default PyPi repository.
    pypi_repository_name: Optional[str] = None
    #: Environment variable name for the pypi repository user
    pypi_user_env: str = "PYPI_USER"
    #: Environment variable name for the pypi repository password
    pypi_password_env: str = "PYPI_PASSWD"  # noqa: S105


T = TypeVar("T")


class PublishPackage(BaseStep):
    """Publish the package to PyPI."""

    def run(self) -> None:
        self.logger.info(f"Running {self.get_name()} step.")
        release_commit = self.find_data(ReleaseCommit)
        if release_commit:
            self.logger.info(f"Found release commit: {release_commit}")
            ci_context = self.find_data(CIContext)
            if ci_context:
                if ci_context.is_ci and not ci_context.is_pull_request:
                    self.publish_package()
                else:
                    self.logger.info("Not running on CI or pull request. Skip publishing the package.")
            else:
                self.logger.info("CI context Unknown. Skip publishing the package.")
        else:
            self.logger.info("No release commit found. There is nothing to be published.")

    def publish_package(self) -> None:
        config = PublishPackageConfig.from_dict(self.config) if self.config else PublishPackageConfig()
        publish_auth_args = []
        if config.pypi_repository_name:
            pypi_user = os.getenv(config.pypi_user_env, None)
            pypi_password = os.getenv(config.pypi_password_env, None)
            if not pypi_user or not pypi_password:
                self.logger.warning(
                    f"Custom pypi repository {config.pypi_repository_name} configured but no credentials. "
                    f"{config.pypi_user_env} or {config.pypi_password_env} environment variables not set. "
                    "Skip releasing and publishing to PyPI."
                )
                return
            publish_auth_args = ["--username", pypi_user, "--password", pypi_password, "--repository", config.pypi_repository_name]
        # For Windows call the poetry executable
        poetry_cmd = ["poetry"] if os.name == "nt" else ["python", "-m", "poetry"]
        self.execute_process([*poetry_cmd, "publish", "--build", *publish_auth_args], "Failed to publish package to PyPI.")
        self.logger.info("[OK] Package published to PyPI.")

    def find_data(self, data_type: Type[T]) -> Optional[T]:
        tmp_data = self.execution_context.data_registry.find_data(data_type)
        if len(tmp_data) > 0:
            return tmp_data[0]
        else:
            return None
