---
name: landppt-ppt-generation
description: Automate LandPPT through a personal API key. Use for creating, resuming, checking, editing, narrating, sharing or exporting projects without the browser, including free HTML/SVG generation, template-package fast mode, file input, SSE progress and asynchronous tasks. Requires a running LandPPT service; this is not an offline PPTX generator.
---

# LandPPT API workflows

Use Python 3.11+ and the bundled scripts; they require only the standard library. Read [the endpoint reference](references/endpoints.md) for modes, request shapes and feature limits. Use the running service's authenticated `/openapi.json` for exact schemas, rather than guessing fields from UI labels.

## Authentication and authority

Obtain a **personal LandPPT API key** from the user's API Key settings. This is a credential for LandPPT, distinct from an AI provider's key. Prefer the environment over CLI arguments or saved configuration:

```powershell
$env:LANDPPT_BASE_URL = 'https://your-landppt.example'
$env:LANDPPT_USER_API_KEY = '<personal key supplied securely by the user>'
python scripts/api_client.py --path /api/auth/me
```

All scripts accept `--base-url` and `--auth-mode bearer|x-api-key`. They use `LANDPPT_USER_API_KEY`, falling back to `LANDPPT_API_KEY`. Do not send a session cookie alongside an API key, put keys in URLs, print them, or include them in generated artifacts. Use HTTPS for remote services. The clients reject redirects to a different origin rather than forwarding the key.

The updated OpenAPI document declares Bearer, `X-API-Key` and session-cookie authentication as alternatives on protected routes; public routes require none. Configure the selected credential in your AI tool after importing the schema. Explicit Bearer/`X-API-Key` credentials take precedence over cookies, including on cache hits; invalid or empty keys never fall back to a session. Prefer key-only requests and check `/api/auth/me`.

Keys inherit the owner's account permissions and credits; there are no per-key read/write scopes. A normal user's key cannot activate admin-only unattended execution. Never request an admin key to bypass a permission error. Rotation of a named key invalidates its previous value; deletion and expiration prevent future authentication. The creation response is the only opportunity to save an automatically generated plaintext key.

**Server upgrade:** apply migration `022` before deploying this auth implementation. New/rotated keys have a unique fingerprint as well as a salted authentication hash. Existing unique keys remain usable and acquire a fingerprint on successful authentication. Registration rejects a key already stored or bound in environment settings. Historical duplicates or overlapping environment/personal bindings fail authentication; sign in through the browser and rotate conflicting keys or remove conflicting environment bindings. Never silently pick an account or repeat a failed billable operation. Older deployments may still contain the bugs audited on 2026-11-01; verify the running server has been upgraded.

## Choose a tool

- `scripts/run_flow.py`: create a **new free-template HTML project**, confirm requirements, generate an outline, generate/confirm its template, stream slides and verify persisted completion. This runner does not implement template-package mode or automatic resume.
- `scripts/project_ops.py`: follow-up outline, page, speech, narration, share, export and task operations on a known project. Use `--help` and subcommand `--help` for arguments.
- `scripts/api_client.py`: any service-relative API route using JSON, URL-encoded forms, multipart files, live SSE or private downloads. Use this for project state, quick/package mode, uploads, AI editing and other routes absent from the convenience scripts.

Examples assume the current directory is this skill's root. Installed skills do not need access to the LandPPT repository or server filesystem for ordinary API work.

## New free-template project

```bash
python scripts/run_flow.py --topic 'Annual operating plan' --page-count 12 --requirements 'Summarize priorities, budget and risks' --output-dir ./outputs
```

The runner defaults to 12 pages and PDF export. Honor the user's requested page count and output format; use `--default-export-format none` when only generation is wanted. The project ID is printed immediately after creation, including under `--quiet`; retain it for recovery. PDF and PPTX conversion depend on the server's configured renderer, permissions and converters.

Execution order:

1. Authenticate, create the project and save its ID.
2. Confirm requirements as a **form**, then generate the outline.
3. Select `template_mode=free`, generate with JSON `{"stream":false}`, then confirm the free template.
4. Call the slide SSE execution endpoint once and observe progress.
5. Verify project `status == completed`, project `slides_count >= target`, and `/slides-data` `total_slides >= target`. Inspect returned slide content when diagnosing missing or broken pages. A complete event or closed stream alone does not prove success.

Template generation is SSE by default. `api_client.py --stream` supports preview/progress; JSON clients must explicitly send `stream:false`. The runner does so. Do not mix these response formats.

## Existing project and interruption recovery

Do not rerun `run_flow.py` after an interruption: it creates a new project. Recover an unknown ID with `GET /api/projects`; otherwise inspect the existing project first:

