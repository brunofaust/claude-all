# Class design — inheritance, DI, attributes

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Class Design

#### Inheritance Pattern for Service Wrappers

```python
class storage_client:
    """Storage client wrapper providing high-level operations."""

    _upload_config: TransferConfig

    def __init__(self, **kwargs: Any) -> None:
        if "client_config" in kwargs:
            kwargs["client_config"]["service_name"] = "s3"
        else:
            kwargs["client_config"] = {"service_name": "s3"}
        super().__init__(**kwargs)

        if TYPE_CHECKING:
            self._client: S3Client
```

#### Dependency Injection Pattern

Pass pre-loaded dependencies into constructors instead of creating them internally. This makes testing straightforward and keeps coupling low.

```python
class data_pipeline:
    """Pipeline for processing data through multiple stages."""

    _storage: storage_client
    _db: database_client
    _notifier: notification_client

    def __init__(
        self,
        storage_obj: storage_client,
        db_obj: database_client,
        notifier_obj: notification_client,
    ) -> None:
        """
        Initialize with required service dependencies.

        All dependencies must be pre-loaded before being passed.

        Args:
            storage_obj: A loaded storage_client for file operations.
            db_obj: A loaded database_client for database operations.
            notifier_obj: A loaded notification_client for notifications.

        Raises:
            ValueError: If any dependency is not loaded.
        """
        if not storage_obj.loaded:
            raise ValueError("storage_obj must be loaded before passing")
        self._storage = storage_obj
```

#### Class Attributes

Declare class-level type annotations for all instance attributes so readers (and type checkers) know what a class holds at a glance:

```python
class data_transformer(data_pipeline):
    """Handles transformation of data between layers."""

    _bucket: str
    _keys: Sequence[full_keys_dtype]
    _source_info: source_info_dtype
    _target_info: target_info_dtype

    _metadata_columns: Sequence[str] = [
        "metadata_file_pk",
        "metadata_timestamp",
        "metadata_deleted",
    ]
```

If a class attribute is immutable, we should use an immutable of Final type hint

```python
from typing import Final

class something:
    “""Do something in the data pipeline."""

    _not_change: Final[str] = “this is an immutable string"
    _keys: Sequence[str] = [“this", "is", "an", "immutable", “list"]
```

