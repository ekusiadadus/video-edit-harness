# Install the skills

English | [日本語](SKILL_INSTALL.ja.md)

Three MIT community skills: `youtube` for regular videos, `tiktok` for vertical shorts and `video-editing` for general editing. Instructions require the separate harness; they do not authorize source uploads. This GitHub distribution is not an official curated-directory listing.

## 1. Prepare the pinned harness

Install Python 3.11+, uv, FFmpeg and ffprobe; for Japanese caption burn-in, provide a CJK font.

```sh
git clone --branch v0.1.0-alpha.5 https://github.com/ekusiadadus/video-edit-harness.git
cd video-edit-harness
uv sync --locked
export VIDEO_EDIT_HARNESS_ROOT="$PWD"
uv run video-harness doctor
```

Keep that environment variable available when starting your agent from another project. The doctor reports checkout/runtime/plugin/skill versions, commands, tools, font, free space and credential **booleans**. Resolve relevant findings. Version differences are diagnostic; verify command compatibility before using a different checkout. No agent installs dependencies automatically.

## 2. Choose one skill installation method

**Codex:** the checkout exposes all three `.agents/skills/` folders. In other projects, copy the selected folders into `~/.agents/skills/` or the project's `.agents/skills/`. Start a fresh session and invoke `$youtube`, `$tiktok` or `$video-editing` with a local path and brief.

**Claude Code marketplace plugin:**

```sh
claude plugin marketplace add ekusiadadus/video-edit-harness
claude plugin install video-editing@video-edit-harness
```

Start a fresh session. Invoke `/video-editing:youtube`, `/video-editing:tiktok` or `/video-editing:video-editing`. Marketplace updates follow main; the harness above remains pinned until explicitly updated. Compare versions with doctor after updates.

**Claude standalone skills:** copy the chosen `.agents/skills/NAME` folder to `~/.claude/skills/NAME` or `.claude/skills/NAME`. Start a new session and invoke `/youtube /path/to/video.mov`, `/tiktok /path/to/video.mov` or `/video-editing`. Choose standalone or plugin for a given skill to avoid duplicates.

## Verified release archives

Download from the [alpha.5 release](https://github.com/ekusiadadus/video-edit-harness/releases/tag/v0.1.0-alpha.5). `RELEASE-MANIFEST.json` lists exactly the current wheel, source archive, three skill ZIPs and plugin ZIP; `SHA256SUMS` covers those artifacts and the manifest. Verify checksums before installing.

Each `NAME-skill-v0.1.0-alpha.5.zip` extracts as `NAME/` with `SKILL.md`, `agents/openai.yaml` and LICENSE. Copy that directory to your agent's skill directory. ZIPs include no harness or media.

`video-editing-claude-plugin-v0.1.0-alpha.5.zip` contains a plugin manifest, all three skills and license. Extract it and run `claude --plugin-dir /absolute/path/to/extracted-plugin` for local pinned loading. Plugin-root `CLAUDE.md` is not automatically loaded; the skill directs the agent to the checkout's README and AGENTS.md.

The wheel installs into a virtual environment with `uv pip install /path/to/video_edit_harness-0.1.0a5-py3-none-any.whl`; it includes preset data and the CLI. The skills still use the checkout's templates and instructions. PyPI publication is outside this release.

## First successful run

Try the [offline synthetic sample](demo/README.md). It has measured word timing, no API-key requirement and explicit upload denial. For your own source, retain existing authorization; cloud calls need a source SHA and authorized providers in the session policy. Denied or unknown permission blocks transcription even with credentials. No local Whisper/ASR. Without a transcript, local grading/audio/framing previews remain available.

[Codex skills](https://developers.openai.com/codex/skills/) · [Claude skills](https://code.claude.com/docs/en/skills) · [Claude marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
