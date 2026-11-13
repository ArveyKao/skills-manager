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

    def test_inventory_strict_exit_code_on_conflict(self):
        conflict = self.base / "conflict"
        (conflict / self.source.name).mkdir(parents=True)
        (conflict / self.source.name / "local-edit").write_text("keep")
        report = manager.inventory(self.library, [conflict])
        self.assertFalse(report["ok"])
        with contextlib.redirect_stdout(io.StringIO()):
            strict = manager.main([
                "inventory", "--library", str(self.library),
                "--agent-root", str(conflict), "--strict",
            ])
        self.assertEqual(strict, 1)
        with contextlib.redirect_stdout(io.StringIO()):
            normal = manager.main([
                "inventory", "--library", str(self.library),
                "--agent-root", str(conflict),
            ])
        self.assertEqual(normal, 0)

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
        with patch.dict(os.environ, {"CODEX_HOME": str(self.base / "custom-codex")}), patch.object(Path, "home", return_value=self.base):
            self.assertEqual(manager.default_library(), self.base / "skills-manager")
            self.assertEqual(manager.default_roots(), [self.base / ".agents/skills", self.base / "custom-codex/skills", self.base / ".claude/skills"])

    def test_cli_default_library_is_central_with_or_without_codex_home(self):
        central = self.base / "skills-manager"
        source = central / "central-skill"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("---\nname: central-skill\ndescription: A fixture\n---\n")
        for configured in (False, True):
            with self.subTest(configured=configured):
                codex = self.base / ("custom-codex" if configured else ".codex")
                output = io.StringIO()
                with patch.dict(os.environ, {"CODEX_HOME": str(codex) if configured else ""}), patch.object(Path, "home", return_value=self.base), contextlib.redirect_stdout(output):
                    code = manager.main(["inventory"])
                report = json.loads(output.getvalue())
                self.assertEqual(code, 0)
                self.assertEqual(report["library"], str(central))
                self.assertEqual([item["name"] for item in report["entries"]], ["central-skill"])
                self.assertEqual([item["root"] for item in report["agent_roots"]], [str(self.base / ".agents/skills"), str(codex / "skills"), str(self.base / ".claude/skills")])
                self.assertTrue(all(mount["status"] == "missing" for mount in report["entries"][0]["mounts"]))
                self.assertFalse((codex / "skills").exists())

    def test_cli_default_sync_uses_central_source_and_codex_discovery_root(self):
        central = self.base / "skills-manager"
        source = central / "central-skill"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("---\nname: central-skill\ndescription: A fixture\n---\n")
        codex = self.base / "custom-codex"
        output = io.StringIO()
        with patch.dict(os.environ, {"CODEX_HOME": str(codex)}), patch.object(Path, "home", return_value=self.base), contextlib.redirect_stdout(output):
            code = manager.main(["sync", "central-skill", "--apply"])
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual([item["status"] for item in report["links"]], ["created"] * 3)
        for root in (self.base / ".agents/skills", codex / "skills", self.base / ".claude/skills"):
            self.assertTrue((root / source.name).is_symlink())
            self.assertEqual((root / source.name).resolve(), source)
        self.assertTrue(source.is_dir())
        self.assertFalse(source.is_symlink())
        self.assertFalse((self.base / ".codex/skills").exists())

    def test_cli_explicit_library_overrides_central_default(self):
        output = io.StringIO()
        with patch.object(Path, "home", return_value=self.base), contextlib.redirect_stdout(output):
            code = manager.main(["inventory", "--library", str(self.library), "--agent-root", str(self.root)])
        self.assertEqual(code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["library"], str(self.library))
        self.assertEqual([item["name"] for item in report["entries"]], ["example-skill"])
        self.assertFalse((self.base / "skills-manager").exists())

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


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.library = self.base / "library"
        self.skill = self.library / "check-skill"
        self.skill.mkdir(parents=True)
        self.write("SKILL.md", "---\nname: check-skill\ndescription: A fixture skill for check tests\n---\n\n# Check\n")
        self.write("references/guide.md", "# Guide\n")

    def write(self, relative, text):
        path = self.skill / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_check(self, **kwargs):
        return manager.check(self.library, ["check-skill"], **kwargs)

    def codes(self, report):
        return [item["code"] for item in report["skills"][0]["issues"]]

    def test_valid_skill_passes(self):
        self.write("SKILL.md", "---\nname: check-skill\ndescription: A fixture skill for check tests\n---\n\n[guide](references/guide.md)\n")
        report = self.run_check()
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["errors"], 0)
        self.assertEqual(report["counts"]["warnings"], 0)

    def test_external_schemes_are_not_local_links(self):
        self.write("references/guide.md", "[web](https://example.com)\n[file](file:///tmp/example)\n")
        report = self.run_check()
        self.assertTrue(report["ok"])
        self.assertNotIn("link_broken", self.codes(report))

    def test_broken_link_is_an_error(self):
        self.write("SKILL.md", "---\nname: check-skill\ndescription: A fixture skill for check tests\n---\n\n[gone](references/gone.md)\n")
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertIn("link_broken", self.codes(report))

    def test_name_mismatch_and_missing_frontmatter(self):
        self.write("SKILL.md", "---\nname: other-skill\ndescription: A fixture skill for check tests\n---\n")
        self.assertIn("name_mismatch", self.codes(self.run_check()))
        self.write("SKILL.md", "# no frontmatter\n")
        self.assertIn("frontmatter_missing", self.codes(self.run_check()))

    def test_host_path_is_info_not_error(self):
        self.write("references/guide.md", "See " + "/Users/" + "example/private/file.txt\n")
        report = self.run_check()
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["counts"]["info"], 1)
        self.assertIn("path_absolute_host", self.codes(report))

    def test_permissions_warning_and_strict(self):
        guide = self.write("references/guide.md", "# Guide\n")
        guide.chmod(0o600)
        report = self.run_check()
        self.assertTrue(report["ok"])
        self.assertIn("permissions", self.codes(report))
        strict = self.run_check(strict=True)
        self.assertFalse(strict["ok"])

    def test_python_and_shell_syntax_errors(self):
        self.write("scripts/bad.py", "def broken(\n")
        self.assertIn("script_syntax", self.codes(self.run_check()))
        self.write("scripts/bad.py", "print('ok')\n")
        self.write("scripts/bad.sh", "if then\n")
        self.assertIn("script_syntax", self.codes(self.run_check()))

    def test_secret_value_is_not_printed(self):
        secret = "AKIA" + "A" * 16
        self.write("references/leak.md", "key = \"%s\"\n" % secret)
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertIn("secret_pattern", self.codes(report))
        self.assertNotIn(secret, json.dumps(report))

    def test_no_secrets_skips_pattern_scan(self):
        secret = "AKIA" + "A" * 16
        self.write("references/leak.md", "key = \"%s\"\n" % secret)
        report = self.run_check(secrets=False)
        self.assertTrue(report["ok"])
        self.assertNotIn("secret_pattern", self.codes(report))

    def test_stale_metadata_is_opt_in(self):
        self.write("SKILL.md", "---\nname: check-skill\ndescription: A fixture skill for check tests\nlast_validated: 2020-01-01\n---\n")
        self.assertIn("stale_metadata", self.codes(self.run_check(stale_days=90)))
        self.assertNotIn("stale_metadata", self.codes(self.run_check(stale_days=0)))

    def test_alias_name_mismatch_is_warning(self):
        target = self.library / "target-dir"
        target.mkdir()
        (target / "SKILL.md").write_text("---\nname: canonical-name\ndescription: A fixture skill for alias tests\n---\n")
        alias = self.library / "short"
        alias.symlink_to(target)
        report = manager.check(self.library, ["short"], strict=False)
        self.assertTrue(report["ok"])
        self.assertIn("name_mismatch_alias", [i["code"] for i in report["skills"][0]["issues"]])

    def test_cli_text_and_exit_code(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = manager.main(["check", "check-skill", "--library", str(self.library), "--format", "text"])
        self.assertEqual(code, 0)
        self.assertIn("OK", output.getvalue())
        self.write("SKILL.md", "---\nname: check-skill\ndescription: A fixture skill for check tests\n---\n\n[gone](missing.md)\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(manager.main(["check", "check-skill", "--library", str(self.library)]), 1)

    def test_sync_rejects_empty_skill_md(self):
        self.write("SKILL.md", "")
        with self.assertRaises(ValueError):
            manager.sync(self.library, [self.base / "root"], ["check-skill"], apply=True)
        self.assertFalse((self.base / "root").exists())

    def test_shell_syntax_error_does_not_print_secret(self):
        secret = "AKIA" + "B" * 16
        self.write("scripts/bad.sh", "if then # %s\nfi\n" % secret)
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertIn("script_syntax", self.codes(report))
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn(secret, manager.check_text(report, True))
        self.assertNotIn(secret, json.dumps(self.run_check(secrets=False)))

    def test_symlink_outside_skill_is_an_error(self):
        outside = self.base / "outside.txt"
        outside.write_text("outside fixture\n")
        (self.skill / "references" / "outside").symlink_to(outside)
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertIn("symlink_outside", self.codes(report))

    def test_symlink_to_sensitive_path_is_an_error(self):
        secrets = self.skill / "secrets"
        secrets.mkdir()
        (self.skill / "references" / "secret-link").symlink_to(secrets)
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertIn("symlink_sensitive", self.codes(report))

    def test_internal_symlink_is_informational(self):
        guide = self.skill / "references" / "guide.md"
        (self.skill / "references" / "guide-link.md").symlink_to(guide)
        report = self.run_check()
        self.assertTrue(report["ok"])
        self.assertIn("symlink_internal", self.codes(report))

    def test_broken_internal_symlink_is_an_error(self):
        (self.skill / "references" / "broken-link.md").symlink_to(
            self.skill / "references" / "missing.md"
        )
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertIn("symlink_outside", self.codes(report))

    def test_publish_rejects_outside_link_and_host_path(self):
        outside = self.library / "outside.md"
        outside.write_text("# Outside\n")
        self.write("references/guide.md", "[outside](../../outside.md)\nSee " + "/Users/" + "example/private/file.txt\n")
        local = self.run_check()
        self.assertTrue(local["ok"])
        published = self.run_check(publish=True)
        self.assertFalse(published["ok"])
        self.assertIn("link_outside_skill", self.codes(published))
        self.assertIn("path_absolute_host", self.codes(published))

    def test_inline_yaml_comments_are_ignored(self):
        self.write("SKILL.md", "---\nname: check-skill # canonical name\ndescription: A fixture skill for check tests # keep\n---\n")
        self.assertTrue(self.run_check()["ok"])

    def test_inventory_broken_library_entry_is_not_ok(self):
        (self.library / "broken-skill").symlink_to(self.base / "missing-skill")
        report = manager.inventory(self.library, [self.base / "root"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["counts"]["broken"], 1)

    def test_inventory_broken_library_entry_exit_code(self):
        (self.library / "broken-skill").symlink_to(self.base / "missing-skill")
        with contextlib.redirect_stdout(io.StringIO()):
            code = manager.main([
                "inventory", "--library", str(self.library), "--agent-root",
                str(self.base / "root"), "--strict",
            ])
        self.assertEqual(code, 1)

    def test_cli_publish_flag_rejects_host_path(self):
        self.write("references/guide.md", "See " + "/Users/" + "example/private/file.txt\n")
        with contextlib.redirect_stdout(io.StringIO()):
            code = manager.main([
                "check", "check-skill", "--library", str(self.library),
                "--publish", "--format", "text",
            ])
        self.assertEqual(code, 1)

    def test_sync_all_reports_alias_scope(self):
        self.write("SKILL.md", "---\nname: check-skill\ndescription: A fixture skill for check tests\n---\n")
        alias = self.library / "short-alias"
        alias.symlink_to(self.skill)
        report = manager.sync(self.library, [self.base / "root"], [], all_skills=True)
        self.assertTrue(report["ok"])
        self.assertTrue(any("alias" in warning for warning in report["warnings"]))

if __name__ == "__main__":
    unittest.main()
