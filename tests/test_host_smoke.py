"""Offline tests of host-harness isolation and result assertions. No Docker/network."""

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from host_smoke import (
    CheckFailure, PROVIDER_ID, SERVICES, checked_state, isolated_compose,
    verify_invalid, verify_success, workflow_graph,
)


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
