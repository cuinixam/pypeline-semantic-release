import os
from abc import ABC, abstractmethod
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
from semantic_release import VersionTranslator, tags_and_versions
from semantic_release.cli.cli_context import CliContextObj
from semantic_release.cli.commands.version import last_released
from semantic_release.cli.config import BranchConfig, GlobalCommandLineOptions, HvcsClient, RemoteConfig, RuntimeContext
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
        # When started from a shell (e.g. cmd on Jenkins) the shell parameter must be set to True
        proc_executor.shell = True if os.name == "nt" else False
        process = proc_executor.execute(handle_errors=False)
        if process and process.returncode != 0:
            raise UserNotificationException(f"{error_msg} Return code: {process.returncode}")


@dataclass
class CIContext:
    #: CI system where the build is running
    ci_system: "CISystem"
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


class CIDetector(ABC):
    """Abstract base class for CI system detectors."""

    @abstractmethod
    def detect(self) -> Optional[CIContext]:
        """Detects the CI system and returns a CIContext, or None if not detected."""
        pass

    @staticmethod
    def get_env_variable(var_name: str, default: Optional[str] = None) -> Optional[str]:
        """Helper function to get environment variables."""
        return os.getenv(var_name, default)


class JenkinsDetector(CIDetector):
    """Detects Jenkins CI."""

    def detect(self) -> Optional[CIContext]:
        if self.get_env_variable("JENKINS_HOME") is not None:
            is_pull_request = self.get_env_variable("CHANGE_ID") is not None
            if is_pull_request:
                target_branch = self.get_env_variable("CHANGE_TARGET")
                current_branch = self.get_env_variable("CHANGE_BRANCH")
            else:
                target_branch = self.get_env_variable("BRANCH_NAME")
                current_branch = target_branch

            return CIContext(
                ci_system=CISystem.JENKINS,
                is_pull_request=is_pull_request,
                target_branch=target_branch,
                current_branch=current_branch,
            )
        return None


class GitHubActionsDetector(CIDetector):
    """Detects GitHub Actions CI."""

    def detect(self) -> Optional[CIContext]:
        if self.get_env_variable("GITHUB_ACTIONS") == "true":
            is_pull_request = self.get_env_variable("GITHUB_EVENT_NAME") == "pull_request"
            if is_pull_request:
                target_branch = self.get_env_variable("GITHUB_BASE_REF")
                current_branch = self.get_env_variable("GITHUB_HEAD_REF")
            else:
                target_branch = self.get_env_variable("GITHUB_REF_NAME")
                current_branch = target_branch

            return CIContext(
                ci_system=CISystem.GITHUB_ACTIONS,
                is_pull_request=is_pull_request,
                target_branch=target_branch,
                current_branch=current_branch,
            )
        return None


class CISystem(Enum):
    UNKNOWN = (auto(), None)  # Special case for unknown
    JENKINS = (auto(), JenkinsDetector)
    GITHUB_ACTIONS = (auto(), GitHubActionsDetector)
    # Add new CI systems here:  MY_CI = (auto(), MyCIDetector)

    def __init__(self, _: Any, detector_class: Optional[Type[CIDetector]]):
        self._value_ = _  # Use auto() value, but ignore it in __init__
        self.detector_class = detector_class

    def get_detector(self) -> Optional[CIDetector]:
        return self.detector_class() if self.detector_class else None


class CheckCIContext(BaseStep):
    """Provide the CI context for the current build."""

    def update_execution_context(self) -> None:
        ci_context: Optional[CIContext] = None

        # Iterate through the CISystem enum and use the first detected CI system
        for ci_system in CISystem:
            detector = ci_system.get_detector()
            if detector:
                ci_context = detector.detect()
                if ci_context:
                    break  # Stop at the first detected CI

        if ci_context is None:
            ci_context = CIContext(
                ci_system=CISystem.UNKNOWN,
                is_pull_request=False,
                target_branch=None,
                current_branch=None,
            )

        if not ci_context.target_branch or not ci_context.current_branch:
            if ci_context.ci_system != CISystem.UNKNOWN:
                self.logger.warning("Detected CI Build but branch names not found.")

        self.execution_context.data_registry.insert(ci_context, self.get_name())


@dataclass
class ReleaseCommit:
    version: Version
    previous_version: Optional[Version] = None


