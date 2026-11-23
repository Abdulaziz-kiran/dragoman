# dragoman

*Dragomans were the interpreters of the Ottoman court. They carried more than words: who was speaking to whom, and how. This tool tries to do the same for subtitles.*

Translate subtitles between any two languages with an LLM, review them in a separate pass, and get back a verified MKV. The video and audio are never re-encoded.

Works on anime, TV series and films. Takes the subtitle track inside an MKV, or an ASS/SRT file. Bring your own model: OpenAI-compatible APIs (OpenAI, Gemini, OpenRouter, Ollama, LM Studio…), Codex, Claude Code or Antigravity.

> **Status: early.** It started as one person's tool for their own viewing and is still being developed. Translation quality is not guaranteed. Bug reports and ideas are welcome in [issues](../../issues).

## What it does

- Reads the whole series and each episode first: characters, who addresses whom and how, terminology, tone.
- Translates in chunks, then runs an independent review pass. Deliberately broken "trap" lines test whether the reviewer is paying attention. Every correction passes a separate meaning check before it is applied; a correction that drops meaning is rejected.
- Shows the translator how long each line stays on screen. A dialogue line still too long to read at `target_cps` characters per second is extended by up to `max_extension_seconds`, never into the next line.
- Writes a receipt for every model call, failed ones included: stage, backend, model, duration, tokens and session id (`work/<title>/receipts.jsonl`, summed per episode in `record.json`).
- If the MKV already carries a target-language track from a streaming platform (Netflix, Amazon, Disney+, Crunchyroll… in the track title, or NF/AMZN/DSNP/ATVP/HMAX in the filename when the track title is neutral), delivers that track instead of translating. Other embedded tracks stay in the MKV as a second track. With `"human_scoring": true` the older path returns: subtitle files in the folder and embedded tracks are aligned and scored, and a good one is used.
- Keeps ASS tags, timing and styles.
- Remuxes without re-encoding and verifies with SHA-256 that video and audio packets did not change.
- Checks that embedded fonts actually contain the characters of your language, and falls back to Source Sans 3 (Latin, Greek, Cyrillic) or a font you supply.
- Adds, by default: a language-level report for language learners, on-screen warnings for scenes you may want to skip, and chapter marks at natural viewing breaks. Each can be turned off.
- Resumes where it stopped. Previous outputs are archived, not deleted.

## Requirements

- Python 3 with no extra packages (developed on 3.15)
- `ffmpeg` and `ffprobe`
- One model provider from the table below
- macOS is where it was developed and run. Linux is expected to work but is untested. Windows is unsupported.

| Backend | What you need | Tested with a real model |
|---|---|---|
| `agy` | Antigravity CLI, signed in | Yes, full run |
| `codex` | Codex CLI, signed in | Yes, full run |
| `openai` | Any OpenAI-compatible endpoint and, usually, an API key in an environment variable | Not yet, only against a local mock server |
| `claude-code` | Claude Code CLI, signed in | Not yet, only with mocked replies |

## Quick start

```bash
git clone https://github.com/Abdulaziz-kiran/dragoman.git
cd dragoman
python3 tests.py                    # no model calls, costs nothing
python3 dragoman.py --setup   # choose provider and model, runs one tiny test call
```

```bash
# Episodes in a folder, English to Spanish
python3 dragoman.py "<folder>" --title "<Show>" --target es --episodes 1-12

# A film
python3 dragoman.py "<video.mkv>" --title "<Film>" --target de --movie

# Subtitle file only, no MKV
python3 dragoman.py "<file.ass>" --title "<Show>" --target fr --episode 1

# Other source language
python3 dragoman.py "<folder>" --title "<Show>" --source ja --target en
```

