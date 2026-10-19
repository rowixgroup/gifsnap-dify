"""Offline tests of host-harness isolation and result assertions. No Docker/network."""

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from host_smoke import (
    CheckFailure, DIFY_REVISION, MARKETPLACE_IDENTIFIER, PROVIDER_ID, SERVICES,
    check_dependencies, check_installed, checked_state, checked_template,
    env_defaults, imported_app, isolated_compose, prepare,
    verify_invalid, verify_success, workflow_graph,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "examples" / "search-gifs.yml"


class HostSmokeTests(unittest.TestCase):
    def test_refuses_non_runner(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(CheckFailure):
            checked_state(Path("/tmp/gifsnap-dify-host"))

    def test_refuses_other_directory(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "RUNNER_TEMP": root}):
            with self.assertRaises(CheckFailure):
                checked_state(Path(root) / "existing-workspace")
            self.assertEqual(checked_state(Path(root) / "gifsnap-dify-host"), Path(root).resolve() / "gifsnap-dify-host")

    def test_generated_stack_exposes_only_loopback_api(self):
        original = {"services": {}, "networks": {"default": {}, "ssrf_proxy_network": {"internal": True}}}
        for name in SERVICES:
            original["services"][name] = {"image": "fixture:1", "ports": ["0.0.0.0:1:1"], "restart": "always",
                                          "profiles": ["irrelevant"], "networks": ["default", "ssrf_proxy_network"],
                                          "env_file": ["old.env"], "volumes": ["./volumes/data:/data"],
                                          "depends_on": {"agent_backend": {}, "redis": {}}}
        original["services"]["api"]["image"] = "langgenius/dify-api:1.17.1"
        original["services"]["worker"]["image"] = "langgenius/dify-api:1.17.1"
        original["services"]["plugin_daemon"]["image"] = "langgenius/dify-plugin-daemon:0.6.10-local"
        original_copy = copy.deepcopy(original)
        result = isolated_compose(original, Path("/tmp/source/docker"), Path("/tmp/private-test"))
        self.assertEqual(original, original_copy)
        self.assertEqual(result["services"]["api"]["ports"], ["127.0.0.1:51873:5001"])
        self.assertTrue(result["networks"]["ssrf_proxy_network"]["internal"])
        for name, service in result["services"].items():
            self.assertNotIn("agent_backend", service.get("depends_on", {}))
            self.assertEqual(service["restart"], "no")
            self.assertNotIn("profiles", service)
            if name != "api":
                self.assertNotIn("ports", service)

    def test_graph_has_no_llm_posting_or_retry_and_one_result(self):
        graph = workflow_graph("happy cat")
        self.assertEqual([n["data"]["type"] for n in graph["nodes"]], ["start", "tool", "end"])
        tool = graph["nodes"][1]["data"]
        self.assertEqual(tool["provider_id"], PROVIDER_ID)
        self.assertEqual(tool["tool_name"], "search_gifs")
        self.assertEqual(tool["tool_configurations"], {"limit": {"type": "constant", "value": 1}})
        self.assertFalse(tool["retry_config"]["retry_enabled"])

    def test_refuses_template_that_can_expand_live_requests(self):
        original = checked_template(TEMPLATE.read_text())
        mutations = [
            lambda doc: doc["workflow"]["graph"]["nodes"].append(copy.deepcopy(doc["workflow"]["graph"]["nodes"][1])),
            lambda doc: doc["workflow"]["graph"]["nodes"][1]["data"]["retry_config"].update(retry_enabled=True),
            lambda doc: doc["workflow"]["graph"]["nodes"][1]["data"]["tool_configurations"]["limit"].update(value=10),
            lambda doc: doc["dependencies"][0]["value"].update(marketplace_plugin_unique_identifier="rowixgroup/gifsnap:0.1.0@unsigned"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                document = copy.deepcopy(original)
                mutate(document)
                with self.assertRaises(CheckFailure):
                    checked_template(yaml.safe_dump(document))

    def test_preparation_preserves_template_and_enforces_marketplace_signature(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "RUNNER_TEMP": root}):
            source = Path(root) / "dify"
            (source / "docker").mkdir(parents=True)
            (source / "docker" / "docker-compose.yaml").write_text("services: {}")
            (source / "docker" / ".env.example").write_text("FORCE_VERIFYING_SIGNATURE=false\nMARKETPLACE_ENABLED=false\n")
            state = Path(root) / "gifsnap-dify-host"
            with patch("host_smoke.subprocess.check_output", return_value=DIFY_REVISION), patch("host_smoke.isolated_compose", return_value={}), patch("builtins.print"):
                prepare(source, state, TEMPLATE)
            values = env_defaults((state / ".env").read_text())
            self.assertEqual(values["FORCE_VERIFYING_SIGNATURE"], "true")
            self.assertEqual(values["MARKETPLACE_ENABLED"], "true")
            self.assertEqual(values["MARKETPLACE_API_URL"], "https://marketplace.dify.ai")
            self.assertEqual((state / "workflow.yml").read_bytes(), TEMPLATE.read_bytes())
            self.assertFalse((state / "package.difypkg").exists())
            self.assertEqual((state / ".env").stat().st_mode & 0o777, 0o600)

    def test_only_complete_warning_free_version_matched_import_passes(self):
        result = {"status": "completed", "app_id": "new-app", "app_mode": "workflow",
                  "current_dsl_version": "0.7.0", "imported_dsl_version": "0.7.0", "warnings": []}
        self.assertEqual(imported_app(result), "new-app")
        for change in ({"status": "pending"}, {"status": "completed-with-warnings"}, {"warnings": [{}]},
                       {"imported_dsl_version": "0.3.1"}, {"app_id": None}):
            with self.subTest(change=change), self.assertRaises(CheckFailure):
                imported_app(result | change)

    def test_dependency_and_installed_provenance_are_both_required(self):
        missing = {"leaked_dependencies": [{"type": "marketplace", "value": {
            "marketplace_plugin_unique_identifier": MARKETPLACE_IDENTIFIER}}]}
        check_dependencies(missing, installed=False)
        check_dependencies({"leaked_dependencies": []}, installed=True)
        installed = {"plugins": [{"plugin_unique_identifier": MARKETPLACE_IDENTIFIER, "source": "marketplace"}]}
        check_installed(installed)
        with self.assertRaises(CheckFailure):
            check_dependencies(missing, installed=True)
        # An empty dependency list alone can also mean its Redis record expired.
        with self.assertRaises(CheckFailure):
            check_installed({"plugins": []})
        installed["plugins"][0]["source"] = "package"
        with self.assertRaises(CheckFailure):
            check_installed(installed)

    def test_invalid_query_requires_plugin_error(self):
        verify_invalid([{"event": "workflow_finished", "data": {"status": "failed", "error": "Search phrase must contain 1 to 200 characters"}}])
        with self.assertRaises(CheckFailure):
            verify_invalid([{"event": "workflow_finished", "data": {"status": "failed", "error": "Unrelated infrastructure error"}}])

    def test_success_requires_original_structured_output(self):
        output = [{"data": [{"url": "https://example.test/original.gif", "preview_url": "https://example.test/poster.png"}], "pagination": {"page": 1}}]
        events = [{"event": "node_finished", "data": {"node_id": "tool", "status": "succeeded", "outputs": {"json": output}}},
                  {"event": "workflow_finished", "data": {"status": "succeeded", "outputs": {"gifs": copy.deepcopy(output)}}}]
        report = verify_success(events)
        self.assertTrue(report["full_url_preserved_through_end_node"])
        self.assertTrue(report["poster_field_present"])
        self.assertNotIn("https://", str(report))
        events[1]["data"]["outputs"]["gifs"][0]["data"][0]["url"] = "https://example.test/poster.png"
        with self.assertRaises(CheckFailure):
            verify_success(events)


if __name__ == "__main__":
    unittest.main()
