"""Offline checks of the example's wiring using the real plugin and SDK.

Selector resolution here is a small test helper, not a Dify workflow executor
or a claim that a workspace import has been tested. All HTTP uses fixtures.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import yaml

from host_smoke import workflow_graph
from test_search import SearchGifsTool, sample


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "search-gifs.yml"


class WorkflowExampleTests(unittest.TestCase):
    def setUp(self):
        self.dsl = yaml.safe_load(EXAMPLE.read_text())
        self.graph = self.dsl["workflow"]["graph"]
        self.nodes = {n["id"]: n["data"] for n in self.graph["nodes"]}
        self.assertEqual(len(self.nodes), len(self.graph["nodes"]), "Duplicate node IDs")
        guard = patch("socket.socket", side_effect=AssertionError("Network forbidden in example tests"))
        guard.start()
        self.addCleanup(guard.stop)

    def parameters(self, inputs):
        declared = {v["variable"] for v in self.nodes["start"]["variables"]}
        bindings = self.nodes["tool"]["tool_parameters"] | self.nodes["tool"]["tool_configurations"]
        values = {}
        for name, binding in bindings.items():
            if binding["type"] == "constant":
                values[name] = binding["value"]
            else:
                self.assertEqual(binding["type"], "variable")
                owner, variable = binding["value"]
                self.assertEqual(owner, "start")
                self.assertIn(variable, declared, "Selector names an undeclared input")
                values[name] = inputs[variable]
        return values

    def invoke_fixture(self, topic, payload, status=200):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(status, json=payload)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            with patch("tools.search_gifs.httpx.Client", return_value=client):
                messages = list(SearchGifsTool.from_credentials({}).invoke(self.parameters({"topic": topic})))
        finally:
            client.close()
        json_messages = [m.message.json_object for m in messages if m.type.value == "json"]
        pool = {"tool": {"json": json_messages}}
        output = {}
        for binding in self.nodes["end"]["outputs"]:
            owner, field = binding["value_selector"]
            output[binding["variable"]] = pool[owner][field]
        return output, requests

    def test_graph_preserves_tested_tool_contract_and_has_no_extra_nodes(self):
        self.assertEqual(self.dsl["kind"], "app")
        self.assertEqual(self.dsl["app"]["mode"], "workflow")
        self.assertIsInstance(self.dsl["version"], str)
        self.assertEqual([n["data"]["type"] for n in self.graph["nodes"]], ["start", "tool", "end"])
        self.assertEqual([(e["source"], e["target"]) for e in self.graph["edges"]], [("start", "tool"), ("tool", "end")])
        tested_tool = workflow_graph("fixture")["nodes"][1]["data"]
        for field in ("provider_id", "provider_type", "provider_name", "tool_name", "tool_node_version", "retry_config"):
            self.assertEqual(self.nodes["tool"][field], tested_tool[field])
        self.assertEqual(self.dsl["workflow"]["environment_variables"], [])
        self.assertEqual(self.dsl["workflow"]["conversation_variables"], [])
        self.assertFalse(self.dsl["workflow"]["features"]["file_upload"]["enabled"])
        self.assertEqual(self.nodes["end"]["outputs"][0]["value_type"], "array[object]")

    def test_bound_topic_reaches_real_plugin_and_original_url_reaches_end(self):
        payload = sample()
        result, requests = self.invoke_fixture("  კატა & dog?  ", payload)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.params["q"], "კატა & dog?")
        self.assertEqual(requests[0].url.params["limit"], "1")
        self.assertEqual(requests[0].url.params["page"], "1")
        self.assertEqual(result["gifs"][0]["data"][0]["url"], payload["data"][0]["url"])
        self.assertNotEqual(result["gifs"][0]["data"][0]["url"], payload["data"][0]["preview_url"])
        self.assertEqual(result["gifs"][0]["pagination"], payload["pagination"])

    def test_empty_response_reaches_end_without_inventing_a_url(self):
        payload = {"data": [], "pagination": {"page": 1, "has_next": False, "next_page": None}}
        result, _ = self.invoke_fixture("unmatched fixture", payload)
        self.assertEqual(result, {"gifs": [payload]})

    def test_failed_search_does_not_become_a_successful_end_result(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.invoke_fixture("fixture", {"error": "fixture outage"}, status=503)

    def test_topic_boundaries_are_enforced_before_any_request(self):
        max_length = self.nodes["start"]["variables"][0]["max_length"]
        with patch("tools.search_gifs.httpx.Client") as transport:
            for topic in ("", "  ", "x" * (max_length + 1)):
                with self.subTest(length=len(topic)), self.assertRaisesRegex(ValueError, "1 to 200"):
                    list(SearchGifsTool.from_credentials({}).invoke(self.parameters({"topic": topic})))
            transport.assert_not_called()
        result, _ = self.invoke_fixture("x" * max_length, sample())
        self.assertEqual(len(result["gifs"][0]["data"]), 1)


if __name__ == "__main__":
    unittest.main()
