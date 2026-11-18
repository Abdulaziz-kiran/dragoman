---
name: dragoman
description: Translate and review ASS/SRT subtitles between configured languages with OpenAI-compatible, agy, Codex or Claude Code backends, then deliver verified MKVs.
---

# dragoman

The Python CLI manages the pipeline. Start it, monitor its log, and report actual results. Keep full translations out of conversation context.

```bash
python3 dragoman.py "INPUT" --target es --backend openai --model MODEL --title "Title"
```

A directory processes episodes in order; `--episodes 1,3-5` selects episodes. A movie uses `--movie`. For subtitle-only input, use `--episode N`; no MKV is generated. `--source` defaults to en; `--target` is required. Use ISO 639-1 or 639-2 codes. Unknown languages require an English name. Use a three-letter code for exact track metadata; unknown two-letter codes use `und` metadata with a warning.

Run `python3 dragoman.py --setup` in a terminal for first-run setup. It detects the three CLIs and whether `OPENAI_API_KEY` is set, asks for backend/model and, for OpenAI-compatible providers, endpoint and key variable name. It stores no key values, preserves other config keys, and runs the same tiny check as `check_backend.py`. Examples are illustrative; select a model available to your account.

Backend and model must be explicitly configured, through flags or `config.json` beside the script (`--config PATH` overrides it). Missing settings offer setup on a terminal; unattended runs exit with a complete example. Missing tools, authentication failures, unknown models, empty key variables and unreachable endpoints give actionable messages. No real backend calls are needed for `python3 tests.py`. `check_backend.py` makes one small schema-constrained request against the configured backend when deliberately run. OpenAI-compatible endpoints use `base_url` and the environment variable named by `api_key_env`; an empty variable name supports local servers. Never display credentials.

## Workflow

1. Select the fullest source-language text track, excluding signs/songs-only and forced tracks. External source subtitles use `--source-subtitle FILE`. Raw OCR artifacts require cleaning or explicit `--accept-ocr`.
2. Check embedded target-language tracks. By default (`human_scoring: false`) only a streaming-platform track is delivered directly: a platform name in the track title, or NF/AMZN/DSNP/ATVP/HMAX in the filename when the track title only names the language. Files beside the video are ignored, and other embedded tracks stay in the MKV. With `human_scoring: true`, target-tagged files and tracks are aligned, checked for coverage and scored against the guide; one with score at least `human_threshold` (8.5), coverage at least 90% and timing match at least 70% is delivered directly, otherwise an aligned one becomes a second track. `--no-human-check` skips this step.
3. Read available episodes into `series.md`. `--series-source DIR` adds earlier context. Extract episode terms, directional register, voices, recurring expressions and ambiguities; reuse series memory. Translate scene-aware chunks in parallel (each line shows its on-screen duration), then independently review with trap lines. Each correction passes a meaning gate (`model_gate`, default the review model; `meaning_gate: false` disables it); a gate failure stops the episode so no unchecked correction is delivered. Dialogue too long to read at `target_cps` is extended by at most `max_extension_seconds`, never into the next line. Preserve ASS tags, styles and timing; drawings and karaoke stay untouched. Script filtering depends on the source/target pair.
4. Deliver ASS and optionally MKV. Verify duration, subtitle event count, presence of video, audio/video packet SHA-256 and subtitle interleaving; retain AV1 packet safeguards. Preserve existing audio default flags unless `--audio-lang CODE` is requested.

Guide: `guide.md`, plus `guides/<target-code>.md` if present, or one complete file named by `guide` in config. Config can override role models with `model_translate`, `model_review`, `model_gate`, `model_series`, `model_warnings`, and `model_level`. Review uses a separate call; a different model is optional.

## Reports and overlays

All three are on by default and can also be disabled with their config boolean set to false:

- `--no-level-report` disables the report (written in `report_language`, default English) assessing source-subtitle difficulty, CEFR, reading load and source-verified useful expressions, using configurable `learner_profile` (default: intermediate learner of the source language). `--level-only` assesses without translating.
- `--no-content-warnings` disables dialogue-based sensitive-scene overlays (reasons in `warning_language`, overlay text from `labels.warning`). These are estimates, not visual scene detection; unavailable scan ranges are reported and warned about.
- `--no-break-chapters` disables natural viewing breaks as MKV chapters; existing chapters survive. No video cutting.

## Output and recovery

`--output DIR` / `output_dir` defaults to `~/dragoman/`, containing `work/`, `library/`, `jobs/` and `watch/`. `work_dir`, `library_dir`, `jobs_dir` and `watch_dir` override single folders. Files use the target code tag. Every model call, failed attempts included, is appended to `work/<title>/receipts.jsonl`; `record.json` sums them per episode and keeps total minutes across reruns (`runs.json`). Existing outputs are archived rather than deleted. Resume with the same command: completed chunks are reused. `--redo` archives a previous job before restarting. Source-unit changes stop a resumed translation to prevent mismatched IDs. Reusing a title with another language pair requires a separate output root, so cached translations and memory cannot cross languages. `--detach` starts an independent process and prints its log path.

Embedded fonts are checked against actual subtitle characters. Fallbacks from repeatable `--fallback-font PATH` are tried before bundled Source Sans 3. Unsupported scripts produce warnings without an unsuitable font substitution. Decorative Latin folding is restricted to the original decorative-style path. No special RTL layout support is provided.

## Reporting

Report requested, delivered and failed counts exactly. Give reasons for failures; do not imply incomplete jobs succeeded. Report warnings about partial/unavailable content scans, missed reviewer traps, possibly incomplete reviews, missing episode context and source lines retained by provider safety filters. Per-job `record.json` and local `run-summary.txt` remain available with reports disabled. Failures are recorded locally too, with prior reports archived. Use these files, `corrections.json` and logs as evidence. If quality samples are requested, show 3-5 corrections and a small sample of final lines.

Do not delete source videos or job files. The tool does not download media, perform image-subtitle OCR, cut video or infer visual content. After code fixes, run `python3 tests.py`.

## Optional anonymous report

The program sends no telemetry. After a completed terminal run, it previews a report built only from version, OS, Python minor version, backend, language codes, counts, trap results, per-stage token totals, elapsed time, feature flags and fixed error categories. It excludes titles, files, paths, subtitle text, model names, endpoints, usernames and raw errors.

`Share this anonymous report with the developer? [y/N/never]` defaults to no. Only `y` prepares a prefilled public GitHub issue link under the user's own account; the user submits it. A second `Open in browser? [y/N]` is required before opening a browser. `never` persists `share_prompt: false`; `--no-share-prompt` suppresses it for one run. Non-terminal, detached and level-only runs never ask. Do not submit the issue on the user's behalf.
