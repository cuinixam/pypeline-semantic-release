# Pypeline steps for semantic release

<p align="center">
  <a href="https://github.com/cuinixam/pypeline-semantic-release/actions/workflows/ci.yml?query=branch%3Amain">
    <img src="https://img.shields.io/github/actions/workflow/status/cuinixam/pypeline-semantic-release/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://github.com/cuinixam/pypeline">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/cuinixam/pypeline/main/assets/badge/v0.json" alt="pypeline">
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

[Pypeline](https://pypeline-runner.readthedocs.io) steps that wrap [python-semantic-release](https://github.com/python-semantic-release/python-semantic-release) to automate versioning and publishing for Python projects.

## Steps overview

| Step | Purpose |
|---|---|
| `CheckCIContext` | Detects the CI system (Jenkins, GitHub Actions) and whether the build is a PR |
| `CreateReleaseCommit` | Computes the next version, creates a release commit and tag, optionally builds and creates a VCS release |
| `PublishPackage` | Publishes the package to PyPI (or a private registry) via Poetry |

The steps communicate through a shared data registry: `CheckCIContext` produces a `CIContext`, `CreateReleaseCommit` produces a `ReleaseCommit`, and `PublishPackage` consumes both to decide whether to publish.

## Installation

Add the package as a dependency in your `pyproject.toml`:

```toml
[tool.poetry.dependencies]
pypeline-semantic-release = "^0"
```

## Quick start

### Minimal `pypeline.yaml`

```yaml
inputs:
  prerelease_token:
    type: string
    description: "Prerelease token (e.g. rc, rc1.dev)"
    default: "rc"
  do_prerelease:
    type: boolean
    description: "Set to true to create a prerelease"
    default: false

pipeline:
  - step: CreateVEnv
    module: pypeline.steps.create_venv

  - step: CheckCIContext
    module: pypeline_semantic_release.steps

  # ... your lint, test, docs steps here ...

  - step: CreateReleaseCommit
    module: pypeline_semantic_release.steps

  - step: PublishPackage
    module: pypeline_semantic_release.steps
```

### Semantic release configuration

Version computation and branching rules are configured in `pyproject.toml` via the standard [python-semantic-release configuration](https://python-semantic-release.readthedocs.io/en/latest/configuration/). For example:

```toml
[tool.semantic_release]
version_toml = ["pyproject.toml:project.version"]
build_command = "uv build"

[tool.semantic_release.branches.main]
match = "main"

[tool.semantic_release.branches.noop]
match = "(?!main$)"
prerelease = true
```

## Step configuration

### `CreateReleaseCommit`

Controls how `semantic-release version` is called.

| Option | Type | Default | Description |
|---|---|---|---|
| `push` | `bool` | `true` | Push the new commit and tag to the remote |
| `build` | `bool` | `false` | Run the `build_command` from `pyproject.toml` (creates dist artifacts) |
| `vcs_release` | `bool` | `false` | Create a VCS release (e.g. GitHub Release) and upload configured assets |

```yaml
- step: CreateReleaseCommit
  module: pypeline_semantic_release.steps
  config:
    build: true
    vcs_release: true
```

> [!NOTE]
> When `build` is `false` (default), `semantic-release version` is called with `--skip-build`.
> When `vcs_release` is `false` (default), it is called with `--no-vcs-release`.
> These defaults keep backward compatibility with existing Jenkins/Bitbucket setups.

### `PublishPackage`

Publishes the package to PyPI via `poetry publish --build`.

| Option | Type | Default | Description |
|---|---|---|---|
| `pypi_repository_name` | `str \| None` | `None` | Poetry repository name (if `None`, publishes to default PyPI) |
| `pypi_user_env` | `str` | `"PYPI_USER"` | Environment variable for the PyPI username |
| `pypi_password_env` | `str` | `"PYPI_PASSWD"` | Environment variable for the PyPI password |

```yaml
- step: PublishPackage
  module: pypeline_semantic_release.steps
  config:
    pypi_repository_name: "my-private-repo"
    pypi_user_env: "PYPI_USER"
    pypi_password_env: "PYPI_PASSWD"
```

When no `pypi_repository_name` is set, the package is published to the default PyPI. This works with [trusted publishing](https://docs.pypi.org/trusted-publishers/) on GitHub Actions (no credentials needed).

## Usage examples

### GitHub Actions — open source project

Build artifacts, create a GitHub Release, and publish to PyPI:

```yaml
# pypeline.yaml
pipeline:
  - step: CheckCIContext
    module: pypeline_semantic_release.steps

  - step: CreateReleaseCommit
    module: pypeline_semantic_release.steps
    config:
      build: true          # runs build_command from pyproject.toml
      vcs_release: true     # creates GitHub Release + uploads assets

  - step: PublishPackage
    module: pypeline_semantic_release.steps
```

The GitHub Actions workflow needs `GH_TOKEN` for the VCS release and `contents: write` permission:

```yaml
# .github/workflows/ci.yml (release job)
release:
  runs-on: ubuntu-latest
  permissions:
    contents: write
    id-token: write    # for PyPI trusted publishing
  steps:
    - uses: actions/checkout@v6
      with:
        fetch-depth: 0
    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - run: pip install pypeline-runner>=1.27
    - name: Release
      env:
        GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      run: pypeline run --step CheckCIContext --step CreateReleaseCommit --step PublishPackage --single
```

> [!TIP]
> With `vcs_release: true`, you don't need the separate `python-semantic-release/publish-action` Docker action.
> `semantic-release version` natively creates the GitHub Release and uploads assets.

### Jenkins / Bitbucket — private registry

No build in the release step (Poetry builds during publish), no VCS release:

```yaml
# pypeline.yaml
pipeline:
  - step: CheckCIContext
    module: pypeline_semantic_release.steps

  - step: CreateReleaseCommit
    module: pypeline_semantic_release.steps
    # defaults: build=false, vcs_release=false

  - step: PublishPackage
    module: pypeline_semantic_release.steps
    config:
      pypi_repository_name: "my-artifactory-repo"
      pypi_user_env: "PYPI_USER"
      pypi_password_env: "PYPI_PASSWD"
```

## Releases and prereleases

### When is a release created?

- A push to the release branch (e.g. `main`) triggers version computation. If `semantic-release` detects a version bump from conventional commits, a release commit and tag are created.
- **No release** is created from pull requests.
- **No prerelease** is created automatically when pushing a feature branch.

### Creating prereleases

Prereleases require the `do_prerelease` input to be explicitly set to `true`:

```shell
pypeline run --input do_prerelease
```

The `prerelease_token` input controls the prerelease suffix (default: `rc`). Multiple developers can use unique tokens to avoid conflicts:

```shell
pypeline run --input do_prerelease --input prerelease_token=rc1.dev
```

#### GitHub Actions `workflow_dispatch`

A common pattern is to use `workflow_dispatch` for prereleases: any manual trigger creates a prerelease from a chosen branch, while pushes to the main branch create regular releases automatically.

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

  workflow_dispatch:
    inputs:
      target_branch:
        description: "The branch to release from"
        required: true
        default: "main"
      prerelease_token:
        type: string
        description: "Prerelease token (e.g. rc, rc1.dev)"
        default: "rc"

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
          ref: ${{ github.event.inputs.target_branch || github.ref_name }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install pypeline-runner>=1.27

      - name: Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          PYPELINE_ARGS="--step CheckCIContext --step CreateReleaseCommit --step PublishPackage --single"

          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            # Manual trigger: create a prerelease from the target branch
            pypeline run $PYPELINE_ARGS \
              --input do_prerelease \
              --input prerelease_token=${{ github.event.inputs.prerelease_token }}
          else
            # Push to main: create a regular release
            pypeline run $PYPELINE_ARGS
          fi
```

> [!NOTE]
> The `target_branch` input is handled by the `actions/checkout` step — it controls which branch git
> checks out. The pypeline steps work on whatever branch is currently checked out.
> The `do_prerelease` input is what tells `CreateReleaseCommit` to allow prerelease versions.

#### Jenkins parameters

```groovy
properties([
    parameters([
        booleanParam(
            name: 'do_prerelease',
            defaultValue: false,
            description: 'Create a prerelease'
        ),
        string(
            name: 'prerelease_token',
            defaultValue: '',
            description: 'Prerelease token (e.g. rc, rc1.dev)'
        ),
    ])
])
```

## Contributing

The project uses [uv](https://docs.astral.sh/uv/) for dependency management. Run `bootstrap.ps1` to set up the environment:

```powershell
.\bootstrap.ps1
```

Run the full pipeline (lint + tests):

```shell
pypeline run
```
