import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gifsnap"))
from tools.search_gifs import API_URL, SearchGifsTool, normalize, parameters, search
from provider.gifsnap import GifSnapProvider


def sample():
    return {
        "data": [
            {
                "id": "fixture-1",
                "title": "Happy cat",
                "url": "https://media.example/cat.gif?sig=a%2Bb&v=1",
                "preview_url": "https://media.example/poster.jpg",
                "width": 400,
                "height": 300,
                "type": "gif",
                "source": "fixture",
            }
        ],
        "pagination": {
            "page": 1,
            "limit": 5,
            "total": 10,
            "has_next": True,
            "next_page": 2,
            "offset": 0,
        },
    }


class SearchTests(unittest.TestCase):
    def invoke_mock(self, response=None, *, handler=None, values=None):
        calls = []

        def handle(request):
            calls.append(request)
            return (
                handler(request)
                if handler
                else httpx.Response(
                    200, json=response if response is not None else sample()
                )
            )

        client = httpx.Client(
            transport=httpx.MockTransport(handle), follow_redirects=False
        )
        with patch("tools.search_gifs.httpx.Client", return_value=client) as factory:
            result = search(values or {"query": "happy cat"})
        self.assertEqual(factory.call_args.kwargs["follow_redirects"], False)
        return result, calls

    def test_query_encoding_fixed_endpoint_and_single_request(self):
        _, calls = self.invoke_mock(
            values={"query": "  კატა & dog? #party  ", "limit": 5.0}
        )
        self.assertEqual(len(calls), 1)
        req = calls[0]
        self.assertEqual(str(req.url).split("?")[0], API_URL)
        self.assertEqual(req.method, "GET")
        self.assertEqual(req.url.params["q"], "კატა & dog? #party")
        self.assertEqual(req.url.params["limit"], "5")
        self.assertEqual(req.url.params["page"], "1")
        self.assertNotIn("authorization", req.headers)

    def test_invalid_inputs_never_call_network(self):
        bad = [None, "", "   ", 5, {}, "x" * 201]
        with patch("tools.search_gifs.httpx.Client") as network:
            for query in bad:
                with self.subTest(query_type=type(query).__name__):
                    with self.assertRaises(ValueError):
                        search({"query": query})
            for field in ("limit", "page"):
                for value in (
                    0,
                    -1,
                    True,
                    "2",
                    None,
                    1.5,
                    float("inf"),
                    float("nan"),
                    10**1000,
                ):
                    with self.subTest(field=field, value_type=type(value).__name__):
                        with self.assertRaises(ValueError):
                            search({"query": "cat", field: value})
            with self.assertRaises(ValueError):
                search({"query": "cat", "limit": 21})
            network.assert_not_called()

    def test_full_media_and_static_poster_remain_distinct(self):
        result, _ = self.invoke_mock()
        self.assertEqual(result["data"][0]["url"], sample()["data"][0]["url"])
        self.assertTrue(result["data"][0]["preview_url"].endswith(".jpg"))
        self.assertNotIn("animated_preview", result["data"][0])

    def test_verified_animated_preview_preserves_mime_and_full_url(self):
        body = sample()
        body["data"][0]["animated_preview"] = {
            "url": "https://media.example/small.mp4",
            "mime_type": "video/mp4",
            "width": 160,
            "height": 120,
            "animated": True,
            "byte_size": 40000,
        }
        result, _ = self.invoke_mock(body)
        self.assertEqual(
            result["data"][0]["animated_preview"], body["data"][0]["animated_preview"]
        )
        self.assertEqual(result["data"][0]["url"], body["data"][0]["url"])

    def test_invalid_optional_preview_falls_back_to_full_media(self):
        for preview in (
            {"animated": False},
            {"animated": True, "mime_type": "image/jpeg"},
            {
                "animated": True,
                "mime_type": "image/gif",
                "url": "javascript:bad",
                "width": 10,
                "height": 10,
            },
        ):
            body = sample()
            body["data"][0]["animated_preview"] = preview
            result, _ = self.invoke_mock(body)
            self.assertNotIn("animated_preview", result["data"][0])
            self.assertEqual(result["data"][0]["url"], body["data"][0]["url"])

    def test_deduplication_does_not_invent_pagination(self):
        body = sample()
        body["data"][0]["content_id"] = "same-content"
        duplicate = copy.deepcopy(body["data"][0])
        duplicate["id"] = "alternate-encoding"
        body["data"] += [duplicate, copy.deepcopy(body["data"][0])]
        result, _ = self.invoke_mock(body)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["pagination"]["next_page"], 2)
        self.assertEqual(result["pagination"]["total"], 10)

    def test_valid_empty_result_is_success(self):
        body = sample()
        body["data"] = []
        body["pagination"].update(has_next=False, next_page=None, total=0)
        result, _ = self.invoke_mock(body)
        self.assertEqual(result["data"], [])
        self.assertFalse(result["pagination"]["has_next"])

    def test_http_errors_are_not_empty_success_and_hide_server_body(self):
        for status in (301, 302, 400, 401, 403, 404, 429, 500, 503):
            with self.subTest(status=status), self.assertRaises(ValueError) as raised:
                self.invoke_mock(
                    handler=lambda r: httpx.Response(
                        status,
                        text="private-upstream-body",
                        headers={"Location": "https://other.example"},
                    )
                )
            self.assertNotIn("private-upstream", str(raised.exception))

    def test_redirect_is_not_followed(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"Location": "https://other.example"})

        with self.assertRaises(ValueError):
            self.invoke_mock(handler=handler)
        self.assertEqual(len(calls), 1)

    def test_timeout_does_not_leak_query(self):
        def handler(request):
            raise httpx.ReadTimeout("private-query", request=request)

        with self.assertRaisesRegex(ValueError, "timed out") as raised:
            self.invoke_mock(handler=handler)
        self.assertNotIn("private-query", str(raised.exception))

    def test_connection_error_is_actionable(self):
        def handler(request):
            raise httpx.ConnectError("private-query", request=request)

        with self.assertRaisesRegex(ValueError, "Cannot reach") as raised:
            self.invoke_mock(handler=handler)
        self.assertNotIn("private-query", str(raised.exception))

    def test_malformed_json_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            self.invoke_mock(
                handler=lambda r: httpx.Response(200, content=b"<html>bad</html>")
            )

    def test_response_size_is_bounded(self):
        with (
            patch("tools.search_gifs.MAX_RESPONSE_BYTES", 100),
            self.assertRaisesRegex(ValueError, "too much data"),
        ):
            self.invoke_mock()

    def test_elapsed_time_is_bounded(self):
        with (
            patch("tools.search_gifs.time.monotonic", side_effect=[0, 21]),
            self.assertRaisesRegex(ValueError, "timed out"),
        ):
            self.invoke_mock()

    def test_invalid_payloads_rejected(self):
        for body in (
            [],
            None,
            {},
            {"error": "private"},
            {"data": "bad", "pagination": {}},
            {"data": [], "pagination": None},
        ):
            with (
                self.subTest(body_type=type(body).__name__),
                self.assertRaises(ValueError),
            ):
                normalize(body, {"q": "cat", "page": 1, "limit": 5})

    def test_unusable_result_urls_rejected(self):
        for url in (
            "javascript:alert(1)",
            "file:///tmp/a.gif",
            "//example.com/a.gif",
            "https://u:p@example.com/a.gif",
            "https://@example.com/a.gif",
            "https://example.com/a\nb.gif",
        ):
            body = sample()
            body["data"][0]["url"] = url
            with (
                self.subTest(url_scheme=url.split(":")[0]),
                self.assertRaises(ValueError),
            ):
                self.invoke_mock(body)

    def test_wrong_page_or_cursor_is_not_silent_success(self):
        for change in (
            {"page": 2},
            {"next_page": 1},
            {"has_next": "false"},
            {"has_next": False, "next_page": 2},
        ):
            body = sample()
            body["pagination"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.invoke_mock(body)

    def test_unexpected_extra_fields_are_not_forwarded(self):
        body = sample()
        body["private_field"] = "private"
        body["data"][0]["unexpected"] = "private"
        result, _ = self.invoke_mock(body)
        self.assertNotIn("private", json.dumps(result))

    def test_sdk_yields_exactly_one_structured_result(self):
        with patch("tools.search_gifs.search", return_value=sample()) as request:
            messages = list(
                SearchGifsTool.from_credentials({}).invoke({"query": "cat"})
            )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].type.value, "json")
        self.assertEqual(messages[0].message.json_object, sample())
        request.assert_called_once_with({"query": "cat"})

    def test_provider_install_does_not_call_network(self):
        with patch("tools.search_gifs.httpx.Client") as network:
            GifSnapProvider()._validate_credentials({})
            network.assert_not_called()

    def test_metadata_runtime_paths_and_no_extra_permissions(self):
        root = Path(__file__).resolve().parents[1] / "gifsnap"
        manifest = yaml.safe_load((root / "manifest.yaml").read_text())
        self.assertEqual(manifest["resource"]["permission"], {})
        self.assertEqual(manifest["network"]["domains"], ["gifsnap.com"])
        provider = yaml.safe_load((root / manifest["plugins"]["tools"][0]).read_text())
        tool = yaml.safe_load((root / provider["tools"][0]).read_text())
        self.assertTrue((root / tool["extra"]["python"]["source"]).is_file())
        self.assertEqual(tool["identity"]["name"], "search_gifs")


if __name__ == "__main__":
    unittest.main()
