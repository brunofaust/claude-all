# Configuration management — Pydantic Settings

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Python Configuration Management

Externalize configuration from code using environment variables and typed settings. Well-managed configuration enables the same code to run in any environment without modification.

### When to Use

- Setting up a new project's configuration system
- Migrating from hardcoded values to environment variables
- Implementing pydantic-settings for typed configuration
- Managing secrets and sensitive values
- Creating environment-specific settings (dev/staging/prod)
- Validating configuration at application startup

### Core Concepts

1. **Externalized Configuration**: All environment-specific values (URLs, secrets, feature flags) come from environment variables, not code.
1. **Typed Settings**: Parse and validate the configuration into typed objects at startup, rather than scattering it throughout the code.
1. **Fail Fast**: Validate all required configuration at application boot. Missing config should crash immediately with a clear message.
1. **Sensible Defaults**: Provide reasonable defaults for local development while requiring explicit values for sensitive settings.

```python
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    api_key: str = Field(alias="API_KEY")
    debug: bool = Field(default=False, alias="DEBUG")


settings = Settings()  # Loads from environment
```

______________________________________________________________________

## Anti-pattern: hardcoded config values

**Rule:** nothing that could differ between environments, deployments, or releases may be hardcoded at module or class level. All such values must come from `Settings`, an env var, or be passed as a parameter.

### What counts as "config"

| Category            | Examples                                                   |
| ------------------- | ---------------------------------------------------------- |
| AI / LLM            | model name, temperature, max tokens, embedding model       |
| Workflow / statuses | Jira status strings, step function state names, task types |
| AWS resource names  | S3 bucket, SQS queue URL, SNS topic ARN, DynamoDB table    |
| Networking          | API base URLs, timeouts, retry counts, batch sizes         |
| Business rules      | thresholds, limits, feature flags, environment names       |

### ❌ Bad — hardcoded at module level

```python
# Any of these is a hardcoded config value — forbidden at module/class scope
MODEL_NAME = "gpt-4o-mini"
JIRA_STATUS_DONE = "Done"
JIRA_STATUS_IN_PROGRESS = "In Progress"
S3_BUCKET = "my-company-data-lake"
SQS_QUEUE_URL = "https://sqs.eu-west-1.amazonaws.com/123/my-queue"
API_BASE_URL = "https://api.internal.company.com"
BATCH_SIZE = 500
MAX_RETRIES = 3


class JiraClient:
    STATUS_CLOSED = "Closed"  # ❌ class-level config constant
    DEFAULT_PROJECT = "DATA"  # ❌ class-level config constant

    async def close_issue(self, key: str) -> None:
        await self._transition(key, self.STATUS_CLOSED)  # hidden hardcode
```

### ✅ Good — values come from Settings

```python
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    llm_model: str = Field(alias="LLM_MODEL")
    jira_status_done: str = Field(alias="JIRA_STATUS_DONE")
    jira_status_in_progress: str = Field(alias="JIRA_STATUS_IN_PROGRESS")
    s3_bucket: str = Field(alias="S3_BUCKET")
    sqs_queue_url: str = Field(alias="SQS_QUEUE_URL")
    api_base_url: str = Field(alias="API_BASE_URL")
    batch_size: int = Field(default=500, alias="BATCH_SIZE")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")

    model_config = {"env_file": ".env"}


SETTINGS = Settings()
```

```python
# Usage — always read from the singleton
from app import SETTINGS


class JiraClient:
    async def close_issue(self, key: str) -> None:
        await self._transition(key, SETTINGS.jira_status_done)
```

### The one exception: function/method parameter defaults

Parameter defaults are explicit call-site overrides — the caller can always pass a different value. They are **not** hidden globals.

```python
# ✅ Allowed — caller can override, nothing is hidden
async def summarise(text: str, model: str = "gpt-4o-mini") -> str: ...


# ✅ Also fine — default drawn from Settings, but overridable
async def summarise(
    text: str,
    model: str = SETTINGS.llm_model,
) -> str: ...
```

But a module-level constant just to feed a default is still banned:

```python
# ❌ The constant is the problem, not the parameter
# (and the _ prefix is also an anti-pattern — module-level names use __all__, not _)
DEFAULT_MODEL = "gpt-4o-mini"  # ← forbidden: hardcoded config at module scope


async def summarise(text: str, model: str = DEFAULT_MODEL) -> str: ...
```

### What IS allowed at module level

True technical constants that are environment-agnostic and will never change:

```python
CACHE_1_HOUR = 3600  # ✅ pure math, not config
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # ✅ protocol limit, not business config
ENCODING = "utf-8"  # ✅ technical detail, not deployment-specific
```

Heuristic: if you'd ever want to change it via an env var in staging vs prod → it's config, not a constant.

______________________________________________________________________

### Best Practices Summary

1. **Never hardcode config** - All environment-specific values from env vars
1. **Use typed settings** - Pydantic-settings with validation
1. **Fail fast** - Crash on missing required config at startup
1. **Provide dev defaults** - Make local development easy
1. **Never commit secrets** - Use `.env` files (gitignored) or secret managers
1. **Namespace variables** - `DB_HOST`, `REDIS_URL` for clarity
1. **Import settings singleton** - Don't call `os.getenv()` throughout code
1. **Document all variables** - README should list required env vars
1. **Validate early** - Check config correctness at boot time
1. **Use secrets_dir** - Support mounted secrets in containers

### Fundamental Patterns

#### Pattern 1: Typed Settings with Pydantic

