# Project Skills

## Available

- [landppt-ppt-generation](landppt-ppt-generation/SKILL.md): automate a running LandPPT service with a personal API key. Includes a new-project free-template runner, follow-up project operations, a general JSON/form/multipart/SSE/download client, and an endpoint reference covering template packages, SVG, uploads, editing and exports.

## Usage

Install the complete `landppt-ppt-generation` directory in your agent's skills directory. Python 3.11+ is sufficient; the bundled scripts use only the standard library. Configure `LANDPPT_BASE_URL` and securely supply `LANDPPT_USER_API_KEY` from personal settings. The key inherits the account's permissions and credits.

```text
Use $landppt-ppt-generation to create a 12-page annual plan and save the PDF locally.
```

```bash
python skills/landppt-ppt-generation/scripts/api_client.py --help
python skills/landppt-ppt-generation/scripts/run_flow.py --help
python skills/landppt-ppt-generation/scripts/project_ops.py --help
```

Downloads stay local by default. Sharing and publishing into the server's public static directory are explicit options. Read [the endpoint reference](landppt-ppt-generation/references/endpoints.md) for supported modes and limitations. This package depends on the LandPPT server; it is not a standalone offline PPTX generator.
