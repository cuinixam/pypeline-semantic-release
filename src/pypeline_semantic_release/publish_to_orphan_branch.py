from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from git import Commit, Repo
from git.exc import GitCommandError
from mashumaro.mixins.dict import DataClassDictMixin
from py_app_dev.core.exceptions import UserNotificationException
from py_app_dev.core.logging import logger

from pypeline_semantic_release.base import BaseStep, change_directory
from pypeline_semantic_release.check_ci_context import CIContext
from pypeline_semantic_release.create_release_commit import ReleaseCommit


@dataclass
class PublishToOrphanBranchConfig(DataClassDictMixin):
    """Configuration for the PublishToOrphanBranch step."""

    #: Name of the orphan branch to publish to (e.g. "generated-code", "gh-pages")
    branch: str
    #: Files or folders relative to the repo root to include on the orphan branch
    paths: list[str] = field(default_factory=list)
    #: Whether to create a tag on the orphan branch commit
    create_tag: bool = True


T = TypeVar("T")


class PublishToOrphanBranch(BaseStep):
    """Publish configured files/folders to a separate orphan branch with a clean release tag."""

    def run(self) -> None:
        self.logger.info(f"Running {self.get_name()} step.")
        config = PublishToOrphanBranchConfig.from_dict(self.config) if self.config else PublishToOrphanBranchConfig()

        release_commit = self._find_data(ReleaseCommit)
        if not release_commit:
            self.logger.info("No release commit found. Nothing to publish to orphan branch.")
            return

        ci_context = self._find_data(CIContext)
        if not ci_context or not ci_context.is_ci:
            self.logger.info("Not running on CI. Skip publishing to orphan branch.")
            return
        if ci_context.is_pull_request:
            self.logger.info("Pull request detected. Skip publishing to orphan branch.")
            return

        if not config.paths:
            self.logger.warning("No paths configured. Nothing to publish to orphan branch.")
            return

        tag_name = f"{config.branch}-{release_commit.version.as_tag()}" if config.create_tag else None

        with change_directory(self.execution_context.project_root_dir):
            self._publish(config, tag_name)

    def _publish(self, config: PublishToOrphanBranchConfig, tag_name: str | None) -> None:
        repo_dir = self.execution_context.project_root_dir
        with Repo(str(repo_dir)) as repo:
            if tag_name and tag_name in [tag.name for tag in repo.tags]:
                self.logger.info(f"Tag {tag_name} already exists. Skip publishing to orphan branch.")
                return

            self._validate_paths(repo_dir, config.paths)
            tree_sha = self._build_tree(repo, repo_dir, config.paths)
            remote_tip = self._fetch_remote_branch_tip(repo, config.branch)
            parent_commits = self._resolve_parent_commits(repo, config.branch, remote_tip)
            message = f"release: {tag_name}" if tag_name else f"release: {config.branch}"
            commit = Commit.create_from_tree(repo, repo.tree(tree_sha), message, parent_commits)
            commit_sha = commit.hexsha
            repo.git.update_ref(f"refs/heads/{config.branch}", commit_sha)

            if tag_name:
                repo.create_tag(tag_name, ref=commit_sha)
                self.logger.info(f"Created commit {commit_sha[:8]} on branch '{config.branch}' with tag '{tag_name}'.")
            else:
                self.logger.info(f"Created commit {commit_sha[:8]} on branch '{config.branch}'.")

        push_refs = [config.branch]
        if tag_name:
            push_refs.append(tag_name)
        self.execute_process(
            ["git", "push", "origin", *push_refs],
            f"Failed to push branch '{config.branch}' to remote.",
        )
        self.logger.info(f"[OK] Pushed branch '{config.branch}' to remote.")

    @staticmethod
    def _validate_paths(repo_dir: Path, paths: list[str]) -> None:
        missing = [path for path in paths if not (repo_dir / path).exists()]
        if missing:
            raise UserNotificationException(f"Configured paths not found in repository: {missing}")

    @staticmethod
    def _build_tree(repo: Repo, repo_dir: Path, paths: list[str]) -> Any:
        """Build a git tree containing only the configured paths."""
        # Use a temporary index file to avoid modifying the repo's working index
        tmp_index_path = repo_dir / ".git" / "tmp_index"
        try:
            env = {"GIT_INDEX_FILE": str(tmp_index_path)}
            for rel_path in paths:
                abs_path = repo_dir / rel_path
                if abs_path.is_file():
                    repo.git.add(rel_path, env=env)
                elif abs_path.is_dir():
                    files = [str(file.relative_to(repo_dir)) for file in abs_path.rglob("*") if file.is_file()]
                    repo.git.add(files, env=env)
            return repo.git.write_tree(env=env)
        finally:
            tmp_index_path.unlink(missing_ok=True)

    @staticmethod
    def _resolve_parent_commits(repo: Repo, branch_name: str, remote_tip: Commit | None) -> list[Commit]:
        """
        Return parent commits for the next commit on the orphan branch.

        Prefers ``remote_tip`` (the already-fetched ``origin/<branch>``) when
        provided, so that a manually-created upstream branch is extended — not
        overwritten by a disconnected orphan commit that a non-forced push
        would reject. Falls back to the local branch tip, then to an empty
        list (true orphan).

        When both remote and local tips exist and diverge, the remote wins and
        the caller's local branch ref will be overwritten by ``update_ref`` — a
        warning is logged so this is visible rather than silent.
        """
        if remote_tip is not None:
            if branch_name in [ref.name for ref in repo.branches]:
                local_tip = repo.heads[branch_name].commit
                if local_tip.hexsha != remote_tip.hexsha:
                    logger.warning(
                        f"Local '{branch_name}' ({local_tip.hexsha[:8]}) diverges from "
                        f"origin/{branch_name} ({remote_tip.hexsha[:8]}). Remote tip wins; "
                        f"local branch will be fast-forwarded to the new commit."
                    )
            return [remote_tip]
        if branch_name in [ref.name for ref in repo.branches]:
            return [repo.heads[branch_name].commit]
        return []

    @staticmethod
    def _fetch_remote_branch_tip(repo: Repo, branch_name: str) -> Commit | None:
        if "origin" not in [remote.name for remote in repo.remotes]:
            return None
        try:
            repo.git.fetch("origin", f"+refs/heads/{branch_name}:refs/remotes/origin/{branch_name}")
        except GitCommandError as err:
            # Distinguish "branch not on remote yet" (expected first-run) from
            # "remote unreachable / auth failed" — operators need the hint.
            logger.warning(f"Could not fetch '{branch_name}' from origin: {err}. Falling back to local branch tip.")
            return None
        try:
            return repo.remotes.origin.refs[branch_name].commit
        except IndexError:
            # Fetch reported success but the tracking ref is missing — genuinely
            # anomalous (corrupted refs, concurrent prune), not the "no remote
            # branch yet" case (which raises GitCommandError above).
            logger.warning(f"Fetched 'origin/{branch_name}' but tracking ref is missing. Falling back to local branch tip.")
            return None

    def _find_data(self, data_type: type[T]) -> T | None:
        tmp_data = self.execution_context.data_registry.find_data(data_type)
        return tmp_data[0] if tmp_data else None
