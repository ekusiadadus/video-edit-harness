PROJECT ?= projects/talk.template.json
USE_CASE ?=
STYLE ?=
CASES ?= outdoor_overcast,outdoor_daylight
STYLES ?= natural,clean_editorial
.PHONY: doctor test inspect presets resolve preview compare plan render transcribe edit-plan edit-preview edit-export
doctor:
	uv run video-harness doctor
test:
	uv run python -m unittest discover -s tests -v
presets:
	uv run video-harness presets
resolve:
	uv run video-harness resolve "$(PROJECT)" $(if $(USE_CASE),--use-case "$(USE_CASE)") $(if $(STYLE),--style "$(STYLE)")
inspect:
	uv run video-harness inspect "$(PROJECT)"
preview:
	uv run video-harness preview "$(PROJECT)"
compare:
	uv run video-harness compare "$(PROJECT)" --use-cases "$(CASES)" --styles "$(STYLES)"
plan:
	uv run video-harness plan "$(PROJECT)"
render:
	uv run video-harness render "$(PROJECT)" $(if $(USE_CASE),--use-case "$(USE_CASE)") $(if $(STYLE),--style "$(STYLE)")

# Transcript/plan paths and output directories must be supplied explicitly.
transcribe:
	uv run --extra transcription-cloud video-harness transcribe "$(PROJECT)"
edit-plan:
	uv run video-harness edit-plan "$(PROJECT)" "$(TRANSCRIPT)" --output "$(OUTPUT)"
edit-preview:
	uv run video-harness edit-preview "$(PROJECT)" "$(PLAN)" --output "$(OUTPUT)"
edit-export:
	uv run video-harness edit-export "$(PROJECT)" "$(PLAN)" --output "$(OUTPUT)"

# Saved editorial workflow: SESSION is the existing session folder.
.PHONY: session-help session-status session-resume session-handoff session-evaluate
session-help:
	uv run video-harness session --help
session-status:
	uv run video-harness session status "$(SESSION)" --deep
session-resume:
	uv run video-harness session resume "$(SESSION)" --actor $(or $(ACTOR),codex)
session-handoff:
	uv run video-harness session handoff "$(SESSION)" --actor $(or $(ACTOR),codex)
session-evaluate:
	uv run video-harness session evaluate "$(SESSION)"
