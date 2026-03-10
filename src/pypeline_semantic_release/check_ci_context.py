import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from pypeline_semantic_release.base import BaseStep


@dataclass
class CIContext:
    #: CI system where the build is running
    ci_system: "CISystem"
    #: Whether the build is for a pull request
    is_pull_request: bool
    #: The branch being build or the branch from the PR to merge into (e.g. main)
    target_branch: str | None
    #: Branch being built or the branch from the PR that needs to be merged (e.g. feature/branch)
    current_branch: str | None

    @property
    def is_ci(self) -> bool:
        """Whether the build is running on a CI system."""
        return self.ci_system != CISystem.UNKNOWN


class CIDetector(ABC):
    """Abstract base class for CI system detectors."""

    @abstractmethod
    def detect(self) -> CIContext | None:
        """Detects the CI system and returns a CIContext, or None if not detected."""
        pass

    @staticmethod
    def get_env_variable(var_name: str, default: str | None = None) -> str | None:
        """Helper function to get environment variables."""
        return os.getenv(var_name, default)


class JenkinsDetector(CIDetector):
    """Detects Jenkins CI."""

    def detect(self) -> CIContext | None:
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

    def detect(self) -> CIContext | None:
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

    def __init__(self, _: Any, detector_class: type[CIDetector] | None):
        self._value_ = _  # Use auto() value, but ignore it in __init__
        self.detector_class = detector_class

    def get_detector(self) -> CIDetector | None:
        return self.detector_class() if self.detector_class else None


class CheckCIContext(BaseStep):
    """Provide the CI context for the current build."""

    def update_execution_context(self) -> None:
        ci_context: CIContext | None = None

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
