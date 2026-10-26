# check-md-links: output modes and JSON schema

`scripts/check_md_links.py` is the `check-md-links` prek gate. It enforces two rules:

- Relative markdown links resolve. Vendored files are exempt (kept byte-identical to
  upstream); files under a vendored entry's `local_only` are still checked.
- Every discovered resource is linked from the README.

## Output modes

- Default: one human-readable line per finding on stdout, plus a `N finding(s).`
  summary on stderr. Exit 1 when there are findings, 0 otherwise.
- `--json`: a single JSON object on stdout and nothing else. Diagnostics go to stderr.
  Exit codes match the default mode for the same input.

## JSON shape (`schema_version` 1)

```json
{
  "schema_version": 1,
  "ok": false,
  "counts": {
    "markdown_tracked": 120,
    "markdown_scanned": 110,
    "markdown_skipped_vendored": 8,
    "markdown_skipped_missing": 1,
    "links_checked": 300,
    "links_resolved": 299,
    "resources_checked": 90,
    "resources_by_kind": {"skill": 40, "agent": 20}
  },
  "broken_links": [
    {"file": "src/a/SKILL.md", "line": 12, "target": "../b.md", "resolved": "src/b.md"}
  ],
  "unlinked_resources": [
    {"kind": "skill", "name": "my-skill", "path": "src/a/my-skill/SKILL.md"}
  ]
}
```

If `git ls-files` fails in `--json` mode, stdout carries an error object instead:

```json
{"schema_version": 1, "ok": false, "error": "git ls-files failed (exit 128): ..."}
```

The exit code is 1 in that case.

## Counts

- `markdown_tracked`: every file `git ls-files '*.md'` lists.
- `markdown_scanned`: link-checked files only. Vendored and missing files are not included.
- `markdown_skipped_vendored`: tracked markdown exempted under vendored entries. Files
  under a `local_only` sidecar are checked, so they are not counted here.
- `markdown_skipped_missing`: tracked in the index but absent from disk.
- `links_checked`: relative link targets examined. External, mailto, anchor and
  site-absolute targets are skipped and not counted.
- `links_resolved`: examined targets whose path exists.
- `resources_checked` and `resources_by_kind`: every resource the README check discovers.

`ok` is true only when there are no broken links and no unlinked resources.

## Path conventions

`file`, `resolved` and `path` are repo-relative POSIX strings, never absolute.
`resolved` is the lexically normalised join of the containing directory and the link
target. It is not symlink-resolved, although existence is tested on the symlink-resolved
path. A target that escapes the repo keeps its leading `..` segments.
