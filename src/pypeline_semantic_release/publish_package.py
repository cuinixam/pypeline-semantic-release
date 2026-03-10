import os
from dataclasses import dataclass
from typing import TypeVar

from mashumaro.mixins.dict import DataClassDictMixin

from pypeline_semantic_release.base import BaseStep
from pypeline_semantic_release.check_ci_context import CIContext
from pypeline_semantic_release.create_release_commit import ReleaseCommit


@dataclass
class PublishPackageConfig(DataClassDictMixin):
    """Configuration for the PublishPackage step."""

    #: PyPi repository name for releasing the package. If not set, the package will be released to the python-semantic-release default PyPi repository.
    pypi_repository_name: str | None = None
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

    def find_data(self, data_type: type[T]) -> T | None:
        tmp_data = self.execution_context.data_registry.find_data(data_type)
        if len(tmp_data) > 0:
            return tmp_data[0]
        else:
            return None

    @staticmethod
    def get_poetry_command() -> list[str]:
        return ["poetry"]
