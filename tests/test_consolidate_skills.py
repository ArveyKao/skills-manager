import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/consolidate_skills.py"
SPEC = importlib.util.spec_from_file_location("consolidate_skills", SCRIPT)
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "agent/skills/example-skill"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text("---\nname: example-skill\ndescription: Fixture\n---\n")
        (self.source / "helper.bin").write_bytes(bytes(range(256)) + b"\x00\xff")
        (self.source / "helper.bin").chmod(0o751)
        self.source.chmod(0o750)
        self.library = self.base / "skills-manager"
        self.target = self.library / "example-skill"

    def manifest(self, **extra):
        return {"library": str(self.library), "entries": [{"source": str(self.source), "target": str(self.target)}], **extra}

    def test_preview_is_read_only_including_optional_report(self):
        report_path = self.base / "report.json"
        original = manager.fingerprint(self.source)
        result = manager.consolidate(self.manifest(report_path=str(report_path)))
        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"][0]["status"], "planned")
        self.assertEqual(manager.fingerprint(self.source), original)
        self.assertFalse(self.source.is_symlink())
        self.assertFalse(self.library.exists())
        self.assertFalse(report_path.exists())

    def test_move_keeps_bytes_modes_git_internal_links_and_full_backup(self):
        (self.source / ".git").mkdir()
        (self.source / ".git/config").write_text("private repository config")
        (self.source / ".env").write_text("secret fixture")
        (self.source / "helper-link").symlink_to("helper.bin")
        before = manager.fingerprint(self.source)
        content = (self.source / "helper.bin").read_bytes()
        result = manager.consolidate(self.manifest(), apply=True)
        self.assertTrue(result["ok"])
        row = result["entries"][0]
        self.assertEqual(row["status"], "moved-and-linked")
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(os.readlink(self.source), str(self.target))
        backup = Path(row["backup"])
        for root in (self.source, self.target, backup):
            self.assertEqual((root / "helper.bin").read_bytes(), content)
            self.assertEqual(stat.S_IMODE((root / "helper.bin").stat().st_mode), 0o751)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o750)
            self.assertEqual((root / "helper-link").read_bytes(), content)
            self.assertEqual(os.readlink(root / "helper-link"), "helper.bin")
            self.assertEqual((root / ".git/config").read_text(), "private repository config")
            self.assertEqual((root / ".env").read_text(), "secret fixture")
        self.assertEqual(row["fingerprint_after"], before)
        self.assertEqual(manager.fingerprint(backup), before)

    def test_existing_destination_blocks_before_backups_or_changes(self):
        self.target.mkdir(parents=True)
        (self.target / "local-edit").write_text("preserve")
        with self.assertRaises(ValueError):
            manager.consolidate(self.manifest(), apply=True)
        self.assertEqual((self.target / "local-edit").read_text(), "preserve")
        self.assertFalse((self.library / ".backups").exists())
        self.assertFalse(self.source.is_symlink())

    def test_invalid_later_entry_blocks_entire_manifest(self):
        data = self.manifest()
        data["entries"].append({"source": str(self.base / "missing"), "target": str(self.library / "other")})
        with self.assertRaises(ValueError):
            manager.consolidate(data, apply=True)
        self.assertFalse(self.library.exists())
        self.assertFalse(self.source.is_symlink())

    def test_nested_sources_and_duplicate_targets_are_rejected_without_changes(self):
        child = self.source / "nested-skill"
        child.mkdir()
        (child / "SKILL.md").write_text("child")
        other = self.base / "other-skill"
        other.mkdir()
        (other / "SKILL.md").write_text("other")
        for source, target in ((child, self.library / "nested"), (other, self.target)):
            with self.subTest(source=source):
                data = self.manifest()
                data["entries"].append({"source": str(source), "target": str(target)})
                with self.assertRaises(ValueError):
                    manager.consolidate(data, apply=True)
                self.assertFalse(self.library.exists())

    def test_source_symlink_and_escape_targets_are_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.source)
        for source, target in ((alias, self.target), (self.source, self.base / "outside"), (self.source, self.source / "inside")):
            with self.subTest(source=source, target=target):
                data = {"library": str(self.library), "entries": [{"source": str(source), "target": str(target)}]}
                with self.assertRaises(ValueError):
                    manager.consolidate(data, apply=True)
                self.assertFalse(self.library.exists())

    def test_external_relative_symlink_and_git_worktree_are_blocked(self):
        (self.source / "external-link").symlink_to("../shared-helper")
        with self.assertRaisesRegex(ValueError, "External relative symlink"):
            manager.consolidate(self.manifest(), apply=True)
        self.assertFalse(self.library.exists())
        (self.source / "external-link").unlink()
        (self.source / ".git").write_text("gitdir: /some/worktree")
        with self.assertRaisesRegex(ValueError, "Git worktree/submodule"):
            manager.consolidate(self.manifest(), apply=True)
        self.assertFalse(self.library.exists())

    def test_link_failure_restores_original_and_marks_remaining_unapplied(self):
        second = self.base / "second-skill"
        second.mkdir()
        (second / "SKILL.md").write_text("second")
        data = self.manifest()
        data["entries"].append({"source": str(second), "target": str(self.library / "second-skill")})
        before = manager.fingerprint(self.source)
        with patch.object(Path, "symlink_to", side_effect=OSError("injected link failure")):
            result = manager.consolidate(data, apply=True)
        self.assertFalse(result["ok"])
        self.assertEqual([row["status"] for row in result["entries"]], ["failed", "not-applied"])
        self.assertEqual(result["entries"][0]["recovery"], "restored-original")
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(manager.fingerprint(self.source), before)
        self.assertFalse(self.target.exists())
        self.assertFalse(second.is_symlink())
        self.assertTrue(Path(result["entries"][0]["backup"]).is_dir())

    def test_concurrent_original_conflict_is_never_overwritten_on_recovery(self):
        original_link = Path.symlink_to

        def conflicting_link(path, target, target_is_directory=False):
            path.write_text("concurrent original")
            return original_link(path, target, target_is_directory=target_is_directory)

        with patch.object(Path, "symlink_to", new=conflicting_link):
            result = manager.consolidate(self.manifest(), apply=True)
        self.assertFalse(result["ok"])
        self.assertIn("recovery_error", result["entries"][0])
        self.assertEqual(self.source.read_text(), "concurrent original")
        self.assertTrue((self.target / "SKILL.md").is_file())
        self.assertTrue(Path(result["entries"][0]["backup"]).is_dir())

    def test_exclusive_rename_preserves_existing_destination(self):
        self.target.mkdir(parents=True)
        (self.target / "local-edit").write_text("keep")
        with self.assertRaises(OSError):
            manager.rename_without_replace(self.source, self.target)
        self.assertEqual((self.target / "local-edit").read_text(), "keep")
        self.assertTrue((self.source / "SKILL.md").is_file())

    def test_grouped_package_preserves_shared_helper_relationships(self):
        package = self.base / "agent/package"
        child = package / "skills/nested-skill"
        child.mkdir(parents=True)
        (child / "SKILL.md").write_text("Use ../../shared-helper.py")
        (package / "shared-helper.py").write_text("print('shared')\n")
        target = self.library / ".packages/agent-package"
        data = {"library": str(self.library), "entries": [{"source": str(package), "target": str(target), "skills": ["skills/nested-skill"]}]}
        result = manager.consolidate(data, apply=True)
        self.assertTrue(result["ok"])
        self.assertEqual(package.resolve(), target)
        self.assertEqual((package / "skills/nested-skill/../../shared-helper.py").read_text(), "print('shared')\n")
        self.assertEqual((target / "skills/nested-skill/SKILL.md").read_text(), "Use ../../shared-helper.py")

    def test_package_requires_explicit_valid_child_skills(self):
        package = self.base / "package"
        package.mkdir()
        for children in (None, [], ["../agent/skills/example-skill"], ["missing"]):
            with self.subTest(children=children):
                entry = {"source": str(package), "target": str(self.library / ".packages/example")}
                if children is not None:
                    entry["skills"] = children
                with self.assertRaises(ValueError):
                    manager.consolidate({"library": str(self.library), "entries": [entry]}, apply=True)
                self.assertFalse(self.library.exists())

    def test_fingerprint_hashes_safe_contents_without_consuming_secrets_or_git(self):
        (self.source / ".git").mkdir()
        (self.source / ".git/config").write_text("git secret")
        (self.source / ".env").write_text("private")
        (self.source / ".feishu_config.json").write_text("credential config")
        auth_stores = {"auth.json", ".auth.json", "auth-profiles.json", ".auth-profiles.json"}
        for name in auth_stores:
            (self.source / name).write_text("credential store fixture")
        (self.source / ".secrets").mkdir()
        (self.source / ".secrets/connection.txt").write_text("credential fixture")
        (self.source / "cache").mkdir()
        (self.source / "cache/token").write_text("private")
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path.name in {".env", ".feishu_config.json"} | auth_stores or ".secrets" in path.parts or ".git" in path.parts or "cache" in path.parts:
                raise AssertionError("Sensitive content must not be hashed")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=guarded_open):
            before = manager.fingerprint(self.source)
        (self.source / ".env").write_text("changed")
        self.assertEqual(manager.fingerprint(self.source), before)
        (self.source / "helper.bin").write_bytes(b"x" * 258)
        self.assertNotEqual(manager.fingerprint(self.source), before)

    def test_cli_apply_writes_new_report_and_refuses_report_overwrite(self):
        report_path = self.base / "reports/result.json"
        manifest_path = self.base / "manifest.json"
        manifest_path.write_text(json.dumps(self.manifest(report_path=str(report_path))))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = manager.main([str(manifest_path), "--apply"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), json.loads(report_path.read_text()))
        with self.assertRaises(ValueError):
            manager.consolidate(self.manifest(report_path=str(report_path)), apply=True)


if __name__ == "__main__":
    unittest.main()
