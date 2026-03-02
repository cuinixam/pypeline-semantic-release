# Pypeline Semantic Release Development Guide for AI Agents

## Project Overview

This package provides [Pypeline](https://pypeline-runner.readthedocs.io) steps to automate semantic versioning and package publishing for Python projects. It wraps [python-semantic-release](https://python-semantic-release.readthedocs.io) and [Poetry](https://python-poetry.org/) into reusable pipeline steps that integrate into any `pypeline.yaml` configuration.

## Project Architecture

### Module layout

All implementation lives in a single module: `src/pypeline_semantic_release/steps.py`.

All steps extend `BaseStep`, which extends `PipelineStep[ExecutionContext]` from `pypeline-runner`. Steps communicate exclusively through `ExecutionContext.data_registry` (insert / `find_data` pattern). Step configurations are dataclasses extending `DataClassDictMixin` (from `mashumaro`), deserialized automatically from the `config:` block in `pypeline.yaml`.

### Pipeline steps

| Step | Reads from registry | Writes to registry | Purpose |
|---|---|---|---|
| `CheckCIContext` | — | `CIContext` | Detects CI system and PR context |
| `CreateReleaseCommit` | `CIContext` | `ReleaseCommit` | Computes next version and creates release commit/tag |
| `PublishPackage` | `CIContext`, `ReleaseCommit` | — | Publishes the package to PyPI via Poetry |

**`CheckCIContext`** iterates through the `CISystem` enum, runs each detector (`JenkinsDetector`, `GitHubActionsDetector`), and inserts the first matching `CIContext` into the registry. When no CI is detected, it inserts a `CIContext` with `ci_system=CISystem.UNKNOWN` (`is_ci == False`).

**`CreateReleaseCommit`** reads `CIContext`; skips on PRs, local runs, and unknown CI. Resolves the next version using `python-semantic-release` library APIs directly. If the version does not already exist as a tag, runs `python -m semantic_release version` as a subprocess. Supports two pipeline inputs:

- `prerelease_token` (`str`, default `"rc"`) — overrides branch-level prerelease tokens.
- `do_prerelease` (`bool`, default `False`) — must be `True` to allow a prerelease to be created.

Config dataclass: `CreateReleaseCommitConfig` — `push: bool = True`.

**`PublishPackage`** reads `ReleaseCommit`; skips if none present (no new release). Runs `python -m poetry publish --build`. Custom repository credentials are read from environment variables defined in `PublishPackageConfig` (`pypi_repository_name`, `pypi_user_env`, `pypi_password_env`).

### Key dataclasses

- `CIContext` — CI system type, `is_pull_request`, `target_branch`, `current_branch`.
- `ReleaseCommit` — `version: Version`, `previous_version: Version | None`.
- `CreateReleaseCommitConfig` — step config (deserialized from `pypeline.yaml`).
- `PublishPackageConfig` — step config (deserialized from `pypeline.yaml`).

## Development Guidelines

### ⚠️ MANDATORY: Plan Before Execution

**NEVER start making changes without presenting a plan first.** This is a critical rule.

1. **Create an implementation plan** documenting:
   - What files will be modified, created, or deleted
   - What changes will be made and why
   - How the changes will be verified
2. **Present the plan for user review** via `notify_user` with `BlockedOnUser=true`
3. **Wait for explicit approval** before proceeding with any file modifications
4. **Only after approval**, begin execution

Skipping this step is unacceptable.

### ⚠️ MANDATORY: Never Change the Plan Without Approval

**NEVER deviate from the approved plan without asking the user first.** If the current approach hits a blocker (e.g., a tool doesn't work, a dependency is missing, a test fails unexpectedly), you MUST:

1. **Stop** — do not attempt an alternative approach on your own
2. **Report the problem** to the user with a clear description of what went wrong
3. **Propose alternatives** if you have ideas, but do NOT implement them
4. **Wait for explicit approval** before changing direction

This applies to all scope changes: switching libraries, replacing test targets, altering architecture, or any deviation from what was agreed upon. The user decides, not the agent.

### Running Tests and Verification

The project uses `pypeline-runner` for all automation. Key commands:

```bash
# Run full pipeline (lint + tests) - this is the primary verification command
pypeline run

# Run only linting (pre-commit hooks)
pypeline run --step PreCommit

# Run only tests with specific Python version
pypeline run --step CreateVEnv --step PyTest --single --input python_version=3.13
```

### CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs:

1. **Lint** (`PreCommit` step) - Runs ruff linting/formatting via pre-commit
2. **Commit Lint** - Enforces [conventional commits](https://www.conventionalcommits.org)
3. **Test** - Matrix: Python 3.10 & 3.13 on Ubuntu and Windows
4. **Release** - Semantic versioning with automatic PyPI publishing

### Code Quality

- **Ruff** handles linting/formatting (configured in `pyproject.toml`)
- **Pre-commit hooks** enforce code standards
- **Type hints** are required (`py.typed` marker present)
- Docstrings follow standard conventions but are not required for all functions

### Dependencies

- **Core** (direct): `py-app-dev` (logging, exceptions, process execution), `pypeline-runner` (base step, execution context)
- **Core** (transitive, heavily used): `python-semantic-release` (version computation and release logic), `GitPython` (git operations), `mashumaro` (step config deserialization)
- **Dev**: `pytest` (testing), `ruff` (linting, formatting), `pre-commit` (hooks)

## Coding Guidelines

- **Less is more** — be concise and question every implementation that looks too complicated; if there is a simpler way, use it.
- **Never nester** — maximum three indentation levels are allowed. Use early returns, guard clauses, and extraction into helper functions to keep nesting shallow. The third level should only be used when truly necessary.
- **Use dataclasses for complex data structures**: Prefer using `dataclasses` over complex standard types (e.g. `tuple[list[str] | None, dict[str, str] | None]`) for function return values or internal data exchange to improve readability and extensibility.
- Always include full **type hints** (functions, methods, public attrs, constants).
- Prefer **pythonic** constructs: context managers, `pathlib`, comprehensions when clear, `enumerate`, `zip`, early returns, no over-nesting.
- Follow **SOLID**: single responsibility; prefer composition; program to interfaces (`Protocol`/ABC); inject dependencies.
- **Naming**: descriptive `snake_case` vars/funcs, `PascalCase` classes, `UPPER_SNAKE_CASE` constants. Avoid single-letter identifiers (including `i`, `j`, `a`, `b`) except in tight math helpers.
- Code should be **self-documenting**. Use docstrings only for public APIs or non-obvious rationale/constraints; avoid noisy inline comments.
- Errors: raise specific exceptions; never `except:` bare; add actionable context.
- Imports: no wildcard; group stdlib/third-party/local, keep modules small and cohesive.
- Testability: pure functions where possible; pass dependencies, avoid globals/singletons.
- Tests: use `pytest`; keep the tests to a minimum; use parametrized tests when possible; do not add useless comments; the tests shall be self-explanatory.
- Pytest fixtures: use them to avoid code duplication; use `conftest.py` for shared fixtures. Use `tmp_path` for file system operations.
- **Never suppress linter/type-checker warnings** by adding ignore rules to `pyproject.toml` or `# noqa` / `# type: ignore` comments. Always fix the underlying code instead.

## Definition of Done

Changes are NOT complete until:

- `pypeline run` executes with **zero failures**
- **All new functionality has tests** - never skip writing tests for new code
- Test coverage includes edge cases and error conditions
