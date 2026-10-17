from typing import Any

from dify_plugin import ToolProvider


class GifSnapProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        # The documented public API is keyless; installing must not generate searches.
        return None
