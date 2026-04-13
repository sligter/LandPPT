# LandPPT Full API Flow Reference

## Auth Header

Use either header form:
- `Authorization: Bearer <USER_API_KEY>`
- `X-API-Key: <USER_API_KEY>`

Examples below use `Authorization`.

```bash
BASE_URL="http://localhost:8000"
API_KEY="YOUR_USER_API_KEY"
AUTH_HEADER="Authorization: Bearer ${API_KEY}"
```

## 1) Verify API Key

```bash
curl -sS -X GET "${BASE_URL}/api/auth/me" \
  -H "${AUTH_HEADER}"
```

Expected: `success=true` and a user object.

## 2) Create Project

```bash
curl -sS -X POST "${BASE_URL}/api/projects" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{
    "scenario":"general",
    "topic":"AI-driven enterprise knowledge management rollout plan",
    "requirements":"Management report covering current state, solution, implementation path, risk, and ROI",
    "language":"zh",
    "network_mode":false
  }'
```

Capture `project_id` from the response.

## 3) Confirm Requirements (Fixed 12 Pages)

```bash
curl -sS -X POST "${BASE_URL}/projects/${PROJECT_ID}/confirm-requirements" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "topic=AI-driven enterprise knowledge management rollout plan" \
  --data-urlencode "audience_type=management" \
  --data-urlencode "page_count_mode=fixed" \
  --data-urlencode "fixed_pages=12" \
  --data-urlencode "ppt_style=general" \
  --data-urlencode "description=End-to-end automated PPT generation test" \
  --data-urlencode "content_source=manual"
```

Expected: `status=success`.

## 4) Generate Outline

```bash
curl -sS -X POST "${BASE_URL}/projects/${PROJECT_ID}/generate-outline" \
  -H "${AUTH_HEADER}"
```

Expected: `status=success` with `outline_content`.

## 5) Select Free Template Mode

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/select-template" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d "{
    \"project_id\":\"${PROJECT_ID}\",
    \"template_mode\":\"free\"
  }"
```

Expected: `success=true`.

## 6) Generate Free Template

### Streaming-first request

```bash
curl -N -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/free-template/generate" \
  -H "${AUTH_HEADER}" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### JSON-only request

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/free-template/generate" \
  -H "${AUTH_HEADER}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"stream":false}'
```

Expected: the template eventually reaches `success=true` / complete state.

### Behavior notes

- This endpoint is streaming-first by default.
- Stream output may include intermediate preview HTML before the final template is persisted.
- If an existing ready free template already exists and `force=false`, the backend may reuse it instead of regenerating.
- Treat this endpoint as a stateful preparation step, not just a one-shot blocking call.

## 7) Inspect Free-Template State (Recommended Before Generate/Confirm/Slides)

```bash
curl -sS -X GET "${BASE_URL}/api/projects/${PROJECT_ID}/free-template" \
  -H "${AUTH_HEADER}"
```

Key fields to branch on:
- `active_mode`
- `available`
- `status` (`pending` / `generating` / `ready` / `error`)
- `confirmed`
- `template`

Recommended interpretation:
- `available=true`, `confirmed=true`, `status=ready`: the template is already approved; slides may start.
- `available=true`, `confirmed=false`: reuse the existing template view, then confirm it; do not assume regenerate is needed.
- `available=false`, `status=pending` or empty: generate is the next step.
- `status=generating`: generation is already in flight; prefer following the current stream rather than starting another one.
- `status=error`: the last generation attempt failed; explain that regeneration is the next step.

## 8) Confirm Free Template

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/free-template/confirm" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"save_to_library":false}'
```

Expected: `success=true`.

### Behavior notes

- Confirmation marks the generated free template as the approved project template state.
- In free-template mode, this confirmation is required before slide generation should be considered valid to start.
- Confirmation is the gate that changes `confirmed` to true; generation alone does not grant that permission.

## 9) Trigger and Observe Slide Generation (SSE)

```bash
curl -N -X GET "${BASE_URL}/api/projects/${PROJECT_ID}/slides/stream" \
  -H "${AUTH_HEADER}"
```

Expected stream event types:
- `progress`
- `slide`
- `complete`
- `error`

### Behavior notes

