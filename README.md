# Pypeline steps for semantic release

<p align="center">
  <a href="https://github.com/cuinixam/pypeline-semantic-release/actions/workflows/ci.yml?query=branch%3Amain">
    <img src="https://img.shields.io/github/actions/workflow/status/cuinixam/pypeline-semantic-release/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://github.com/cuinixam/pypeline">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/cuinixam/pypeline/main/assets/badge/v0.json" alt="pypeline">
  </a>
  <a href="https://python-poetry.org/">
    <img src="https://img.shields.io/badge/packaging-poetry-299bd7?style=flat-square&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAASCAYAAABrXO8xAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAJJSURBVHgBfZLPa1NBEMe/s7tNXoxW1KJQKaUHkXhQvHgW6UHQQ09CBS/6V3hKc/AP8CqCrUcpmop3Cx48eDB4yEECjVQrlZb80CRN8t6OM/teagVxYZi38+Yz853dJbzoMV3MM8cJUcLMSUKIE8AzQ2PieZzFxEJOHMOgMQQ+dUgSAckNXhapU/NMhDSWLs1B24A8sO1xrN4NECkcAC9ASkiIJc6k5TRiUDPhnyMMdhKc+Zx19l6SgyeW76BEONY9exVQMzKExGKwwPsCzza7KGSSWRWEQhyEaDXp6ZHEr416ygbiKYOd7TEWvvcQIeusHYMJGhTwF9y7sGnSwaWyFAiyoxzqW0PM/RjghPxF2pWReAowTEXnDh0xgcLs8l2YQmOrj3N7ByiqEoH0cARs4u78WgAVkoEDIDoOi3AkcLOHU60RIg5wC4ZuTC7FaHKQm8Hq1fQuSOBvX/sodmNJSB5geaF5CPIkUeecdMxieoRO5jz9bheL6/tXjrwCyX/UYBUcjCaWHljx1xiX6z9xEjkYAzbGVnB8pvLmyXm9ep+W8CmsSHQQY77Zx1zboxAV0w7ybMhQmfqdmmw3nEp1I0Z+FGO6M8LZdoyZnuzzBdjISicKRnpxzI9fPb+0oYXsNdyi+d3h9bm9MWYHFtPeIZfLwzmFDKy1ai3p+PDls1Llz4yyFpferxjnyjJDSEy9CaCx5m2cJPerq6Xm34eTrZt3PqxYO1XOwDYZrFlH1fWnpU38Y9HRze3lj0vOujZcXKuuXm3jP+s3KbZVra7y2EAAAAAASUVORK5CYII=" alt="Poetry">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="ruff">
  </a>
  <a href="https://github.com/pre-commit/pre-commit">
    <img src="https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square" alt="pre-commit">
  </a>
</p>
<p align="center">
  <a href="https://pypi.org/project/pypeline-semantic-release/">
    <img src="https://img.shields.io/pypi/v/pypeline-semantic-release.svg?logo=python&logoColor=fff&style=flat-square" alt="PyPI Version">
  </a>
  <img src="https://img.shields.io/pypi/pyversions/pypeline-semantic-release.svg?style=flat-square&logo=python&amp;logoColor=fff" alt="Supported Python versions">
  <img src="https://img.shields.io/pypi/l/pypeline-semantic-release.svg?style=flat-square" alt="License">
</p>

So you are using [Pypeline](https://pypeline-runner.readthedocs.io) and you want to automate your python package release process, then you might want to consider the following steps:

1. **`CheckCIContext` Step**:

   - Checks if the current CI context (e.g. Jenkins, Github, etc.) and updates the information in the execution environment to be used by the other steps.

2. **`CreateReleaseCommit` Step**:

   - Automates versioning and creates a new release commit and tag based on your commit messages.
   - It is a wrapper for the [python-semantic-release](https://github.com/python-semantic-release/python-semantic-release) tool to be used as Pypeline step.

3. **`PublishPackage` Step**:
   - Uses **poetry** to publish your package to PyPI or another repository.
   - Configures credentials dynamically from environment variables.

## How to use it

You need to add this module as a dependency in your `pyproject.toml` and then use the steps in your `pypeline.yaml` configuration.

```yaml
inputs:
  prerelease_token:
    type: string
    description:
      "The prerelease token can be used when multiple users want to create release candidates.
      One can define an own unique token to avoid conflicts: rcN.dev, where N is a digit. For example: rc1.dev"
    required: false
    default: "rc"
  do_prerelease:
    type: boolean
    description: "If set to true, will create a prerelease. This is required to avoid creating prereleases automatically when pushing a branch."
    required: false
    default: false

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

### Create releases

The `CreateReleaseCommit` step will create a release commit based on the `semantic-release` configuration options in the `pyproject.toml` file.

```toml
[tool.semantic_release.branches.main]
match = "main"
prerelease = false

[tool.semantic_release.branches.feature]
match = "(?!main$)"
prerelease = true
```

When is a release created?

- When a commit is pushed to the `main` branch, the step will create a release commit and tag if `semantic-release` detects a new version shall be created.
- No release is created from a pull request
- No release candidate is created automatically when pushing a branch. This is to avoid creating release candidates when a branch is pushed. See below how to create prereleases.

### Create prereleases

Prereleases are only created when the `do_prerelease` input is set to `true`.
One needs to provide the `do_prerelease` input when running the `pypeline`.

> [!NOTE]
> To create a prerelease, one needs to push branch and manually trigger a build with the `do_prerelease` input set to `true`.

Depending on the CI system, one needs to define input parameters for the users to select when manually triggering the pipeline.

#### Github Actions

For Github Actions one can define the inputs in the workflow file:

```yaml
name: CI

on:
  push:
    branches: [develop]
  pull_request:
    branches: [develop]

  workflow_dispatch:
    inputs:
      do_prerelease:
        type: boolean
        description: "If set to true, will create a prerelease.
          This is required to avoid creating prereleases automatically when pushing a branch."
        required: false
        default: false

      prerelease_token:
        description:
          "The prerelease token can be used when multiple users want to create release candidates.
          One can define an own unique token to avoid conflicts: rcN.dev, where N is a digit. For example: rc1.dev"
        required: false
        default: "rc"
```

> [!NOTE]
> The way inputs are defined in Github Actions is similar to how they are defined in [Pypeline](https://pypeline-runner.readthedocs.io).

#### Jenkins

For Jenkins, one can define the inputs in the pipeline script:

```groovy
properties([
    parameters ([
    booleanParam(
            name: 'do_prerelease',
            defaultValue: false,
            description: '''If set to true, will create a prerelease.
                This is required to avoid creating prereleases automatically when pushing a branch.''',
        ),
    string(
            name: 'prerelease_token',
            defaultValue: '',
            description: '''The prerelease token can be used when multiple users
                want to create release candidates. One can define an own unique token
                to avoid conflicts: rcN.dev, where N is a digit. For example: rc1.dev'''
        ),
    ])
])
```

## Contributing ✨

The project uses Poetry for dependencies management and packaging.
Run the `bootstrap.ps1` script to install Python and create the virtual environment.

```powershell
.\bootstrap.ps1
```

This will also generate a `poetry.lock` file, you should track this file in version control.

To execute the test suite, call pytest inside Poetry's virtual environment via `poetry run`:

```shell
.venv/Scripts/poetry run pytest
```

Check out the Poetry documentation for more information on the available commands.

For those using [VS Code](https://code.visualstudio.com/) there are tasks defined for the most common commands:

- bootstrap
- run tests
- run all checks configured for pre-commit

See the `.vscode/tasks.json` for more details.
