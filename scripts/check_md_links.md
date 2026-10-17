# check_md_links `--json` output

`scripts/check_md_links.py --json` prints one JSON object on stdout (indent=2) instead of
the human-readable report. Exit codes are identical in both modes.

```
{
  "ok": false,                       # bool: no broken links and no unlinked resources
  "error": null,                     # null, or a string when the gate could not run
  "counts": {
    "markdown_scanned": 12,          # tracked *.md read from disk (not vendored/missing)
    "links_checked": 40,             # relative link targets that resolved to an existing path
    "resources_checked": 9,          # len(discover([])): the resources the README must link
    "vendored_skipped": 3            # tracked *.md files exempt as vendored
  },
  "broken_links": [
    {
      "file": "src/a/b.md",          # file containing the link, repo-relative, posix
      "line": 7,                     # 1-based line number in that file
      "target": "../gone.md",        # raw link target as written
      "resolved": "src/gone.md"      # missing resolved path, relative to repo root
    }
  ],
  "unlinked_resources": [
    {
      "kind": "skill",               # resource kind from discover()
      "name": "my-skill",            # resource name from discover()
      "path": "src/x/my-skill/SKILL.md"  # source file, repo-relative, posix
    }
  ]
}
```

Not counted as "scanned": tracked markdown files missing from the working tree.
Not counted as "links_checked": broken links (they appear in `broken_links`), external URLs,
mailto/tel, site-absolute `/` links, and pure `#anchor` links. Vendored files appear only in
`vendored_skipped`.

If the gate cannot run at all under `--json`, stdout is
`{"ok": false, "error": "<ExcType>: <message>"}` and the exit code is 1; a one-line
`check_md_links: <ExcType>: <message>` diagnostic goes to stderr.
