class TestJsonMode:
    def _setup_git_repo(self, tmp_path: Path) -> Path:
        """Initialize a git repo in tmp_path and return the repo path."""
        repo = tmp_path
        (repo / ".git").mkdir()
        (repo / ".git" / "config").write_text("[core]\n")
        # Initialize an empty repo by running git init
        import subprocess

        subprocess.run(
            ["git", "init"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        # Set user info for commits
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
        )
        return repo

    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON mode on a clean tree should report pass: true and zero counts."""
        import json
        from io import StringIO

        repo = self._setup_git_repo(tmp_path)
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        (repo / "README.md").write_text("# README\n")
        md_file = repo / "test.md"
        md_file.write_text("See [link](./test.md)\n")
        resource_file = repo / "resource.txt"
        resource_file.write_text("dummy")

        class dummy_item:
            kind = "resource"
            name = "resource"
            src = resource_file

        monkeypatch.setattr("claude_all.cli.discover", lambda _: [dummy_item()])
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setenv("CLAUDE_ALL_ROOT", str(repo))

        # Save original state
        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        try:
            sys.argv = ["check_md_links", "--json"]
            from check_md_links import main

            exit_code = main()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue()
        error = sys.stderr.getvalue()

        assert exit_code == 0
        data = json.loads(output)
        assert data["pass"] is True
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["counts"]["resources_checked"] == 1
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON mode with a broken link should report pass: false and the broken link."""
        import json
        from io import StringIO

        repo = self._setup_git_repo(tmp_path)
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        (repo / "README.md").write_text("# README\n")
        md_file = repo / "test.md"
        md_file.write_text("See [link](./nonexistent.md)\n")
        # No resources to keep it simple
        monkeypatch.setattr("claude_all.cli.discover", lambda: [])
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setenv("CLAUDE_ALL_ROOT", str(repo))

        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        try:
            sys.argv = ["check_md_links", "--json"]
            from check_md_links import main

            exit_code = main()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue()
        error = sys.stderr.getvalue()

        assert exit_code == 1
        data = json.loads(output)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        broken = data["broken_links"][0]
        assert broken["containing_file"] == "test.md"
        assert broken["raw_link_target"] == "./nonexistent.md"
        # resolved_path should be the absolute path to nonexistent.md
        assert broken["resolved_path"] == str((repo / "nonexistent.md").resolve())
        assert data["unlinked_resources"] == []

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JSON mode with an unlinked resource should report pass: false and the resource."""
        import json
        from io import StringIO

        repo = self._setup_git_repo(tmp_path)
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        (repo / "README.md").write_text("# README\n")
        md_file = repo / "test.md"
        md_file.write_text("No links here.\n")
        resource_file = repo / "resource.txt"
        resource_file.write_text("dummy")

        class dummy_item:
            kind = "resource"
            name = "resource"
            src = resource_file

        monkeypatch.setattr("claude_all.cli.discover", lambda _: [dummy_item()])
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setenv("CLAUDE_ALL_ROOT", str(repo))

        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        try:
            sys.argv = ["check_md_links", "--json"]
            from check_md_links import main

            exit_code = main()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue()
        error = sys.stderr.getvalue()

        assert exit_code == 1
        data = json.loads(output)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 1
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        assert data["unlinked_resources"][0] == "resource.txt"

    def test_json_default_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure that without --json, the output is unchanged from before."""
        from io import StringIO

        repo = self._setup_git_repo(tmp_path)
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        (repo / "README.md").write_text("# README\n")
        md_file = repo / "test.md"
        md_file.write_text("See [link](./nonexistent.md)\n")
        # No resources
        monkeypatch.setattr("claude_all.cli.discover", lambda: [])
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setenv("CLAUDE_ALL_ROOT", str(repo))

        # Test without --json
        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        try:
            sys.argv = ["check_md_links"]
            from check_md_links import main

            exit_code = main()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue()
        error = sys.stderr.getvalue()

        assert exit_code == 1
        assert "test.md:1: broken-link -> ./nonexistent.md" in output
        assert "1 finding(s)." in error

        # Now test with --json
        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        try:
            sys.argv = ["check_md_links", "--json"]
            from check_md_links import main

            exit_code = main()
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue()
        error = sys.stderr.getvalue()

        assert exit_code == 1
        # stderr should be empty in JSON mode
        assert error == ""
        data = json.loads(output)
        assert data["pass"] is False
        assert len(data["broken_links"]) == 1
