from pypeline_semantic_release.steps import CreateReleaseCommit, CreateReleaseCommitConfig, ReleaseCommit
from tests.conftest import PyPackageRepo
from tests.utils import assert_element_of_type


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
