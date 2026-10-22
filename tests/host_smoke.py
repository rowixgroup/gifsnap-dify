"""Manual, disposable Dify 1.17.1 host/workflow check on a public CI runner.

Never targets an existing workspace. ``prepare`` refuses non-GitHub runners,
verifies the upstream source revision and creates a fresh private state folder.
``run`` uses only that folder and a fixed loopback address. No app is published.
The live case is opt-in and makes at most one workflow invocation; no retries.

Official API source: langgenius/dify at DIFY_REVISION, particularly
controllers/console/{setup,auth/login,workspace/plugin,app/app_import,app/workflow}.py.
This tests the actual console API, plugin daemon and workflow executor, not UI.
"""

from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import quote

import httpx
import yaml

DIFY_REVISION = "8387590ace4a094de812b7847fc6a4c3a27cd52b"
MARKETPLACE_IDENTIFIER = "rowixgroup/gifsnap:0.1.2@a5a0a0bfb6cd2f679a6b92f9869e0398fafaf5315f858d80baa5f831682cdeca"
BASE_URL = "http://127.0.0.1:51873"
PROVIDER_ID = "rowixgroup/gifsnap/gifsnap"
SERVICES = ("init_permissions", "db_postgres", "redis", "ssrf_proxy", "plugin_daemon", "api", "worker")
STATE_NAME = "gifsnap-dify-host"


