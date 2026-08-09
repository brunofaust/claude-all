# brunofaust-python-style Skill

## Overview
The `brunofaust-python-style` skill provides best practices, reference materials, and enforcement guidance for maintaining consistent Python code quality across projects. It covers topics such as async patterns, testing, type hints, and Python version-specific features.

## Key References

### Python 3.14 Free-Thread Feature
For details on using Python 3.14's free-thread feature, including when to use it, pros and cons, and compatibility checks, refer to:

- [python-3.14-free-thread.md](references/python-3.14-free-thread.md)

### Other Python Best Practices
- [Async Patterns](references/async-patterns.md)
- [Testing Strategies](references/testing.md)
- [Type Hint Usage](references/type-hints.md)

## Configuration
This skill integrates with the `pyproject.toml` configuration and enforces style guidelines through pre-commit hooks. Ensure your project's `pyproject.toml` includes the necessary settings for Python 3.14 and free-thread compatibility checks.

## Implementation
The skill utilizes Pydantic v2 for schema validation, SQLAlchemy 2.0 for database interactions, and `structlog` for structured logging. It ensures all database tables include `org_id` for multi-tenancy and uses `bcrypt` for secure password hashing.
