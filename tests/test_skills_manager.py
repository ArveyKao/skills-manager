import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/skills_manager.py"
SPEC = importlib.util.spec_from_file_location("skills_manager", SCRIPT)
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class SkillsManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.library = self.base / "library"
        self.source = self.library / "example-skill"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text("---\nname: example-skill\ndescription: A fixture\n---\n")
        self.root = self.base / "first agent/skills"

    def sync(self, roots=None, **kwargs):
        return manager.sync(self.library, [self.root] if roots is None else roots, ["example-skill"], **kwargs)

    def test_preview_creates_nothing(self):
        result = self.sync()
        self.assertTrue(result["ok"])
        self.assertEqual(result["links"][0]["status"], "create")
        self.assertFalse(self.root.parent.exists())

    def test_three_roots_are_idempotent_and_deduplicated(self):
        roots = [self.root, self.base / "second", self.base / "third"]
        result = self.sync(roots + [self.root], apply=True)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["links"]), 3)
        for root in roots:
            self.assertEqual((root / self.source.name).resolve(), self.source)
        again = self.sync(roots, apply=True)
        self.assertEqual([item["status"] for item in again["links"]], ["linked"] * 3)

    def test_conflicts_prevent_any_change_and_preserve_content(self):
        for kind in ("directory", "file", "wrong-link", "broken-link"):
            with self.subTest(kind=kind):
                root = self.base / kind
                root.mkdir()
                target = root / self.source.name
                if kind == "directory":
                    target.mkdir()
                    (target / "local-edit").write_text("keep me")
                elif kind == "file":
                    target.write_text("keep me")
                else:
                    target.symlink_to(self.base if kind == "wrong-link" else self.base / "missing")
                before = os.readlink(target) if target.is_symlink() else None
                result = self.sync([self.root, root], apply=True)
                self.assertFalse(result["ok"])
                self.assertFalse(self.root.exists())
                if kind == "directory":
                    self.assertEqual((target / "local-edit").read_text(), "keep me")
                elif kind == "file":
                    self.assertEqual(target.read_text(), "keep me")
                else:
                    self.assertEqual(os.readlink(target), before)

    def test_inventory_reports_orphans_and_skips_hidden_without_content_reads(self):
        self.sync(apply=True)
        (self.root / "orphan").symlink_to(self.base / "missing")
        (self.library / "cli-only").mkdir()
        (self.library / ".system").mkdir()
        with patch.object(Path, "read_text", side_effect=AssertionError("No file-content reads")), patch.object(Path, "read_bytes", side_effect=AssertionError("No file-content reads")):
            report = manager.inventory(self.library, [self.root])
        sources = {item["name"]: item for item in report["entries"]}
        self.assertEqual(sources["example-skill"]["mounts"][0]["status"], "linked")
        self.assertFalse(sources["cli-only"]["has_skill_md"])
        self.assertNotIn(".system", sources)
        mounts = {item["name"]: item for item in report["agent_roots"][0]["entries"]}
        self.assertFalse(mounts["orphan"]["managed_name"])
        self.assertEqual(mounts["orphan"]["status"], "broken-link")

    def test_all_selects_only_skills(self):
        (self.library / "cli-only").mkdir()
        (self.library / ".system").mkdir()
        (self.library / ".system/SKILL.md").write_text("hidden")
        result = manager.sync(self.library, [self.root], [], all_skills=True, apply=True)
        self.assertTrue(result["ok"])
        self.assertEqual([p.name for p in self.root.iterdir()], ["example-skill"])

    def test_invalid_selection_never_writes(self):
        for names in ([], ["../escape"], ["/absolute"], [".system"], [""], ["bad name"], ["a" * 65]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                manager.sync(self.library, [self.root], names, apply=True)
        with self.assertRaises(ValueError):
            manager.sync(self.library, [self.root], ["example-skill"], all_skills=True, apply=True)
        with self.assertRaises(FileNotFoundError):
            manager.sync(self.library, [self.root], ["absent"], apply=True)
        self.assertFalse(self.root.exists())

    def test_invalid_later_source_prevents_partial_apply(self):
        (self.library / "cli-only").mkdir()
        with self.assertRaises(ValueError):
            manager.sync(self.library, [self.root], ["example-skill", "cli-only"], apply=True)
        self.assertFalse(self.root.exists())

    def test_bad_root_ancestor_prevents_partial_apply(self):
        blocked = self.base / "blocked"
        blocked.write_text("keep me")
        with self.assertRaises(ValueError):
            self.sync([self.root, blocked / "nested"], apply=True)
        self.assertFalse(self.root.exists())
        broken = self.base / "broken-root"
        broken.symlink_to(self.base / "absent")
        with self.assertRaises(ValueError):
            self.sync([self.root, broken], apply=True)
        self.assertFalse((self.base / "absent").exists())

    def test_alias_source_and_canonical_directory(self):
        alias = self.library / "alias-skill"
        alias.symlink_to(self.source)
        result = manager.sync(self.library, [self.root], [alias.name], apply=True)
        self.assertTrue(result["ok"])
        self.assertEqual((self.root / alias.name).resolve(), self.source)
        result = self.sync([self.library], apply=True)
        self.assertEqual(result["links"][0]["status"], "canonical-directory")
        self.assertFalse(self.source.is_symlink())

    def test_self_containing_mount_rejected(self):
        with self.assertRaises(ValueError):
            self.sync([self.source / "nested"], apply=True)
        self.assertFalse((self.source / "nested").exists())

    def test_symlink_loop_is_reported_and_preserved(self):
        self.root.mkdir(parents=True)
        target = self.root / self.source.name
        target.symlink_to(target)
        result = self.sync(apply=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["links"][0]["status"], "broken-link")
        self.assertEqual(os.readlink(target), str(target))

    def test_late_failure_reports_partial_state_without_overwrite(self):
        roots = [self.root, self.base / "second", self.base / "third"]
        original = Path.symlink_to

        def conflicting_link(path, target, target_is_directory=False):
            if path.parent == roots[1]:
                path.write_text("concurrent edit")
            return original(path, target, target_is_directory=target_is_directory)

        with patch.object(Path, "symlink_to", new=conflicting_link):
            result = self.sync(roots, apply=True)
        self.assertFalse(result["ok"])
        self.assertEqual([item["status"] for item in result["links"]], ["created", "failed", "not-applied"])
        self.assertEqual((roots[1] / self.source.name).read_text(), "concurrent edit")
        self.assertFalse(roots[2].exists())

    def test_codex_home_is_respected_without_reading_other_environment(self):
        with patch.dict(os.environ, {"CODEX_HOME": str(self.base / "custom-codex")}):
            self.assertEqual(manager.default_roots()[1], self.base / "custom-codex/skills")

    def test_cli_custom_roots_override_defaults(self):
        output = io.StringIO()
        with patch.object(manager, "default_roots", side_effect=AssertionError("Explicit roots should win")), contextlib.redirect_stdout(output):
            code = manager.main(["sync", "example-skill", "--library", str(self.library), "--agent-root", str(self.root), "--apply"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["ok"])
        self.assertEqual((self.root / self.source.name).resolve(), self.source)

    def test_cli_conflict_returns_failure_json(self):
        self.root.mkdir(parents=True)
        (self.root / self.source.name).write_text("local")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = manager.main(["sync", "example-skill", "--library", str(self.library), "--agent-root", str(self.root), "--apply"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