Language codes are ISO 639-1 or 639-2. Any pair works; see [Languages](#languages) for the ones with built-in support. Run `python3 dragoman.py --help` for every option. Common ones: `--season N`, `--source-subtitle FILE`, `--audio-lang CODE`, `--redo`, `--no-human-check`, `--no-level-report`, `--no-content-warnings`, `--no-break-chapters`, `--no-mux`, `--detach`.

Output goes to `~/dragoman/` (`--output` changes it). Finished MKVs are in `watch/`, subtitles in `library/`, the full record of each job in `jobs/`.

Copy [config.example.json](config.example.json) to `config.json` to change models per role (`model_translate`, `model_review`, `model_gate`, `model_series`, `model_warnings`, `model_level`), chunk sizes and paths (`output_dir`, or `work_dir`, `library_dir`, `jobs_dir`, `watch_dir` separately). `source` and `target` set a default language pair (then `--target` can be left out), `guide_extra` adds your own guide file(s) after the bundled guide (for example who you translate for, or taste rules), `guide` points to a complete guide of your own instead of the bundled one, `audio_lang` sets a default audio language, `labels` changes on-screen and file labels (warning overlay, break chapters, human-translation track, level report file), `report_language` and `warning_language` set the language of the level report and of on-screen warning reasons (default: the target language), `context_notes` adds instructions to the episode-context step, `honorific_comments` (default off) unwraps honorifics that some fansub releases keep in ASS comments (`Rei{**-kun}`, `{*}Sis{*Akari-neechan}`) so the translator sees them, `translator_notes` (default off) lets the translator add at most four short on-screen notes per episode for wordplay that cannot survive translation, `max_quota_wait_seconds` (default 3600, `agy` only) caps how long one model call waits for a quota reset, and `--config PATH` keeps a personal configuration outside the repository. The translation style lives in [guide.md](guide.md), and `guides/<language>.md` adds rules for one target language. Text between `<!-- review-only -->` and `<!-- /review-only -->` in any guide file is shown only to the reviewer and the meaning gate.

## Languages

Every pair of ISO 639 languages can be used. These target languages also have built-in support: a guide addendum with that language's conventions (`guides/<code>.md`: formal and informal address, titles, punctuation, typical mistakes, reviewer checks) and on-screen text in that language (`locales/<code>.json`: warning overlay, break chapters, subtitle track title, level report).

| Code | Language | | Code | Language |
|---|---|---|---|---|
| `en` | English | | `ja` | Japanese |
| `tr` | Turkish | | `zh` | Chinese (Simplified by default) |
| `ru` | Russian | | `ko` | Korean |
| `es` | Spanish | | `ar` | Arabic (Modern Standard) |
| `de` | German | | `pt` | Portuguese (Brazilian by default) |
| `fr` | French | | | |

`python3 dragoman.py --languages` prints the list. The Turkish and English addenda were written and reviewed by hand; the others were drafted with an LLM and checked for structure, so corrections from native speakers are very welcome. Other target languages use the general guide and English on-screen text. To add one, copy `locales/en.json` and write `guides/<code>.md`; `python3 tests.py` checks that keys and placeholders match.

[SKILL.md](SKILL.md) tells coding agents how to run the tool.

## Privacy

The program sends subtitle text to the provider you choose, and to nothing else. Job records stay on your computer; they contain file paths and titles.

After a run, it can ask whether you want to share an anonymous report. It is off unless you answer yes. You see the exact text first. It contains only the tool version, OS, provider type, language pair, counts, durations and error categories, never titles, file names, paths or subtitle text. Saying yes only produces a pre-filled GitHub issue link, posted publicly under your own account when you submit it yourself. `--no-share-prompt` removes the question.

## Known limitations

- Image-based subtitles (PGS) are not read. There is no OCR.
- It translates from a subtitle, not from audio, so errors in the source subtitle carry over.
- Right-to-left scripts have no special handling and are untested; the Arabic pack is text only.
- For scripts outside Latin, Greek and Cyrillic you need to pass `--fallback-font` if the embedded fonts lack the characters.
- On very long series the series guide gets compressed, and a new season only extends the memory.
- The meaning check of review corrections is itself a model call and can be wrong.
- Tests do not call a model; model behaviour is only visible in real runs. Real runs so far are few.
- Internal Python identifiers are in Turkish, for now.

## Copyright

This repository holds code and instructions only, no video or subtitle files. You are responsible for the rights to whatever you process.

The code is under the [MIT License](LICENSE). Source Sans 3 in `fonts/` is under the [SIL Open Font License](fonts/OFL.txt).

## Türkçe

Altyazıları yapay zekâ ile istediğiniz dile çevirir (Türkçe altyazı çeviri dahil), ayrı bir adımda inceler ve videoyu yeniden kodlamadan MKV olarak paketler. Anime, dizi ve film için. Kurulum için yukarıdaki adımlar geçerli, Türkçe için örnek: `--target tr`. Türkçe yerleşik desteklidir: Türkçeye özel çeviri kuralları [guides/tr.md](guides/tr.md), ekrandaki uyarı, mola ve rapor metni [locales/tr.json](locales/tr.json) dosyasındadır. Kendi tercihlerinizi (izleyici kitlesi, üslup) `guide_extra` ile ayrı bir dosyada ekleyebilirsiniz.
