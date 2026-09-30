# Nokido — Third-Party Notices

Nokido is licensed under the GNU Affero General Public License v3.0
(see `LICENSE`). It ships third-party files with its web portal, and includes
methodology and skill content adapted from a third-party open-source project.
Their licenses are listed below and reproduced as each license requires.

---

## Third-party components shipped with the web portal

The web portal serves the files below from `app/web_hub/static/`, vendored so
that it works offline. Each file is pinned by SHA-256 in [`vendor.lock`](vendor.lock).
Each version was read in the file itself, then checked byte for byte against the
upstream release of that version (2026-09-29: 22 files out of 22 identical).
The license texts, copied verbatim from upstream, are in [`licenses/`](licenses/).

| Component | Version | License | File(s) in `app/web_hub/static/` | License text |
|---|---|---|---|---|
| Alpine.js | 3.14.8 | MIT | `alpine.min.js` | [`licenses/alpinejs/`](licenses/alpinejs/) |
| @babel/standalone | 7.29.0 | MIT | `babel.min.js` | [`licenses/babel-standalone/`](licenses/babel-standalone/) |
| Cytoscape.js | 3.28.1 | MIT | `cytoscape.min.js` | [`licenses/cytoscape/`](licenses/cytoscape/) |
| htmx | 2.0.4 | 0BSD | `htmx.min.js` | [`licenses/htmx/`](licenses/htmx/) |
| Lucide | 0.544.0 | ISC (portions MIT, from Feather) | `lucide.min.js` | [`licenses/lucide/`](licenses/lucide/) |
| React | 18.3.1 | MIT | `react.min.js` | [`licenses/react/`](licenses/react/) |
| ReactDOM | 18.3.1 | MIT | `react-dom.min.js` | [`licenses/react-dom/`](licenses/react-dom/) |
| Redoc | 2.5.3 | MIT | `redoc.standalone.js` | [`licenses/redoc/`](licenses/redoc/) |
| Swagger UI | 5.32.14 | Apache-2.0 | `swagger-ui-bundle.js`, `swagger-ui.css` | [`licenses/swagger-ui/`](licenses/swagger-ui/) (with its `NOTICE`) |
| normalize.css (inside `swagger-ui.css`) | 7.0.0 | MIT | `swagger-ui.css` | [`licenses/normalize.css/`](licenses/normalize.css/) |
| Tailwind CSS (Play CDN) | 3.4.17 | MIT | `tailwind.min.js` | [`licenses/tailwindcss/`](licenses/tailwindcss/) |
| Vega | 5.33.1 | BSD-3-Clause | `vega.min.js` | [`licenses/vega/`](licenses/vega/) |
| Vega-Lite | 5.23.0 | BSD-3-Clause | `vega-lite.min.js` | [`licenses/vega-lite/`](licenses/vega-lite/) |
| Vega-Embed | 6.29.0 | BSD-3-Clause | `vega-embed.min.js` | [`licenses/vega-embed/`](licenses/vega-embed/) |
| vis-network | 9.1.9 | Apache-2.0 OR MIT | `vis-network.min.js` | [`licenses/vis-network/`](licenses/vis-network/) (both texts) |
| Inter | Google Fonts v20 (latin subset, variable font) | OFL-1.1 | `fonts/inter-{400,500,600,700}.woff2` | [`licenses/inter/`](licenses/inter/) |
| JetBrains Mono | Google Fonts v24 (latin subset, variable font) | OFL-1.1 | `fonts/jetbrains-mono-{400,500,700}.woff2` | [`licenses/jetbrains-mono/`](licenses/jetbrains-mono/) |

The Redoc and Swagger UI bundles embed further modules, each under its own
license. Their bundled notices (`*.LICENSE.txt`, next to each component's license)
list them; they include DOMPurify, under Apache-2.0 or MPL-2.0.

Python dependencies are not shipped in this repository: pip installs them, and
`tools/forge_license_guard.py` checks their licenses for AGPLv3 compatibility. The
same tool with `--embarques` checks the table above against `vendor.lock`. It
refuses an undeclared file, a bundle replaced without updating the lock, and a
missing license text. With `--declarees`, it checks every dependency declared in
`pyproject.toml` and `requirements*.txt`.

### Other dependencies (fetched or built at install time, not shipped)

Measured on 2026-09-29, from the committed lockfiles, license read from each
registry at the exact locked version:

- **Rust** (`Cargo.lock` of `go_services/forge_brain_worker`, `rust_ext/forge_bm25`,
  `sandbox/spin_pilot/health_poc`): 281 crates, all under permissive or weak-copyleft
  licenses compatible with the AGPLv3 (MIT, Apache-2.0 and their dual forms,
  Unlicense, Zlib, ISC, BSD-2-Clause, BSL-1.0, MPL-2.0, Unicode-3.0,
  CDLA-Permissive-2.0), plus the project's own crates.
- **Deno** (`proxy_deno/deno.lock`): `deno.land/std@0.224.0` and
  `deno.land/x/sqlite@v3.9.1`, both MIT.
- **Go** (`go_services/forge_dispatcher`): standard library only.
- **Docker base images**: `python:3.12-slim`, `python:3.14-slim`,
  `denoland/deno:alpine`, plus services run as separate containers
  (`ollama/ollama`, `searxng/searxng` (AGPL-3.0), `adminer`). Separate programs,
  not combined with Nokido's code.

Not inventoried here: machine-learning model weights (downloaded separately, each
under its own license) and the content of the published RAG knowledge pack.

### Optional component under an incompatible license: Scapy

Scapy (`GPL-2.0-only`) can be used by the network capture workflows
(`app/forge_network.py`). It is **not** a dependency of Nokido: it is not declared
(`app/requirements.txt` lists it only as a commented, optional line), not shipped,
and never imported unless it is already installed, at the first packet capture.
GPL-2.0-only cannot be combined with the AGPLv3 in a distributed work: installing
Scapy is the user's choice, for their own use, and Nokido works without it.

---

## obra/superpowers

- Source: https://github.com/obra/superpowers
- License: MIT License
- Copyright (c) 2025 Jesse Vincent

The Nokido skills `forge-tdd` and `forge-systematic-debugging` (under
`docs/skills/`) are adapted from the *test-driven-development* and
*systematic-debugging* skills of obra/superpowers.

```
MIT License

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
