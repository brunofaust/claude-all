# Docstrings

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Docstring Format

Use Google-style docstrings. Always include a descriptive opening sentence explaining what the function does and why. Add context about behavior, edge cases, or important details in a second paragraph when helpful.

```python
async def get_entity_metadata(
    self,
    layer: Literal["raw", "curated"],
    **kwargs: Any,
) -> raw_metadata_dtype | curated_metadata_dtype:
    """
    Retrieve entity metadata configuration for a specific data layer.

    The metadata is loaded from the application configuration and cached
    to reduce repeated remote lookups. For the curated layer, the metadata
    type depends on whether the entity uses a normalized or flat model.

    Args:
        layer: The data layer to retrieve metadata for.
        **kwargs: Additional key-value pairs used to locate the specific
            entity within the configuration (e.g., source, schema, table).

    Returns:
        A typed dictionary containing the entity metadata configuration.
        For raw: raw_metadata_dtype.
        For curated: curated_metadata_normalized_dtype or
            curated_metadata_flat_dtype.

    Raises:
        KeyError: If the entity is not found in the configuration.
        MetadataNotDefined: If metadata fields are incomplete.

    Examples:
        >>> metadata = await svc.get_entity_metadata(
        ...     layer="raw", source="erp", schema="public", table="users"
        ... )
        >>> metadata["primary_keys"]
        {"id": "Int64"}
    """
```

#### Docstring Rules

- Opening sentence describes what the function does (imperative mood)
- Second paragraph provides behavioral context when needed (if possible, explain the usage in the full project context)
- `Args:` — every parameter documented, with its purpose
- `Returns:` — describe what's returned and when different types are possible
- `Raises:` — every exception the caller should be aware of
- `Examples:` — include for complex or non-obvious functions
- For simple one-line getters, a one-line docstring is fine:
    ```python
    async def is_loaded(self) -> bool:
        """Check whether the client has been loaded."""
    ```