- Treat the slide stream as progress reporting, not the final success source of truth.
- If the project is in free-template mode and the free template has not been confirmed, the stream may immediately emit an `error` event instead of starting generation.
- For resilience testing, the client may disconnect and later verify completion by polling.

## 10) Verify Final Status and Slide Count

```bash
curl -sS -X GET "${BASE_URL}/api/projects/${PROJECT_ID}" \
  -H "${AUTH_HEADER}"
```

```bash
curl -sS -X GET "${BASE_URL}/api/projects/${PROJECT_ID}/slides-data" \
  -H "${AUTH_HEADER}"
```

Pass criteria:
- project `status == completed`
- `slides_count >= target_pages`
- `total_slides >= target_pages`

Final status verification is more authoritative than the raw stream outcome.

## 11) Generate Share Link (Recommended After Completion)

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/share/generate" \
  -H "${AUTH_HEADER}"
```

Expected fields:
- `success: true`
- `share_token`
- `share_url` (path like `/share/<token>`)

Open link:
- `${BASE_URL}${share_url}`

## Recovery / resume helper

If a previous run may already have created the project, avoid another `POST /api/projects)` first.
List recent projects and reuse the best matching `project_id`.

```bash
curl -sS -X GET "${BASE_URL}/api/projects?page=1&page_size=10" \
  -H "${AUTH_HEADER}"
```

Use the returned `project_id` with status polling, share/export operations, or other `project_ops`-style follow-up steps.

## Outline and PPT Editing Endpoints

Update outline:

```bash
curl -sS -X POST "${BASE_URL}/projects/${PROJECT_ID}/update-outline" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"outline_content":"...json or text outline content..."}'
```

Confirm outline:

```bash
curl -sS -X POST "${BASE_URL}/projects/${PROJECT_ID}/confirm-outline" \
  -H "${AUTH_HEADER}"
```

Update full PPT HTML:

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/update-html" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"slides_html":"<!doctype html>..."}'
```

Update `slides_data`:

```bash
curl -sS -X PUT "${BASE_URL}/api/projects/${PROJECT_ID}/slides" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"slides_data":[...]}'
```

## Speech Script Endpoints

Generate scripts:

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/speech-script/generate" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{
    "generation_type":"full",
    "language":"zh",
    "customization":{
      "tone":"conversational",
      "target_audience":"general_public",
      "language_complexity":"moderate"
    }
  }'
```

List scripts:

```bash
curl -sS -X GET "${BASE_URL}/api/projects/${PROJECT_ID}/speech-scripts?language=zh" \
  -H "${AUTH_HEADER}"
```

Update one script:

```bash
curl -sS -X PUT "${BASE_URL}/api/projects/${PROJECT_ID}/speech-scripts/slide/0?language=zh" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"script_content":"updated script text"}'
```

## Narration Audio Endpoints

Generate narration (background task):

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/narration/generate" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"provider":"edge_tts","language":"zh"}'
```

Download slide narration audio:

```bash
curl -L -X GET "${BASE_URL}/api/projects/${PROJECT_ID}/narration/audio/0?language=zh&autogen=true" \
  -H "${AUTH_HEADER}" \
  -o "slide_1_narration.mp3"
```

## Export Endpoints

Export HTML ZIP:

```bash
curl -L -X GET "${BASE_URL}/api/projects/${PROJECT_ID}/export/html" \
  -H "${AUTH_HEADER}" \
  -o "slides.zip"
```

Export PDF (background task):

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/export/pdf/async" \
  -H "${AUTH_HEADER}"
```

Export standard PPTX (background task):

```bash
curl -sS -X GET "${BASE_URL}/api/projects/${PROJECT_ID}/export/pptx" \
  -H "${AUTH_HEADER}"
```

Export image-based PPTX (background task):

```bash
curl -sS -X POST "${BASE_URL}/api/projects/${PROJECT_ID}/export/pptx-images" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[{"index":0,"title":"Slide 1","html_content":"<!doctype html>..."}]}'
```

## Background Task Polling and Download

Poll status:

```bash
curl -sS -X GET "${BASE_URL}/api/landppt/tasks/${TASK_ID}" \
  -H "${AUTH_HEADER}"
```

Download task result:

```bash
curl -L -X GET "${BASE_URL}/api/landppt/tasks/${TASK_ID}/download" \
  -H "${AUTH_HEADER}" \
  -o "task_result.bin"
```
