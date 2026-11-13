import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import contextlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("skill_catalog", ROOT / "scripts/skill_catalog.py")
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class SkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.library = self.base / "library"
        self.library.mkdir()
        self.output = self.base / "catalog.json"

    def write(self, name, frontmatter, body="# Skill\n"):
        path = self.library / name
        path.mkdir()
        (path / "SKILL.md").write_text(
            "---\n%s\n---\n\n%s" % (frontmatter, body), encoding="utf-8"
        )

    def build(self):
        document = catalog.build_catalog(self.library)
        catalog.write_catalog(document, self.output)
        return document

    def test_builds_summary_and_writes_private_catalog(self):
        self.write(
            "deploy-frontend",
            "name: deploy-frontend\n"
            "description: Deploy the GMS frontend\n"
            "whenToUse: Use for frontend deployment\n"
            "aliases: web, portal\n"
            "tags: deploy, frontend\n",
        )
        document = self.build()
        self.assertEqual(document["counts"]["skills"], 1)
        self.assertEqual(document["counts"]["with_when_to_use"], 1)
        self.assertEqual(document["counts"]["with_aliases"], 1)
        self.assertEqual(document["skills"][0]["aliases"], ["web", "portal"])
        self.assertEqual(document["skills"][0]["when_to_use"], "Use for frontend deployment")
        if os.name != "nt":
            self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)

    def test_search_ranks_name_description_and_alias(self):
        self.write(
            "deploy-frontend",
            "name: deploy-frontend\n"
            "description: Deploy the GMS frontend\n"
            "whenToUse: Use for frontend deployment\n"
            "aliases: web, portal\n",
        )
        self.write(
            "deploy-backend",
            "name: deploy-backend\n"
            "description: Deploy the backend service\n",
        )
        self.write(
            "billing-report",
            "name: billing-report\n"
            "description: Merge Alibaba Cloud monthly bills\n",
        )
        self.build()
        result = catalog.search(self.output, "deploy frontend", 5)
        self.assertFalse(result["no_match"])
        self.assertEqual(result["candidates"][0]["name"], "deploy-frontend")
        self.assertIn("deploy", result["candidates"][0]["matched"])
        self.assertEqual(catalog.search(self.output, "portal")["candidates"][0]["name"], "deploy-frontend")
        self.assertEqual(catalog.search(self.output, "backend")["candidates"][0]["name"], "deploy-backend")
        self.assertEqual(catalog.search(self.output, "billing")["candidates"][0]["name"], "billing-report")

    def test_limit_and_no_match(self):
        self.write("one", "name: one\ndescription: Deploy frontend\n")
        self.write("two", "name: two\ndescription: Deploy frontend again\n")
        self.build()
        result = catalog.search(self.output, "deploy", 1)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertGreaterEqual(result["total"], 2)
        missing = catalog.search(self.output, "kubernetes cluster", 5)
        self.assertTrue(missing["no_match"])
        self.assertEqual(missing["candidates"], [])

    def test_duplicate_alias_is_collapsed_and_prefers_canonical(self):
        self.write("one", "name: one\ndescription: Deploy frontend\n")
        (self.library / "one-alias").symlink_to(self.library / "one")
        document = self.build()
        self.assertEqual(document["counts"]["skills"], 1)
        self.assertEqual(document["counts"]["duplicates"], 1)
        result = catalog.search(self.output, "deploy", 5)
        self.assertEqual([item["name"] for item in result["candidates"]], ["one"])

    def test_disabled_model_invocation_is_not_indexed(self):
        self.write(
            "private-skill",
            "name: private-skill\n"
            "description: Private helper\n"
            "disable-model-invocation: true\n",
        )
        document = self.build()
        self.assertEqual(document["counts"]["skills"], 0)

    def test_catalog_revision_is_stable_for_unchanged_content(self):
        self.write("one", "name: one\ndescription: Deploy frontend\n")
        first = self.build()["revision"]
        second = self.build()["revision"]
        self.assertEqual(first, second)

    def test_catalog_check_detects_stale_content(self):
        self.write("one", "name: one\ndescription: Deploy frontend\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(catalog.main([
                "catalog", "--library", str(self.library), "--catalog", str(self.output),
            ]), 0)
            self.assertEqual(catalog.main([
                "catalog", "--library", str(self.library), "--catalog", str(self.output),
                "--check",
            ]), 0)
        (self.library / "one" / "SKILL.md").write_text(
            "---\nname: one\ndescription: Deploy frontend v2\n---\n\n# Skill\n",
            encoding="utf-8",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(catalog.main([
                "catalog", "--library", str(self.library), "--catalog", str(self.output),
                "--check",
            ]), 1)

    def test_catalog_dry_run_writes_nothing(self):
        self.write("one", "name: one\ndescription: Deploy frontend\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(catalog.main([
                "catalog", "--library", str(self.library), "--catalog", str(self.output),
                "--dry-run",
            ]), 0)
        self.assertFalse(self.output.exists())

    def test_missing_catalog_is_an_error(self):
        with self.assertRaises(ValueError):
            catalog.search(self.base / "missing.json", "deploy")

    def test_empty_query_is_an_error(self):
        self.write("one", "name: one\ndescription: Deploy frontend\n")
        self.build()
        with self.assertRaises(ValueError):
            catalog.search(self.output, "   ")

    def test_cli_text_and_exit_code(self):
        self.write("one", "name: one\ndescription: Deploy frontend\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(catalog.main([
                "catalog", "--library", str(self.library), "--catalog", str(self.output),
            ]), 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(catalog.main([
                "search", "deploy", "--catalog", str(self.output), "--format", "text",
            ]), 0)
        self.assertIn("one", output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(catalog.main([
                "search", "kubernetes", "--catalog", str(self.output),
            ]), 1)


if __name__ == "__main__":
    unittest.main()
