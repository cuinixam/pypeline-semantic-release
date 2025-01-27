# Pypeline step for semantic release

So you are using [Pypeline](https://pypeline-runner.readthedocs.io) and you want to automate your python package release process, then you might want to consider the following steps:

1. **`CheckCIContext` Step**:

   - Checks if the current CI context (e.g. Jenkins, Github, etc.) and updates the information in the execution environment to be used by the other steps.

2. **`CreateReleaseCommit` Step**:

   - Automates versioning and creates a new release commit and tag based on your commit messages.
   - It is a wrapper for the [python-semantic-release](https://github.com/python-semantic-release/python-semantic-release) tool to be used as Pypeline step.

3. **`PublishPackage` Step**:
   - Uses **poetry** to publish your package to PyPI or another repository.
   - Configures credentials dynamically from environment variables.

You need to define this module as a dependency in your `pyproject.toml` and then use it in your `pypeline.yaml` configuration.

```yaml
pipeline:
  - step: CreateVEnv
    module: pypeline.steps.create_venv

  - step: CheckCIContext
    module: pypeline-semantic-release.steps

  - step: CreateReleaseCommit
    module: pypeline-semantic-release.steps

  - step: PublishPackage
    module: pypeline-semantic-release.steps
    config:
      pypi_repository_name: my-repo
      pypi_user_env: PYPI_USER
      pypi_password_env: PYPI_PASSWD
```

```{toctree}
:hidden:

about/_changelog.md

```
