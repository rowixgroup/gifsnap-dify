# Validation record

## October 19, 2026 — importable workflow and signed Marketplace installation

- 36 offline tests pass, including the example's variable bindings, empty/error
  handling and the host test's isolation and dependency checks.
- The exact [workflow YAML](examples/search-gifs.yml), SHA-256
  `147dd5c5ff41fff98d30bd4cd7a38531bce1137dc18151968df30ea663566197`,
  imported into a fresh Dify Community Edition 1.17.1 workspace without warnings.
- Dify detected and installed its exact Marketplace 0.1.0 dependency with
  signature verification enabled. Installed source and package identifier were
  verified; the imported graph was not replaced by a test graph.
- Whitespace input reached the plugin's validation and failed before a search.
  One explicitly enabled `happy cat` search returned one GIF, preserving the
  full media URL, poster and structured JSON through the End node. The optional
  animated-preview field was absent in that result.
- [Successful test run](https://github.com/rowixgroup/gifsnap-dify/actions/runs/39236905817),
  tested source commit `4bd6e8a290d954904e8458332f194f3caa032c69`;
  live QA search began October 19 at 10:23:31 UTC. Teardown succeeded.
- This exercised the real console API and workflow engine, not the visual editor
  or Dify Cloud. One Marketplace installation and one search are owner/agent QA;
  they do not establish independent usage, retention or revenue. No application
  was published and no existing workspace was modified.

## October 17, 2026 — historical preview-package validation

- Python 3.12.13; Dify plugin SDK 0.10.2; official plugin CLI 0.6.11.
- 21 offline tests pass: inputs, bounded requests, URL encoding, media/rendition
  handling, deduplication, pagination, failures and actual SDK message output.
- The built `.difypkg` loads in the official CLI's local plugin runtime. Provider
  validation succeeds without a network call. Empty search input produces an
  actionable tool error. One deliberately labeled owner/agent QA search returned
  one real GIF with full media, a static poster and a verified animated preview.
  This QA invocation is not external adoption.
- Dify Marketplace Toolkit's package checks report zero blocking failures.
  The domain scan finds only `gifsnap.com`. OSV found no known vulnerabilities in
  the two directly pinned requirements at this check; this is not a guarantee
  about all transitive dependencies or future vulnerabilities.
- The package uses no Dify model/tool/app/storage/endpoint permissions.
- The exact published 0.1.0 package passed a complete Start → GifSnap Search
  GIFs → End workflow in a disposable Dify Community Edition 1.17.1 host,
  using plugin daemon 0.6.10-local. Package installation and tool discovery
  succeeded; a 201-character query produced the expected input error; one
  explicitly enabled `happy cat` QA search returned exactly one result and
  preserved the tool's structured output, full media URL and poster through
  the End node. That result did not include the optional animated-preview field.
  [Successful host test](https://github.com/rowixgroup/gifsnap-dify/actions/runs/39064995661),
  October 17, 2026, 20:04 UTC; harness commit `b4d9d9f`.
- The host check exercised Dify's real console API and workflow engine, not
  its visual editor or Dify Cloud. It used a fresh loopback-only test instance
  that allowed the checksum-verified unsigned preview; it does not establish
  signed Marketplace installation. No existing workspace policy was changed.
  Temporary services, storage and test credentials were removed afterward.
- Six additional offline harness checks cover isolation, input-error assertions
  and unchanged structured-output forwarding. The host test used no LLM, paid
  model credentials, published application or external posting step. Its single
  live search is owner/agent QA, not an independent integration.
- Marketplace acceptance, independent installs and retained integrations have
  not been established by these checks.

## Reproduce the current checks

Run offline tests from the repository root:

```sh
uv sync --project gifsnap --frozen --no-dev
gifsnap/.venv/bin/python -m unittest discover -s tests -v
dify plugin package ./gifsnap -o ./gifsnap-0.1.1.difypkg
gifsnap/.venv/bin/python tests/package_smoke.py gifsnap-0.1.1.difypkg --cli dify
```

The default package smoke test does not call GifSnap. `--live` explicitly enables
one synthetic API request; use it only when necessary and classify it as QA.

The separate **Disposable Dify host smoke test** workflow can be run manually
from GitHub Actions. It imports `examples/search-gifs.yml` into a fresh workspace
and verifies its signed Marketplace dependency, discovery and invalid-input
handling. Signature verification stays enabled. It defaults to no live GifSnap
search. Enable `live_search` only when a real workflow result needs verification;
it permits one search and does not retry it. The harness refuses existing
workspaces and non-GitHub-runner execution. Every test installation and live
search should be classified as QA rather than independent adoption.