Create a central settings class that loads and validates all configurations.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, PostgresDsn, ValidationError
import sys


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Database
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(alias="DB_NAME")
    db_user: str = Field(alias="DB_USER")
    db_password: str = Field(alias="DB_PASSWORD")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    # API Keys
    api_secret_key: str = Field(alias="API_SECRET_KEY")

    # Feature flags
    enable_new_feature: bool = Field(default=False, alias="ENABLE_NEW_FEATURE")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# Create singleton instance at module load (__init__.py)
SETTINGS = Settings()
```

Import `SETTINGS` throughout your application:

```python
from app import SETTINGS


def get_database_connection():
    return connect(
        host=SETTINGS.db_host,
        port=SETTINGS.db_port,
        database=SETTINGS.db_name,
    )
```

#### Pattern 2: Fail Fast on Missing Configuration

Required settings should crash the application immediately with a clear error.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, ValidationError
import sys

class Settings(BaseSettings):
    # Required - no default means it must be set
    api_key: str = Field(alias="API_KEY")
    database_url: str = Field(alias="DATABASE_URL")

    # Optional with defaults
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

try:
    settings = Settings()
except ValidationError as e:
    for error in e.errors():
        field = error["loc"][0]
        msg = error["msg"]
        print(f"Setting {field}: {msg}")
    sys.exit(1)
```

A clear error at startup is better than a cryptic `None` failure mid-request.

#### Pattern 3: Local Development Defaults

Provide sensible defaults for local development while requiring explicit values for secrets.

```python
class Settings(BaseSettings):
    # Has local default, but prod will override
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")

    # Always required - no default for secrets
    db_password: str = Field(alias="DB_PASSWORD")
    api_secret_key: str = Field(alias="API_SECRET_KEY")

    # Development convenience
    debug: bool = Field(default=False, alias="DEBUG")

    model_config = {"env_file": ".env"}
```

Create a `.env` file for local development (never commit this):

```bash
# .env (add to .gitignore)
DB_PASSWORD=local_dev_password
API_SECRET_KEY=dev-secret-key
DEBUG=true
```

#### Pattern 4: Namespaced Environment Variables

Prefix related variables for clarity and easy debugging.

```bash
# Database configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp
DB_USER=admin
DB_PASSWORD=secret

# Redis configuration
REDIS_URL=redis://localhost:6379
REDIS_MAX_CONNECTIONS=10

# Authentication
AUTH_SECRET_KEY=your-secret-key
AUTH_TOKEN_EXPIRY_SECONDS=3600
AUTH_ALGORITHM=HS256

# Feature flags
FEATURE_NEW_CHECKOUT=true
FEATURE_BETA_UI=false
```

Makes `env | grep DB_` useful for debugging.

### Pattern 5: Type Coercion

Pydantic handles common conversions automatically.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    # Automatically converts "true", "1", "yes" to True
    debug: bool = False

    # Automatically converts string to int
    max_connections: int = 100

    # Parse comma-separated string to list
    allowed_hosts: list[str] = Field(default_factory=list)

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [host.strip() for host in v.split(",") if host.strip()]
        return v
```

Usage:

```bash
ALLOWED_HOSTS=example.com,api.example.com,localhost
MAX_CONNECTIONS=50
DEBUG=true
```

### Pattern 6: Environment-Specific Configuration

Use an environment enum to switch behavior.

```python
from enum import Enum
from pydantic_settings import BaseSettings
from pydantic import Field, computed_field


class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    environment: Environment = Field(
        default=Environment.LOCAL,
        alias="ENVIRONMENT",
    )

    # Settings that vary by environment
    log_level: str = Field(default="DEBUG", alias="LOG_LEVEL")

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @computed_field
    @property
    def is_local(self) -> bool:
        return self.environment == Environment.LOCAL


# Usage
if settings.is_production:
    configure_production_logging()
else:
    configure_debug_logging()
```

### Pattern 7: Nested Configuration Groups

Organize related settings into nested models.

```python
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str
    user: str
    password: str


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379"
    max_connections: int = 10


class Settings(BaseSettings):
    database: DatabaseSettings
    redis: RedisSettings
    debug: bool = False

    model_config = {
        "env_nested_delimiter": "__",
        "env_file": ".env",
    }
```

Environment variables use double underscore for nesting:

```bash
DATABASE__HOST=db.example.com
DATABASE__PORT=5432
DATABASE__NAME=myapp
DATABASE__USER=admin
DATABASE__PASSWORD=secret
REDIS__URL=redis://redis.example.com:6379
```

### Pattern 8: Secrets from Files

For container environments, read secrets from mounted files.

```python
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    # Read from environment variable or file
    db_password: str = Field(alias="DB_PASSWORD")

    model_config = {
        "secrets_dir": "/run/secrets",  # Docker secrets location
    }
```

Pydantic will look for `/run/secrets/db_password` if the env var isn't set.

### Pattern 9: Configuration Validation

Add custom validation for complex requirements.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator


class Settings(BaseSettings):
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(alias="DB_PORT")
    read_replica_host: str | None = Field(default=None, alias="READ_REPLICA_HOST")
    read_replica_port: int = Field(default=5432, alias="READ_REPLICA_PORT")

    @model_validator(mode="after")
    def validate_replica_settings(self):
        if self.read_replica_host and self.read_replica_port == self.db_port:
            if self.read_replica_host == self.db_host:
                raise ValueError("Read replica cannot be the same as primary database")
        return self
```