class CheckFailure(Exception):
    """Only fixed, non-sensitive failure codes may be included in reports."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise CheckFailure(code)


def checked_state(path: Path) -> Path:
    require(os.environ.get("GITHUB_ACTIONS") == "true", "github_runner_required")
    root = Path(os.environ.get("RUNNER_TEMP", "/nonexistent")).resolve()
    path = path.resolve()
    require(root.is_dir() and path.parent == root and path.name == STATE_NAME, "unsafe_state_directory")
    return path


def check_graph(graph: dict) -> None:
    """Refuse extra nodes, outbound tools, changed inputs, or automatic retries."""
    nodes = graph.get("nodes", [])
    require(len(nodes) == 3 and {node.get("id") for node in nodes} == {"start", "tool", "end"}, "unexpected_template_nodes")
    data = {node["id"]: node["data"] for node in nodes}
    require([data[name].get("type") for name in ("start", "tool", "end")] == ["start", "tool", "end"], "unexpected_template_node_types")
    variables = data["start"].get("variables", [])
    require(len(variables) == 1 and variables[0].get("variable") == "topic"
            and variables[0].get("type") == "text-input" and variables[0].get("required") is True
            and variables[0].get("max_length") == 200, "unexpected_template_input")
    tool = data["tool"]
    require(tool.get("provider_id") == PROVIDER_ID and tool.get("provider_type") == "builtin"
            and tool.get("provider_name") == "gifsnap" and tool.get("tool_name") == "search_gifs"
            and tool.get("tool_node_version") == "2", "unexpected_template_tool")
    require(tool.get("tool_parameters") == {"query": {"type": "variable", "value": ["start", "topic"]},
                                            "page": {"type": "constant", "value": 1}}
            and tool.get("tool_configurations") == {"limit": {"type": "constant", "value": 1}}, "unexpected_template_parameters")
    require(tool.get("retry_config") == {"retry_enabled": False, "max_retries": 0, "retry_interval": 0}, "template_retries_not_disabled")
    require(data["end"].get("outputs") == [{"variable": "gifs", "value_selector": ["tool", "json"], "value_type": "array[object]"}], "unexpected_template_output")
    edges = graph.get("edges", [])
    require(len(edges) == 2 and {(edge.get("source"), edge.get("target")) for edge in edges}
            == {("start", "tool"), ("tool", "end")}, "unexpected_template_edges")


def checked_template(content: str) -> dict:
    require(len(content.encode()) < 65536, "template_too_large")
    document = yaml.safe_load(content)
    require(isinstance(document, dict) and document.get("kind") == "app" and document.get("version") == "0.7.0"
            and document.get("app", {}).get("mode") == "workflow", "unexpected_template_format")
    require(document.get("dependencies") == [{"type": "marketplace", "value": {
        "marketplace_plugin_unique_identifier": MARKETPLACE_IDENTIFIER}}], "unexpected_template_dependency")
    workflow = document["workflow"]
    require(not workflow.get("environment_variables") and not workflow.get("conversation_variables"), "template_contains_variables")
    check_graph(workflow["graph"])
    return document


def env_defaults(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#") and "=" in line)


def isolated_compose(original: dict, docker_dir: Path, state: Path) -> dict:
    """Retain official service definitions but narrow this disposable host."""
    result = {"name": "gifsnap-host-smoke", "services": {}, "networks": {}}
    for name in SERVICES:
        service = copy.deepcopy(original["services"][name])
        service.pop("profiles", None)
        service.pop("ports", None)
        service.pop("container_name", None)
        service["restart"] = "no"
        if "depends_on" in service:
            service["depends_on"] = {key: val for key, val in service["depends_on"].items() if key in SERVICES}
        if "env_file" in service:
            service["env_file"] = [str(state / ".env")]
        mounts = []
        for mount in service.get("volumes", []):
            require(isinstance(mount, str), "unexpected_volume_definition")
            source, target = mount.split(":", 1)
            require(source.startswith("./"), "unexpected_volume_source")
            source_path = state / source[2:] if source.startswith("./volumes/") else docker_dir / source[2:]
            mounts.append(str(source_path) + ":" + target)
        if mounts:
            service["volumes"] = mounts
        result["services"][name] = service
    result["services"]["api"]["ports"] = ["127.0.0.1:51873:5001"]
    # This check uses only Tool nodes, not the separate Agent backend or code sandbox.
    # All remaining upstream API/worker/daemon wiring stays in the source .env.
    used_networks = {net for service in result["services"].values() for net in service.get("networks", ["default"])}
    result["networks"] = {net: copy.deepcopy(original.get("networks", {}).get(net, {})) for net in used_networks}
    require(result["services"]["api"]["image"] == "langgenius/dify-api:1.17.1", "unexpected_api_version")
    require(result["services"]["worker"]["image"] == "langgenius/dify-api:1.17.1", "unexpected_worker_version")
    require(result["services"]["plugin_daemon"]["image"] == "langgenius/dify-plugin-daemon:0.6.10-local", "unexpected_daemon_version")
    return result


def prepare(source: Path, state_path: Path, template: Path) -> None:
    state = checked_state(state_path)
    require(not state.exists(), "state_must_be_fresh")
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    require(revision == DIFY_REVISION, "upstream_revision_mismatch")
    template_bytes = template.read_bytes()
    checked_template(template_bytes.decode())
    state.mkdir(mode=0o700)
    docker_dir = source.resolve() / "docker"
    original = yaml.safe_load((docker_dir / "docker-compose.yaml").read_text())
    values = env_defaults((docker_dir / ".env.example").read_text())
    db_password, redis_password = secrets.token_hex(24), secrets.token_hex(24)
    init_password, owner_password = secrets.token_hex(12), secrets.token_hex(20) + "Aa1"
    values.update({
        "SECRET_KEY": secrets.token_hex(32), "INIT_PASSWORD": init_password,
        "DB_PASSWORD": db_password, "DB_DEFAULT_DATABASE": "postgres", "REDIS_PASSWORD": redis_password,
        "CELERY_BROKER_URL": f"redis://:{redis_password}@redis:6379/1",
        "PLUGIN_DAEMON_KEY": secrets.token_hex(32), "PLUGIN_DIFY_INNER_API_KEY": secrets.token_hex(32),
        "CONSOLE_API_URL": BASE_URL, "CONSOLE_WEB_URL": BASE_URL,
        "SERVICE_API_URL": BASE_URL, "APP_API_URL": BASE_URL, "APP_WEB_URL": BASE_URL,
        "CONSOLE_CORS_ALLOW_ORIGINS": BASE_URL, "WEB_API_CORS_ALLOW_ORIGINS": BASE_URL,
        "COOKIE_DOMAIN": "", "COMPOSE_PROFILES": "", "ENABLE_COLLABORATION_MODE": "false",
        "CELERY_WORKER_AMOUNT": "1", "SERVER_WORKER_AMOUNT": "1",
        "LOG_LEVEL": "ERROR", "ENABLE_REQUEST_LOGGING": "false",
        "PLUGIN_PYTHON_ENV_INIT_TIMEOUT": "180", "PLUGIN_MAX_EXECUTION_TIMEOUT": "60",
        "MARKETPLACE_ENABLED": "true", "MARKETPLACE_API_URL": "https://marketplace.dify.ai", "CHECK_UPDATE_URL": "",
        # The actual Marketplace dependency must pass Dify's signature check.
        # An unsigned preview package is never substituted in this test.
        "FORCE_VERIFYING_SIGNATURE": "true",
    })
    env_path = state / ".env"
    env_path.write_text("\n".join(f"{key}={val}" for key, val in values.items()) + "\n")
    env_path.chmod(0o600)
    (state / "compose.yaml").write_text(yaml.safe_dump(isolated_compose(original, docker_dir, state), sort_keys=False))
    (state / "workflow.yml").write_bytes(template_bytes)
    marker = state / "test-state.json"
    marker.write_text(json.dumps({"source_revision": revision, "template_sha256": hashlib.sha256(template_bytes).hexdigest(),
                                  "init_password": init_password, "owner_password": owner_password}))
    marker.chmod(0o600)
    print("Disposable loopback-only host prepared; test credentials remain private.")


def workflow_graph(query: str) -> dict:
    nodes = [
        {"id": "start", "type": "custom", "position": {"x": 0, "y": 0},
         "data": {"type": "start", "title": "Synthetic QA start", "variables": []}},
        {"id": "tool", "type": "custom", "position": {"x": 300, "y": 0},
         "data": {"type": "tool", "title": "GifSnap QA search", "provider_id": PROVIDER_ID,
                  "provider_type": "builtin", "provider_name": "gifsnap", "tool_name": "search_gifs",
                  "tool_label": "Search GIFs", "tool_node_version": "2", "tool_configurations": {"limit": {"type": "constant", "value": 1}},
                  "tool_parameters": {"query": {"type": "constant", "value": query},
                                      "page": {"type": "constant", "value": 1}},
                  "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 0}}},
        {"id": "end", "type": "custom", "position": {"x": 600, "y": 0},
         "data": {"type": "end", "title": "Inspect structured result",
                  "outputs": [{"variable": "gifs", "value_selector": ["tool", "json"], "value_type": "array[object]"}]}},
    ]
    edges = [{"id": f"{left}-{right}", "source": left, "target": right, "type": "custom",
              "sourceHandle": "source", "targetHandle": "target",
              "data": {"sourceType": nodes[index]["data"]["type"], "targetType": nodes[index + 1]["data"]["type"]}}
             for index, (left, right) in enumerate((("start", "tool"), ("tool", "end")))]
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 1}}


class Console:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE_URL + "/console/api", timeout=30,
                                   trust_env=False, follow_redirects=False,
                                   headers={"Origin": BASE_URL, "Referer": BASE_URL + "/"})

    def headers(self) -> dict[str, str]:
        token = self.client.cookies.get("csrf_token")
        return {"X-CSRF-Token": token} if token else {}

    def request(self, method: str, path: str, **kwargs):
        response = self.client.request(method, path, headers=self.headers(), **kwargs)
        require(200 <= response.status_code < 300, f"console_http_{response.status_code}")
        return response.json() if response.content else {}

    def wait(self) -> None:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                response = self.client.get("/setup")
                if response.status_code == 200:
                    require(response.json().get("step") == "not_started", "refusing_initialized_workspace")
                    return
            except httpx.RequestError:
                pass
            time.sleep(3)
        raise CheckFailure("host_readiness_timeout")

    def stream_run(self, app_id: str, inputs: dict | None = None) -> list[dict]:
        events, byte_count = [], 0
        deadline = time.monotonic() + 90
        with self.client.stream("POST", f"/apps/{app_id}/workflows/draft/run", json={"inputs": inputs or {}, "files": []},
                                headers=self.headers(), timeout=90) as response:
            require(response.status_code == 200, f"workflow_http_{response.status_code}")
            for line in response.iter_lines():
                byte_count += len(line)
                require(byte_count < 2 * 1024 * 1024, "workflow_output_too_large")
                require(time.monotonic() < deadline, "workflow_timeout")
                if line.startswith("data:"):
                    item = line[5:].strip()
                    if item and item != "[DONE]":
                        events.append(json.loads(item))
                if events and events[-1].get("event") == "workflow_finished":
                    return events
        raise CheckFailure("workflow_missing_finished_event")


def finished(events: list[dict]) -> dict:
    matches = [event["data"] for event in events if event.get("event") == "workflow_finished"]
    require(len(matches) == 1, "workflow_terminal_event_count")
    return matches[0]


def verify_invalid(events: list[dict]) -> None:
    end = finished(events)
    require(end.get("status") == "failed", "invalid_query_did_not_fail")
    errors = [end.get("error", "")]
    errors.extend(event.get("data", {}).get("error", "") for event in events if event.get("event") == "node_finished")
    require(any("Search phrase must contain 1 to 200 characters" in str(error) for error in errors),
            "invalid_query_wrong_error")


def verify_success(events: list[dict]) -> dict:
    end = finished(events)
    require(end.get("status") == "succeeded", "live_workflow_failed")
    messages = end.get("outputs", {}).get("gifs")
    require(isinstance(messages, list) and len(messages) == 1, "json_output_not_forwarded")
    payload = messages[0]
    require(isinstance(payload, dict) and isinstance(payload.get("data"), list), "missing_structured_data")
    require(len(payload["data"]) == 1, "expected_one_result")
    item = payload["data"][0]
    require(isinstance(item.get("url"), str) and item["url"].startswith("https://"), "missing_full_media_url")
    require(payload.get("pagination", {}).get("page") == 1, "pagination_not_preserved")
    tool_events = [e.get("data", {}) for e in events if e.get("event") == "node_finished" and e.get("data", {}).get("node_id") == "tool"]
    require(len(tool_events) == 1 and tool_events[0].get("status") == "succeeded", "tool_node_not_succeeded")
    require(tool_events[0].get("outputs", {}).get("json") == messages, "end_changed_tool_output")
    return {"result_count": 1, "full_url_preserved_through_end_node": True,
            "poster_field_present": "preview_url" in item,
            "animated_preview_field_present": "animated_preview" in item,
            "structured_output_forwarded_unchanged": True}


def imported_app(result: dict) -> str:
    # Current DSL version should import directly. Never silently confirm a
    # version mismatch or claim a partial/unsupported import is a successful test.
    require(result.get("status") == "completed", "dsl_import_not_completed")
    require(not result.get("warnings"), "dsl_import_has_warnings")
    require(result.get("imported_dsl_version") == "0.7.0" and result.get("current_dsl_version") == "0.7.0", "dsl_import_version_mismatch")
    require(result.get("app_mode") == "workflow" and bool(result.get("app_id")), "dsl_import_missing_workflow")
    return result["app_id"]


def check_dependencies(result: dict, *, installed: bool) -> None:
    dependencies = result.get("leaked_dependencies")
    require(isinstance(dependencies, list), "dependency_response_missing")
    if installed:
        require(not dependencies, "dependency_still_missing")
    else:
        require(len(dependencies) == 1 and dependencies[0].get("type") == "marketplace"
                and dependencies[0].get("value", {}).get("marketplace_plugin_unique_identifier") == MARKETPLACE_IDENTIFIER,
                "unexpected_missing_dependency")


def wait_install(console: Console, installation: dict) -> None:
    if installation.get("all_installed"):
        return
    task = installation.get("task_id")
    require(bool(task), "missing_install_task")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        status = console.request("GET", "/workspaces/current/plugin/tasks/" + quote(task, safe=""))["task"]["status"]
        require(status in {"pending", "running", "success"}, "marketplace_install_failed")
        if status == "success":
            return
        time.sleep(3)
    raise CheckFailure("marketplace_install_timeout")


def check_installed(result: dict) -> None:
    matches = [plugin for plugin in result.get("plugins", [])
               if plugin.get("plugin_unique_identifier") == MARKETPLACE_IDENTIFIER]
    require(len(matches) == 1 and matches[0].get("source") == "marketplace", "signed_marketplace_install_not_verified")


def run(state_path: Path, report_path: Path, live: bool) -> int:
    report = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), "status": "failed",
              "dify_version": "1.17.1", "dify_revision": DIFY_REVISION, "plugin_daemon": "0.6.10-local",
              "marketplace_plugin_unique_identifier": MARKETPLACE_IDENTIFIER,
              "host_kind": "disposable GitHub runner, console API", "mode": "marketplace_template_import",
              "visual_ui_test": False, "published_app": False, "external_adoption": False,
              "qa_marketplace_installs_attempted": 0,
              "live_qa_requests_attempted": 0, "live_qa_query": "happy cat" if live else None,
              "cases": {}, "failure_stage": "state"}
    console = None
    try:
        state = checked_state(state_path)
        marker = json.loads((state / "test-state.json").read_text())
        template_bytes = (state / "workflow.yml").read_bytes()
        require(marker.get("source_revision") == DIFY_REVISION
                and marker.get("template_sha256") == hashlib.sha256(template_bytes).hexdigest(), "state_mismatch")
        checked_template(template_bytes.decode())
        values = env_defaults((state / ".env").read_text())
        require(values.get("MARKETPLACE_ENABLED") == "true" and values.get("FORCE_VERIFYING_SIGNATURE") == "true"
                and values.get("MARKETPLACE_API_URL") == "https://marketplace.dify.ai", "signed_marketplace_settings_required")
        report["signature_enforcement_enabled"] = True
        report["template_sha256"] = marker["template_sha256"]
        console = Console()
        report["failure_stage"] = "readiness"
        console.wait()
        report["failure_stage"] = "setup"
        console.request("POST", "/init", json={"password": marker["init_password"]})
        console.request("POST", "/setup", json={"email": "gifsnap-host-smoke@example.com", "name": "Synthetic GifSnap QA",
                                                 "password": marker["owner_password"], "language": "en-US"})
        report["failure_stage"] = "login"
        console.request("POST", "/login", json={"email": "gifsnap-host-smoke@example.com", "remember_me": False,
                                                 "password": base64.b64encode(marker["owner_password"].encode()).decode()})
        require(bool(console.client.cookies.get("csrf_token")), "missing_csrf_cookie")
        report["failure_stage"] = "template_import"
        app_id = imported_app(console.request("POST", "/apps/imports", json={
            "mode": "yaml-content", "yaml_content": template_bytes.decode()}))
        report["cases"]["exact_template_import"] = "completed_without_warnings"
        dependency_path = f"/apps/imports/{app_id}/check-dependencies"
        report["failure_stage"] = "dependency_detection"
        check_dependencies(console.request("GET", dependency_path), installed=False)
        report["cases"]["marketplace_dependency_detected"] = "passed"
        report["failure_stage"] = "marketplace_install"
        report["qa_marketplace_installs_attempted"] = 1
        installation = console.request("POST", "/workspaces/current/plugin/install/marketplace", json={
            "plugin_unique_identifiers": [MARKETPLACE_IDENTIFIER]})
        wait_install(console, installation)
        # Verify both installed provenance and import dependency resolution.
        # The latter alone could be empty after its 10-minute Redis TTL expires.
        check_installed(console.request("GET", "/workspaces/current/plugin/list"))
        check_dependencies(console.request("GET", dependency_path), installed=True)
        report["cases"]["signed_marketplace_dependency_install"] = "passed"
        report["failure_stage"] = "tool_discovery"
        tools = console.request("GET", "/workspaces/current/tool-provider/builtin/" + PROVIDER_ID + "/tools")
        require(isinstance(tools, list) and any(tool.get("name") == "search_gifs" for tool in tools), "tool_not_discoverable")
        report["cases"]["tool_discovery"] = "passed"
        report["failure_stage"] = "imported_draft"
        draft_path = f"/apps/{app_id}/workflows/draft"
        draft = console.request("GET", draft_path)
        check_graph(draft.get("graph", {}))
        report["cases"]["imported_graph_contract"] = "passed"
        report["failure_stage"] = "invalid_input_workflow"
        # Nonempty whitespace passes the host's required text input check but
        # is rejected after trimming by the plugin, before its network request.
        # Only that specific error counts as the plugin guard passing.
        verify_invalid(console.stream_run(app_id, {"topic": "   "}))
        report["cases"]["invalid_input_workflow"] = "plugin_guard_passed"
        if live:
            report["failure_stage"] = "live_workflow"
            # This is the only live invocation; failures are intentionally not retried.
            report["live_qa_requests_attempted"] = 1
            report["live_qa_started_at_utc"] = datetime.now(timezone.utc).isoformat()
            report["cases"]["live_workflow"] = verify_success(console.stream_run(app_id, {"topic": "happy cat"}))
        report["status"] = "passed" if live else "passed_host_live_search_skipped"
        report.pop("failure_stage")
    except CheckFailure as error:
        report["failure_code"] = str(error)
    except Exception as error:
        # Never include request bodies, responses, cookie values or raw exception text.
        report["failure_code"] = "unexpected_" + type(error).__name__
    finally:
        if console:
            console.client.close()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    return 0 if report["status"].startswith("passed") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--dify-source", type=Path, required=True)
    prep.add_argument("--state", type=Path, required=True)
    prep.add_argument("--template", type=Path, required=True)
    smoke = sub.add_parser("run")
    smoke.add_argument("--state", type=Path, required=True)
    smoke.add_argument("--report", type=Path, required=True)
    smoke.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        try:
            prepare(args.dify_source, args.state, args.template)
        except CheckFailure as error:
            print("Preparation refused: " + str(error), file=sys.stderr)
            return 1
        return 0
    return run(args.state, args.report, args.live)


if __name__ == "__main__":
    raise SystemExit(main())
