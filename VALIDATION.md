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
- No full Dify Community Edition UI/workflow or Dify Cloud workspace test has
  been performed yet. The official local plugin runtime is the integration
  environment tested so far. This limitation is disclosed in the review request.
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
