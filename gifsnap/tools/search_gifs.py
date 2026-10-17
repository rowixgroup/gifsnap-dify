"""A bounded, read-only client for GifSnap's documented search endpoint."""

from collections.abc import Generator
import json
import math
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

API_URL = "https://gifsnap.com/api/v1/gifs/search"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ELAPSED_SECONDS = 20
USER_AGENT = "GifSnap-Dify/0.1.0 (+https://github.com/rowixgroup/gifsnap-dify)"


def whole_number(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a whole number from {minimum} to {maximum}.")
    if not minimum <= value <= maximum or value != int(value):
        raise ValueError(f"{name} must be a whole number from {minimum} to {maximum}.")
    return int(value)


def parameters(values: dict[str, Any]) -> dict[str, Any]:
    query = values.get("query")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("Search phrase must contain 1 to 200 characters.")
    return {
        "q": query.strip(),
        "limit": whole_number(values.get("limit", 5), "Result limit", 1, 20),
        "page": whole_number(values.get("page", 1), "Page", 1, 1_000_000),
    }


def media_url(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 8192
        or any(ord(c) <= 32 for c in value)
    ):
        raise ValueError(
            "GifSnap returned an invalid media URL. Please try again later."
        )
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in ("http", "https")
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "GifSnap returned an invalid media URL. Please try again later."
        )
    # Preserve signed URLs exactly; no media download or rewriting is performed.
    return value


def normalize(payload: Any, requested: dict[str, Any]) -> dict[str, Any]:
    bad = "GifSnap returned an unexpected response. Please try again later."
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError(bad)
    data, pagination = payload.get("data"), payload.get("pagination")
    if (
        not isinstance(data, list)
        or len(data) > requested["limit"]
        or not isinstance(pagination, dict)
    ):
        raise ValueError(bad)
    if (
        type(pagination.get("has_next")) is not bool
        or type(pagination.get("page")) is not int
    ):
        raise ValueError(bad)
    if pagination["page"] != requested["page"]:
        raise ValueError(bad)
    next_page = pagination.get("next_page")
    if pagination["has_next"]:
        if type(next_page) is not int or next_page <= pagination["page"]:
            raise ValueError(bad)
    elif next_page is not None:
        raise ValueError(bad)

    results = []
    seen_ids: set[str] = set()
    seen_content: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(bad)
        if (
            not isinstance(item.get("id"), str)
            or not item["id"]
            or not isinstance(item.get("title"), str)
        ):
            raise ValueError(bad)
        result: dict[str, Any] = {
            "id": item["id"],
            "title": item["title"],
            "url": media_url(item.get("url")),
        }
        for field in ("width", "height"):
            number = item.get(field)
            if (
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or not math.isfinite(number)
                or number < 0
            ):
                raise ValueError(bad)
            result[field] = number
        if item.get("type") not in ("gif", "sticker"):
            raise ValueError(bad)
        result["type"] = item["type"]
        if item.get("preview_url"):
            result["preview_url"] = media_url(item["preview_url"])
        for field in ("source", "content_id"):
            if isinstance(item.get(field), str) and item[field]:
                result[field] = item[field]
        preview = item.get("animated_preview")
        if isinstance(preview, dict) and preview.get("animated") is True:
            if preview.get("mime_type") in (
                "image/gif",
                "image/webp",
                "video/mp4",
                "video/webm",
            ):
                try:
                    normalized_preview = {
                        "url": media_url(preview.get("url")),
                        "mime_type": preview["mime_type"],
                        "width": whole_number(
                            preview.get("width"), "Preview width", 1, 480
                        ),
                        "height": whole_number(
                            preview.get("height"), "Preview height", 1, 480
                        ),
                        "animated": True,
                    }
                    if "byte_size" in preview:
                        normalized_preview["byte_size"] = whole_number(
                            preview["byte_size"], "Preview size", 1, 524288
                        )
                    result["animated_preview"] = normalized_preview
                except ValueError:
                    # An unusable optional rendition must not replace the full URL.
                    pass
        content_id = result.get("content_id")
        if result["id"] in seen_ids or content_id and content_id in seen_content:
            continue
        seen_ids.add(result["id"])
        if content_id:
            seen_content.add(content_id)
        results.append(result)

    # Follow the API cursor; total is an estimate and deduplication can shorten a page.
    output_pagination = {
        "page": pagination["page"],
        "has_next": pagination["has_next"],
        "next_page": next_page,
    }
    for field in ("limit", "offset", "total"):
        value = pagination.get(field)
        if (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        ):
            output_pagination[field] = value
    return {"data": results, "pagination": output_pagination}


def search(values: dict[str, Any]) -> dict[str, Any]:
    params = parameters(values)
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(10, connect=5), follow_redirects=False
        ) as client:
            with client.stream(
                "GET",
                API_URL,
                params=params,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            ) as response:
                if response.status_code == 429:
                    raise ValueError(
                        "GifSnap is rate limited. Wait before trying again."
                    )
                if response.status_code >= 500:
                    raise ValueError(
                        "GifSnap is temporarily unavailable. Please try again later."
                    )
                if response.status_code != 200:
                    raise ValueError(
                        f"GifSnap search failed (HTTP {response.status_code}). Check the inputs or try again later."
                    )
                content = bytearray()
                for chunk in response.iter_bytes(4096):
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise ValueError(
                            "GifSnap returned too much data. Please try again with fewer results."
                        )
                    if time.monotonic() - started > MAX_ELAPSED_SECONDS:
                        raise ValueError(
                            "GifSnap search timed out. Please try again later."
                        )
        payload = json.loads(content)
    except httpx.TimeoutException:
        raise ValueError("GifSnap search timed out. Please try again later.") from None
    except httpx.HTTPError:
        raise ValueError("Cannot reach GifSnap. Please try again later.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError(
            "GifSnap returned invalid JSON. Please try again later."
        ) from None
    return normalize(payload, params)


class SearchGifsTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        yield self.create_json_message(search(tool_parameters))
