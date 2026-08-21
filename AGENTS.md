# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

Three independent Poetry projects in one git repo. There is no top-level build — `cd` into a
subproject first.

| Directory | Package | What it is |
| --- | --- | --- |
| `tex2pdf-service/` | `arxiv-tex2pdf-service` (`tex2pdf`) | FastAPI service that compiles a submission tarball to PDF inside a TeX Live Docker image |
| `tex2pdf-tools/` | `arxiv-tex2pdf-tools` (`tex2pdf_tools`) | Library: `preflight`, `zerozeroreadme`, `tex_inspection`, `directives`. No TeX-running service code |
| `pdf_profile/` | `pdf_profile` | PDF digest/profiling tool, used for comparing compile output |

CI mirrors this split with path filters: `.github/workflows/test_service.yaml` fires only on
`tex2pdf-service/**`, `test_tools.yaml` only on `tex2pdf-tools/**`. `pdf_profile` has no workflow.

### The tex2pdf-tools overlay — read this before editing the library

`tex2pdf-service` declares `arxiv-tex2pdf-tools` as a **git dependency pinned in
`poetry.lock`**, not a path dependency. A plain `poetry install` therefore installs the
GitHub-pinned commit, and local edits to `tex2pdf-tools/` are silently ignored. Every context
overlays the working tree on top:

- dev: `make install.dev` (`poetry install` + `poetry run pip install --no-deps -e ../tex2pdf-tools`)
- CI: same `pip install --no-deps -e ../tex2pdf-tools` step
- Docker: `Appliance.Dockerfile` copies `tex2pdf-tools/` to `/tmp` and `pip install --no-deps` it
  over the poetry-installed copy — which is why the build context is the **repo root** (`..` in
  the Makefile), not `tex2pdf-service/`.

If a change to `tex2pdf_tools` doesn't seem to take effect in the service, the overlay is missing.

## Commands

### tex2pdf-tools

```bash
cd tex2pdf-tools
poetry install --with=dev
PYTHONPATH=$PWD poetry run pytest tests
PYTHONPATH=$PWD poetry run pytest tests/preflight/test_preflight.py::test_name --no-cov   # single test
```

`pyproject.toml` sets `addopts = "--cov=tex2pdf_tools --cov-fail-under=70"`, so any partial run
fails the coverage gate unless you pass `--no-cov`.

Tests shell out to a real TeX installation (`kpsewhich`, engines) plus `pdfinfo` (poppler-utils)
and `pngcheck`. CI installs TeX Live via `zauguin/install-texlive` with an explicit package list —
add to that list when a new fixture needs a new LaTeX package.

`make regenerate_test_json` is meant to refresh the preflight golden JSON, but it (and
`check_all_submissions.sh`) still invokes `python -m tex2pdf_tools.preflight parser <dir>`; the
subcommand was renamed to `parse`, so both are currently broken.

### tex2pdf-service

```bash
cd tex2pdf-service
make install.dev                              # poetry install + tex2pdf-tools overlay
PYTHONPATH=$PWD poetry run pytest tests
PYTHONPATH=$PWD poetry run pytest tests/test_watermark.py   # no Docker needed
```

`tests/test_watermark.py`, `tests/test_patch.py`, `tests/test_typings.py` are pure unit tests.
`tests/test_docker.py` and `tests/test_sandbox.py` are marked `@pytest.mark.integration`; their
module fixtures build the images (`make app2023.docker app2025.docker`) and start containers, so
they need Docker and the **gvisor `runsc` runtime**. Useful options from `conftest.py`:
`--no-docker-setup` (reuse already-running containers), `--keep-docker-running`,
`--docker-port-2023`.

Build and run the appliance:

```bash
make app.docker          # builds 2023, 2024 and 2025 images
make app2025.docker      # one year only
make app.run             # runs all three; ports 6301 / 6302 / 6303 -> container 8080
make app2025.proxy.run   # proxy-mode container, --network host, env from tests/local-proxy-test-2025.env
make app.stop
make help                # the Makefile self-documents via #-# comments
```

