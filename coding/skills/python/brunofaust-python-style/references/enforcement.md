# Enforcement Hook Matrix

Every rule in this skill has an enforcement mechanism. If a rule has no enforcement, it is aspirational, not required.

## Matrix

| Rule | Enforced by | Bypass |
|---|---|---|
| Pydantic on boundaries | mypy strict + `skill_enforcer.py` rule `no_dict_any_in_signatures` | per-file allow list |
| Frozen dataclasses internally | `skill_enforcer.py` rule `dataclass_must_be_frozen` | `# skill-allow: mutable-dataclass` comment |
| No raw boto3 outside aws_resources/ | ruff `banned-api` (TID251) | `[per-file-ignores]` in pyproject.toml |
| No raw httpx outside integrations/ | ruff `banned-api` (TID251) | `[per-file-ignores]` in pyproject.toml |
| No silent except | ruff `BLE001`, `skill_enforcer.py` rule `no_debug_in_except` | `# noqa: BLE001` with explanation |
| Public names only (`__all__` not `_`) | vulture + `skill_enforcer.py` rule `no_module_underscore_names` | add to `__all__` |
| Thin lambda handlers (<20 stmts) | `skill_enforcer.py` rule `thin_lambda_handlers` | none — split into feature service |
| Dockerfile per resource | `skill_enforcer.py` rule `resource_mandatory_files` | none |
| CLAUDE.md per resource | `skill_enforcer.py` rule `resource_mandatory_files` | none |
| Layer dependency direction | `import-linter` | refactor required |
| CHANGELOG updated | `precommit_changelog.sh` + GitHub Action | `skip-changelog` label |
| Docs updated with code | `precommit_docs.sh` + GitHub Action | `skip-docs` label |
| Resource CLAUDE.md updated | `precommit_resource_docs.sh` + GitHub Action | none |
| Conventional commits | commitizen `commit-msg` hook | none |
| Docstring coverage ≥ 90% | interrogate | raise the floor |
| No bare `# type: ignore` | `python-check-blanket-type-ignore` | use specific code |
| No bare `# noqa` | ruff `RUF100` | use specific code |
| Test mirrors src structure | `skill_enforcer.py` rule `test_mirrors_src` | none |

**Single enforcement tool:** `scripts/skill_enforcer.py` — AST-based, config-driven via `skill_rules.toml`. One hook in `prek.toml`, all rules toggleable.

## `skill_enforcer.py` skeleton

```python
import ast, sys, pathlib, tomllib

class SkillChecker(ast.NodeVisitor):
    def __init__(self, path, rules):
        self.path = path
        self.rules = rules
        self.errors = []

    def visit_FunctionDef(self, node):
        # Rule: no dict[str, Any] params outside integrations/
        if "integrations/" not in str(self.path):
            for arg in node.args.args:
                if self._is_dict_any(arg.annotation):
                    self.errors.append(f"{self.path}:{node.lineno} dict[str, Any] in signature")
        # Rule: no business logic in lambda handlers
        if "aws_resources/lambdas/" in str(self.path) and node.name == "lambda_handler":
            stmt_count = sum(1 for n in ast.walk(node) if isinstance(n, ast.stmt))
            if stmt_count > self.rules.get("thin_lambda_handlers", {}).get("max_statements", 20):
                self.errors.append(f"{self.path}:{node.lineno} handler too thick ({stmt_count} stmts)")
        self.generic_visit(node)

    def visit_Assign(self, node):
        # Rule: ban module-level underscore-prefixed names
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id.startswith("_") and not t.id.startswith("__"):
                self.errors.append(f"{self.path}:{node.lineno} module-level _{t.id} — use __all__")

    def visit_ImportFrom(self, node):
        # Rule: no raw SDK imports outside owner folders
        banned = self.rules.get("banned_imports", {})
        for sdk, owner_glob in banned.items():
            if sdk == "enabled":
                continue
            if node.module and node.module.startswith(sdk) and owner_glob not in str(self.path):
                self.errors.append(f"{self.path}:{node.lineno} import {sdk} only allowed in {owner_glob}")

    def visit_ExceptHandler(self, node):
        # Rule: no silent except (log.debug inside except = swallowing)
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and self._is_log_debug(n):
                self.errors.append(f"{self.path}:{node.lineno} log.debug inside except — silent swallow")

def main():
    rules = tomllib.loads(pathlib.Path("skill_rules.toml").read_text())
    errors = []
    for f in pathlib.Path("src").rglob("*.py"):
        tree = ast.parse(f.read_text())
        c = SkillChecker(f, rules)
        c.visit(tree)
        errors.extend(c.errors)
    if errors:
        print("\n".join(errors))
        sys.exit(1)
```

## `skill_rules.toml` example

```toml
[rules.no_dict_any_in_signatures]
enabled = true
allowed_paths = ["src/*/integrations/**", "src/*/api/schemas/**"]
message = "Use Pydantic model or dataclass, not dict[str, Any]"

[rules.banned_imports]
enabled = true
"httpx" = "src/*/integrations/**"
"boto3" = "src/*/aws_resources/**"
"aioboto3" = "src/*/aws_resources/**"
"atlassian" = "src/*/integrations/jira/**"

[rules.no_module_underscore_names]
enabled = true
exclude_files = ["**/conftest.py", "**/__init__.py"]

[rules.thin_lambda_handlers]
enabled = true
max_statements = 20
paths = ["src/*/aws_resources/lambdas/**/handler.py"]

[rules.no_debug_in_except]
enabled = true

[rules.resource_mandatory_files]
enabled = true
resource_folders = [
    "src/*/aws_resources/lambdas/*",
    "src/*/aws_resources/ecs_tasks/*",
    "src/*/aws_resources/batch_jobs/*",
    "src/*/aws_resources/step_functions/*",
    "src/*/aws_resources/codebuild_projects/*",
    "src/*/aws_resources/glue_jobs/*",
]
required_files = ["README.md", "CLAUDE.md"]
require_dockerfile = ["lambdas/*", "ecs_tasks/*", "batch_jobs/*"]

[rules.test_mirrors_src]
enabled = true
src_root = "src"
test_root = "tests/unit"
```

## Plug into `prek.toml`

```toml
[[repos]]
repo = "local"
hooks = [{
  id = "skill-enforcer",
  name = "🐍 skill · Enforce coding rules via AST",
  entry = "python scripts/skill_enforcer.py",
  language = "system",
  files = "\\.py$"
}]
```
