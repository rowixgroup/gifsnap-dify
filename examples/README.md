# Search GIFs workflow

**Security notice:** this historical example pins 0.1.0, which includes a known
`certifi` vulnerability. Do not import it for a new deployment. Use manual
workflow setup with GifSnap 0.1.2 or later; the example will be updated after
the signed Marketplace 0.1.2 identifier is available. The historical test
results below do not validate the patched release.

Use the [workflow YAML](https://raw.githubusercontent.com/rowixgroup/gifsnap-dify/refs/heads/codex/dify-plugin/examples/search-gifs.yml) to try **topic → GIF search → JSON result** without configuring an AI model. It returns up to one match and does not send messages or download media.

1. Use a Dify 1.17.1+ workspace where you can create apps and install plugins.
2. In **Studio**, open the **Create** dropdown, choose **Import DSL file**, then select **From URL**. Paste the link below and choose **Create**. Alternatively, save [search-gifs.yml](search-gifs.yml) and use the **From DSL file** tab.
3. If Dify asks to install a missing dependency, review **GifSnap by rowixgroup** on [Marketplace](https://marketplace.dify.ai/plugin/rowixgroup/gifsnap) and follow your workspace policy. No GifSnap API key is currently required.
4. Inspect the three nodes, then choose **Test Run** and enter a short **GIF topic**, such as `happy cat`. Running the workflow sends that topic to GifSnap; importing the file does not run a search. No model-provider credentials are needed.

```text
https://raw.githubusercontent.com/rowixgroup/gifsnap-dify/refs/heads/codex/dify-plugin/examples/search-gifs.yml
```

The dependency is pinned to the approved Marketplace **0.1.0** package, including its signed package identifier. The source repository's newer documentation version does not mean a newer Marketplace package is approved. Do not replace that identifier with the checksum of an unsigned preview or disable package verification.

## Read the result

The End node returns `gifs`, an **array of tool JSON messages**. The first message contains the API's `data` array and `pagination` object. For a nonempty result, the original media URL is:

```text
gifs[0].data[0].url
```

Use this full URL unchanged. `preview_url` may be a static poster, and an optional `animated_preview` may need a video renderer. A JSON workflow output is not an automatically animated chat message.

An empty `gifs[0].data` means no matches. A timeout, rate limit or invalid topic fails the run; it is not converted into a successful empty result. Check the Search GIFs node's error before retrying manually. The example has automatic retries disabled.

Enter only a topic, 1–200 characters after trimming. Do not include private conversations, secrets or personal information. The tool sends that topic to GifSnap, and Dify may retain workflow inputs and outputs in its run history. See the [plugin privacy policy](https://github.com/rowixgroup/gifsnap-dify/blob/codex/dify-plugin/gifsnap/PRIVACY.md) and [API documentation](https://gifsnap.com/docs#rest).

## Verification

This exact file passed a [fresh Dify 1.17.1 import and workflow test](https://github.com/rowixgroup/gifsnap-dify/actions/runs/39236905817) on October 19, 2026. It imported without warnings, resolved the signed Marketplace 0.1.0 dependency with signature verification enabled, rejected invalid input, and returned one real GIF with its full URL and structured output unchanged. Temporary services and test credentials were removed afterward.

The host test used Dify's console API and workflow engine, not its visual editor or Dify Cloud. Its one installation and one search were owner QA, not an independent integration. The 36 offline checks cover selectors, plugin input validation, original URL forwarding, empty results, failures and test isolation using synthetic responses. No live GIF search is required to run them:

```sh
uv sync --project gifsnap --frozen --no-dev
gifsnap/.venv/bin/python -m unittest discover -s tests -v
```

Schema references, pinned to the inspected Dify revision:

- [App import/export service](https://github.com/langgenius/dify/blob/8387590ace4a094de812b7847fc6a4c3a27cd52b/api/services/app_dsl_service.py)
- [Current app DSL version](https://github.com/langgenius/dify/blob/8387590ace4a094de812b7847fc6a4c3a27cd52b/api/constants/dsl_version.py)
- [Official manual-input workflow fixture](https://github.com/langgenius/dify/blob/8387590ace4a094de812b7847fc6a4c3a27cd52b/api/tests/fixtures/workflow/simple_passthrough_workflow.yml)
