.PHONY: install dev lint format typecheck test test-cov clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"
	playwright install chromium
	pre-commit install

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck:
	mypy src/aat/

test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=aat --cov-report=term-missing --cov-report=html

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
