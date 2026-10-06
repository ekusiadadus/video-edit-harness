# Contributing

Use Python 3.11+ and uv. Install FFmpeg/ffprobe before media integration tests.

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv build
uv run python scripts/package_release.py --output dist
uv run python scripts/smoke_wheel.py dist/video_edit_harness-0.1.0a5-py3-none-any.whl
```

Keep changes focused and preserve source media and earlier session revisions. Add tests for observable behavior and integrity failures. Cloud tests must mock providers; do not upload real footage or require secrets in CI. Treat human listening/visual decisions and FCP GUI checks separately from software success. Read AGENTS.md for editing invariants.

Do not include media, credentials, transcripts, private project JSON, source paths, caches, or generated session artifacts in issues or pull requests. A small synthetic reproducer and sanitized tool versions are usually enough. Contributions are licensed under the repository's MIT license.

Release checklist: update the PEP 440 version and matching Git tag, lock dependencies, run tests and clean-install smoke checks, review the exact staged file list and distribution contents, commit, create an annotated tag, push, and publish wheel/sdist/skill ZIP with SHA256SUMS. Initial prereleases use tags such as `v0.1.0-alpha.1` (Python `0.1.0a1`). Do not call an alpha stable or claim unperformed perceptual checks.