@dataclass
class CreateReleaseCommitConfig(DataClassDictMixin):
    """Configuration for the CreateReleaseCommit step."""

    #: Whether or not to push the new commit and tag to the remote
    push: bool = True


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
        self.update_prerelease_token(config.branches)
        last_release = self.last_released_version(config.repo_dir, tag_format=config.tag_format)
        self.logger.info(f"Last released version: {last_release}")
        next_version = self.next_version(context)

        if not next_version:
            if ci_context:
                self.logger.info(f"Current branch {ci_context.current_branch} is not configured to be released.")
            else:
                self.logger.info("No CI context, assuming local run. Skip releasing the package.")
            return

        self.logger.info(f"Next version: {next_version}")
        self.logger.info(f"Next version tag: {next_version.as_tag()}")

        if not ci_context.is_ci:
            self.logger.info("No CI context, assuming local run. Skip releasing the package.")
            return

        if ci_context.is_pull_request:
            self.logger.info("Pull request detected. Skip releasing the package.")
            return

        # Collect all tags and versions to check if the next version already exists
        all_versions = self.collect_all_tags_and_versions(config.repo_dir, config.tag_format)
        if self.does_version_exist(next_version, all_versions):
            self.logger.info(f"Version {next_version} already exists. No release needed.")
            return

        if next_version.is_prerelease:
            self.logger.info(f"Detected pre-release version: {next_version}.")
            do_prerelease = self.execution_context.get_input("do_prerelease")
            if not do_prerelease:
                self.logger.info("Pre-release version detected but 'do_prerelease' is not set. Skip releasing the package.")
                return

        self.logger.info("Version doesn't exist yet. Running semantic release.")
        self.do_release(config.remote)
        # Store the release commit to be updated in the data registry
        self.release_commit = ReleaseCommit(version=next_version, previous_version=last_release)

    def update_prerelease_token(self, branches: Dict[str, BranchConfig]) -> None:
        """Iterate over all branches and update the prerelease token."""
        prerelease_token = self.execution_context.get_input("prerelease_token")
        if prerelease_token:
            for branch in branches.values():
                if branch.prerelease_token or branch.prerelease:
                    branch.prerelease_token = prerelease_token
                    self.logger.info(f"Updated prerelease token for branches matching {branch.match} to {prerelease_token}")

    def last_released_version(self, repo_dir: Path, tag_format: str) -> Optional[Version]:
        last_release_str = last_released(repo_dir, tag_format)
        return last_release_str[1] if last_release_str else None

    def collect_all_tags_and_versions(self, repo_dir: Path, tag_format: str) -> List[Version]:
        with Repo(str(repo_dir)) as git_repo:
            ts_and_vs = tags_and_versions(git_repo.tags, VersionTranslator(tag_format=tag_format))
        return [item[1] for item in ts_and_vs] if ts_and_vs else []

    @staticmethod
    def does_version_exist(version: Version, versions: List[Version]) -> bool:
        """Check if a version exists in the list of versions."""
        return any(version == v for v in versions)

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

    def do_release(self, remote_config: RemoteConfig) -> None:
        config = CreateReleaseCommitConfig.from_dict(self.config) if self.config else CreateReleaseCommitConfig()
        self.quote_token_for_url(remote_config)
        semantic_release_args = ["--skip-build", "--no-vcs-release"]
        semantic_release_args.append("--push" if config.push else "--no-push")
        prerelease_token = self.execution_context.get_input("prerelease_token")
        if prerelease_token:
            semantic_release_args.extend(["--prerelease-token", prerelease_token])
        # For Windows call the semantic-release executable
        self.execute_process(
            [
                *self.get_semantic_release_command(),
                "version",
                *semantic_release_args,
            ],
            "Failed to create release commit.",
        )
        self.logger.info("[OK] New release commit created and pushed to remote.")

    @staticmethod
    def get_semantic_release_command() -> List[str]:
        return ["python", "-m", "semantic_release"]

    @staticmethod
    def quote_token_for_url(remote_config: RemoteConfig) -> None:
        """Update the remote TOKEN environment variable because it will be used in the push URL and requires all special characters to be URL encoded."""
        if remote_config.type == HvcsClient.BITBUCKET:
            os.environ["BITBUCKET_TOKEN"] = quote_plus(os.getenv("BITBUCKET_TOKEN", ""))


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
        self.execute_process([*self.get_poetry_command(), "publish", "--build", *publish_auth_args], "Failed to publish package to PyPI.")
        self.logger.info("[OK] Package published to PyPI.")

    def find_data(self, data_type: Type[T]) -> Optional[T]:
        tmp_data = self.execution_context.data_registry.find_data(data_type)
        if len(tmp_data) > 0:
            return tmp_data[0]
        else:
            return None

    @staticmethod
    def get_poetry_command() -> List[str]:
        return ["python", "-m", "poetry"]
