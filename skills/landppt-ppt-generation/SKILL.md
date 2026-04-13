---
name: landppt-ppt-generation
description: Execute and verify the end-to-end LandPPT protected project workflow for non-browser automation, including project creation, interruption-safe recovery, free-template generation and confirmation, slide generation, share/export, and post-generation speech or narration operations. Use this skill whenever the user wants to generate, resume, verify, edit, narrate, share, or export a LandPPT project through scripts, curl, n8n, CLI, or other API-driven automation instead of the web UI.
---

# LandPPT PPT Generation

## Overview

Execute the LandPPT protected API workflow with a user API key and return Markdown-formatted status/output.
Exported files are published to public `/static` paths by default.
Prefer the bundled Python scripts for reliability. Use direct curl calls only when the user explicitly asks for curl-only execution.

## Preferred execution mode

1. Use `scripts/run_flow.py` for a new end-to-end project run.
2. Use `scripts/project_ops.py` for follow-up work on an existing `project_id`.
3. Keep long-running tasks observable with heartbeat-style progress updates.
4. Preserve and report `project_id` as soon as it exists so interrupted runs can be resumed safely.

## Core workflow

Follow this order unless the user explicitly asks for a narrower post-generation operation.

1. Validate prerequisites.
- Confirm the service is reachable, usually `http://localhost:8000`.
- Use the user API key through `Authorization: Bearer <key>` unless `X-API-Key` is requested.
- Default to 12 pages unless the user requests another count.

2. Create or resume the project.
- For a fresh run, create the project first.
- If the run may already have created a project, do **not** blindly rerun project creation. Reuse the existing `project_id` when possible.

3. Confirm requirements and generate the outline.
- Confirm requirements before outline generation.
- Generate the outline and, when needed, enforce the target page count with `--strict-outline-pages`.

4. Select and prepare free-template mode.
- Select `template_mode=free`.
- Generate the free template.
- Treat free-template generation as streaming-first when the user wants verification detail; preview events may appear before the final template is persisted.
- Confirm the free template before starting slide generation.

5. Generate slides and verify completion.
- Start slide generation through the stream endpoint.
- Treat the stream as progress, not final proof of success.
- A run only passes after final polling confirms:
  - `GET /api/projects/{project_id}` returns `status == completed`
  - `slides_count >= target_pages`
  - `GET /api/projects/{project_id}/slides-data` returns `total_slides >= target_pages`

6. Perform post-success actions as requested.
- Generate a share link after success unless the user wants to skip it.
- Run default PDF export unless the user disables it.
- Use `scripts/project_ops.py` for share/export/speech/narration/task flows on an existing project.

## Hard gate: free-template confirmation

If the project is in free-template mode, `GET /api/projects/{project_id}/slides/stream` should be treated as blocked until the free template has been confirmed.
Do not skip the confirm step or treat it as optional.
If the user is debugging this path, explain that the stream can immediately emit an error when `free_template_confirmed` is still false.
Treat `slides/stream` as an execution endpoint, not a probe for deciding what to do next.

## State-first diagnostic mode

When the user is asking how to verify, resume, debug, or decide the next step for an existing project, do not drift into the full create-project cookbook.
Lead with the minimum state probes and branch from those facts.
Mirror the user's requested format and length when possible.

Canonical state probes for an existing `project_id`:
- `GET /api/projects/{project_id}/free-template`
  - preferred first check when the question is specifically about free-template state, confirm-vs-generate, preview/reuse, or whether slides may start
  - key fields: `available`, `status`, `confirmed`, `active_mode`
- `GET /api/projects/{project_id}`
  - authoritative project status and `slides_count`
- `GET /api/projects/{project_id}/slides-data`
  - authoritative `total_slides`

Preferred decision tree for free-template mode:
1. If `available == true`, `confirmed == true`, and `status == "ready"`, slides are allowed to start.
2. If `available == true` but `confirmed == false`, do not regenerate first; confirm the existing template.
3. If `available == false` and `status` is `pending` or empty, generate a template.
4. If `status == "generating"`, follow the current stream or wait; do not launch a parallel regenerate call unless the user explicitly wants to restart.
5. If `status == "error"`, explain that the last attempt failed and regeneration is the next step, usually with explicit restart intent.
6. If the user says an existing template may already be present, call out the reuse path when `force=false`.

Preferred decision tree for interruption-safe resume:
1. First recover or confirm the existing `project_id` with `GET /api/projects`, not `POST /api/projects`.
2. Check `GET /api/projects/{project_id}` and `GET /api/projects/{project_id}/slides-data` before suggesting any restart.
3. In free-template mode, check `GET /api/projects/{project_id}/free-template` before telling the user to call `slides/stream`.
4. Only recommend a fresh create-project run when you have explicitly ruled out reuse of the interrupted project.

## Success criteria

Treat the workflow as successful only when all of the following are true:
- `final_project_status == completed`
- `final_slides_count >= target_pages`
- `slides_data_total >= target_pages`

A stream `complete` event or stream closure alone is **not** enough.

## Report structure

Return Markdown with the most useful machine-usable fields first:
- `project_id`
- `outline_slides`
- `final_project_status`
- `final_slides_count`
- `slides_data_total`
- `share_url`
- `public_file_url`
- `success`

