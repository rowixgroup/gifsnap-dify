"""Invoke the built archive through Dify's official local plugin runtime.

One live synthetic search is optional and explicitly enabled with --live.
No model calls, credentials or media downloads are used.
"""

import argparse
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

parser = argparse.ArgumentParser()
parser.add_argument("package")
parser.add_argument("--cli", default="dify")
parser.add_argument("--live", action="store_true")
parser.add_argument("--report")
a = parser.parse_args()
p = subprocess.Popen(
    [
        a.cli,
        "plugin",
        "run",
        str(Path(a.package).resolve()),
        "--response-format",
        "json",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)
lines = queue.Queue()


def read():
    for line in p.stdout:
        lines.put(line)


threading.Thread(target=read, daemon=True).start()
requests = [
    (
        "credentials",
        "validate_tool_credentials",
        {"provider": "gifsnap", "credentials": {}},
    ),
    (
        "invalid",
        "invoke_tool",
        {
            "provider": "gifsnap",
            "tool": "search_gifs",
            "credentials": {},
            "tool_parameters": {"query": ""},
        },
    ),
]
if a.live:
    requests.append(
        (
            "live",
            "invoke_tool",
            {
                "provider": "gifsnap",
                "tool": "search_gifs",
                "credentials": {},
                "tool_parameters": {"query": "happy cat", "limit": 1, "page": 1},
            },
        )
    )
responses = {name: [] for name, _, _ in requests}
ended = set()
ready = False
deadline = time.monotonic() + 180
try:
    while time.monotonic() < deadline:
        try:
            raw = lines.get(timeout=1)
        except queue.Empty:
            if p.poll() is not None:
                raise RuntimeError("Plugin runtime exited before completing checks")
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = item.get("type")
        if kind == "plugin_ready":
            ready = True
            for name, action, request in requests:
                p.stdin.write(
                    json.dumps(
                        {
                            "invoke_id": name,
                            "type": "tool",
                            "action": action,
                            "request": request,
                        }
                    )
                    + "\n"
                )
            p.stdin.flush()
        name = item.get("invoke_id")
        if name in responses:
            responses[name].append(item)
        elif kind == "error":
            raise RuntimeError(str(item.get("response")))
        if kind == "plugin_invoke_end":
            ended.add(name)
            if len(ended) == len(requests):
                break
    if not ready or len(ended) != len(requests):
        raise RuntimeError("Plugin runtime checks timed out")
    credential_results = [
        x["response"]
        for x in responses["credentials"]
        if x["type"] == "plugin_response"
    ]
    assert credential_results == [{"result": True}], (
        "Credential validation did not succeed"
    )
    invalid_errors = [
        x["response"]["error"] for x in responses["invalid"] if x["type"] == "error"
    ]
    assert (
        len(invalid_errors) == 1
        and "Search phrase must contain 1 to 200 characters" in invalid_errors[0]
    ), "Invalid query was not rejected correctly"
    assert not any(x["type"] == "plugin_response" for x in responses["invalid"]), (
        "Invalid input produced a successful result"
    )
    summary = {
        "runtime_ready": ready,
        "credential_validation": "passed",
        "invalid_query": "rejected",
        "live_qa_requests": int(a.live),
    }
    if a.live:
        assert not any(x["type"] == "error" for x in responses["live"]), (
            "Live tool invocation failed"
        )
        results = [
            x["response"] for x in responses["live"] if x["type"] == "plugin_response"
        ]
        assert len(results) == 1 and results[0]["type"] == "json", (
            "Expected one structured result"
        )
        payload = results[0]["message"]["json_object"]
        assert len(payload["data"]) == 1 and payload["data"][0]["url"].startswith(
            "https://"
        ), "Live response lacked a valid media result"
        assert payload["pagination"]["page"] == 1
        summary.update(
            live_search="passed",
            result_count=1,
            animated_preview_present="animated_preview" in payload["data"][0],
        )
    print(json.dumps(summary, indent=2), flush=True)
    if a.report:
        Path(a.report).write_text(json.dumps(summary, indent=2) + "\n")
finally:
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
