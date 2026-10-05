# Record a real editing session

[English](SCREEN_RECORDING.md) | [日本語](SCREEN_RECORDING.ja.md)

Screen Studio can record a Codex editing session while the harness processes an actual MP4 or MOV. Screen Studio records the screen; the harness writes the edits and deliverables. Keep the unedited file and session history.

## Prepare

Use a dedicated Codex window and one project. For a public demo, use footage you can publish. Close unrelated conversations, terminals, email, browser tabs, and notifications. Keep credentials in environment variables; do not display `.env`, shell history, or provider responses containing credentials. A recording is a separate public artifact: authorization to edit footage does not imply authorization to publish it.

Configure the project and editing brief using the [README](../README.md). Confirm the source color space, audio tracks, and preview range. Authorize the specific cloud transcription upload before running `session transcribe`. OpenAI is tried before Azure; there is no local Whisper model.

## Capture

1. In Screen Studio, choose **Window** and select the dedicated Codex window. Use **Area** if you need to hide a sidebar. Do not record the whole display unnecessarily.
2. Leave the microphone and camera off unless needed. Enable system audio only when it is needed and you can isolate the playback you intend to capture. Keep unrelated audio off.
3. Start recording, then ask Codex to use the `video-editing` skill with your project and brief. Capture the real transcript inspection, exact-word edit plan, selection, and `session render` command and result. Do not type a pretend agent transcript.
4. Stop the first capture before switching applications. Record the browser preview or Final Cut Pro window as a separate capture when appropriate. Play the source and edit so viewers can hear the difference. Timestamped feedback and a second render make a useful final segment.
5. Export the recordings. Keep the raw recording, trim waiting time in a derived version, and clearly label any cuts, time compression, narration, and AI-generated voice. Check video and audio synchronization and listen across edit boundaries.
6. Review every frame for private information before publishing. Add captions. For README, publish the MP4 plus a small clickable GIF/poster and describe exactly what is demonstrated.

A useful 45–90-second sequence is: editing request → transcript and plan → real render → before/after playback → feedback and revision → generated FCPXML. Show actual FCP import and playback only if they were performed; an exported XML is not GUI proof.

## This environment's recording boundary

Screen Studio is installed and its recording controls were inspected. Native computer automation cannot access Codex or Ghostty here. Selecting the Codex capture window and starting/stopping that recording must therefore be done manually. This is an automation access restriction, not evidence that Screen Studio cannot record Codex. No Codex screen recording is bundled with the current README walkthrough, which uses an actual synthetic source and harness render with explanatory cards.
