from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from git import Repo
from pypeline.domain.execution_context import ExecutionContext
from semantic_release.version.version import Version

from pypeline_semantic_release.check_ci_context import CIContext, CISystem
from pypeline_semantic_release.create_release_commit import ReleaseCommit
from pypeline_semantic_release.publish_to_orphan_branch import PublishToOrphanBranch, PublishToOrphanBranchConfig
from tests.conftest import PyPackageRepo


def _create_execution_context(
    repo: PyPackageRepo,
    version: str,
    previous_version: str | None = None,
    is_ci: bool = True,
    is_pr: bool = False,
) -> ExecutionContext:
    execution_context = ExecutionContext(project_root_dir=Path(repo.repo.working_dir))
    release_commit = ReleaseCommit(
        version=Version.parse(version),
        previous_version=Version.parse(previous_version) if previous_version else None,
    )
    execution_context.data_registry.insert(release_commit, "test")
    ci_system = CISystem.JENKINS if is_ci else CISystem.UNKNOWN
    ci_context = CIContext(ci_system=ci_system, is_pull_request=is_pr, target_branch="main", current_branch="main")
    execution_context.data_registry.insert(ci_context, "test")
    return execution_context


def _create_step(
    execution_context: ExecutionContext,
    config: PublishToOrphanBranchConfig | None = None,
) -> PublishToOrphanBranch:
    cfg = config or PublishToOrphanBranchConfig(branch="generated-code")
    return PublishToOrphanBranch(execution_context, config=cfg.to_dict())


def _write_file(repo: PyPackageRepo, rel_path: str, content: str = "generated") -> None:
    path = Path(repo.repo.working_dir) / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    repo.repo.index.add([rel_path])
    repo.repo.index.commit(f"chore: add {rel_path}")


def test_happy_path_single_file(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "output/result.c", "int main() {}")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/result.c"])
    step = _create_step(ctx, config)

    with patch.object(step, "execute_process"):
        step.run()

    repo = py_package_tmp.repo
    assert "generated-code" in [b.name for b in repo.branches]
    assert "generated-code-v1.0.0-dev.1" in [t.name for t in repo.tags]
    # Verify the commit is a true orphan (no parents, no shared history with develop)
    orphan_commit = repo.heads["generated-code"].commit
    assert len(orphan_commit.parents) == 0
    # Verify only the configured file is on the orphan branch
    blob_paths = [blob.path for blob in orphan_commit.tree.traverse() if blob.type == "blob"]
    assert "output/result.c" in blob_paths


def test_happy_path_folder(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "gen/src/module.c", "void foo() {}")
    _write_file(py_package_tmp, "gen/src/module.h", "#pragma once")
    ctx = _create_execution_context(py_package_tmp, "2.0.0-rc.1")
    config = PublishToOrphanBranchConfig(branch="artifacts", paths=["gen/src"])
    step = _create_step(ctx, config)

    with patch.object(step, "execute_process"):
        step.run()

    repo = py_package_tmp.repo
    assert "artifacts" in [b.name for b in repo.branches]
    assert "artifacts-v2.0.0-rc.1" in [t.name for t in repo.tags]
    orphan_commit = repo.heads["artifacts"].commit
    assert len(orphan_commit.parents) == 0
    blob_paths = [blob.path for blob in orphan_commit.tree.traverse() if blob.type == "blob"]
    assert "gen/src/module.c" in blob_paths
    assert "gen/src/module.h" in blob_paths