Open `http://localhost:6303/docs` for the OpenAPI UI. `tools/setup-like-prod.sh` brings up a
prod-like pair (2023 backend + 2025 proxy frontend).

Running the app outside Docker for debugging requires the local image plus
`sudo install -m 755 bin/docker_pdflatex.sh /usr/local/bin`, then:

```bash
LOCAL_EXEC=t uvicorn --host 0.0.0.0 --port=6301 tex2pdf.tex2pdf_api:app
```

Batch-compile a directory of tarballs against a running service and harvest results into
`score.db`: `python bin/compile_submissions.py compile ~/tarballs` / `... harvest ~/tarballs`.

### pdf_profile

```bash
cd pdf_profile
make bootstrap && . venv/bin/activate && poetry install
pytest tests
python bin/pdfprof.py some.pdf
```

### Lint and types

Ruff config lives in the **root** `pyproject.toml` (line length 120, target py311, pydocstyle
pep257); `tex2pdf-tools/pyproject.toml` inherits it via `extend`. Pre-commit runs `ruff --fix` and
`ruff-format`. CI enforces `ruff check` and `ruff format --check --diff` for `tex2pdf-tools` only,
but keep the other subprojects clean too.

mypy is configured per-subproject (`mypy.ini`, near-strict: `disallow_untyped_defs`,
`disallow_untyped_calls`, `warn_return_any`, pydantic plugin) and is enforced *through pytest* —
`tests/test_typings.py` shells out to `mypy tex2pdf` / `mypy tex2pdf_tools/<pkg>`. A type error
shows up as a failing test.

## Architecture

### Compile request flow

`POST /convert/` (`tex2pdf/tex2pdf_api.py`) → save upload → `tarball.unpack_tarball` into
`<tmp>/in`, output to `<tmp>/out` → load `ZeroZeroReadMe(in_dir)` → decide local vs. proxied
compile → `ConverterDriver.generate_pdf()` → `ConversionOutcomeMaker` packs `out/` plus
`outcome-<tag>.json` into a gzip tarball, which is the response body. Errors are returned as
`{"message": ...}` JSON with 400/422/500.

Other endpoints: `POST /stamp/` (watermark an existing PDF), `POST /autotex/` (legacy AutoTeX path,
requires a resolvable arXiv ID), `GET /texlive/info`, `GET /texlive/version`, `GET /` healthcheck.

### TeX Live version routing (proxy mode)

A deployment is either a plain compiler or a **proxy** that forwards to sibling Cloud Run services
running other TeX Live years. This is the most subtle part of the service.

- Enabled by `TEX2PDF_PROXY_RELEASE=1`. Targets come from `TEX2PDF_KEYS_TO_URLS_<key>` env vars
  (e.g. `TEX2PDF_KEYS_TO_URLS_tl2023=...`), falling back to `PROJECT_NR`-derived defaults in
  `tex2pdf/__init__.py`.
- `TEX2PDF_SCOPES` is a `key:epoch:key:epoch:...` string mapping submission timestamp ranges to
  keys, duplicating AutoTeX's `CUTOVER*` constants (the originals are quoted in `__init__.py`).
- `determine_compilation_system()` precedence: explicit `zzrm.texlive_version` → a 00README that
  exists but has no version (implies `tl2023`) → timestamp lookup in `TEX2PDF_SCOPES` → `"current"`
  (compile in this container).
- Forwarding goes through `remote_call.convert_pdf_remote`, which retries 503/504 (Cloud Run cold
  start) up to 3 attempts, rewinding the upload stream each time. `RemoteConverterDriver` /
  `AutoTeXConverterDriver` in `converter_driver.py` are the driver-level equivalents.

### Converters

`ConverterDriver` (`converter_driver.py`) owns the work dir, the time budget
(`MAX_TIME_BUDGET`, default 595s), the top-level-file selection and the watermarking.
`select_converter_class()` in `tex_to_pdf_converters.py` maps the ZZRM compiler string to a class:

