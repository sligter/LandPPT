# LandPPT endpoint reference

Checked against repository routes on 2026-11-01. Prefixes below are complete paths. All protected routes accept a personal key in `Authorization: Bearer KEY` or `X-API-Key: KEY`. The same authentication also covers protected `/projects/...` form endpoints. Account ownership, admin restrictions, feature permissions, credits and provider configuration still apply.

## Discover schemas and authenticate

```bash
python scripts/api_client.py --path /api/auth/me
python scripts/api_client.py --path /openapi.json --out ./outputs/openapi.json
```

Do not transmit the key to another origin. The OpenAPI schema describes types, multipart field names and optional parameters, but some dynamically parsed request bodies need the source notes below. A route being present does not guarantee a configured model, credits, converter or browser renderer.

After the backend auth upgrade, `securitySchemes` declares `BearerAuth`, `ApiKeyAuth` (`X-API-Key`) and `SessionCookie` as OR alternatives on protected operations. Public operations have no auth requirement. Operation IDs are unique; duplicate method/path registrations document the first runtime handler. Import the running server's schema and configure the selected credential. Older deployments may lack these declarations. Runtime authentication remains enforced by middleware independently of schema generation.

| Method | Path | Purpose / body |
| --- | --- | --- |
| GET | `/api/auth/me` | Check the effective user before mutations |
| GET | `/api/auth/api-keys` | Own key metadata; plaintext is not returned |
| POST | `/api/auth/api-keys` | JSON: `name`, optional `api_key`, optional `expires_in_days` (1–3650); creates or rotates that name |
| DELETE | `/api/auth/api-keys/{key_id}` | Revoke own key; do not delete the caller's key accidentally |
| GET | `/api/projects` | Recover existing project IDs |
| POST | `/api/projects` | JSON: `scenario`, `topic`, `requirements`, `language`, `network_mode` |
| GET | `/api/projects/{project_id}` | Persisted status and counts |
| GET | `/api/projects/{project_id}/slides-data` | Persisted slide content and `total_slides` |
| POST | `/api/projects/{project_id}/duplicate` | Explicitly duplicate an existing project |
| DELETE | `/api/projects/{project_id}` | Delete a project only when requested |

Prefer generated random keys. Migration `022` adds a unique key fingerprint while preserving old salted hashes; existing unique keys are upgraded on authentication. Duplicate custom keys and environment collisions are rejected, and ambiguous historical bindings fail authentication. Explicit keys take precedence over cookies and cannot fall back to a session on failure. Keys carry the owner's full permissions, without separate per-key scopes. This skill does not configure the user's model provider or create an admin account.

## Requirements, outline and sources

`POST /projects/{project_id}/confirm-requirements` takes **form or multipart**, not JSON. Required: `topic`, `audience_type`. Common fields:

- `page_count_mode=fixed`, `fixed_pages=12` (or `ai_decide` with `min_pages` / `max_pages`).
- `ppt_style`, `custom_style_prompt`, `description`.
- `content_source=manual|file|url`; use repeated `file_upload` files for file input or `content_urls` for URL input. See the deployed schema for processing options.
- `render_mode=html|svg` selects the page representation.
- `generation_mode=freeform|package`; package mode also needs a valid `package_version_id` visible to this account.
- `unattended_mode=true` is admin-only; do not enable it implicitly.

