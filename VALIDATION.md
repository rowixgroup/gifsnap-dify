# Validation record — October 17, 2026

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

Reproduce offline tests from the repository root:

```sh
uv sync --project gifsnap --frozen --no-dev
gifsnap/.venv/bin/python -m unittest discover -s tests -v
dify plugin package ./gifsnap -o ./gifsnap-0.1.0.difypkg
gifsnap/.venv/bin/python tests/package_smoke.py gifsnap-0.1.0.difypkg --cli dify
```

The default package smoke test does not call GifSnap. `--live` explicitly enables
one synthetic API request; use it only when necessary and classify it as QA.

The separate **Disposable Dify host smoke test** workflow can be run manually
from GitHub Actions. It defaults to installation, discovery and invalid-input
checks without a live GifSnap search. Enable `live_search` only when a real
workflow result needs verification; it permits one search and does not retry it.
The harness refuses existing workspaces and non-GitHub-runner execution. Its
temporary package-trust configuration is for this isolated test only; follow
your own workspace's installation policy when using the preview.
