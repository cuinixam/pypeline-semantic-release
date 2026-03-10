import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from urllib.parse import quote_plus

from git import Repo
from mashumaro.mixins.dict import DataClassDictMixin
from py_app_dev.core.exceptions import UserNotificationException
from pypeline.domain.execution_context import ExecutionContext
from semantic_release import VersionTranslator, tags_and_versions
from semantic_release.cli.cli_context import CliContextObj
from semantic_release.cli.commands.version import last_released
from semantic_release.cli.config import BranchConfig, GlobalCommandLineOptions, HvcsClient, RemoteConfig, RuntimeContext
from semantic_release.errors import NotAReleaseBranch
from semantic_release.version.algorithm import next_version
from semantic_release.version.version import Version

from pypeline_semantic_release.base import BaseStep, change_directory
from pypeline_semantic_release.check_ci_context import CIContext


@dataclass
class ReleaseCommit:
    version: Version
    previous_version: Version | None = None


@dataclass
class CreateReleaseCommitConfig(DataClassDictMixin):
    """Configuration for the CreateReleaseCommit step."""

    #: Whether or not to push the new commit and tag to the remote
    push: bool = True


class CreateReleaseCommit(BaseStep):
    """Create new commit using semantic release."""

    def __init__(self, execution_context: ExecutionContext, group_name: str | None = None, config: dict[str, Any] | None = None) -> None:
        super().__init__(execution_context, group_name, config)
        self.release_commit: ReleaseCommit | None = None

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

    def update_prerelease_token(self, branches: dict[str, BranchConfig]) -> None:
        """Iterate over all branches and update the prerelease token."""
        prerelease_token = self.execution_context.get_input("prerelease_token")
        if prerelease_token:
            for branch in branches.values():
                if branch.prerelease_token or branch.prerelease:
                    branch.prerelease_token = prerelease_token
                    self.logger.info(f"Updated prerelease token for branches matching {branch.match} to {prerelease_token}")

    def last_released_version(self, repo_dir: Path, tag_format: str) -> Version | None:
        last_release_str = last_released(repo_dir, tag_format)
        return last_release_str[1] if last_release_str else None

    def collect_all_tags_and_versions(self, repo_dir: Path, tag_format: str) -> list[Version]:
        with Repo(str(repo_dir)) as git_repo:
            ts_and_vs = tags_and_versions(git_repo.tags, VersionTranslator(tag_format=tag_format))
        return [item[1] for item in ts_and_vs] if ts_and_vs else []

    @staticmethod
    def does_version_exist(version: Version, versions: list[Version]) -> bool:
        """Check if a version exists in the list of versions."""
        return any(version == v for v in versions)

    def next_version(self, context: CliContextObj) -> Version | None:
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
    def get_semantic_release_command() -> list[str]:
        return ["python", "-m", "semantic_release"]

    @staticmethod
    def quote_token_for_url(remote_config: RemoteConfig) -> None:
        """Update the remote TOKEN environment variable because it will be used in the push URL and requires all special characters to be URL encoded."""
        if remote_config.type == HvcsClient.BITBUCKET:
            os.environ["BITBUCKET_TOKEN"] = quote_plus(os.getenv("BITBUCKET_TOKEN", ""))
