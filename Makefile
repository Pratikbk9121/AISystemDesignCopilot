.PHONY: install lint format format-check typecheck test test-integration lock lock-dev precommit-install precommit-run

# Install the project in editable mode with dev extras.
install:
	pip install -e ".[dev]"

# Lint with ruff (no auto-fix).
lint:
	ruff check app/ tests/ scripts/ evals/

# Auto-format with black.
format:
	black app/ tests/ scripts/ evals/

# Check formatting without writing.
format-check:
	black --check app/ tests/ scripts/ evals/

# Static type-check the app package.
typecheck:
	mypy app/

# Fast unit tests (skip integration suite).
test:
	pytest -m "not integration" -q

# Integration tests (require Redis + Qdrant running).
test-integration:
	pytest -m integration -q

# Regenerate the pinned production lockfile from pyproject.toml.
# Requires `uv` (https://github.com/astral-sh/uv). Run after editing
# `[project].dependencies` in pyproject.toml.
lock:
	uv pip compile pyproject.toml -o requirements.txt --generate-hashes

# Regenerate the pinned dev lockfile (production + dev extras).
lock-dev:
	uv pip compile pyproject.toml --extra dev -o requirements-dev.lock --generate-hashes

# Install the pre-commit git hook into .git/hooks.
precommit-install:
	pre-commit install

# Run all pre-commit hooks against every tracked file.
precommit-run:
	pre-commit run --all-files