def test_multiple_paths(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "gen/output.c", "code")
    _write_file(py_package_tmp, "docs/README.md", "# Docs")
    ctx = _create_execution_context(py_package_tmp, "1.2.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="release", paths=["gen/output.c", "docs"])
    step = _create_step(ctx, config)

    with patch.object(step, "execute_process"):
        step.run()

    repo = py_package_tmp.repo
    orphan_tree = repo.heads["release"].commit.tree
    blob_paths = [blob.path for blob in orphan_tree.traverse() if blob.type == "blob"]
    assert "gen/output.c" in blob_paths
    assert "docs/README.md" in blob_paths


def test_orphan_branch_already_exists(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "output/v1.c", "v1")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/v1.c"])
    step = _create_step(ctx, config)
    with patch.object(step, "execute_process"):
        step.run()

    # Second release with updated file
    _write_file(py_package_tmp, "output/v1.c", "v2")
    ctx2 = _create_execution_context(py_package_tmp, "1.1.0-dev.1")
    config2 = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/v1.c"])
    step2 = _create_step(ctx2, config2)
    with patch.object(step2, "execute_process"):
        step2.run()

    repo = py_package_tmp.repo
    assert "generated-code-v1.0.0-dev.1" in [t.name for t in repo.tags]
    assert "generated-code-v1.1.0-dev.1" in [t.name for t in repo.tags]
    # Orphan branch commit has a parent (the previous orphan commit)
    orphan_commit = repo.heads["generated-code"].commit
    assert len(orphan_commit.parents) == 1


def test_tag_already_exists_skips(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "output/file.c", "code")
    ctx = _create_execution_context(py_package_tmp, "1.0.0")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/file.c"])
    step = _create_step(ctx, config)
    with patch.object(step, "execute_process"):
        step.run()

    # Run again with same version — should skip
    ctx2 = _create_execution_context(py_package_tmp, "1.0.0")
    _create_step(ctx2, config).run()

    repo = py_package_tmp.repo
    assert [t.name for t in repo.tags].count("generated-code-v1.0.0") == 1


def test_no_release_commit(py_package_tmp: PyPackageRepo) -> None:
    execution_context = ExecutionContext(project_root_dir=Path(py_package_tmp.repo.working_dir))
    ci_context = CIContext(ci_system=CISystem.JENKINS, is_pull_request=False, target_branch="main", current_branch="main")
    execution_context.data_registry.insert(ci_context, "test")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["some/path"])
    step = _create_step(execution_context, config)

    step.run()

    assert "generated-code" not in [b.name for b in py_package_tmp.repo.branches]


def test_non_prerelease_version(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "output/file.c", "code")
    ctx = _create_execution_context(py_package_tmp, "3.0.0")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/file.c"])
    step = _create_step(ctx, config)
    with patch.object(step, "execute_process"):
        step.run()

    repo = py_package_tmp.repo
    assert "generated-code-v3.0.0" in [t.name for t in repo.tags]
    assert "generated-code" in [b.name for b in repo.branches]


def test_missing_paths_raises_error(py_package_tmp: PyPackageRepo) -> None:
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["nonexistent/path"])
    step = _create_step(ctx, config)

    with pytest.raises(Exception, match="Configured paths not found"):
        step.run()


def test_not_ci_skips(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "output/file.c", "code")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1", is_ci=False)
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/file.c"])
    _create_step(ctx, config).run()

    assert "generated-code" not in [b.name for b in py_package_tmp.repo.branches]


def test_pull_request_skips(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "output/file.c", "code")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1", is_pr=True)
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/file.c"])
    _create_step(ctx, config).run()

    assert "generated-code" not in [b.name for b in py_package_tmp.repo.branches]


def test_create_tag_false_skips_tag(py_package_tmp: PyPackageRepo) -> None:
    _write_file(py_package_tmp, "build/index.html", "<html/>")
    ctx = _create_execution_context(py_package_tmp, "1.0.0")
    config = PublishToOrphanBranchConfig(branch="gh-pages", paths=["build"], create_tag=False)
    step = _create_step(ctx, config)
    with patch.object(step, "execute_process"):
        step.run()

    repo = py_package_tmp.repo
    assert "gh-pages" in [b.name for b in repo.branches]
    assert len(repo.tags) == 0


def test_empty_paths_config_skips(py_package_tmp: PyPackageRepo) -> None:
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=[])
    _create_step(ctx, config).run()

    assert "generated-code" not in [b.name for b in py_package_tmp.repo.branches]


def _seed_orphan_branch_on_origin(tmp_path: Path, branch: str) -> tuple[Path, str]:
    """Create a bare origin repo with a pre-existing orphan branch. Return (bare_path, tip_sha)."""
    bare_path = tmp_path / "origin.git"
    Repo.init(bare_path, bare=True)

    seeder_path = tmp_path / "seeder"
    seeder_path.mkdir()
    seeder = Repo.init(seeder_path, initial_branch=branch)
    seeder.create_remote("origin", str(bare_path))
    seed_file = seeder_path / "seed.txt"
    seed_file.write_text("seed")
    seeder.index.add(["seed.txt"])
    seed_commit = seeder.index.commit("seed commit on orphan branch")
    seeder.git.push("origin", branch)
    return bare_path, seed_commit.hexsha