```bash
python scripts/api_client.py --path /api/projects/PROJECT_ID
python scripts/api_client.py --path /api/projects/PROJECT_ID/slides-data
python scripts/api_client.py --path /api/projects/PROJECT_ID/free-template
```

For free-template mode, inspect `available`, `confirmed`, `status`, and `active_mode`:

- Existing available, confirmed, ready template: slide generation may proceed.
- Available but unconfirmed: confirm the existing template; do not regenerate it.
- Pending/unavailable: generate it, then confirm.
- Generating: poll state and follow the current run; avoid duplicate generation.
- Error: report the failure and decide whether a retry is appropriate before restarting billable work.

`GET /api/projects/ID/slides/stream` **starts execution**, despite its GET verb. Do not use it as a status probe or replay it after a timeout without inspecting state. Preserve `project_id` and any `task_id` even when a request fails. Task state may continue changing after the client disconnects.

## Quick/package mode and SVG

Read the endpoint reference before these flows. The runner above remains a free-template HTML runner.

For template-package fast mode, list usable packages, confirm requirements with `generation_mode=package` and `package_version_id`, generate the outline, and select the version through `/template-package` if it is not already selected. Inspect the package snapshot before starting slides. Do not apply the free-template confirmation gate to a package project. Page edits use `expected_revision`; on 409, reload state and reconcile instead of blindly overwriting.

For SVG freeform output, set `render_mode=svg` when confirming requirements and retain the normal template/outline gates. SVG generation is available through the API; the editor's native-object/vector PPTX exporters run in browser JavaScript and do **not** have equivalent dedicated server export routes. Never describe the standard server PPTX export as the SVG native exporter.

## Arbitrary requests, uploads and streams

```bash
python scripts/api_client.py --method POST --path /api/projects --json-file project.json
python scripts/api_client.py --method POST --path /projects/PROJECT_ID/confirm-requirements --form 'topic=Annual plan' --form 'audience_type=management' --form 'page_count_mode=fixed' --form 'fixed_pages=12'
python scripts/api_client.py --method POST --path /api/projects/PROJECT_ID/free-template/generate --json '{"stream":true}' --stream --timeout 3600
python scripts/api_client.py --path /api/projects/PROJECT_ID/slides/stream --stream --timeout 3600
python scripts/api_client.py --path /api/landppt/tasks/TASK_ID/download --out ./outputs/deck.pdf
```

Use `--json-file` for complex bodies, `--form FIELD=VALUE` for form fields and `--file FIELD=PATH` for multipart file uploads. Fields/files can repeat. For uploaded project source material use the reference's confirmed-requirements flow, not a guessed provider upload endpoint. Do not combine JSON with form/file arguments. Quote encoded query strings as a single `--path` argument.

An HTTP 200 may still contain `success:false` or an SSE error event; inspect the body and follow-up state. Never automatically retry a mutation or a generation endpoint merely because the connection broke. Fix 401 authentication, respect 403 permissions, check ownership/IDs for 404, reload revision conflicts on 409, and use `/openapi.json` to resolve 422 request errors.

## Share and exports

Downloads remain **private local files by default**. Generation does not create a share link unless the user requests sharing; pass `run_flow.py --share-link` or explicitly run `project_ops.py share-generate`. A public share grants access to anyone holding its link. Disable it through the reference endpoint when requested.

```bash
python scripts/project_ops.py --output-dir ./outputs export-pdf --project-id PROJECT_ID
python scripts/project_ops.py --output-dir ./outputs export-html --project-id PROJECT_ID
python scripts/project_ops.py --output-dir ./outputs export-pptx-standard --project-id PROJECT_ID
python scripts/project_ops.py task-status --task-id TASK_ID
python scripts/project_ops.py --output-dir ./outputs task-download --task-id TASK_ID
```

Async exports return a task ID. Poll it to `completed` before downloading; report `failed`/`cancelled` without claiming a file is ready. Export access and conversion availability are separate from key validity. The image PPTX route expects rendered slide images; it is not an automatic native-object conversion.

Only when the user explicitly requests public-file publishing **and** the actual server static directory is mounted locally, use `--publish-static --public-static-dir SERVER_STATIC_ROOT`. The directory must already exist. This copies the file into a public `/static/` path without authenticated download protection. A client-local directory cannot publish a file on a remote server. No server static path is guessed by default. `LANDPPT_PUBLIC_STATIC_DIR` alone does not enable publishing.

## Reporting

Lead with `project_id`, persisted status, slide counts and local artifact path. Include `task_id` for pending exports and a share URL only if one was requested and actually created. Report the failed endpoint/status and existing ID on error. Do not paste credentials or invent public URLs. Distinguish API availability, schema validation and local mocked tests from a paid end-to-end generation run.
