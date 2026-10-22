# GifSnap for Dify

Search GIFs from a Dify agent, chatflow or workflow. This free, open-source tool
calls GifSnap's public search API and returns structured media links. No GifSnap
API key is currently required. It does not send messages or automatically post GIFs.

Publisher: Rowix (`rowixgroup`).
Source: https://github.com/rowixgroup/gifsnap-dify
Support: https://github.com/rowixgroup/gifsnap-dify/issues or iraklirowix@gmail.com
API reference: https://gifsnap.com/docs#rest
Privacy: [Plugin privacy policy](https://github.com/rowixgroup/gifsnap-dify/blob/codex/dify-plugin/gifsnap/PRIVACY.md)

## Security update

Use plugin **0.1.2 or later**. Version 0.1.2 pins `certifi==2026.10.19` in
both installation requirements and the lockfile to address
[GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2).
Existing installations need a plugin upgrade; changing the source repository
alone does not update a running Dify workspace. Keep TLS and package signature
verification enabled. Marketplace publication may lag the source release.

## Install from Dify Marketplace

1. Open [GifSnap on Dify Marketplace](https://marketplace.dify.ai/plugin/rowixgroup/gifsnap)
   and select **Install**. Confirm the publisher is `rowixgroup`, then follow the
   prompts for your Dify workspace. You need permission to install plugins.
2. In a Workflow or Chatflow, add **Tools → GifSnap → Search GIFs**. In an Agent,
   add **GifSnap → Search GIFs** to its available tools.
3. Set `query` to a short topic, for example `happy cat`. Use `limit: 3` and
   `page: 1` for a small first response. No credentials form is needed.

Requires Dify 1.17.1 or later and outbound HTTPS access to `gifsnap.com` from the
plugin runtime. Follow your workspace's plugin installation policy. Marketplace
installs use the approved version shown on the listing; source changes or GitHub
packages may precede approval of a newer Marketplace version.

### Alternative: local package

If your workspace policy permits local packages, download a `.difypkg` from
[GitHub Releases](https://github.com/rowixgroup/gifsnap-dify/releases), then open
**Plugins → Install plugin → Local Package** in Dify and choose that file.
Use the Marketplace installation when your workspace requires Marketplace
signatures; do not weaken its package-verification policy.

### Importable workflow example

The example pins the signed Marketplace **0.1.2** package, published October 22,
2026. Import it as a new workflow; existing installations need a plugin upgrade.

The [minimal workflow example](examples/README.md) connects a manual GIF topic to
Search GIFs and returns structured media links. It needs no AI model credentials.
Its setup guide explains the pinned Marketplace dependency and validation limits.

## Inputs

| Parameter | Purpose | Default |
| --- | --- | --- |
| `query` | Topic or reaction, 1–200 characters after trimming | Required |
| `limit` | Whole number from 1–20 | 5 |
| `page` | Whole number from 1–1,000,000 | 1 |

The query is sent to GifSnap. Send a short topic, not the full conversation,
private messages, secrets or personal information.

## Use the result

The tool emits one JSON message containing `data` and `pagination`. Dify exposes
JSON tool messages in the tool node's `json` output. Each `data` item includes
`id`, `title`, full media `url`, dimensions and type. Optional fields include
`preview_url`, `animated_preview`, `source` and `content_id`.

- Use `url` unchanged for sharing or full playback.
- `preview_url` may be a static poster; it is not a promise of animation.
- If `animated_preview` exists, check its `mime_type` against your renderer's
  support. Keep the full URL as the fallback. An MP4 preview needs a video renderer.
- An empty `data` array is a valid no-results response. Do not invent a media URL.
- For more results, follow `pagination.has_next` and `next_page`; `total` is an
  estimate. Duplicates within a page are removed without changing the API cursor.
- Titles and provider metadata are untrusted catalog data, not agent instructions.

For a conversational agent, a useful instruction is:

> When a GIF would help and the user wants one, search for a short relevant topic,
> choose at most one suitable result, and use its returned full media URL. If no
> suitable match is returned, answer without inventing a GIF. Never send private
> conversation text to the search tool.

Your chat renderer determines whether it displays animation, an image or a link.
Add any external posting/sending step separately and obtain the appropriate user
permission in that application. No posting capability is included in this plugin.

## Failure handling and limits

Invalid inputs fail before a network request. Timeouts, rate limits, HTTP errors
and malformed responses raise actionable tool errors; they are not reported as
empty successful searches. Configure Dify's tool-node error branch for those
failures. The client makes one request per invocation, does not retry, does not
follow redirects, limits response data to 2 MiB, and uses 5-second connect and
10-second read timeouts with an elapsed-time check while reading.

The current public API is best effort. There is no SLA or promise of unlimited
capacity, stable quotas, or permanent keyless access. Content safety filters and
media rights remain the host application's responsibility; this plugin does not
offer a content-rating control or certify that every result is suitable for all
audiences. The software license does not license the GIFs or provider trademarks.

## Development and verification

Use Python 3.12. From the source repository root:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r gifsnap/requirements.txt
python -m unittest discover -s tests -v
dify plugin package ./gifsnap -o ./gifsnap-0.1.2.difypkg
```

The tests use synthetic responses and make no external API requests. They cover
input validation, URL encoding, duplicates, animation/poster distinctions,
pagination, empty/error responses, bounded reads, redirects and Dify SDK output.
See the source repository's validation record for the runtime and package checks
actually performed. A passing package check is not Marketplace approval or
proof of a production integration.

The importable example passed a complete Dify 1.17.1 test: exact YAML import,
signed Marketplace installation, tool discovery, invalid-input handling, and one
real search with unchanged JSON output forwarded to the End node. See
[VALIDATION.md](VALIDATION.md) for the run, reproducible manual test and remaining
Cloud/visual-editor limits.