```
BaseConverter ├── PdfLatexConverter ├── XeLatexConverter
              │                     └── LuaLatexConverter
              ├── PdfTexConverter
              └── BaseDviConverter  ├── LatexConverter        (latex → dvips → ps2pdf)
                                    └── VanillaTexConverter
```

`_run_base_engine_necessary_times` re-runs the engine up to `MAX_LATEX_RUNS` driven by log
scanning (`rerun_needles`, `MISSING_CITE_RE`, `error_needles`), and `_determine_bib_bbl_processor`
picks bibtex/bibtex8/biber and makeindex. Every subprocess run is recorded into the outcome dict
(argv, stdout, stderr, return code, in/out files), which is what makes `outcome-*.json` the primary
debugging artifact.

### tex2pdf-tools packages

- **`preflight`** — parses a source directory without compiling: builds a document graph, resolves
  includes via `kpsewhich` (`kpse_search.lua`), determines top-level files and a `CompilerSpec`,
  and reports `TeXFileIssue`s. Entry point `generate_preflight_response(rundir, json=)`.
  CLI: `python -m tex2pdf_tools.preflight parse <dir>` / `report <json>`.
  `plugin_api.py` discovers extra QA checks through `importlib.metadata` entry points
  (`tex2pdf_tools.preflight.{file,pdf,source_file,source_tree}_checks`) — **no check heuristics
  live in this public package**, and plugin loading/invocation is deliberately fail-open.
- **`zerozeroreadme`** — the `00README` model (`ZeroZeroReadMe`). v1 is `00README.xxx`, v2 is
  `00README.json` (`.yml/.yaml/.toml/...` are deprecated and ignored with a warning);
  `ZZRM_CURRENT_VERSION` is the spec version. `is_ready_for_compilation`/`is_supported_compiler`
  gate the service, and `update_from_preflight()` fills a ZZRM in when the submission has none and
  `auto_detect` is on.
- **`tex_inspection`** — regex-level source scanning (packages, `\includegraphics`, `.bbl`
  discovery) plus `banned_tex.yaml`.
- **`directives`** — CLI/manager over directives files under a submission base dir.

### Sandboxing

With `ENABLE_SANDBOX=1`, `BaseConverter.decorate_args` prefixes every TeX command with
`/usr/local/bin/bwrap-tex.sh` (`bin/bwrap-tex.sh`), which runs it under bubblewrap with
`--unshare-all`, uid 65534 and a minimal read-only bind set. It relies on a **custom-built bwrap**
that skips loopback setup so `--unshare-net` works under gvisor; the container itself must run with
`--runtime=runsc`. Adding a tool that needs new paths means extending `RO_BIND_BIN` /
`RO_BIND_TEXLIVE` there.

### Configuration

Behaviour is env-var driven, read once at import in `tex2pdf/__init__.py` and
`tex2pdf_tools/preflight/feature_flags.py`. Notable: `TEXLIVE_BASE_RELEASE` (which TeX Live this
container is), `MAX_TIME_BUDGET`, `MAX_LATEX_RUNS`, `MAX_TOPLEVEL_TEX_FILES`,
`MAX_APPENDING_FILES`, `USE_ADDON_TREE` (adds `texmf-arxiv` via `TEXMFAUXTREES`), `ENABLE_SANDBOX`,
`ENABLE_MAKEINDEX`, `ENABLE_LUALATEX`, `ENABLE_JS_CHECKS`, `PREFLIGHT_SOURCE_SUSPICIOUS`,
`LOCAL_EXEC`. New flags follow the `env_flag()` opt-in pattern.

## Conventions

- Commit subjects are `[component] summary` (e.g. `[watermark] ...`, `[preflight] ...`) or
  `TICKET: summary` for Jira-tracked work; branches are named after the ticket or the change.
- Test fixtures for the service are self-contained tarball directories under
  `tex2pdf-service/tests/fixture/tarballs/<case-name>/` — add a directory to add a case.
- Python 3.11 everywhere.
