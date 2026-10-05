# Install the video-editing skill

English | [日本語](SKILL_INSTALL.ja.md)

This is a public, MIT-licensed community skill for Codex and Claude Code. It is distributed from this GitHub repository and its releases; it is not listed in the vendors' official curated directories. The skill requires Video Edit Harness, Python 3.11+, uv, FFmpeg and ffprobe. It installs no local Whisper model and grants no permission to upload footage.

## Prepare the harness

```sh
git clone --branch v0.1.0-alpha.3 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
export VIDEO_EDIT_HARNESS_ROOT="$PWD"
```

Keep `VIDEO_EDIT_HARNESS_ROOT` available in the environment from which you start your agent. The skill does not automatically install dependencies or fetch a missing checkout. If the checkout is absent, follow these steps before editing. Do not overwrite an existing installation without reviewing it.

## Codex

The checkout already exposes `.agents/skills/video-editing`. To use it in other projects, copy that folder to `~/.agents/skills/video-editing`, or install the release's `video-editing-skill-v0.1.0-alpha.3.zip` there after verifying `SHA256SUMS`. The ZIP extracts as `video-editing/` and includes `SKILL.md`, `agents/openai.yaml`, and MIT license. It contains no harness or media.

Start a new Codex session and invoke `$video-editing`, for example: “Use $video-editing to compare three indoor grades for my local project. Do not upload the source.” See the [official Codex skill guide](https://developers.openai.com/codex/skills).

## Claude Code

Install the repository's community plugin through its marketplace:

```sh
claude plugin marketplace add ekusiadadus/video-edit-harness
claude plugin install video-editing@video-edit-harness
```

Start a new Claude Code session and invoke `/video-editing:video-editing`. Marketplace updates follow the public repository; the separate harness checkout above stays pinned until you explicitly update it. You can also use the standalone skill ZIP by copying its `video-editing/` folder into `~/.claude/skills/` and invoking `/video-editing`. Choose one method to avoid duplicate skill loading.

The release's `video-editing-claude-plugin-v0.1.0-alpha.3.zip` is a portable plugin package with a manifest, the same skill, and license; it does not bundle the harness or media. Extract it and use `claude --plugin-dir /absolute/path/to/extracted-plugin` for local loading. `CLAUDE.md` at an installed plugin root is not automatically loaded; the skill explicitly directs the agent to the harness README and AGENTS.md. See [official marketplace instructions](https://code.claude.com/docs/en/plugin-marketplaces).

## Privacy and evidence

An explicit no-upload restriction also prohibits cloud transcription for that source. Grading, audio normalization, previews and technical checks can run locally. Without an existing sealed transcript, do not invent word timestamps or run transcript-backed pacing edits. Public demo media is synthetic. Human listening/visual review and FCP GUI checks remain separate from software validation.

## Use /tiktok

Verify and extract `tiktok-skill-v0.1.0-alpha.3.zip`, then copy `tiktok/` into `~/.claude/skills/tiktok`. Start a new session and invoke `/tiktok /path/to/video.mov`. In Codex, install the same folder under `~/.agents/skills/tiktok` and invoke `$tiktok`. The marketplace plugin invokes `/video-editing:tiktok`. See [TikTok workflow](TIKTOK.md).