```bash
python scripts/api_client.py --method POST --path /projects/PROJECT_ID/confirm-requirements --form 'topic=Annual plan' --form 'audience_type=management' --form 'page_count_mode=fixed' --form 'fixed_pages=12' --form 'content_source=file' --file 'file_upload=./report.pdf'
```

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/projects/{project_id}/generate-outline` | Generate after requirements; JSON response |
| GET | `/projects/{project_id}/outline-stream` | SSE generation; execution, not a status probe |
| POST | `/projects/{project_id}/update-outline` | JSON `outline_content` |
| POST | `/projects/{project_id}/confirm-outline` | Confirm the current outline; inspect response before selecting a template |
| GET | `/api/upload/formats` | Supported document formats |
| POST | `/api/upload` | Multipart `file`; processes a document, does not complete a project |
| POST | `/api/upload/analyze` | Multipart `file`; analysis/suggestions |
| POST | `/api/files/upload-and-generate-outline` | Repeated multipart `files`, plus form fields; standalone outline route |
| POST | `/api/image/upload` | Image upload; see schema for fields/options |
| GET | `/api/research/status` | Research availability/configuration |
| POST | `/api/research/conduct` | Research request; inspect schema and result |

Standalone outline/document routes are distinct from persisted project workflows. Do not assume that uploading a file automatically stores an outline on an existing project.

## Free templates, global templates and slides

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/projects/{project_id}/select-template` | JSON `project_id`, `template_mode=free`; other modes require their documented template fields |
| GET | `/api/projects/{project_id}/selected-template` | Selected template state |
| GET | `/api/projects/{project_id}/free-template` | `available`, `status`, `confirmed`, `active_mode` |
| POST | `/api/projects/{project_id}/free-template/generate` | JSON `force` (default false), `stream` (default true); `stream:false` gives JSON |
| POST | `/api/projects/{project_id}/free-template/confirm` | JSON `save_to_library:false` for project-only confirmation |
| POST | `/api/projects/{project_id}/free-template/adjust` | Adjust the template; consult source/schema for the request body |
| GET | `/api/global-master-templates/` | Legacy global template library; trailing slash matters |
| GET | `/api/projects/{project_id}/slides/stream` | SSE **starts slide generation**; free mode requires template confirmation |
| POST | `/api/projects/{project_id}/slides/cancel` | Request generation cancellation |
| POST | `/api/projects/{project_id}/slides/{slide_number}/regenerate/async` | Regenerate a single page; this endpoint uses a 1-based slide number |
| POST | `/api/projects/{project_id}/slides/batch-regenerate/async` | JSON uses 0-based `slide_indices` or `regenerate_all` |
| POST | `/api/projects/{project_id}/slides/{slide_index}/save` | Save a page; 0-based index; inspect request body |
| POST | `/api/projects/{project_id}/slides/{slide_index}/lock` | Lock page |
| POST | `/api/projects/{project_id}/slides/{slide_index}/unlock` | Unlock page |
| GET | `/api/projects/{project_id}/versions` | Version history |
| POST | `/api/projects/{project_id}/versions/{version}/restore` | Restore only the requested version |
| POST | `/api/ai/slide-edit-agent/stream` | Agent edit SSE; schema includes current page context and request limits |
| POST | `/api/ai/slide-edit-agent/apply` | Apply an agent proposal; do not assume streaming alone saved it |
| POST | `/api/ai/slide-edit-agent/cancel` | Cancel the requested agent run |

SSE endpoints can report application errors inside HTTP 200 responses. `api_client.py --stream` prints complete data frames and exits nonzero for explicit error events. Always verify persisted project/slide state after generation or edits. A disconnected client is not evidence that the server stopped.

## Fast/template-package workflow

List usable package versions first. Confirm requirements with `generation_mode=package` and `package_version_id` so outline generation knows layout constraints. After the outline exists, select the package if needed and inspect its snapshot. Start slide generation only after prerequisites are satisfied. Do not generate or confirm a free template for a package project.

```bash
python scripts/api_client.py --path /api/global-master-templates/packages
python scripts/api_client.py --method POST --path /projects/PROJECT_ID/confirm-requirements --form 'topic=Annual plan' --form 'audience_type=management' --form 'generation_mode=package' --form 'package_version_id=VERSION_ID'
python scripts/api_client.py --method POST --path /projects/PROJECT_ID/generate-outline
python scripts/api_client.py --method POST --path /api/projects/PROJECT_ID/template-package --json-file package-selection.json
python scripts/api_client.py --path /api/projects/PROJECT_ID/template-package
```

