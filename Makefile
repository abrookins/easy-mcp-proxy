.PHONY: help install lint format check test coverage clean all

# Default target
help:
	@echo "Available targets:"
	@echo "  install    - Install dependencies (dev)"
	@echo "  lint       - Run ruff linting"
	@echo "  format     - Format code with ruff"
	@echo "  check      - Run all checks (lint + format check)"
	@echo "  test       - Run tests with coverage"
	@echo "  coverage   - Run tests and generate HTML coverage report"
	@echo "  clean      - Remove build artifacts and caches"
	@echo "  all        - Run check + test"

# Install dependencies
install:
	uv sync --dev

# Run ruff linting
lint:
	uv run ruff check .

# Format code with ruff
format:
	uv run ruff format .

# Check formatting without modifying (for CI)
format-check:
	uv run ruff format --check .

# Run all checks (what CI does)
check: lint format-check

# Run tests with coverage
test:
	uv run pytest

# Run tests with HTML coverage report
coverage:
	uv run pytest --cov-report=html
	@echo "Coverage report generated in htmlcov/"

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Run all checks and tests (full CI simulation)
all: check test

