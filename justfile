lint:
    ruff check .
fmt:
    ruff format .
check:
    uv run python -m mypy src/
fix:
    ruff check --fix .
    ruff format .
test:
    uv run python -m pytest -n auto -v -m "not slow"
test-full:
    uv run python -m pytest -n auto -v
test-cov:
    uv run python -m pytest -n auto --cov=src --cov-report=term-missing -v
re:
    uv tool install --reinstall .
publish:
    rm -f dist/*.tar.gz dist/*.whl
    uv build
    uv publish --token "$UV_PUBLISH_TOKEN"
    uv tool install --reinstall zenit
    git add -A
    git commit -m "release: v{{version}}"
    git tag -a v{{version}} -m "release v{{version}}"
    git push origin main --tags

version := `uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"`