`package-selection.json` contains `{"version_id":123,"options":{}}`, using an actual accessible version ID. Read the deployed `PackageOptions` schema to customize options.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/global-master-templates/packages` | Available package versions |
| GET | `/api/global-master-templates/packages/{version_id}` | Version/manifest details |
| POST | `/api/global-master-templates/packages-generate` | Generate a package with SSE; JSON `prompt` and schema-defined options |
| POST | `/api/global-master-templates/packages-import` | Package import; schema-defined multipart/body |
| POST | `/api/global-master-templates/packages-pptx/analyze` | Analyze reference PPTX; see schema |
| POST | `/api/global-master-templates/packages-pptx/import` | PPTX-to-package import; see schema |
| GET | `/api/global-master-templates/packages/{version_id}/export` | Download package export privately with `--out` |
| POST | `/api/projects/{project_id}/template-package` | JSON `version_id`, `options` |
| GET | `/api/projects/{project_id}/template-package` | Snapshot with pages, content and revisions |
| GET | `/api/projects/{project_id}/package-pages/{slide_id}/layouts` | Compatible layout choices |
| PUT | `/api/projects/{project_id}/package-pages/{slide_id}/content` | JSON `expected_revision`, `content` (typed PageContent) |
| POST | `/api/projects/{project_id}/package-pages/{slide_id}/action` | JSON `expected_revision`, `action`, optional component/visual/image IDs |
| POST | `/api/projects/{project_id}/package-pages/{slide_id}/edit` | JSON `expected_revision`, `instruction` |

Package page edits use `slide_id` from the snapshot, not a guessed numeric index. On revision conflict (409), reload and reconcile. A published/available package and a generated free template are different resources.

## Speech, narration, exports and tasks

Convenience commands are in `project_ops.py`; place its global options before the subcommand.

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/projects/{project_id}/speech-script/generate` | Generate speech; check returned progress/task IDs |
| GET | `/api/projects/{project_id}/speech-scripts` | Persisted speech scripts |
| PUT | `/api/projects/{project_id}/speech-scripts/slide/{slide_index}` | Update one script |
| POST | `/api/projects/{project_id}/speech-script/export` | DOCX/Markdown binary download |
| POST | `/api/projects/{project_id}/narration/generate` | TTS provider/voice parameters; may return a task |
| POST | `/api/projects/{project_id}/narration/reference-audio` | Upload reference audio; inspect multipart schema |
| GET | `/api/projects/{project_id}/narration/audio/{slide_index}` | Audio download; may auto-generate unless autogen is disabled |
| GET | `/api/projects/{project_id}/export/html` | HTML download |
| POST | `/api/projects/{project_id}/export/pdf/async` | Start PDF task |
| GET | `/api/projects/{project_id}/export/pdf` | Synchronous PDF download |
| GET | `/api/projects/{project_id}/export/pptx` | Start standard PPTX conversion task; GET has side effects |
| POST | `/api/projects/{project_id}/export/pptx-images` | Image-based PPTX from rendered slide images |
| POST | `/api/projects/{project_id}/export/narration-audio` | Narration audio export task |
| POST | `/api/projects/{project_id}/export/narration-video` | Narrated video export task |
| GET | `/api/landppt/tasks/{task_id}` | Owner-scoped status/progress |
| GET | `/api/landppt/tasks/{task_id}/download` | Owner-scoped completed task download |
| GET | `/api/projects/{project_id}/share/info` | Current share configuration |
| POST | `/api/projects/{project_id}/share/generate` | **Explicit sharing only**; creates a public capability link |
| POST | `/api/projects/{project_id}/share/disable` | Disable the public link |

The editor's client-side native SVG/object and vector PPTX exporters have no dedicated equivalent server API. Standard PPTX conversion and image PPTX are different export paths. Do not promise every browser export from a server API call. Do not create anonymous `/static` copies by default; use protected downloads.

## Admin-only unattended pipeline

`GET /api/unattended/stages` lists stages. Starting with `POST /api/projects/{project_id}/unattended/start` requires an admin account and confirmed requirements. JSON options include `stop_after`, `language`, `template_id`, TTS options and `render_mode`. Poll `GET /api/projects/{project_id}/unattended/status`; cancel through `POST /api/projects/{project_id}/unattended/cancel`. Stage execution may incur model/TTS/export charges. Ordinary account keys are intentionally restricted; use the manual workflow instead.

## Compatibility boundary

`/v1/models`, `/v1/chat/completions` and `/v1/completions` form a limited chat compatibility facade. The current chat route returns JSON even when `stream:true` is supplied; it is not a full streaming/tools API or a substitute for the persisted project workflow. No `/v1/responses` endpoint is registered. Use the LandPPT project endpoints above for creation, template selection, edits and exports.
