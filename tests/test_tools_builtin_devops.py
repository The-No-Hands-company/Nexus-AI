import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.tools_builtin import (
    tool_create_issue,
    tool_create_pull_request,
    tool_create_directory,
    tool_git_checkout,
    tool_git_diff,
    tool_git_log,
    tool_git_pull,
    tool_git_status,
    tool_list_issues,
    tool_search_in_files,
    tool_unzip_files,
    tool_zip_files,
)


class TestToolsBuiltinDevOps(unittest.TestCase):
    def test_create_directory_creates_nested_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = tool_create_directory("a/b/c", workdir=tmp)
            self.assertIn("✅ Directory ready:", result)
            self.assertTrue((Path(tmp) / "a" / "b" / "c").exists())

    def test_search_in_files_finds_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "notes.txt"
            p.write_text("alpha\nneedle line\nomega\n", encoding="utf-8")
            result = tool_search_in_files("needle", include_glob="*.txt", workdir=tmp)
            self.assertIn("Found 1 match(es)", result)
            self.assertIn("notes.txt:2", result)

    def test_zip_and_unzip_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "one.txt").write_text("one", encoding="utf-8")
            (data_dir / "two.txt").write_text("two", encoding="utf-8")

            zip_result = tool_zip_files(["data"], "out/archive.zip", workdir=tmp)
            self.assertIn("✅ Created zip:", zip_result)

            unzip_result = tool_unzip_files("out/archive.zip", "unzipped", workdir=tmp)
            self.assertIn("✅ Extracted", unzip_result)
            self.assertTrue((Path(tmp) / "unzipped" / "data" / "one.txt").exists())
            self.assertTrue((Path(tmp) / "unzipped" / "data" / "two.txt").exists())

    @patch("src.tools_builtin.subprocess.run")
    def test_git_status_uses_subprocess_output(self, run_mock):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "## main\n M src/file.py\n"
        proc.stderr = ""
        run_mock.return_value = proc

        result = tool_git_status(repo_path=".", workdir="/tmp")
        self.assertIn("## main", result)
        self.assertIn("M src/file.py", result)

    @patch("src.tools_builtin.subprocess.run")
    def test_git_log_uses_subprocess_output(self, run_mock):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "abc123 2026-04-17 bot commit"
        proc.stderr = ""
        run_mock.return_value = proc

        result = tool_git_log(repo_path=".", max_count=5, workdir="/tmp")
        self.assertIn("abc123", result)

    @patch("src.tools_builtin.subprocess.run")
    def test_git_diff_formats_as_diff_block(self, run_mock):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "diff --git a/a.txt b/a.txt\n+line"
        proc.stderr = ""
        run_mock.return_value = proc

        result = tool_git_diff(repo_path=".", ref="HEAD", workdir="/tmp")
        self.assertTrue(result.startswith("```diff"))
        self.assertIn("diff --git", result)

    @patch("src.tools_builtin.subprocess.run")
    def test_git_checkout_success(self, run_mock):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "Switched to branch 'feature/x'"
        proc.stderr = ""
        run_mock.return_value = proc

        result = tool_git_checkout(repo_path=".", branch="feature/x", create=False, workdir="/tmp")
        self.assertIn("Switched to branch", result)

    @patch("src.tools_builtin.subprocess.run")
    def test_git_pull_success(self, run_mock):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "Already up to date."
        proc.stderr = ""
        run_mock.return_value = proc

        result = tool_git_pull(repo_path=".", remote="origin", branch="main", ff_only=True, workdir="/tmp")
        self.assertIn("Already up to date", result)

    @patch("src.tools_builtin.subprocess.run")
    def test_create_pull_request_success(self, run_mock):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "https://github.com/org/repo/pull/12"
        proc.stderr = ""
        run_mock.return_value = proc

        result = tool_create_pull_request("Title", "Body", base="main", head="feature/x", repo_path=".", workdir="/tmp")
        self.assertIn("https://github.com", result)

    @patch("src.tools_builtin.subprocess.run")
    def test_list_and_create_issue_success(self, run_mock):
        first = MagicMock()
        first.returncode = 0
        first.stdout = "12\tOPEN\tBug title"
        first.stderr = ""

        second = MagicMock()
        second.returncode = 0
        second.stdout = "https://github.com/org/repo/issues/13"
        second.stderr = ""

        run_mock.side_effect = [first, second]

        list_result = tool_list_issues(repo_path=".", state="open", limit=10, workdir="/tmp")
        self.assertIn("Bug title", list_result)

        create_result = tool_create_issue("New bug", "body", labels="bug", repo_path=".", workdir="/tmp")
        self.assertIn("/issues/13", create_result)


if __name__ == "__main__":
    unittest.main()