Include raw JSON in fenced code blocks when payload inspection matters.
If a step fails, report the exact endpoint or script step, HTTP status if known, response body, and the latest known `project_id`.

## Operational gotcha: retries can create duplicate projects

This workflow is **not idempotent** once `POST /api/projects` has succeeded.
If a runner is interrupted and you simply rerun from scratch, you may create duplicate projects with the same topic.

Preferred recovery behavior:
- Prefer unbuffered execution for long runs:
  - `python -u scripts/run_flow.py ...`
- Prefer background or persistent execution for long generations.
- If interruption may have happened after project creation:
  - list recent projects via `GET /api/projects`
  - locate the most likely matching project
  - reuse that `project_id`
  - continue with `scripts/project_ops.py` or direct status polling instead of creating a new project

Cleanup only if the user explicitly asks:
- Cancel slide generation: `POST /api/projects/{project_id}/slides/cancel`
- Delete the project: `DELETE /api/projects/{project_id}`

## Script usage

Run from this skill folder:

```bash
python scripts/run_flow.py \
  --base-url http://localhost:8000 \
  --api-key "YOUR_USER_API_KEY" \
  --topic "AI-driven enterprise knowledge management rollout plan" \
  --requirements "Management report covering current state, solution, implementation path, risk, and ROI" \
  --page-count 12 \
  --heartbeat-sec 20 \
  --strict-outline-pages
```

Useful flags:
- `--disconnect-after-sec 30`: intentionally disconnect the slide stream and prove backend completion through polling.
- `--completion-timeout-sec 3600`: adjust final completion wait time.
- `--heartbeat-sec 20`: periodic progress updates for long tasks.
- `--skip-share-link`: skip share-link generation.
- `--default-export-format none`: disable default PDF export.
- `--public-static-subdir downloads`: set the `/static` subdirectory for returned file links.
- `--public-static-dir "<PATH>"`: override the static root directory.
- `--quiet`: keep script output compact.

## Post-generation and maintenance operations

Use `scripts/project_ops.py` whenever the user already has a `project_id` or only wants part of the lifecycle.
This is the preferred tool for maintenance operations and background task handling.

Supported operations include:
- share-link generation
- outline update and confirmation
- PPT HTML update or `slides_data` update
- speech script generation, listing, update, deletion, and export
- narration generation and per-slide download
- HTML, PDF, standard PPTX, and image-based PPTX export
- task polling and task download

Examples:

```bash
python scripts/project_ops.py share-generate --project-id "<PROJECT_ID>"
```

```bash
python scripts/project_ops.py outline-update --project-id "<PROJECT_ID>" --outline-file "./outline.json"
python scripts/project_ops.py outline-confirm --project-id "<PROJECT_ID>"
```

```bash
python scripts/project_ops.py speech-generate --project-id "<PROJECT_ID>" --generation-type full --wait
python scripts/project_ops.py speech-update --project-id "<PROJECT_ID>" --slide-index 0 --script-content "Updated narration script"
```

```bash
python scripts/project_ops.py narration-generate --project-id "<PROJECT_ID>" --language zh --wait
python scripts/project_ops.py narration-download --project-id "<PROJECT_ID>" --slide-index 0 --out "./slide1.mp3"
```

```bash
python scripts/project_ops.py export-html --project-id "<PROJECT_ID>" --out "./slides.zip"
python scripts/project_ops.py export-pdf --project-id "<PROJECT_ID>" --mode async --wait
python scripts/project_ops.py export-pptx-standard --project-id "<PROJECT_ID>" --wait
python scripts/project_ops.py export-pptx-images --project-id "<PROJECT_ID>" --wait
python scripts/project_ops.py task-status --task-id "<TASK_ID>"
python scripts/project_ops.py task-download --task-id "<TASK_ID>" --out "./result.bin"
```

## Curl-only mode

Only use curl when the user explicitly requires endpoint-by-endpoint testing.
Reference `references/endpoints.md` and preserve this sequence:
1. `GET /api/auth/me`
2. `POST /api/projects`
3. `POST /projects/{project_id}/confirm-requirements`
4. `POST /projects/{project_id}/generate-outline`
5. `POST /api/projects/{project_id}/select-template` with `template_mode=free`
6. `POST /api/projects/{project_id}/free-template/generate`
7. `POST /api/projects/{project_id}/free-template/confirm`
8. `GET /api/projects/{project_id}/slides/stream`
9. `GET /api/projects/{project_id}`
10. `GET /api/projects/{project_id}/slides-data`

When documenting or debugging curl-only runs:
- call out that free-template generation is streaming-first by default
- call out that free-template confirmation is required before the slide stream
- use final polling checks as the authoritative pass criteria

## Failure handling

When a step fails:
1. Stop the chain and report the exact endpoint or script step, HTTP status, and response body.
2. Preserve and return `project_id` if it already exists.
3. For stream uncertainty, keep polling before declaring failure.
4. If a task-oriented export was started, report the `task_id` and next polling/download step.

## Resources

- `scripts/run_flow.py`: end-to-end workflow runner and verifier, including share-link output and default PDF public file link output.
- `scripts/project_ops.py`: follow-up operations for outline/PPT/speech/narration/export tasks and task polling/download.
- `references/endpoints.md`: endpoint order, curl examples, and behavior notes for streaming and verification semantics.