def test_remote_branch_exists_uses_remote_tip_as_parent(py_package_tmp: PyPackageRepo, tmp_path: Path) -> None:
    bare_path, remote_tip_sha = _seed_orphan_branch_on_origin(tmp_path, "generated-code")
    repo = py_package_tmp.repo
    repo.delete_remote("origin")
    repo.create_remote("origin", str(bare_path))

    _write_file(py_package_tmp, "output/result.c", "int main() {}")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/result.c"])
    step = _create_step(ctx, config)

    with patch.object(step, "execute_process"):
        step.run()

    new_commit = repo.heads["generated-code"].commit
    assert len(new_commit.parents) == 1
    assert new_commit.parents[0].hexsha == remote_tip_sha
    blob_paths = [blob.path for blob in new_commit.tree.traverse() if blob.type == "blob"]
    assert "output/result.c" in blob_paths


def test_remote_wins_when_local_and_remote_diverge(py_package_tmp: PyPackageRepo, tmp_path: Path) -> None:
    """Local `generated-code` exists but is stale/diverged — remote tip must be used as parent, with a warning."""
    bare_path, remote_tip_sha = _seed_orphan_branch_on_origin(tmp_path, "generated-code")
    repo = py_package_tmp.repo
    repo.delete_remote("origin")
    repo.create_remote("origin", str(bare_path))

    # Simulate a stale/divergent local `generated-code` by pointing it at an unrelated commit.
    local_tip = repo.head.commit
    repo.git.update_ref("refs/heads/generated-code", local_tip.hexsha)
    assert local_tip.hexsha != remote_tip_sha

    _write_file(py_package_tmp, "output/result.c", "int main() {}")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/result.c"])
    step = _create_step(ctx, config)

    with patch("pypeline_semantic_release.publish_to_orphan_branch.logger") as mock_logger, patch.object(step, "execute_process"):
        step.run()

    new_commit = repo.heads["generated-code"].commit
    assert [p.hexsha for p in new_commit.parents] == [remote_tip_sha]
    warn_msgs = [str(call.args[0]) for call in mock_logger.warning.call_args_list]
    assert any("diverges" in msg and "generated-code" in msg for msg in warn_msgs)


def test_fetch_failure_falls_back_and_warns(py_package_tmp: PyPackageRepo) -> None:
    """Unreachable remote must not silently produce a disconnected orphan commit without a warning."""
    # The fixture's origin points at `git@github.com:user/repo.git` — unreachable in tests,
    # so the fetch will raise GitCommandError. Seed a local branch directly to exercise fallback.
    repo = py_package_tmp.repo
    local_tip_sha = repo.head.commit.hexsha
    repo.git.update_ref("refs/heads/generated-code", local_tip_sha)

    _write_file(py_package_tmp, "output/result.c", "int main() {}")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/result.c"])
    step = _create_step(ctx, config)

    with patch("pypeline_semantic_release.publish_to_orphan_branch.logger") as mock_logger, patch.object(step, "execute_process"):
        step.run()

    new_commit = repo.heads["generated-code"].commit
    assert [p.hexsha for p in new_commit.parents] == [local_tip_sha]
    warn_calls = [str(call.args[0]) for call in mock_logger.warning.call_args_list]
    assert any("generated-code" in msg and "origin" in msg for msg in warn_calls)


def test_push_command_invoked_with_expected_refs(py_package_tmp: PyPackageRepo) -> None:
    """The push command must include the branch name and the tag (when create_tag is True)."""
    _write_file(py_package_tmp, "output/result.c", "int main() {}")
    ctx = _create_execution_context(py_package_tmp, "1.0.0-dev.1")
    config = PublishToOrphanBranchConfig(branch="generated-code", paths=["output/result.c"])
    step = _create_step(ctx, config)

    mock_exec = MagicMock()
    with patch.object(step, "execute_process", mock_exec):
        step.run()

    mock_exec.assert_called_once()
    command = mock_exec.call_args.args[0]
    assert command[:3] == ["git", "push", "origin"]
    assert "generated-code" in command
    assert "generated-code-v1.0.0-dev.1" in command
