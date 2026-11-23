#!/usr/bin/env python3
"""Translate, review, archive and verify multilingual subtitle deliveries using structured LLM replies."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import sys
import copy
import unicodedata
import urllib.request
import urllib.error
import email.utils
import threading
import time
from pathlib import Path

SURUM = "1.4.0"
KOK = Path(__file__).resolve().parent
EV = Path.home()
VARSAYILAN = {
    "output_dir": "~/dragoman",
    "backend": None, "model": None,
    "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY",
    "translate_chunk": 100, "review_chunk": 60, "parallel": 3,
    "satir_sinir": 42, "reading_speed_threshold": 20,
    "content_warnings": True, "human_check": True, "human_threshold": 8.5,
    "break_chapters": True, "level_report": True, "learner_profile": "intermediate learner of the source language",
    "timeout_seconds": 900, "fallback_fonts": [], "share_prompt": True,
    # agy backend: longest total wait for one quota reset per model call; a later reset stops the episode instead.
    "max_quota_wait_seconds": 3600,
    # Reviewer corrections pass a separate meaning check before they are applied.
    "meaning_gate": True,
    # Readable speed in characters per second: translators see each line's duration; too-fast dialogue is extended.
    "target_cps": 17, "max_extension_seconds": 1.5,
    # Off by default: only a streaming-platform target track (title or neutral title + filename tag) skips translation.
    "human_scoring": False,
    "audio_lang": None, "guide": None, "guide_extra": [],
    # Default language pair when --source/--target are omitted on the command line.
    "source": None, "target": None,
    # None: the target language (overlay reasons and level reports are read by target-language viewers).
    "labels": {}, "report_language": None, "warning_language": None,
    "context_notes": "",  # extra instructions appended to the episode-context task (for example memory-label rules)
    # Fansub releases that keep honorifics in ASS comments (Rei{**-kun}, {*}Sis{*Akari-neechan}): show them to the model.
    "honorific_comments": False,
    # At most 4 short on-screen notes per episode for wordplay that cannot survive translation.
    "translator_notes": False,
}
# Viewer-facing labels; config "labels" overrides single keys (for example in the target language).
# Built-in target-language packs live in locales/<code>.json; config "labels" still wins over them.
LABELS_DEFAULT = {"warning": "⚠ Possible sensitive scene ({reasons}) → {until}", "break": "⏸ Break point {n}", "start": "Start",
                  "human_track": "{language} (human translation)", "level_file": "Language level",
                  "sensitive_scene": "sensitive scene", "scan_unavailable": "scan unavailable (content safety)",
                  "scan_unavailable_episode": "content scan unavailable for this episode"}
LABELS = dict(LABELS_DEFAULT)
# Level report text (level.md and the season table), translated by locale packs.
REPORT_DEFAULT = {
    "title": "Language level — {episode}", "confidence": "confidence",
    "reading_load": "Reading load: {wpm} words/minute; median {median} columns/second, fastest 10% {p90}+; fast lines {fast}%. {unique} unique words.",
    "difficulties": "Difficulties", "expressions": "Useful expressions",
    "expression_columns": ["Time", "Expression", "Kind", "Meaning", "Usefulness"],
    "evidence": "Level evidence", "note": "Approximate content assessment; not a personal test or CEFR certificate.",
    "profile": "Profile", "season_title": "{title} — Source subtitle reading assessment",
    "season_columns": ["Episode", "CEFR", "Suitability", "Words/minute", "Fast lines (columns/second, top 10%)", "Summary"],
    "season_note": "Approximate content assessment; see level.md in each episode job archive.",
    "suitability": {"comfortable": "comfortable viewing", "productive_challenge": "challenging but useful",
                    "substantial_support": "substantial support recommended"},
    "confidence_levels": {"low": "low", "medium": "medium", "high": "high"},
}
REPORT = dict(REPORT_DEFAULT)
ROLES = ("translate", "review", "series", "warnings", "level", "gate")

# Common ISO 639-1 codes, ISO 639-2/T, optional ISO 639-2/B, and English names.
LANGUAGES = {}
for _row in (
    "en eng English;tr tur Turkish;de deu/ger German;fr fra/fre French;zh zho/chi Chinese;"
    "ja jpn Japanese;ko kor Korean;es spa Spanish;pt por Portuguese;it ita Italian;"
    "ru rus Russian;ar ara Arabic;hi hin Hindi;bn ben Bengali;ur urd Urdu;fa fas/per Persian;"
    "nl nld/dut Dutch;el ell/gre Greek;cs ces/cze Czech;sk slk/slo Slovak;ro ron/rum Romanian;"
    "hu hun Hungarian;pl pol Polish;uk ukr Ukrainian;be bel Belarusian;bg bul Bulgarian;"
    "sr srp Serbian;hr hrv Croatian;bs bos Bosnian;sl slv Slovenian;mk mkd/mac Macedonian;"
    "sq sqi/alb Albanian;hy hye/arm Armenian;ka kat/geo Georgian;az aze Azerbaijani;"
    "kk kaz Kazakh;ky kir Kyrgyz;uz uzb Uzbek;tk tuk Turkmen;mn mon Mongolian;"
    "sv swe Swedish;da dan Danish;no nor Norwegian;fi fin Finnish;is isl/ice Icelandic;"
    "et est Estonian;lv lav Latvian;lt lit Lithuanian;ga gle Irish;cy cym/wel Welsh;"
    "he heb Hebrew;yi yid Yiddish;th tha Thai;vi vie Vietnamese;id ind Indonesian;"
    "ms msa/may Malay;tl tgl Tagalog;ta tam Tamil;te tel Telugu;ml mal Malayalam;"
    "kn kan Kannada;mr mar Marathi;gu guj Gujarati;pa pan Punjabi;ne nep Nepali;"
    "si sin Sinhala;my mya/bur Burmese;km khm Khmer;lo lao Lao;sw swa Swahili;"
    "af afr Afrikaans;zu zul Zulu;am amh Amharic;so som Somali;mt mlt Maltese;"
    "eu eus/baq Basque;ca cat Catalan;gl glg Galician;la lat Latin;bo bod/tib Tibetan"
).split(";"):
    _two, _three, _name = _row.split(" ", 2)
    _codes = (_two, *_three.split("/"))
    for _code in _codes:
        LANGUAGES[_code] = {"code": _two, "iso3": _codes[1], "name": _name, "codes": _codes}


def locale(code: str) -> dict:
    """Built-in pack for a target language (labels, report text, native name); empty if none ships."""
    path = KOK / "locales" / f"{code}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def builtin_languages() -> list[str]:
    return sorted(p.stem for p in (KOK / "locales").glob("*.json"))


def language(code: str, name: str | None = None) -> dict:
    code = code.lower().strip()
    if code in LANGUAGES:
        return dict(LANGUAGES[code], name=name or LANGUAGES[code]["name"])
    if not re.fullmatch(r"[a-z]{2,3}", code) or not name:
        raise ValueError(f"Unknown language code {code!r}; provide --source-name or --target-name with an English name")
    return {"code": code, "iso3": code if len(code) == 3 else "und", "name": name, "codes": (code,)}


SOURCE = language("en")
TARGET = None  # Initialized by the required --target before any work.
BACKEND_CONFIG = {}
FALLBACK_PATHS = []


def cjk_allowed() -> bool:
    return SOURCE["code"] in ("ja", "zh", "ko") or TARGET["code"] in ("ja", "zh", "ko")


def columns(text: str) -> int:
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in ISARET.sub("", text))


def latin_target() -> bool:
    return TARGET["code"] in set("en tr de fr es pt it nl cs sk ro hu pl hr bs sl sq az uz tk sv da no fi is et lv lt ga cy id ms tl sw af mt eu ca gl la vi".split())


def fold_latin(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f\uac00-\ud7af]")
ETIKET = re.compile(r"(\{[^}]*\})")
CIZIM = re.compile(r"\\p[1-9]")
KARAOKE = re.compile(r"\\[kK][fo]?\d")
ATLA_STIL = re.compile(r"romaji|kanji|karaoke|japanese|\bjp\b|\bjpn\b", re.I)
SARKI_STIL = re.compile(r"\bop\b|\bed\b|opening|ending|insert|song|lyric|^op|^ed", re.I)
TABELA_STIL = re.compile(r"(?<![a-z])(sign|title|logo|typeset|note|screen|text|card|caption|eyecatch|preview)", re.I)
DIYALOG_STIL = re.compile(r"default|main|dialog|italic|top|alt|flash|thought|narrat|overlap|\bspeech", re.I)
ISARET = re.compile(r"⟦\d+⟧")

_yaz_kilidi = threading.Lock()


def log(mesaj: str) -> None:
    with _yaz_kilidi:
        print(f"[{dt.datetime.now():%H:%M:%S}] {mesaj}", flush=True)


def guide_extras(a: dict) -> list[str]:
    """"guide_extra" as a list of non-empty paths (a single string is accepted)."""
    ekler = [a["guide_extra"]] if isinstance(a.get("guide_extra"), str) else list(a.get("guide_extra") or [])
    return [e.strip() for e in ekler if isinstance(e, str) and e.strip()]


def ayarlar(config: str | None = None) -> dict:
    a = dict(VARSAYILAN)
    dosya = Path(config).expanduser() if config else KOK / "config.json"
    if dosya.exists():
        a.update(json.loads(dosya.read_text(encoding="utf-8")))
        if a.get("guide") and not Path(a["guide"]).expanduser().is_absolute():  # relative to the config file
            a["guide"] = str(dosya.resolve().parent / a["guide"])
        a["guide_extra"] = [str(e if Path(e).expanduser().is_absolute() else dosya.resolve().parent / e) for e in guide_extras(a)]
    root = Path(a["output_dir"]).expanduser()
    # Explicit folder settings override the output_dir layout (watch_dir sets the watch folder).
    for k, folder, key in (("work_dir", "work", "work_dir"), ("library_dir", "library", "library_dir"),
                           ("jobs_dir", "jobs", "jobs_dir"), ("watch", "watch", "watch_dir")):
        a[k] = Path(a[key]).expanduser() if a.get(key) else root / folder
    return a


def configure(a: dict, source: str, target: str, source_name=None, target_name=None) -> None:
    global SOURCE, TARGET, BACKEND_CONFIG, FALLBACK_PATHS, LABELS, REPORT
    SOURCE, TARGET = language(source, source_name), language(target, target_name)
    pack = locale(TARGET["code"])
    # Viewer-facing name (MKV track title, human track label): explicit --target-name, else the pack's native name.
    TARGET["display"] = target_name or pack.get("native_name") or TARGET["name"]
    english = LANGUAGES.get(TARGET["code"], {}).get("name") or TARGET["name"]
    # Filled-in defaults are remembered so that reconfiguring the same dict for another target recomputes them.
    derived = set(a.get("_derived_languages") or ())
    for key in ("report_language", "warning_language"):
        if not a.get(key) or key in derived:
            a[key] = english
            derived.add(key)
    a["_derived_languages"] = sorted(derived)
    if TARGET["iso3"] == "und":
        log("WARNING: unknown two-letter target has no ISO 639-2 mapping; track metadata will use und. Supply a three-letter code for an exact tag.")
    if a.get("backend") not in ("openai", "agy", "codex", "claude-code") or not a.get("model"):
        raise ValueError("Backend and model are required; run --setup or use: python3 dragoman.py INPUT --target es --backend openai --model gpt-4.1-mini")
    for role in ROLES:
        a["model_" + role] = a.get("model_" + role) or (a.get("model_review") if role == "gate" else None) or a["model"]
    BACKEND_CONFIG = dict(a)
    LABELS = {**LABELS_DEFAULT, **(pack.get("labels") or {}), **(a.get("labels") or {})}
    REPORT = {**REPORT_DEFAULT, **(pack.get("report") or {})}
    for key in ("suitability", "confidence_levels"):
        REPORT[key] = {**REPORT_DEFAULT[key], **((pack.get("report") or {}).get(key) or {})}
    FALLBACK_PATHS = [Path(f).expanduser() for f in a.get("fallback_fonts", [])]


def jyaz(yol: Path, veri) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(yol.suffix + ".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(yol)


def joku(yol: Path, varsayilan=None):
    return json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else varsayilan


def sha(yol_ya_da_metin) -> str:
    h = hashlib.sha256()
    if isinstance(yol_ya_da_metin, Path):
        h.update(yol_ya_da_metin.read_bytes())
    else:
        h.update(yol_ya_da_metin.encode("utf-8"))
    return h.hexdigest()[:12]


class ModelHatasi(Exception):
    pass


class BolumHatasi(Exception):
    pass


class GuvenlikEngeli(ModelHatasi):
    """Provider content safety block; split the request instead of retrying blindly."""


GUVENLIK = ("safety filter", "content safety", "prohibited use", "sensitive words", "response was blocked", "safety_block",
            "finish_reason: safety", "finishreason.safety", "recitation", "content_filter", "refusal", "permission_denied: safety")


_KOTA_KILIDI = threading.Lock()
_KOTA_BITIS: dict[str, float] = {}  # quota group -> time.time() until which a found reset already covers every thread


def _kota_bekle(model: str, metin_ipucu: bool = False, beklenen: float = 0.0) -> bool:
    """Wait for an exhausted agy quota group to reset. Parallel threads share one /usage reading; the total wait of one
    call (`beklenen` already waited) is capped by max_quota_wait_seconds, beyond which the call fails with a clear error."""
    model = model.lower()
    grup_adi = "Gemini 4 Argon" if "argon" in model else ("Gemini Models" if "gemini" in model else "Claude and GPT models")
    sinir = BACKEND_CONFIG.get("max_quota_wait_seconds")
    sinir = 3600.0 if sinir is None else float(sinir)
    mesaj = None
    with _KOTA_KILIDI:
        bekle = _KOTA_BITIS.get(grup_adi, 0) - time.time()
        if bekle <= 0:
            bekle = None
            try:
                cikti = subprocess.run(["agy", "-p", "/usage", "--output-format", "json", "--print-timeout", "60s"],
                                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir())
                veri = json.loads(cikti.stdout)
                en_gec = None
                for grup in veri["command"]["data"]["groups"]:
                    if grup["name"] != grup_adi:
                        continue
                    for kova in grup["buckets"]:
                        if kova["remaining_fraction"] < 0.02:
                            t = dt.datetime.fromisoformat(kova["reset_time"].replace("Z", "+00:00"))
                            en_gec = t if en_gec is None or t > en_gec else en_gec
                if en_gec:
                    bekle = max(60, (en_gec - dt.datetime.now(dt.timezone.utc)).total_seconds() + 90)
                    mesaj = f"Quota exhausted ({grup_adi}); {en_gec.astimezone():%d.%m %H:%M} waiting until reset ({bekle/60:.0f} minutes)."
            except Exception as e:
                if metin_ipucu:
                    bekle = 900
                    mesaj = f"Could not read quota table ({e}); error indicates quota exhaustion; waiting 15 minutes."
            if bekle is not None:
                _KOTA_BITIS[grup_adi] = time.time() + bekle
        else:
            mesaj = f"Quota exhausted ({grup_adi}); another request is already waiting for the reset ({bekle/60:.0f} minutes)."
    if bekle is None:
        return False
    if beklenen + bekle > sinir:
        raise ModelHatasi(f"Quota exhausted ({grup_adi}); the reset is {bekle/60:.0f} minutes away, beyond max_quota_wait_seconds "
                          f"({sinir:.0f}); rerun the same command after the reset")
    log(mesaj)
    time.sleep(bekle)
    return True


HATA_DOSYASI: Path | None = None


def _hata_kaydi(model: str, hata: str) -> None:
    if HATA_DOSYASI:
        with _yaz_kilidi, open(HATA_DOSYASI, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": dt.datetime.now().isoformat(timespec="seconds"), "model": model,
                                "error": _redact(hata)[:500]}, ensure_ascii=False) + "\n")


RECEIPT: list = [None, ""]  # [title receipts.jsonl path, episode label]; set before each episode and the series step
RUN_FILE: list = [None]
_CALL = threading.local()  # per-thread session id reported by the last transport call


def receipt_write(model: str, stage: str | None, attempt: int, t0: float, status: str, usage: dict | None, error: str) -> None:
    """One line per model call, successful or failed: when, which stage, backend, model, duration, tokens, session id."""
    if not RECEIPT[0]:
        return
    line = {"time": dt.datetime.fromtimestamp(t0).isoformat(timespec="seconds"), "seconds": round(time.time() - t0, 1),
            "version": SURUM, "episode": RECEIPT[1], "stage": stage or "other", "backend": BACKEND_CONFIG.get("backend"),
            "model": model, "attempt": attempt + 1, "status": status, "session": getattr(_CALL, "session", None),
            "usage": usage or {}, "error": _redact(error)[:200] if error else None}
    try:  # a receipt or timer write failure must not discard a paid reply
        if RUN_FILE[0] and RUN_FILE[0].parent.name == RECEIPT[1]:
            run_minutes(RUN_FILE[0].parent)  # an interrupted run counts until its last model call
        with _yaz_kilidi, open(RECEIPT[0], "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as e:
        log(f"Could not write receipt: {e}")


def kullanim_sayilari(usage) -> dict[str, int]:
    """Token counts of one call under the internal names; OpenAI names (prompt/completion, reasoning details) and
    missing or None values are normalized."""
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, dict) else {}
    def sayi(*values):
        for v in values:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
        return 0
    return {"input_tokens": sayi(usage.get("input_tokens"), usage.get("prompt_tokens")),
            "output_tokens": sayi(usage.get("output_tokens"), usage.get("completion_tokens")),
            "thinking_tokens": sayi(usage.get("thinking_tokens"), details.get("reasoning_tokens"))}


def receipt_summary(path: Path, label: str, since: float = 0) -> dict:
    """All calls of one episode (failed attempts and warning, break and level calls included).
    `since`: first run of this job directory; calls of a job archived by --redo are not counted."""
    lines = [json.loads(x) for x in (path.read_text(encoding="utf-8").splitlines() if path.exists() else []) if x.strip()]
    lines = [x for x in lines if x.get("episode") == label
             and dt.datetime.fromisoformat(x.get("time", "1970-01-01T00:00:00")).timestamp() >= int(since) - 1]
    total = {k: sum(kullanim_sayilari(x.get("usage"))[k] for x in lines) for k in ("input_tokens", "output_tokens", "thinking_tokens")}
    return {"calls": len(lines), "failed": sum(x.get("status") != "SUCCESS" for x in lines), **total,
            "minutes": round(sum(x.get("seconds", 0) for x in lines) / 60, 1), "file": str(path)}


def run_start(is_dir: Path) -> float:
    """Each run of an episode is appended to runs.json, so reruns do not reset the elapsed minutes."""
    path = is_dir / "runs.json"
    now = time.time()
    with _yaz_kilidi:
        jyaz(path, joku(path, []) + [{"start": now, "end": now, "version": SURUM}])
    RUN_FILE[0] = path
    RECEIPT[:] = [is_dir.parent / "receipts.jsonl", is_dir.name]
    return now


def run_minutes(is_dir: Path) -> float:
    path = is_dir / "runs.json"
    with _yaz_kilidi:
        runs = joku(path, [])
        if runs:
            runs[-1]["end"] = time.time()
            jyaz(path, runs)
    return round(sum(r["end"] - r["start"] for r in runs) / 60, 1)


def _sonuc_bul(cikti: str):
    sonuc = None
    for satir in (cikti or "").splitlines():
        try:  # parse as JSON so separator spacing or key order cannot hide the result
            d = json.loads(satir)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("event") == "result" and isinstance(d.get("result"), dict):
            sonuc = d["result"]
    return sonuc


YAPILANDIRMA = ("unknown model", "invalid model", "model not found", "not a valid model", "unsupported model", "no such model", "model_not_found", "invalid_api_key", "does not exist")
BEKLEMELER = [30, 120, 900, 1800, 3600]


def _strict_schema(schema: dict) -> dict:
    result = copy.deepcopy(schema)
    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(result)
    return result


def _validate(value, schema: dict, path="reply") -> None:
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool}
    if kind in types and (not isinstance(value, types[kind]) or (kind in ("number", "integer") and isinstance(value, bool))):
        raise ModelHatasi(f"Invalid {path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ModelHatasi(f"Invalid enum at {path}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ModelHatasi(f"Missing required key at {path}.{key}")
        for key, item in value.items():
            if key not in schema.get("properties", {}) and schema.get("additionalProperties") is False:
                raise ModelHatasi(f"Unexpected key at {path}.{key}")
            rule = schema.get("properties", {}).get(key, schema.get("additionalProperties", {}))
            if isinstance(rule, dict):
                _validate(item, rule, path + "." + key)
    if isinstance(value, list):
        for item in value:
            _validate(item, schema.get("items", {}), path + "[]")


def _redact(text: str) -> str:
    env = BACKEND_CONFIG.get("api_key_env", "OPENAI_API_KEY")
    key = os.environ.get(env, "") if env else ""
    return str(text).replace(key, "<REDACTED>") if key else str(text)


class _RetryAfter(Exception):
    def __init__(self, seconds, message):
        self.seconds, self.message = seconds, message


def _openai(model, istem, sema, timeout):
    url = BACKEND_CONFIG.get("base_url", "https://api.openai.com/v1").rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    env = BACKEND_CONFIG.get("api_key_env", "OPENAI_API_KEY")
    key = os.environ.get(env, "") if env else ""
    headers = {"Content-Type": "application/json"}
    if env and not key:
        raise ModelHatasi("API key environment variable is empty")
    if key:
        headers["Authorization"] = "Bearer " + key
    body = {"model": model, "messages": [{"role": "user", "content": istem}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "subtitle_reply", "schema": sema}}}
    for fallback in (False, True):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.load(response)
            choice = data["choices"][0]
            if choice.get("finish_reason") == "content_filter" or choice.get("message", {}).get("refusal"):
                raise GuvenlikEngeli("content safety refusal")
            return json.loads(choice["message"]["content"]), data.get("usage", {})
        except urllib.error.HTTPError as error:
            message = _redact(error.read().decode("utf-8", "replace"))
            if error.code == 429:
                retry = error.headers.get("Retry-After", "30")
                try:
                    seconds = float(retry)
                except ValueError:
                    try:
                        seconds = (email.utils.parsedate_to_datetime(retry) - dt.datetime.now(dt.timezone.utc)).total_seconds()
                    except (TypeError, ValueError):
                        seconds = 30
                raise _RetryAfter(max(0, seconds), message)
            if error.code == 400 and not fallback and not any(x in message.lower() for x in (*GUVENLIK, *YAPILANDIRMA)):
                body["response_format"] = {"type": "json_object"}
                body["messages"][0]["content"] = istem + "\nReturn JSON satisfying this schema:\n" + json.dumps(sema)
                continue
            raise ModelHatasi(f"HTTP {error.code}: {message}")


def _agy(model, istem, sema, timeout):
    mesaj = json.dumps({"event": "user", "message": {"content": istem}}, ensure_ascii=False)
    p = subprocess.Popen(
        ["agy", "--input-format", "stream-json", "--output-format", "stream-json", "--model", model,
         "--json-schema", json.dumps(sema), "--disable-slash-commands", "--sandbox",
         "--print-timeout", f"{timeout}s", "-p="], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=tempfile.gettempdir(), start_new_session=True)
    cikti, hata = "", ""
    try:
        cikti, hata = p.communicate(mesaj + "\n", timeout=timeout + 120)
    except subprocess.TimeoutExpired:
        hata = "timeout"
    finally:
        try:
            os.killpg(p.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
    # Some CLIs emit a paid result but fail to exit; recover that result after termination.
    if not cikti:
        try:
            cikti, hata2 = p.communicate(timeout=10)
            hata = hata or hata2
        except (subprocess.TimeoutExpired, ValueError):
            pass
    _CALL.session = (re.findall(r'"(?:conversation_id|session_id)"\s*:\s*"([^"]+)"', cikti or "") or [None])[-1]
    sonuc = _sonuc_bul(cikti)
    if sonuc and sonuc.get("status") == "SUCCESS" and isinstance(sonuc.get("structured_output"), dict):
        return sonuc["structured_output"], sonuc.get("usage", {})
    _CALL.usage = (sonuc or {}).get("usage")  # a failed attempt may still have spent tokens
    raise ModelHatasi((sonuc or {}).get("error") or (hata if hata and hata.strip() else "") or (
        f"unrecognized reply: no result event or structured output ({len(cikti)} bytes)" if (cikti or "").strip() else "empty reply"))


def _cli(backend, model, istem, sema, timeout):
    with tempfile.TemporaryDirectory() as tmp:
        if backend == "codex":
            schema_file, output_file = Path(tmp) / "schema.json", Path(tmp) / "reply.json"
            schema_file.write_text(json.dumps(_strict_schema(sema)), encoding="utf-8")
            name, colon, effort = model.rpartition(":")
            if not colon:
                name = model
            cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral", "-m", name,
                   "--output-schema", str(schema_file), "-o", str(output_file)]
            if colon:
                cmd += ["-c", f"model_reasoning_effort={effort}"]
            result = subprocess.run(cmd + ["-"], input=istem, capture_output=True, text=True, cwd=tmp, timeout=timeout)
            if result.returncode:
                raise ModelHatasi(result.stderr or result.stdout or "codex failed")
            return json.loads(output_file.read_text(encoding="utf-8")), {}
        cmd = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(sema), "--model", model, "--tools", ""]
        result = subprocess.run(cmd, input=istem, capture_output=True, text=True, cwd=tmp, timeout=timeout)
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict):
            _CALL.session, _CALL.usage = data.get("session_id"), data.get("usage")
        if result.returncode or not isinstance(data, dict):
            raise ModelHatasi(result.stderr or result.stdout or "claude-code failed")
        if data.get("is_error") or "structured_output" not in data:
            raise ModelHatasi(str(data.get("result", "claude-code failed")))
        return data.get("structured_output"), data.get("usage", {})


def model_cagir(model: str, istem: str, sema: dict, zaman_asimi: int, deneme: int = len(BEKLEMELER) + 1) -> tuple[dict, dict]:
    backend = BACKEND_CONFIG.get("backend")
    if not backend or not model:
        raise ModelHatasi("Backend and model are required; for example --backend openai --model my-model")
    stage = stage_of(sema)
    # Dynamic translation IDs must be explicit properties for strict-schema backends.
    if backend == "codex" and sema in (CEVIRI_SEMA, CEVIRI_NOT_SEMA):
        ids = re.findall(r"^([^ \n]+) \[[^\n]*\]:", istem.split("TRANSLATE:\n")[-1].split("\n\nNext lines")[0], re.M)
        sema = copy.deepcopy(sema)
        sema["properties"]["translations"] = {"type": "object", "properties": {i: {"type": "string"} for i in ids}, "required": ids}
    son_hata, i, kota_beklemesi, kota_suresi = "", 0, 0, 0.0
    while i < deneme:
        retry_after = None
        t0 = time.time()
        _CALL.session = _CALL.usage = None
        try:
            if backend == "openai":
                reply, usage = _openai(model, istem, sema, zaman_asimi)
            elif backend == "agy":
                reply, usage = _agy(model, istem, sema, zaman_asimi)
            elif backend in ("codex", "claude-code"):
                reply, usage = _cli(backend, model, istem, sema, zaman_asimi)
            else:
                raise ModelHatasi("Unknown backend")
            _CALL.usage = usage
            if not isinstance(reply, dict):
                raise ModelHatasi("Reply must be a JSON object")
            _validate(reply, sema)
            record_usage(stage, usage)
            receipt_write(model, stage, i, t0, "SUCCESS", usage, "")
            return reply, usage
        except _RetryAfter as error:
            retry_after, son_hata = error.seconds, error.message
            receipt_write(model, stage, i, t0, "ERROR", getattr(_CALL, "usage", None), son_hata)
        except (ModelHatasi, OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError) as error:
            fix = provider_fix(error, BACKEND_CONFIG)
            receipt_write(model, stage, i, t0, "ERROR", getattr(_CALL, "usage", None), fix or str(error))
            if fix:
                with _yaz_kilidi:
                    RUN_STATS["errors"].add(error_category(error))
                _hata_kaydi(model, fix)
                raise ModelHatasi(fix) from None
            son_hata = _redact(str(error))
        son_hata = _redact(son_hata)
        with _yaz_kilidi:
            RUN_STATS["errors"].add(error_category(son_hata))
        _hata_kaydi(model, son_hata)
        metin = son_hata.lower()
        if any(g in metin for g in GUVENLIK):
            if i == 0 and i + 1 < deneme and "prohibited" not in metin and "sensitive words" not in metin:
                i += 1
                continue
            raise GuvenlikEngeli(son_hata)
        if any(y in metin for y in YAPILANDIRMA) or "unknown backend" in metin or "http 401" in metin or "http 403" in metin:
            raise ModelHatasi(f"Configuration error, not retried: {son_hata}")
        kota_t0 = time.monotonic()
        if backend == "agy" and deneme > 1 and kota_beklemesi < 12 and _kota_bekle(model, metin_ipucu=any(
                x in metin for x in ("quota", "exhaust", "429", "rate limit", "resource_exhausted", "limit reached", "usage limit")),
                beklenen=kota_suresi):
            kota_beklemesi += 1
            kota_suresi += time.monotonic() - kota_t0
            continue
        if i + 1 >= deneme:
            break
        bekle = retry_after if retry_after is not None else BEKLEMELER[min(i, len(BEKLEMELER) - 1)]
        log(f"Model error ({model}, attempt {i+1}/{deneme}): {son_hata[:200]}; retrying in {bekle:g} seconds")
        time.sleep(bekle)
        i += 1
    raise ModelHatasi(son_hata)


class Ass:
    def __init__(self, metin: str):
        self.satirlar = metin.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.bicim = None
        self.olaylar: list[dict] = []
        bolum = ""
        for i, s in enumerate(self.satirlar):
            st = s.strip()
            if st.startswith("[") and st.endswith("]"):
                bolum = st.lower()
            elif bolum == "[events]" and st.lower().startswith("format:"):
                self.bicim = [x.strip().lower() for x in st.split(":", 1)[1].split(",")]
            elif bolum == "[events]" and st.startswith("Dialogue:") and self.bicim:
                govde = s.split(":", 1)[1].lstrip()
                alanlar = govde.split(",", len(self.bicim) - 1)
                self.olaylar.append({"index": i, "fields": alanlar})
        if not self.bicim:
            raise ValueError("ASS file has no [Events] Format line")
        self.i_metin = self.bicim.index("text")
        self.i_stil = self.bicim.index("style")
        self.i_bas = self.bicim.index("start")
        self.i_son = self.bicim.index("end")

    def metin(self, o): return o["fields"][self.i_metin]
    def stil(self, o): return o["fields"][self.i_stil].strip()
    def bas(self, o): return sure_sn(o["fields"][self.i_bas])
    def son(self, o): return sure_sn(o["fields"][self.i_son])

    def stil_satiri(self, ad: str, degerler: dict) -> str | None:
        """A Style line for an added overlay, laid out by this file's Styles Format line (None without one)."""
        bolum, bicim, ssa = "", None, False
        for s in self.satirlar:
            st = s.strip()
            if st.startswith("[") and st.endswith("]"):
                bolum = st.lower()
            elif bolum in ("[v4+ styles]", "[v4 styles]") and st.lower().startswith("format:"):
                bicim, ssa = [x.strip().lower() for x in st[7:].split(",")], bolum == "[v4 styles]"
                break
        if not bicim:
            return None
        hazir = {"name": ad, "fontname": "Arial", "fontsize": 20, "primarycolour": "&H00FFFFFF", "secondarycolour": "&H000000FF",
                 "outlinecolour": "&H00000000", "tertiarycolour": "&H00000000", "backcolour": "&H80000000", "bold": 0, "italic": 0,
                 "underline": 0, "strikeout": 0, "scalex": 100, "scaley": 100, "spacing": 0, "angle": 0, "borderstyle": 1,
                 "outline": 1, "shadow": 0, "alignment": 2, "marginl": 20, "marginr": 20, "marginv": 10, "alphalevel": 0,
                 "encoding": 1, **degerler}
        if ssa:  # SSA alignment numbering: 2 bottom centre, 6 top centre
            hazir["alignment"] = {8: 6, 2: 2}.get(hazir["alignment"], hazir["alignment"])
        return "Style: " + ",".join(str(hazir.get(k, 0)) for k in bicim)

    def ust_stiller(self) -> set[str]:
        """Style names aligned at the top of the screen (ASS 7-9, SSA 5-7)."""
        bolum, bicim, sonuc = "", None, set()
        for s in self.satirlar:
            st = s.strip()
            if st.startswith("[") and st.endswith("]"):
                bolum = st.lower()
            elif bolum in ("[v4+ styles]", "[v4 styles]") and st.lower().startswith("format:"):
                bicim = [x.strip().lower() for x in st[7:].split(",")]
            elif bicim and "alignment" in bicim and st.startswith("Style:"):
                alan = [x.strip() for x in st[6:].split(",")]
                ust = ("5", "6", "7") if bolum == "[v4 styles]" else ("7", "8", "9")
                if len(alan) == len(bicim) and alan[bicim.index("alignment")] in ust:
                    sonuc.add(alan[0])
        return sonuc

    def play_res_y(self) -> int:
        for s in self.satirlar:
            m = re.match(r"\s*PlayResY\s*:\s*(\d+)", s)
            if m:
                return int(m.group(1))
        return 288

    def yaz(self, yeni_metinler: dict[int, str], ek_olaylar: list[str], ek_stil: str | None) -> str:
        satirlar = list(self.satirlar)
        for o in self.olaylar:
            if o["index"] in yeni_metinler:
                alanlar = list(o["fields"])
                alanlar[self.i_metin] = yeni_metinler[o["index"]]
                satirlar[o["index"]] = "Dialogue: " + ",".join(alanlar)
        cikti = []
        bolum = ""
        for s in satirlar:
            st = s.strip()
            if st.startswith("[") and st.endswith("]"):
                bolum = st.lower()
            cikti.append(s)
            if ek_stil and bolum in ("[v4+ styles]", "[v4 styles]") and st.lower().startswith("format:"):
                cikti.append(ek_stil)
            if bolum == "[events]" and st.lower().startswith("format:"):
                cikti.extend(ek_olaylar)
        return "\n".join(cikti)


def sure_sn(t: str) -> float:
    h, m, s = t.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def sn_ass(x: float) -> str:
    x = max(0.0, x)
    h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def parcala(metin: str) -> tuple[list[str], list[int]]:
    parcalar = ETIKET.split(metin)
    dolu = [i for i, p in enumerate(parcalar) if not p.startswith("{") and re.sub(r"\\h|\\N|\s", "", p)]
    return parcalar, dolu


def tur_bul(stil: str, metin: str) -> str:
    if SARKI_STIL.search(stil):
        return "song"
    if TABELA_STIL.search(stil):
        return "sign"

    if re.search(r"\\(pos|move|org|clip|iclip)\(", metin) and not DIYALOG_STIL.search(stil):
        return "sign"
    return "dialogue"


# {*}Sis{*Akari-neechan}: a short displayed form, then its alternate (non-empty, not starting with * or a space) wins.
ONURSAL_ALT = re.compile(r"\{\*\}([^{}\\*.,!?:;]{1,24}?)\{\*([^{}\\*\s.,!?:;][^{}\\.,!?:;]{0,29})\}")
ONURSAL_EK = re.compile(r"\{\*\*(-[a-z]+(?:-[a-z]+)?)\}")  # Rei{**-kun}: an honorific suffix, nothing else


def onursal_ac(metin: str) -> str:
    """Unwrap fansub honorific comments into plain text, so the model sees them and no marker is created."""
    return ONURSAL_EK.sub(lambda m: m.group(1), ONURSAL_ALT.sub(lambda m: m.group(2), metin))


def onursal_uygula(ass: Ass) -> int:
    """Rewrite the source events' text in memory (config honorific_comments); returns the number of changed events."""
    sayi = 0
    for o in ass.olaylar:
        yeni = onursal_ac(o["fields"][ass.i_metin])
        if yeni != o["fields"][ass.i_metin]:
            o["fields"][ass.i_metin] = yeni
            sayi += 1
    return sayi


def birimleri_cikar(ass: Ass) -> tuple[list[dict], dict[int, dict]]:
    birimler: dict = {}
    esleme: dict[int, dict] = {}
    son_gorulen: dict[str, tuple[str, float]] = {}  # dialogue text -> (style, end of its latest copy)
    tekrar_sayac: dict[str, int] = {}
    for o in sorted(ass.olaylar, key=lambda o: ass.bas(o)):
        metin, stil = ass.metin(o), ass.stil(o)
        if CIZIM.search(metin) or KARAOKE.search(metin) or (SOURCE["code"] != "ja" and ATLA_STIL.search(stil)) or ass.son(o) <= ass.bas(o):
            continue
        parcalar, dolu = parcala(metin)
        duz = "".join(p for p in parcalar if not p.startswith("{")).strip()
        if not dolu or (not cjk_allowed() and CJK.search(duz)) or not any(c.isalpha() for c in duz):
            continue
        birlesik = len(dolu) > 3 and sum(len(parcalar[i]) for i in dolu) / len(dolu) < 4
        if len(dolu) == 1 or birlesik:
            anahtar = duz
        else:
            anahtar = "".join((f"⟦{k}⟧" if k else "") + parcalar[i] for k, i in enumerate(dolu))
        tur = tur_bul(stil, metin)
        anahtar_k = anahtar
        if tur == "dialogue":
            # Only layered copies (same style, overlapping or starting within 0.2 s of the previous copy's end) share a
            # unit; a line spoken again later is a new unit with its own context.
            onceki = son_gorulen.get(anahtar)
            ayni = onceki is not None and onceki[0] == stil and ass.bas(o) <= onceki[1] + 0.2
            if onceki is not None and not ayni:
                tekrar_sayac[anahtar] = tekrar_sayac.get(anahtar, 0) + 1
            anahtar_k = (anahtar, tekrar_sayac.get(anahtar, 0))
            son_gorulen[anahtar] = (stil, max(ass.son(o), onceki[1]) if ayni else ass.son(o))
        if anahtar_k not in birimler:
            birimler[anahtar_k] = {"id": str(len(birimler) + 1), "text": anahtar, "style": stil,
                                   "kind": tur, "start": ass.bas(o), "end": ass.son(o), **birim_izleri(ass, o, parcalar, dolu)}
        elif tur == "dialogue":
            birimler[anahtar_k]["end"] = max(birimler[anahtar_k]["end"], ass.son(o))
        esleme[o["index"]] = {"id": birimler[anahtar_k]["id"], "parts": parcalar, "nonempty": dolu, "merged": birlesik}
    return list(birimler.values()), esleme


def birim_izleri(ass: Ass, o: dict, parcalar: list[str], dolu: list[int]) -> dict:
    """Actor name, italic over the whole line (often inner voice or narration) and top placement, when present."""
    iz = {}
    if "name" in ass.bicim and o["fields"][ass.bicim.index("name")].strip():
        iz["name"] = o["fields"][ass.bicim.index("name")].strip()
    etiketler = [p for p in parcalar if p.startswith("{")]
    bas = "".join(p for p in parcalar[:dolu[0]] if p.startswith("{"))
    ara = "".join(p for p in parcalar[dolu[0] + 1:dolu[-1]] if p.startswith("{"))  # tags between visible parts only
    if (re.findall(r"\\i([01])", bas) or ["0"])[-1] == "1" and not re.search(r"\\i0|\\r", ara):
        iz["italic"] = True
    if any(re.search(r"\\an[789]", p) for p in etiketler):
        iz["top"] = True
    return iz


KONUSMACI = re.compile(r"(?:\s|⟦\d+⟧)*[-‐–—]")


def satir_kir(metin: str, sinir: int) -> str:
    if "\\N" in metin:
        satirlar = metin.split("\\N")
        if all(columns(line) <= sinir for line in satirlar):
            return metin
        if len(satirlar) > 1 and all(KONUSMACI.match(line) for line in satirlar):
            # "- A\N- B": one speaker per line; wrap each speaker's part separately and keep the dash structure.
            return "\\N".join(satir_kir(line, sinir) for line in satirlar)
        metin = " ".join(line.strip() for line in satirlar)
    if columns(metin) <= sinir:
        return metin
    # A space before closing punctuation (French " ?", " !", " :", " ;", " »") or after "«" is not a break point.
    onceki = lambda i: ISARET.sub("", metin[:i])[-1:]  # neighbours are read through zero-width markers
    sonraki = lambda i: ISARET.sub("", metin[i + 1:])[:1]
    bosluklar = [m.start() for m in re.finditer(" ", metin)
                 if (sonraki(m.start()) not in tuple("?!:;»") or not sonraki(m.start())) and onceki(m.start()) != "«"]
    orta = columns(metin) / 2
    if bosluklar:
        i = min(bosluklar, key=lambda i: abs(columns(metin[:i]) - orta) - (6 if onceki(i) and onceki(i) in ",.;:!?…" else 0))
        return metin[:i] + "\\N" + metin[i+1:]
    # Preserve whole markers and combining sequences when wrapping unspaced scripts.
    units = re.findall(r"⟦\d+⟧|.[\u0300-\u036f]*", metin)
    candidates, total = [], 0
    for j, unit in enumerate(units[:-1], 1):
        total += columns(unit)
        if total:
            candidates.append((abs(total - orta), j))
    if not candidates:
        return metin
    j = min(candidates)[1]
    return "".join(units[:j]) + "\\N" + "".join(units[j:])


def olaya_yerlestir(ceviri: str, e: dict, tur: str, sinir: int) -> tuple[str, bool]:
    parcalar = list(e["parts"])
    dolu = e["nonempty"]
    uyari = False
    kir = (lambda t: satir_kir(t, sinir)) if tur == "dialogue" else (lambda t: t)
    if e.get("merged"):
        parcalar[dolu[0]] = kir(ISARET.sub("", ceviri))
        for i, p in enumerate(parcalar):
            if i != dolu[0] and not p.startswith("{"):
                parcalar[i] = ""
    elif len(dolu) == 1:
        parcalar[dolu[0]] = kir(ceviri)
    else:
        # Wrapping measures visible text only (markers are zero-width), so a break never moves a marker.
        if ISARET.findall(ceviri) == [f"⟦{k}⟧" for k in range(1, len(dolu))]:
            # A source break between two tags ({\b0}\N{\i1}) stays when every line fits; otherwise it becomes a space and
            # the line is wrapped once, never twice.
            ara = [i for i, p in enumerate(parcalar) if i not in dolu and not p.startswith("{") and "\\N" in p]
            kirilmis = kir(ceviri)
            if ara and tur == "dialogue":
                bolumler = ISARET.split(ceviri)
                gorunen = "".join(bolumler[dolu.index(i)] if i in dolu else ("" if p.startswith("{") else p) for i, p in enumerate(parcalar))
                if all(columns(line) <= sinir for line in gorunen.split("\\N")):
                    kirilmis = ceviri
                elif all(KONUSMACI.match(line) for line in gorunen.split("\\N")):
                    bolumler = [satir_kir(x, sinir) for x in ISARET.split(ceviri)]
                    kirilmis = "".join(x + (f"⟦{k + 1}⟧" if k + 1 < len(bolumler) else "") for k, x in enumerate(bolumler))
                else:
                    for i in ara:
                        parcalar[i] = re.sub(r"\s*\\N\s*", " ", parcalar[i])
            bolumler = ISARET.split(kirilmis)
            for k, i in enumerate(dolu):
                parcalar[i] = bolumler[k]
        else:
            uyari = True
            parcalar[dolu[0]] = kir(ISARET.sub("", ceviri))
            for i, p in enumerate(parcalar):
                if i != dolu[0] and not p.startswith("{"):
                    parcalar[i] = ""
    return "".join(parcalar), uyari


def sure_uzat(ass: Ass, esleme: dict[int, dict], turler: dict[str, str], yeni: dict[int, str], cps: float, en_cok: float) -> int:
    """Extend the end of dialogue events whose translation is too long to read in time. The start never moves; at most
    `en_cok` seconds and never into the next dialogue event. Returns the number of extended events."""
    diyalog = sorted((o for o in ass.olaylar if o["index"] in esleme and turler.get(esleme[o["index"]]["id"]) == "dialogue"),
                     key=lambda o: ass.bas(o))
    baslar = [ass.bas(o) for o in diyalog]
    sayi = 0
    for k, o in enumerate(diyalog):
        bas, son = ass.bas(o), ass.son(o)
        harf = columns(ETIKET.sub("", yeni.get(o["index"], "")).replace("\\N", " ").strip())
        if not cps or son - bas >= harf / cps:
            continue
        sonraki = next((b for b in baslar[k + 1:] if b >= son - 0.01), None)  # an overlap starting inside this line is no limit
        hedef = min(bas + harf / cps, son + en_cok, (sonraki - 0.05) if sonraki is not None else 1e9)
        if hedef > son + 0.04:
            o["fields"][ass.i_son] = sn_ass(hedef)
            sayi += 1
    return sayi


YEDEK_FONT = "Source Sans 3"
YEDEK_DOSYALAR = sorted((KOK / "fonts").glob("SourceSans3-*.otf"))


def _font_oku(veri: bytes, ofs: int = 0) -> tuple[str | None, set[int]]:
    n = struct.unpack_from(">H", veri, ofs + 4)[0]
    tablolar = {}
    for i in range(n):
        etiket, _, t_ofs, uzun = struct.unpack_from(">4sIII", veri, ofs + 12 + 16 * i)
        tablolar[etiket] = (t_ofs, uzun)
    aile = None
    if b"name" in tablolar:
        t, _ = tablolar[b"name"]
        say, depo = struct.unpack_from(">HH", veri, t + 2)
        adlar = {}
        for i in range(say):
            plat, kod, dil, ad_id, uz, o = struct.unpack_from(">HHHHHH", veri, t + 6 + 12 * i)
            if ad_id not in (1, 16):
                continue
            ham = veri[t + depo + o:t + depo + o + uz]
            try:
                metin = ham.decode("utf-16-be") if plat in (0, 3) else ham.decode("latin-1")
            except UnicodeDecodeError:
                continue
            adlar.setdefault(ad_id, metin)
        aile = adlar.get(1) or adlar.get(16)
    kodlar: set[int] = set()
    if b"cmap" in tablolar:
        t, _ = tablolar[b"cmap"]
        say = struct.unpack_from(">H", veri, t + 2)[0]
        for i in range(say):
            _, _, alt = struct.unpack_from(">HHI", veri, t + 4 + 8 * i)
            a = t + alt
            try:
                bicim = struct.unpack_from(">H", veri, a)[0]
                if bicim == 4:
                    seg = struct.unpack_from(">H", veri, a + 6)[0] // 2
                    sonlar = struct.unpack_from(f">{seg}H", veri, a + 14)
                    baslar = struct.unpack_from(f">{seg}H", veri, a + 16 + 2 * seg)
                    delta_pos = a + 16 + 4 * seg
                    range_pos = a + 16 + 6 * seg
                    for j, (b, e) in enumerate(zip(baslar, sonlar)):
                        delta = struct.unpack_from(">h", veri, delta_pos + 2*j)[0]
                        offset = struct.unpack_from(">H", veri, range_pos + 2*j)[0]
                        for code in range(b, min(e + 1, 0xFFFF)):
                            glyph = (code + delta) & 0xFFFF
                            if offset:
                                glyph = struct.unpack_from(">H", veri, range_pos + 2*j + offset + 2*(code-b))[0]
                                if glyph:
                                    glyph = (glyph + delta) & 0xFFFF
                            if glyph:
                                kodlar.add(code)
                elif bicim == 12:
                    grup = struct.unpack_from(">I", veri, a + 12)[0]
                    for g in range(grup):
                        b, e, glyph = struct.unpack_from(">III", veri, a + 16 + 12 * g)
                        if e - b < 0x20000:
                            kodlar.update(range(b + (glyph == 0), e + 1))
            except struct.error:
                continue
    return aile, kodlar


def font_kapsami(dosyalar: list[Path]) -> dict[str, set[int]]:
    sonuc: dict[str, set[int]] = {}
    for f in dosyalar:
        try:
            veri = f.read_bytes()
            ofslar = [0]
            if veri[:4] == b"ttcf":
                say = struct.unpack_from(">I", veri, 8)[0]
                ofslar = list(struct.unpack_from(f">{say}I", veri, 12))
            for o in ofslar:
                aile, kodlar = _font_oku(veri, o)
                if aile and kodlar:
                    sonuc.setdefault(aile.strip().lower(), set()).update(kodlar)
        except (struct.error, OSError, IndexError):
            continue
    return sonuc


def video_fontlari(video: Path) -> dict[str, set[int]]:
    ekler = [s["index"] for s in ffprobe(video) if s.get("codec_type") == "attachment"]
    if not ekler:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        for i in ekler:
            subprocess.run(["ffmpeg", "-v", "quiet", "-y", f"-dump_attachment:{i}", str(Path(tmp) / f"{i}.font"),
                            "-i", str(video)], capture_output=True)
        return font_kapsami(sorted(Path(tmp).glob("*.font")))


FN = re.compile(r"\\fn([^\\}]*)")


def olay_sutunlari(bicim: list[str] | None) -> tuple[int, int, int]:
    """Column count, style index and text index of Dialogue lines (standard ASS layout without a Format line)."""
    if bicim and "style" in bicim and "text" in bicim:
        return len(bicim), bicim.index("style"), bicim.index("text")
    return 10, 3, 9
DEKOR_STIL = re.compile(r"rune|cipher|symbol|glyph|alien", re.I)


def font_duzelt(metin: str, kapsam: dict[str, set[int]]) -> tuple[str, list[str]]:
    satirlar = metin.split("\n")
    bicim, stil_i, gerekli, olay_bicim = None, {}, {}, None
    fallback_files = FALLBACK_PATHS + YEDEK_DOSYALAR
    fallback_coverage = font_kapsami(fallback_files)
    fallbacks = []
    for path in fallback_files:
        for family, codes in font_kapsami([path]).items():
            # Preserve the family spelling from the font's name table.
            try:
                name, _ = _font_oku(path.read_bytes())
            except (OSError, struct.error, IndexError):
                name = family
            fallbacks.append((name or family, codes))
    for i, line in enumerate(satirlar):
        st = line.strip()
        if st.lower().startswith("format:") and bicim is None and "fontname" in st.lower():
            bicim = [x.strip().lower() for x in st[7:].split(",")]
        elif st.lower().startswith("format:") and "text" in [x.strip().lower() for x in st[7:].split(",")]:
            olay_bicim = [x.strip().lower() for x in st[7:].split(",")]
        elif st.startswith("Style:") and bicim:
            alan = st[6:].split(",")
            stil_i[alan[0].strip()] = i
        elif st.startswith("Dialogue:"):
            n, si, ti = olay_sutunlari(olay_bicim)
            parca = st[9:].split(",", n - 1)
            if len(parca) == n:
                text = ETIKET.sub("", parca[ti]).replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
                harf = {c for c in text if not c.isspace()}
                gerekli.setdefault(parca[si].strip(), set()).update(harf)

    def eksik_mi(aile, harf):
        codes = kapsam.get(aile.strip().lstrip("@").lower())
        return codes is not None and any(ord(c) not in codes for c in harf)

    def replacement(aile, harf):
        for name, codes in fallbacks:
            if all(ord(c) in codes for c in harf):
                return name
        missing = sorted(c for c in harf if not any(ord(c) in codes for codes in fallback_coverage.values()))
        names = ", ".join(f"U+{ord(c):04X} {unicodedata.name(c, 'UNKNOWN')}" for c in missing[:12])
        log(f"WARNING: no fallback covers text used by {aile}; keeping font. Unsupported characters/scripts: {names}")
        return None

    degisen, katla = [], set()
    if bicim:
        fi = bicim.index("fontname")
        for ad, i in stil_i.items():
            harf = gerekli.get(ad, set())
            alan = satirlar[i].split(":", 1)[1].split(",")
            if harf and eksik_mi(alan[fi], harf):
                if latin_target() and DEKOR_STIL.search(ad):
                    folded = set(fold_latin("".join(harf)))
                    if not eksik_mi(alan[fi], folded):
                        katla.add(ad)
                        degisen.append(f"{ad}: decorative font retained; Latin accents folded with NFKD")
                        continue
                name = replacement(alan[fi], harf)
                if name:
                    degisen.append(f"{ad}: {alan[fi].strip()} -> {name}")
                    alan[fi] = name
                    satirlar[i] = "Style:" + ",".join(alan)
    n, si, ti = olay_sutunlari(olay_bicim)
    for i, line in enumerate(satirlar):
        if not line.startswith("Dialogue:"):
            continue
        onek, govde = line.split(":", 1)
        parca = govde.split(",", n - 1)
        if len(parca) != n:
            continue
        if parca[si].strip() in katla:
            parca[ti] = "".join(part if part.startswith("{") else fold_latin(part) for part in ETIKET.split(parca[ti]))
        parts = ETIKET.split(parca[ti])
        for k, part in enumerate(parts):
            if not (part.startswith("{") and FN.search(part)):
                continue
            # The inline font covers text up to the next \fn or \r override.
            harf = set()
            for q in parts[k + 1:]:
                if q.startswith("{"):
                    if FN.search(q) or re.search(r"\\r", q):
                        break
                    continue
                harf |= {c for c in q.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ") if not c.isspace()}
            def degis(m, harf=harf):
                if harf and eksik_mi(m.group(1), harf):
                    name = replacement(m.group(1), harf)
                    if name:
                        degisen.append(f"inline font {m.group(1)} -> {name}")
                        return "\\fn" + name
                return m.group(0)
            parts[k] = FN.sub(degis, part)
        parca[ti] = "".join(parts)
        satirlar[i] = onek + ":" + ",".join(parca)
    return "\n".join(satirlar), sorted(set(degisen))


def ffprobe(video: Path) -> list[dict]:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout)["streams"]


def kismi_iz(baslik: str, akis: dict | None = None) -> bool:
    """Forced, commentary, karaoke or signs/songs-only track (a full track that also has signs/songs is not one)."""
    if re.search(r"\bforced\b|karaoke|commentary", baslik, re.I) or ((akis or {}).get("disposition") or {}).get("forced"):
        return True
    return bool(re.search(r"\bsigns?\b|\bsongs?\b|\btitles?\b", baslik, re.I)) and not re.search(r"\bfull\b|dialog|complete", baslik, re.I)


def olay_sayisi(yol: Path) -> int:
    return yol.read_text(encoding="utf-8", errors="replace").count("\nDialogue:")


def altyazi_sec(video: Path, hedef: Path) -> dict:
    adaylar = []
    for s in ffprobe(video):
        if s.get("codec_type") != "subtitle":
            continue
        dil = s.get("tags", {}).get("language", "und").lower()
        baslik = s.get("tags", {}).get("title", "")
        if dil not in SOURCE["codes"]:
            continue
        if s.get("codec_name") not in ("ass", "ssa", "subrip", "mov_text", "webvtt"):
            continue
        if kismi_iz(baslik, s):
            continue
        adaylar.append(s)
    if not adaylar:
        raise SystemExit(f"No suitable source-language text subtitle found: {video.name} (image subtitles such as PGS are unsupported)")
    en_iyi, en_cok = None, -1
    for s in adaylar:
        gecici = hedef.with_name(f"candidate-{s['index']}.ass")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", f"0:{s['index']}", str(gecici)], check=True)
        sayi = olay_sayisi(gecici)
        if sayi > en_cok:
            en_iyi, en_cok = (s, gecici), sayi
    s, dosya = en_iyi
    dosya.replace(hedef)
    for f in hedef.parent.glob("candidate-*.ass"):
        f.unlink()
    return {"track": s["index"], "title": s.get("tags", {}).get("title", ""), "events": en_cok}


def ozgun_ses(akislar: list[dict], tercih: str | None) -> dict | None:
    sesler = [s for s in akislar if s.get("codec_type") == "audio"
              and not re.search(r"commentary", s.get("tags", {}).get("title", ""), re.I)]
    if not sesler:
        return None
    for dil in (language(tercih)["codes"] if tercih else []):
        for s in sesler:
            if (s.get("tags", {}).get("language") or "").lower() == dil:
                return s
    return sesler[0]


def altyazi_ic_ice(dosya: Path, iz: int, sure: float) -> bool:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", str(iz), "-show_entries", "packet=pts_time,pos",
                        "-of", "csv=p=0", str(dosya)], capture_output=True, text=True)
    boyut, sapma = dosya.stat().st_size, []
    for satir in p.stdout.split():
        try:
            t, pos = satir.split(",")[:2]
            sapma.append(abs(int(pos) / boyut - float(t) / max(sure, 1)))
        except ValueError:
            continue
    if len(sapma) < 5:
        return True
    return sorted(sapma)[len(sapma) // 2] < 0.15


BOS_SHA256 = "SHA256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def akis_hash(dosya: Path) -> list[str]:
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-fflags", "+noparse+nofillin", "-i", str(dosya),
                        "-map", "0:v", "-map", "0:a", "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-"],
                       capture_output=True, text=True, check=True)
    return [x.split(",", 1)[1] for x in p.stdout.split() if "," in x]


def paketle(video: Path, ass: Path, cikti: Path, ses_tercih: str | None, yedek_font: bool = False,
            ek: list[tuple[Path, str]] | None = None, molalar: list[dict] | None = None) -> dict:
    ek = ek or []
    cikti.parent.mkdir(parents=True, exist_ok=True)
    bos = shutil.disk_usage(cikti.parent).free
    if bos < video.stat().st_size * 1.2:
        raise SystemExit(f"Insufficient space in watch directory: {bos / 1e9:.1f} GB free, {video.stat().st_size * 1.2 / 1e9:.1f} GB required. "
                         "Free space before retrying.")
    akislar = ffprobe(video)
    ses = ozgun_ses(akislar, ses_tercih) if ses_tercih else None
    av1 = any(s.get("codec_name") == "av1" for s in akislar if s.get("codec_type") == "video")
    gecici = cikti.with_name(cikti.stem + ".writing.mkv")
    k = ["ffmpeg", "-v", "error", "-y"]
    meta, isaret_sayisi = None, None
    if molalar:
        meta = cikti.with_name(cikti.stem + ".chapters.txt")
        isaret_sayisi = bolum_isaretleri(video, molalar, video_suresi(video), meta)
    if av1:
        k += ["-fflags", "+noparse+nofillin", "-i", str(video), "-i", str(video), "-i", str(ass)]
        for y, _ in ek:
            k += ["-i", str(y)]
        if meta:
            k += ["-i", str(meta), "-map_chapters", str(3 + len(ek))]
        k += ["-map", "0:v", "-map", "1:a", "-map", "2:0"] + sum((["-map", f"{3 + j}:0"] for j in range(len(ek))), []) + ["-map", "1:s?", "-map", "1:t?"]
    else:
        k += ["-i", str(video), "-i", str(ass)]
        for y, _ in ek:
            k += ["-i", str(y)]
        if meta:
            k += ["-i", str(meta), "-map_chapters", str(2 + len(ek))]
        k += ["-map", "0:v", "-map", "0:a", "-map", "1:0"] + sum((["-map", f"{2 + j}:0"] for j in range(len(ek))), []) + ["-map", "0:s?", "-map", "0:t?"]
    ek_sayisi = sum(1 for s in akislar if s.get("codec_type") == "attachment")
    if yedek_font:
        for j, f in enumerate(FALLBACK_PATHS + YEDEK_DOSYALAR):
            mime = "application/x-truetype-font" if f.suffix.lower() in (".ttf", ".ttc") else "application/vnd.ms-opentype"
            k += ["-attach", str(f), f"-metadata:s:t:{ek_sayisi + j}", f"mimetype={mime}",
                  f"-metadata:s:t:{ek_sayisi + j}", f"filename={f.name}"]

    k += ["-c", "copy", "-max_interleave_delta", "0", "-disposition:s", "0", "-disposition:s:0", "default",
          "-metadata:s:s:0", f"language={TARGET['iso3']}", "-metadata:s:s:0", f"title={TARGET.get('display', TARGET['name'])}"]
    for j, (_, baslik) in enumerate(ek, 1):
        k += [f"-metadata:s:s:{j}", f"language={TARGET['iso3']}", f"-metadata:s:s:{j}", f"title={baslik}"]
    if ses_tercih:
        k += ["-disposition:a", "0"]
    if ses is not None:
        sira = [s["index"] for s in akislar if s.get("codec_type") == "audio"].index(ses["index"])
        k += [f"-disposition:a:{sira}", "default"]
    k += [str(gecici)]
    try:
        return _paketi_dogrula(video, ass, cikti, gecici, k, meta, isaret_sayisi, ses, av1, molalar, yedek_font)
    finally:  # a failed mux or verification leaves no partial MKV, chapter file or verification copy behind
        for f in (gecici, meta, gecici.with_name("verify.ass")):
            if f is not None and f.exists():
                f.unlink()


def _paketi_dogrula(video, ass, cikti, gecici, k, meta, isaret_sayisi, ses, av1, molalar, yedek_font) -> dict:
    subprocess.run(k, check=True)
    yeni = ffprobe(gecici)
    def sure(v):
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(v)],
                           capture_output=True, text=True)
        return float(p.stdout.strip() or 0)
    d1, d2 = sure(video), sure(gecici)
    target_unit = next(s for s in yeni if s.get("codec_type") == "subtitle")
    kontrol = gecici.with_name("verify.ass")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(gecici), "-map", f"0:{target_unit['index']}", str(kontrol)], check=True)
    olay = kontrol.read_text(encoding="utf-8").count("\nDialogue:")
    kontrol.unlink()
    beklenen = ass.read_text(encoding="utf-8").count("\nDialogue:")
    video_say = sum(1 for s in yeni if s.get("codec_type") == "video")
    dagilim_ok = altyazi_ic_ice(gecici, target_unit["index"], d2)
    h1, h2 = akis_hash(video), akis_hash(gecici)

    # An empty stream hash must not make lost video packets look like a successful copy.
    hash_ok = h1 == h2 and bool(h1) and not any(x.endswith(BOS_SHA256) for x in h1)
    if abs(d1 - d2) > 1.5 or olay != beklenen or video_say == 0 or not hash_ok or not dagilim_ok:
        raise SystemExit(f"Package verification failed: duration {d1:.1f}/{d2:.1f}, subtitle events {olay}/{beklenen}, video {video_say}, "
                         f"identical audio/video {hash_ok}, subtitle interleaving {dagilim_ok}")
    if meta:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(gecici)], capture_output=True, text=True)
        bulunan = len(json.loads(p.stdout or "{}").get("chapters", []))
        meta.unlink()
        if bulunan != isaret_sayisi:
            raise SystemExit(f"Package verification failed: chapters {bulunan}/{isaret_sayisi}")
    if cikti.exists():
        archived = cikti.parent / "previous"
        archived.mkdir(exist_ok=True)
        shutil.move(str(cikti), archived / f"{cikti.stem}-{time.time_ns()}{cikti.suffix}")
    gecici.replace(cikti)
    return {"file": str(cikti), "break_chapters": [m["t"] for m in (molalar or [])], "duration_seconds": round(d2, 1), "audio": (ses or {}).get("tags", {}).get("language"),
            "av1_dual_input": av1, "subtitle_events": olay,
            "identical_av": hash_ok, "fallback_font": yedek_font}


SERI_SEMA = {"type": "object", "properties": {"series": {"type": "string"}}, "required": ["series"]}


def seri_sorunlari(metin: str, kapsam: list[str]) -> list[str]:
    """Problems of a series guide answer, in English for the log and the retry prompt."""
    sorunlar = []
    if len(metin.split()) < 250:
        sorunlar.append("too short")
    if not re.search(r"(->|→)[^\n|]*\|[^\n]*\|", metin):  # the address table, whatever language the headings use
        sorunlar.append("the directional address table `speaker -> listener | register | address | note` is missing")
    if kapsam and not (kapsam[0] in metin and kapsam[-1] in metin):
        sorunlar.append(f"the source range must cover {kapsam[0]}–{kapsam[-1]}")
    if not cjk_allowed() and CJK.search(metin):
        sorunlar.append("it contains CJK characters; write names and terms in the source or target script")
    return sorunlar


def cjk_temizle(deger):
    """Remove CJK characters from every string of a JSON-like value."""
    if isinstance(deger, str):
        return CJK.sub("", deger)
    if isinstance(deger, list):
        return [cjk_temizle(x) for x in deger]
    if isinstance(deger, dict):
        return {k: cjk_temizle(v) for k, v in deger.items()}
    return deger


def seri_hazirla(a: dict, eser: str, kaynaklar: list[tuple[str, Path]], seri_dir: Path, rehber: str) -> Path:
    hedef = seri_dir / "series.md"
    if hedef.exists():
        return hedef
    log(f"Preparing series guide: {len(kaynaklar)} episodes to read.")
    metinler = []
    for etiket, ass_yolu in kaynaklar:
        ass = Ass(ass_yolu.read_text(encoding="utf-8", errors="replace"))
        if a.get("honorific_comments") is True:
            onursal_uygula(ass)
        satirlar, son_duz = [], None
        for o in sorted(ass.olaylar, key=lambda o: ass.bas(o)):
            t = ass.metin(o)
            if CIZIM.search(t) or KARAOKE.search(t) or (SOURCE["code"] != "ja" and ATLA_STIL.search(ass.stil(o))):
                continue
            duz = ETIKET.sub("", t).replace("\\N", " ").strip()
            ad = o["fields"][ass.bicim.index("name")].strip() if "name" in ass.bicim else ""
            if duz and (cjk_allowed() or not CJK.search(duz)) and (ad, duz) != son_duz:
                satirlar.append(f"{ad}: {duz}" if ad else duz)
                son_duz = (ad, duz)
        metinler.append(f"### {etiket}\n" + "\n".join(satirlar))
    aralik = f"{kaynaklar[0][0]}–{kaynaklar[-1][0]}" if len(kaynaklar) > 1 else kaynaklar[0][0]
    rehber = rehber_rolu(rehber, False)
    gorev = f"""You are the context specialist for a subtitle translation team. Write a SERIES GUIDE for "{eser}" from the supplied source subtitles. Write English Markdown, at most 2500 words. Source range: ARALIK.
Include: source range (mark partial if appropriate); characters (source spelling, spoiler-free identity, voice); directional address table `speaker -> listener | register | address | note` describing target-language politeness, T-V forms and honorifics (or n/a); locked source-to-target terminology; overall tone; song translation approach.
Use established target-language equivalents for game and profession terms unless the viewer's addendum says otherwise. Describe each voice by concrete markers (formality, sentence length, typical phrasing), not by piles of adjectives.
Use the supplied translation guide. Keep honorifics only as permitted there. Do not invent information. Record only information affecting translation, never retell the plot. Describe characters as first encountered; do not reveal hidden identities, deaths, secrets or betrayals. Note register changes by episode without explaining spoilers. No tools. Return the guide in `series`.
Translation guide:
{rehber}
"""

    partiler, parti, boy = [], [], 0
    for m in metinler:
        if parti and boy + len(m) > 350_000:
            partiler.append(parti); parti, boy = [], 0
        parti.append(m); boy += len(m)
    partiler.append(parti)
    mevcut, okunamayan, okunan, bozuk = "", [], [], []
    sira = list(partiler)
    k = 0
    etiketi = lambda m: m.split("\n", 1)[0][4:].strip()
    while sira:
        parti = sira.pop(0); k += 1
        kapsam = okunan + [etiketi(m) for m in parti]
        aralik_yazi = f"{kapsam[0]}–{kapsam[-1]}" if len(kapsam) > 1 else kapsam[0]
        if mevcut:
            istem = (gorev.replace("ARALIK", aralik_yazi) + "\n\nUpdate the existing series guide with the new episodes and return the entire guide "
                     "(preserve correct information; add characters, terminology and register changes). Keep everything about "
                     "the earlier episodes, and update the source range at the top to cover every episode read so far "
                     f"({kapsam[0]}–{kapsam[-1]}).\n\n---- EXISTING SERIES GUIDE ----\n"
                     + mevcut + "\n\n---- NEW SUBTITLES ----\n" + "\n\n".join(parti))
        else:
            istem = gorev.replace("ARALIK", aralik_yazi) + "\n\n---- SUBTITLES ----\n" + "\n\n".join(parti)
        if len(partiler) > 1:
            log(f"Series guide: batch {k}/{len(partiler)}")
        try:
            cevap, _ = model_cagir(a["model_series"], istem, SERI_SEMA, a["timeout_seconds"] * 2)
        except GuvenlikEngeli:
            if len(parti) > 1:
                log(f"Series batch blocked by content safety; {len(parti)} episodes split in half.")
                sira[:0] = [parti[:len(parti) // 2], parti[len(parti) // 2:]]
            else:
                okunamayan.append(parti[0].split("\n", 1)[0].lstrip("# "))
                log(f"Series guide: {okunamayan[-1]} blocked by content safety; skipped.")
            continue
        yeni = cevap["series"].strip()
        aralik_k = kapsam if len(kapsam) > 1 else []  # the range is checked whenever several episodes are read
        sorunlar = seri_sorunlari(yeni, aralik_k)
        if sorunlar:
            log(f"Series guide: {'; '.join(sorunlar)}; retrying once.")
            try:
                cevap, _ = model_cagir(a["model_series"], istem + "\n\nYour previous answer had these problems; fix them: "
                                       + "; ".join(sorunlar) + ".", SERI_SEMA, a["timeout_seconds"] * 2)
                ikinci = cevap["series"].strip()
                if (len(seri_sorunlari(ikinci, aralik_k)), -len(ikinci.split())) < (len(sorunlar), -len(yeni.split())):
                    yeni = ikinci
            except ModelHatasi:
                pass
            sorunlar = seri_sorunlari(yeni, aralik_k)
            if not cjk_allowed() and CJK.search(yeni):
                yeni = CJK.sub("", yeni)
            if sorunlar:
                log(f"WARNING: series guide still has problems ({'; '.join(sorunlar)}); CJK characters were removed if any.")
            if mevcut and any(x == "too short" or "address table" in x for x in sorunlar):
                log("WARNING: the updated series guide is broken; the previous version is kept for these episodes.")
                bozuk += [etiketi(m) for m in parti]
                continue
        mevcut = yeni or mevcut
        okunan = kapsam
    if not mevcut:
        raise SystemExit("Could not write series guide: every episode was blocked by content safety")
    if okunamayan:
        mevcut += "\n\n> Note: episodes unread due to content safety: " + ", ".join(okunamayan)
    if bozuk:
        mevcut += "\n\n> Note: episodes not merged (the update came back broken): " + ", ".join(bozuk)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(f"<!-- {eser} series guide · dragoman {SURUM} · {a['model_series']} · {dt.date.today()} · source {aralik} -->\n\n"
                     + mevcut + "\n", encoding="utf-8")
    log(f"Series guide written: {hedef}")
    return hedef


BAGLAM_SEMA = {"type": "object", "properties": {
    "terms": {"type": "array", "items": {"type": "object", "properties": {
        "source": {"type": "string"}, "translation": {"type": "string"}, "note": {"type": "string"}},
        "required": ["source", "translation", "note"]}},
    "addresses": {"type": "array", "items": {"type": "object", "properties": {
        "from": {"type": "string"}, "to": {"type": "string"}, "register": {"type": "string"},
        "address": {"type": "string"}, "note": {"type": "string"}},
        "required": ["from", "to", "register", "address", "note"]}},
    "voices": {"type": "array", "items": {"type": "object", "properties": {
        "character": {"type": "string"}, "note": {"type": "string"}}, "required": ["character", "note"]}},
    "recurring": {"type": "array", "items": {"type": "object", "properties": {
        "source": {"type": "string"}, "translation": {"type": "string"}}, "required": ["source", "translation"]}},
    "uncertainties": {"type": "array", "items": {"type": "string"}},
    "turns": {"type": "array", "items": {"type": "object", "properties": {
        "first_id": {"type": "string"}, "last_id": {"type": "string"}, "speaker": {"type": "string"},
        "listener": {"type": "string"}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}},
        "required": ["first_id", "last_id", "speaker", "listener", "confidence"]}},
    "breaks": {"type": "array", "items": {"type": "object", "properties": {
        "last_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["last_id", "reason"]}}},
    "required": ["terms", "addresses", "voices", "recurring", "uncertainties", "turns", "breaks"]}
DURAK_SEMA = {"type": "object", "properties": {"breaks": BAGLAM_SEMA["properties"]["breaks"]}, "required": ["breaks"]}
DURAK_GOREV = ("Return all natural breaks throughout the episode (usually 5-12): a scene or small event closes, "
               "place/time changes, and neither dialogue nor tension is interrupted. Exclude the opening/ending "
               "and the start/end of the episode. Each break has last_id (last line before the break) and a brief "
               "spoiler-free reason.\n")


def hafiza_yukle(a: dict, eser: str, seri_dir: Path) -> dict:
    yol = seri_dir / "memory.json"
    if yol.exists():
        return joku(yol)
    h = {"terms": {}, "addresses": {}, "voices": {}}
    jyaz(yol, h)
    return h


def bolum_sirasi(etiket) -> tuple[int, int] | None:
    m = re.fullmatch(r"S(\d+)E(\d+)", str(etiket or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def hafiza_gecerli(x: dict, etiket: str | None) -> bool:
    """A memory entry is known at this episode unless it comes from a later one (entries without a label count as earlier)."""
    simdi, kayit = bolum_sirasi(etiket), bolum_sirasi(x.get("episode"))
    return simdi is None or kayit is None or kayit <= simdi


def hafiza_surumleri(x: dict) -> list[dict]:
    """Versions of one memory entry (an entry written before versions existed is its own single version)."""
    return x.get("versions") or [{k: v for k, v in x.items() if k != "versions"}]


def surum_sirasi(x: dict) -> tuple[int, int]:
    return bolum_sirasi(x.get("episode")) or (-1, -1)  # unlabeled: known before every numbered episode


def hafiza_sec(x: dict, etiket: str | None) -> dict | None:
    adaylar = [v for v in hafiza_surumleri(x) if hafiza_gecerli(v, etiket)]
    return max(adaylar, key=surum_sirasi) if adaylar else None


def hafiza_metni(h: dict, etiket: str | None = None) -> str:
    e = lambda x: f'({x.get("episode", "?")}) '
    g = lambda d: [v for v in (hafiza_sec(x, etiket) for x in d.values()) if v]
    satir = [f'- {e(t)}{t["source"]} → {t["translation"]}' + (f' ({t["note"]})' if t.get("note") else "") for t in g(h.get("terms", {}))]
    satir += [f'- {e(x)}{x.get("direction", "")}: {x.get("register", "")} {x.get("address", "")} — {x.get("note", "")}'.replace("  ", " ")
              for x in g(h.get("addresses", {}))]
    satir += [f'- {e(x)}{x["character"]} voice: {x["note"]}' for x in g(h.get("voices", {}))]
    return "\n".join(satir)


def hafiza_guncelle(seri_dir: Path, baglam: dict, etiket: str) -> None:
    yol = seri_dir / "memory.json"
    h = joku(yol, {"terms": {}, "addresses": {}, "voices": {}})
    # Recurring everyday lines stay episode decisions, not locked memory. Each key keeps one version per episode, so episodes
    # translated out of order each see the decision of the latest episode not after them; the top level is the latest version.
    def koy(bolum, anahtar, deger):
        eski = h.setdefault(bolum, {}).get(anahtar)
        surumler = [v for v in (hafiza_surumleri(eski) if eski else []) if v.get("episode") != etiket] + [deger]
        surumler.sort(key=surum_sirasi)
        h[bolum][anahtar] = {**surumler[-1], "versions": surumler}
    for t in baglam.get("terms", []):
        koy("terms", t["source"].lower(), {"source": t["source"], "translation": t["translation"], "note": t.get("note", ""), "episode": etiket})
    for x in baglam.get("addresses", []):
        yon = f'{x["from"]} → {x["to"]}'
        koy("addresses", yon.lower(), {"direction": yon, "register": x["register"], "address": x["address"], "note": x["note"], "episode": etiket})
    for x in baglam.get("voices", []):
        koy("voices", x["character"].lower(), {"character": x["character"], "note": x["note"], "episode": etiket})
    jyaz(yol, h)


def baglam_metni(b: dict) -> str:
    satir = []
    if b["terms"]:
        satir += ["Terms (use consistently throughout this episode):"] + [f'- {t["source"]} → {t["translation"]}' + (f' ({t["note"]})' if t["note"] else "") for t in b["terms"]]
    if b["addresses"]:
        satir += ["Directional address and register:"] + [f'- {x["from"]} → {x["to"]}: {x["register"]}' + (f', {x["address"]}' if x["address"] else "") + (f' — {x["note"]}' if x["note"] else "") for x in b["addresses"]]
    if b["voices"]:
        satir += ["Character voices:"] + [f'- {x["character"]}: {x["note"]}' for x in b["voices"]]
    if b["recurring"]:
        satir += ["Recurring expressions (same translation):"] + [f'- {x["source"]} → {x["translation"]}' for x in b["recurring"]]
    if b["uncertainties"]:
        satir += ["Uncertainties (take care):"] + [f"- {x}" for x in b["uncertainties"]]
    return "\n".join(satir)


def bolum_baglami(a: dict, ass: "Ass", birimler: list[dict], seri: str, hafiza: dict, rehber: str, is_dir: Path,
                  etiket: str | None = None) -> dict:
    dosya = is_dir / "episode-context.json"
    if dosya.exists():
        return joku(dosya)
    satirlar = []
    for b in birimler:
        if b["kind"] in ("dialogue", "sign"):
            ad = "|".join(x for x in (b.get("name", ""), "italic" if b.get("italic") else "", "top" if b.get("top") else "") if x) \
                if b["kind"] == "dialogue" else "sign"
            satirlar.append(f'{b["id"]} [{int(b["start"] // 60)}:{int(b["start"] % 60):02d}] ' + (f"[{ad}] " if ad else "") + ISARET.sub("", b["text"]))
    molalar = a.get("break_chapters", True) is not False
    istem = (f"{rehber_rolu(rehber, False)}\n\n---- SERIES GUIDE ----\n{seri}\n\n"
             + f"---- SERIES MEMORY ----\n{hafiza_metni(hafiza, etiket)}\n\n"
             + "Read the entire episode and make shared decisions for translators working on separate chunks. "
             "Return only what is specific to this episode or new or changed compared with the series guide and memory; do not "
             "copy entries that are already there unchanged. Return terms (source, translation, note), addresses (from, to, "
             "register, address, note), voices (character, note), recurring expressions, uncertainties (with IDs), and turns. "
             "Register is free text describing how each speaker addresses each listener in the target language: "
             "T-V form, politeness, honorifics, or n/a. Preserve previously used decisions unless the source changes; "
             "explain any change. Context never overrides clear source meaning. Follow the guide, invent nothing, "
             "and do not leak later-episode information. "
             "Turns: runs of consecutive lines (first_id..last_id) with who speaks (speaker) to whom (listener) and your "
             "confidence (high, medium, low). Never guess: leave out lines you cannot attribute from the dialogue itself; a "
             "line without a name is not narration unless the source shows narration. Lines marked [sign] are on-screen text "
             "for context. No tools.\n" + (DURAK_GOREV if molalar else "Return `breaks` as an empty list.\n")
             + (f"\n{a['context_notes']}\n" if a.get("context_notes") else "") +
             "\n---- EPISODE (id [minute:second] [name|flags] text) ----\n" + "\n".join(satirlar))
    cevap, kullanim = model_cagir(a["model_series"], istem, BAGLAM_SEMA, a["timeout_seconds"])
    if not cjk_allowed() and CJK.search(json.dumps(cevap, ensure_ascii=False)):
        log("Episode context contains CJK characters; retrying once.")
        try:
            ikinci, kullanim = model_cagir(a["model_series"], istem + "\n\nDo not use CJK characters anywhere in the answer.",
                                           BAGLAM_SEMA, a["timeout_seconds"])
            cevap = ikinci
        except ModelHatasi:
            pass
        if CJK.search(json.dumps(cevap, ensure_ascii=False)):
            log("WARNING: episode context still contained CJK characters; they were removed.")
            cevap = cjk_temizle(cevap)
    sonuc = {k: cevap.get(k, []) for k in BAGLAM_SEMA["required"]}
    if not molalar:  # breaks were not asked for: a later run with break chapters must still look for them
        sonuc.pop("breaks")
    sonuc["usage"] = kullanim
    jyaz(dosya, sonuc)
    log(f"Episode context: {len(sonuc['terms'])} terms, {len(sonuc['addresses'])} addresses, {len(sonuc['voices'])} voices, "
        f"{len(sonuc['uncertainties'])} uncertainties.")
    return sonuc


def konusmaci_ata(birimler: list[dict], turlar: list[dict]) -> int:
    """Speaker and listener from medium/high-confidence turns onto the units of each run; returns tagged units."""
    sira = {b["id"]: k for k, b in enumerate(birimler)}
    sayi = 0
    for t in turlar:
        k1, k2 = sira.get(str(t.get("first_id"))), sira.get(str(t.get("last_id")))
        if t.get("confidence") not in ("high", "medium") or k1 is None or not str(t.get("speaker", "")).strip():
            continue
        for b in birimler[k1:(k2 if k2 is not None and k2 >= k1 else k1) + 1]:
            konusan = str(t["speaker"]).strip()
            if b["kind"] == "dialogue" and (not b.get("name") or b["name"].casefold() == konusan.casefold()):
                b["speaker"], b["listener"] = b.get("name") or konusan, str(t.get("listener", "")).strip()
                sayi += 1
    return sayi


def durak_adaylari(a: dict, birimler: list[dict], is_dir: Path, baglam: dict | None) -> list[dict]:
    if baglam is not None and "breaks" in baglam:  # the context call already answered, even with no breaks
        return baglam["breaks"]
    dosya = is_dir / "break-candidates.json"
    if dosya.exists():
        return joku(dosya)["breaks"]
    satirlar = [f'{b["id"]} [{int(b["start"] // 60)}:{int(b["start"] % 60):02d}] {_sade(b["text"])}' for b in birimler if b["kind"] == "dialogue"]
    istem = ("Episode source subtitles follow (id [minute:second] text). Task:\n" + DURAK_GOREV + "No tools.\n\n"
             + "\n".join(satirlar))
    try:
        cevap, kul = model_cagir(a["model_translate"], istem, DURAK_SEMA, a["timeout_seconds"])
    except ModelHatasi as e:
        log(f"Could not identify break candidates: {e}")
        return []
    jyaz(dosya, {"breaks": cevap.get("breaks", []), "usage": kul})
    return cevap.get("breaks", [])


def mola_sec(adaylar: list[dict], birimler: list[dict], sure: float) -> list[dict]:
    diyalog = sorted((b for b in birimler if b["kind"] == "dialogue"), key=lambda b: b["start"])
    bul = {b["id"]: b for b in diyalog}
    noktalar = []
    for d in adaylar:
        b = bul.get(str(d.get("last_id")))
        if not b:
            continue
        sonraki = next((x["start"] for x in diyalog if x["start"] > b["end"] + 0.05), sure)
        if sonraki - b["end"] < 1.0:
            continue
        t = round(b["end"] + min(1.5, (sonraki - b["end"]) / 2), 2)
        if 120 < t < sure - 120:
            noktalar.append({"t": t, "reason": d.get("reason", ""), "last_id": b["id"]})
    secilen = []
    for n in sorted(noktalar, key=lambda n: n["t"]):
        if not secilen or n["t"] - secilen[-1]["t"] >= 60:
            secilen.append(n)
    return secilen


def bolum_isaretleri(video: Path, molalar: list[dict], sure: float, hedef: Path) -> int:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(video)], capture_output=True, text=True)
    mevcut = [(float(c["start_time"]), (c.get("tags") or {}).get("title", "")) for c in json.loads(p.stdout or "{}").get("chapters", [])]
    noktalar = mevcut or [(0.0, LABELS["start"])]
    for k, m in enumerate(molalar, 1):
        noktalar.append((m["t"], LABELS["break"].format(n=k)))
    noktalar.sort()
    satir = [";FFMETADATA1"]
    for i, (bas, ad) in enumerate(noktalar):
        son = noktalar[i + 1][0] if i + 1 < len(noktalar) else sure
        if son - bas < 1:
            continue
        ad = ad.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")
        satir += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(bas * 1000)}", f"END={int(son * 1000)}", f"title={ad}"]
    hedef.write_text("\n".join(satir) + "\n", encoding="utf-8")
    return satir.count("[CHAPTER]")


CEVIRI_SEMA = {"type": "object", "properties": {
    "translations": {"type": "object", "additionalProperties": {"type": "string"}}}, "required": ["translations"]}
CEVIRI_NOT_SEMA = {"type": "object", "properties": {**CEVIRI_SEMA["properties"], "notes": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}}, "required": ["id", "text"]}}},
    "required": ["translations"]}
NOT_SINIRI, NOT_UZUNLUK = 4, 80  # translator notes: at most per episode, characters per note

KATEGORILER = ["meaning_error", "reversed_negation", "omission_or_addition", "speaker_or_register", "inconsistent_term",
               "unnatural_or_invented_slang", "broken_format"]
INCELEME_SEMA = {"type": "object", "properties": {
    "corrections": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "category": {"type": "string", "enum": KATEGORILER},
        "new": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["id", "category", "new", "reason"]}},
    "last_reviewed_id": {"type": "string"}},
    "required": ["corrections", "last_reviewed_id"]}

KAPI_SEMA = {"type": "object", "properties": {"decisions": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "string"}, "decision": {"type": "string", "enum": ["accept", "reject"]}, "reason": {"type": "string"}},
    "required": ["id", "decision", "reason"]}}}, "required": ["decisions"]}


def anlam_kapisi(a: dict, adaylar: list[dict], rehber: str, is_dir: Path, baglam: str = "", birimler: list[dict] | None = None) -> dict:
    """Meaning gate for reviewer corrections: reject when AFTER carries less of the source meaning than BEFORE. A correction
    without a decision, or one that content safety blocks, is rejected (the existing translation already passed review).
    Content-safety blocks split the list; any other model error stops the episode (no unchecked corrections are delivered;
    the same command resumes). The cache is validated by a signature of the correction list."""
    dosya = is_dir / "meaning-gate.json"
    model = a.get("model_gate") or a.get("model_review")
    imza = sha(json.dumps([model, sha(rehber), [(d["id"], d["after"]) for d in adaylar]], ensure_ascii=False))
    onceki = joku(dosya)
    if onceki and onceki.get("signature") == imza:
        return onceki
    if not adaylar:
        return {"status": "not needed", "rejected": {}}
    gorev = (f"{rehber_rolu(rehber, True)}\n\n" + (f"---- SERIES GUIDE AND EPISODE CONTEXT ----\n{baglam}\n\n" if baglam else "")
             + "---- TASK ----\nA reviewer wants to change the subtitle translations below. Each has SOURCE (with its on-screen "
             "duration and neighbouring source lines for context), BEFORE (current translation), AFTER (proposed) and the "
             "reviewer's reason. `accept` only when both hold: the claimed error really exists in BEFORE, and AFTER carries the "
             "whole meaning of SOURCE (emphasis, negation, questions and who is speaking to whom included) at least as well as "
             "BEFORE. Also accept when BEFORE adds casual fillers or a register absent from SOURCE and AFTER fixes that without "
             "losing meaning, and when AFTER applies an explicit rule of the guide or the viewer's addendum. If AFTER drops any "
             "meaning element of SOURCE, or if it is a matter of taste, `reject`. One decision per id with a short reason. No tools.\n\n")
    sira = {b["id"]: k for k, b in enumerate(birimler or [])}
    def komsular(d):
        k = sira.get(d["id"])
        if k is None:
            return ""
        b = birimler[k]
        yakin = [x["text"] for x in birimler[max(0, k - 2):k]] + ["▶"] + [x["text"] for x in birimler[k + 1:k + 3]]
        return f'  LINE: {birim_basligi(b)}\n  NEIGHBOURS: ' + " | ".join(yakin) + "\n"
    kararlar, kullanim, filtre, kuyruk = {}, [], [], [adaylar]
    while kuyruk:
        p = kuyruk.pop(0)
        istem = gorev + "\n".join(f'{d["id"]} [{d["category"]}]\n  SOURCE: {d["source"]}\n{komsular(d)}  BEFORE: {d["before"]}\n'
                                   f'  AFTER: {d["after"]}\n  REASON: {d["reason"]}' for d in p)
        try:
            cevap, kul = model_cagir(model, istem, KAPI_SEMA, a["timeout_seconds"])
        except GuvenlikEngeli:
            if len(p) > 1:
                kuyruk[:0] = [p[:len(p) // 2], p[len(p) // 2:]]
            else:
                filtre.append(p[0]["id"])
            continue
        except ModelHatasi as e:
            raise BolumHatasi(f"meaning gate unavailable ({str(e)[:200]}); corrections were not applied unchecked, rerun the same command")
        kararlar.update({str(k.get("id")): k for k in cevap.get("decisions", [])}); kullanim.append(kul)
    red = {d["id"]: ("not checked: blocked by content safety" if d["id"] in filtre else
                     kararlar[d["id"]]["reason"] if d["id"] in kararlar else "no gate decision")
           for d in adaylar if d["id"] in filtre or kararlar.get(d["id"], {}).get("decision") != "accept"}
    sonuc = {"status": "done", "rejected": red, "decisions": list(kararlar.values()), "blocked": filtre, "usage": kullanim, "signature": imza}
    jyaz(dosya, sonuc)
    log(f"Meaning gate: {len(adaylar) - len(red)}/{len(adaylar)} corrections accepted.")
    return sonuc


SANSUR_SEMA = {"type": "object", "properties": {
    "scenes": {"type": "array", "items": {"type": "object", "properties": {
        "first_id": {"type": "string"}, "last_id": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["first_id", "last_id", "reason"]}}}, "required": ["scenes"]}


def birim_basligi(b: dict) -> str:
    """[kind|style|italic|top|duration|≤~N chars|name|speaker → listener]; empty fields are omitted."""
    sure = max(0.0, b["end"] - b["start"])
    alanlar = [b["kind"], b["style"], "italic" if b.get("italic") else "", "top" if b.get("top") else "", f"{sure:.1f} s"]
    cps = BACKEND_CONFIG.get("target_cps", 17) or 0
    if b["kind"] == "dialogue" and cps and sure * cps < 60:
        alanlar.append(f"≤~{int(sure * cps)} chars")
    alanlar.append("" if b.get("name") == b.get("speaker") else b.get("name", ""))
    if b.get("speaker"):
        alanlar.append(f'{b["speaker"]} → {b["listener"]}' if b.get("listener") else b["speaker"])
    return "[" + "|".join(x for x in alanlar if x) + "]"


def _satir(b: dict) -> str:
    return f'{b["id"]} {birim_basligi(b)}: {b["text"]}'


def sahne_parcala(birimler: list[dict], hedef: int) -> list[list[dict]]:
    parcalar, i = [], 0
    while i < len(birimler):
        son = min(len(birimler), i + hedef)
        if son < len(birimler):
            alt = i + int(hedef * 0.6)
            en_iyi, bosluk = son, -1.0
            for j in range(alt, min(len(birimler), i + int(hedef * 1.3))):
                ara = birimler[j]["start"] - birimler[j - 1]["end"]
                if ara > bosluk:
                    en_iyi, bosluk = j, ara
            son = en_iyi
        parcalar.append(birimler[i:son])
        i = son
    return parcalar


def metin_temizle(t: str) -> str:
    t = t.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    t = re.sub(r"\\n", " ", t)
    t = re.sub(r"\{[^{}]*\}", "", t).replace("{", "").replace("}", "")
    t = "".join(c for c in t if c >= " " or c == " ")
    return re.sub(r"[ ]{2,}", " ", t).strip()


ENGLISH_WORDS = set("the a an i you he she it we they is are was were am be been do does did have has had will would can could should "
                    "to of in on at for with from this that these those what why how who when where not no yes and or but my your his her our their me him us them "
                    "there here go going come get got know think want like just really very so if because".split())


def untranslated_line(t: str, source: str | None = None) -> bool:
    def normalized(text):
        return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", _sade(text)).casefold()))
    if source is not None and normalized(t) != normalized(source):
        return False
    words = re.findall(r"[^\W_]+", _sade(t))
    if SOURCE["code"] == "en":
        return sum(k.lower() in ENGLISH_WORDS for k in re.findall(r"[A-Za-z']+", _sade(t))) >= 2
    return len(words) >= 2


def _cevir_istek(a, parca, onceki, sonraki, rehber, seri) -> dict[str, str]:
    istem = (f"{rehber_rolu(rehber, False)}\n\n---- SERIES GUIDE ----\n{seri}\n\n"
             "Translate every subtitle unit below into the target language. Format: id [kind|style|flags|duration|limit|name|"
             "speaker → listener]: text; duration is how many seconds the line stays on screen, `≤~N chars` is the length that "
             "can be read in that time, `italic` often marks inner voice or narration and `top` text at the top of the screen. "
             "Speaker tags are hints; explicit source meaning wins. "
             f"Viewers cannot read faster than about {a.get('target_cps', 17)} characters per second: on short lines drop needless "
             "length, never meaning. "
             "Return a translation for every unchanged ID in `translations`. Omit nothing. No tools."
             + (f" `notes` (a list of id and text, each at most {NOT_UZUNLUK} characters, in the target language) is only for a pun, "
                "wordplay or double meaning that matters for the scene and cannot survive translation (for example a name that is "
                f"also a word). Never for culture words, food or honorifics. The whole episode keeps at most {NOT_SINIRI} notes, so "
                "nearly every chunk has none; return an empty list."
                if a.get("translator_notes") is True else "")
             + "\n\nPrevious lines (context only, do not translate):\n" + "\n".join(b["text"] for b in onceki)
             + "\n\nTRANSLATE:\n" + "\n".join(_satir(b) for b in parca)
             + "\n\nNext lines (context only, do not translate):\n" + "\n".join(b["text"] for b in sonraki))
    cevap, kullanim = model_cagir(a["model_translate"], istem, CEVIRI_NOT_SEMA if a.get("translator_notes") is True else CEVIRI_SEMA,
                                  a["timeout_seconds"])
    bul = {b["id"]: b for b in parca}
    sonuc = {}
    for k, v in cevap.get("translations", {}).items():
        if k not in bul or not isinstance(v, str) or not metin_temizle(v):
            continue
        v = metin_temizle(v)
        if not cjk_allowed() and CJK.search(v):
            continue
        b = bul[k]

        if b["kind"] == "dialogue" and untranslated_line(v, b["text"]):
            continue
        sonuc[k] = v
    notlar = {}
    if a.get("translator_notes") is True and isinstance(cevap.get("notes"), list):
        for n in cevap["notes"]:
            k, v = str((n or {}).get("id", "")), (n or {}).get("text")
            v = metin_temizle(v) if isinstance(v, str) else ""
            if k in sonuc and v and len(v) <= NOT_UZUNLUK and (cjk_allowed() or not CJK.search(v)):
                notlar[k] = v
    return sonuc, kullanim, notlar


def parca_yarima_al(dosya: Path, kullanim_devami: bool = False) -> None:
    yarim = dosya.with_suffix(".partial.json")
    if yarim.exists():
        shutil.copyfile(yarim, yarim.with_name(f"{yarim.stem}-{time.time_ns()}.json"))
        eski, yeni = joku(yarim), joku(dosya)
        yeni["translations"] = {**eski.get("translations", {}), **yeni.get("translations", {})}
        if eski.get("notes") or yeni.get("notes"):
            yeni["notes"] = {**eski.get("notes", {}), **yeni.get("notes", {})}
        for alan in ("untranslated", "blocked"):
            yeni[alan] = [i for i in dict.fromkeys(eski.get(alan, []) + yeni.get(alan, []))
                          if i not in yeni["translations"]]
        if not kullanim_devami:
            yeni["usage"] = eski.get("usage", []) + yeni.get("usage", [])
        jyaz(dosya, yeni)
    os.replace(dosya, yarim)


def cevir_parca(a, no, parca, onceki, sonraki, rehber, seri, is_dir) -> dict:
    dosya = is_dir / "translations" / f"{no:03d}.json"
    sonuc = {"translations": {}, "untranslated": [], "blocked": [], "usage": []}
    yarim = dosya.with_suffix(".partial.json")
    if dosya.exists():
        sonuc = joku(dosya)
        sonuc.setdefault("blocked", [])
        if not all(b["id"] in sonuc["translations"] or b["id"] in sonuc["untranslated"] or b["id"] in sonuc["blocked"] for b in parca):
            raise BolumHatasi(f"Chunk {no}: saved translations do not match this chunk ({dosya}); job plan needs inspection")
        if not sonuc["untranslated"]:
            return sonuc
        log(f"Chunk {no}: retrying {len(sonuc['untranslated'])} untranslated units.")
        sonuc["untranslated"] = []
    elif yarim.exists():
        y = joku(yarim)
        ids = {b["id"] for b in parca}
        sonuc["translations"].update({k: v for k, v in y.get("translations", {}).items() if k in ids})
        sonuc["blocked"] = [i for i in y.get("blocked", []) if i in ids and i not in sonuc["translations"]]
        sonuc["usage"] = list(y.get("usage", []))
        if y.get("notes"):
            sonuc["notes"] = {k: v for k, v in y["notes"].items() if k in sonuc["translations"]}
    kuyruk = [parca]
    while kuyruk:
        p = kuyruk.pop(0)
        eksik = [b for b in p if b["id"] not in sonuc["translations"] and b["id"] not in sonuc["blocked"]]
        engel = False
        for _ in range(2):
            if not eksik:
                break
            sira = [b["id"] for b in parca]
            i0, i1 = sira.index(eksik[0]["id"]), sira.index(eksik[-1]["id"])
            bu_onceki = (list(onceki) + parca[:i0])[-6:] if i0 else onceki
            bu_sonraki = (parca[i1 + 1:] + list(sonraki))[:4] if i1 + 1 < len(parca) else sonraki
            try:
                ceviri, kullanim, *ek = _cevir_istek(a, eksik, bu_onceki, bu_sonraki, rehber, seri)
            except GuvenlikEngeli:
                engel = True
                break
            except ModelHatasi:


                jyaz(dosya, sonuc)
                parca_yarima_al(dosya, kullanim_devami=True)
                raise
            sonuc["translations"].update(ceviri); sonuc["usage"].append(kullanim)
            if ek and ek[0]:
                sonuc.setdefault("notes", {}).update(ek[0])
            eksik = [b for b in eksik if b["id"] not in sonuc["translations"]]
        if eksik and len(eksik) > 1:
            yari = len(eksik) // 2
            log(f"Chunk {no}: {len(eksik)} units missing" + (" (content safety)" if engel else "") + ", splitting in half and retrying.")
            kuyruk[:0] = [eksik[:yari], eksik[yari:]]
        elif eksik and engel:
            sonuc["blocked"].append(eksik[0]["id"])
            log(f"Chunk {no}: unit {eksik[0]['id']} blocked by provider safety; source text retained and reported.")
        elif eksik:
            sonuc["untranslated"].append(eksik[0]["id"])
    jyaz(dosya, sonuc)
    log(f"Translation chunk {no} complete ({len(sonuc['translations'])}/{len(parca)} units"
        + (f", {len(sonuc['untranslated'])} untranslated" if sonuc["untranslated"] else "") + ").")
    return sonuc


def incele_parca(a, no, parca, ceviri, rehber, seri, is_dir, onceki=(), sonraki=()) -> dict:
    dosya = is_dir / "review" / f"{no:03d}.json"
    imza = sha(json.dumps([(b["id"], ceviri.get(b["id"])) for b in parca], ensure_ascii=False))
    if dosya.exists():
        kayit = joku(dosya)
        if kayit.get("signature") == imza:  # records without a signature (older versions) are reviewed again
            return kayit
        eski = dosya.with_name(f"{dosya.stem}-stale-{time.time_ns()}.json")
        os.replace(dosya, eski)
        log(f"Review chunk {no}: saved review belongs to other units or translations; kept as {eski.name} and reviewing again.")
    sonuc = {"corrections": [], "last_reviewed_id": None, "last_id": parca[-1]["id"], "usage": [], "blocked": [], "trap": [],
             "ids": [b["id"] for b in parca], "signature": imza}
    eksik_okuma = False
    kuyruk = [parca]
    sira = [b["id"] for b in parca]
    while kuyruk:
        p = kuyruk.pop(0)
        i0, i1 = sira.index(p[0]["id"]), sira.index(p[-1]["id"])
        p_onceki = (list(onceki) + parca[:i0])[-3:] if i0 else onceki  # a split half sees its neighbours inside the chunk
        p_sonraki = (parca[i1 + 1:] + list(sonraki))[:3] if i1 + 1 < len(parca) else sonraki
        try:
            d, son, kul = _incele_istek(a, p, ceviri, rehber, seri, tuzak_kur(p, ceviri, no, 0) if p is parca else None, p_onceki, p_sonraki)
            if p is parca and d is not None and d[-1] is False:

                log(f"Review chunk {no}: reviewer missed trap line; reviewing once more.")
                sonuc["trap"].append(False)
                d2, son, kul2 = _incele_istek(a, p, ceviri, rehber, seri, tuzak_kur(p, ceviri, no, 1), p_onceki, p_sonraki)
                sonuc["usage"].append(kul)
                if d2[1] is not False:  # the second reviewer caught its trap (or had none): only its corrections count
                    d, kul = d2, kul2
                else:
                    birlesik = {x["id"]: x for x in d[0] + d2[0]}
                    d, kul = (list(birlesik.values()), d2[1]), kul2
            if d is not None and d[1] is not None:
                sonuc["trap"].append(d[1])
            d = d[0]
        except GuvenlikEngeli:
            if len(p) > 1:
                kuyruk[:0] = [p[:len(p) // 2], p[len(p) // 2:]]
            else:
                sonuc["blocked"].append(p[0]["id"])
            continue
        sonuc["corrections"] += d; sonuc["usage"].append(kul); sonuc["last_reviewed_id"] = son
        eksik_okuma = eksik_okuma or str(son or "") != str(p[-1]["id"])
    if sonuc["blocked"]:
        log(f"Review chunk {no}: {len(sonuc['blocked'])} units blocked by content safety.")
    sonuc["possibly_incomplete"] = eksik_okuma
    jyaz(dosya, sonuc)
    log(f"Review chunk {no} complete ({len(sonuc['corrections'])} corrections)."
        + (" Reviewer may not have read to the end." if sonuc["possibly_incomplete"] else ""))
    return sonuc


def tuzak_kur(parca, ceviri, no, deneme):
    """Pair unrelated lines in the reviewer prompt only; never insert the trap in final subtitles."""
    uzun = [b for b in parca if b["kind"] == "dialogue" and len(_sade(b["text"])) >= 25 and len(_sade(ceviri.get(b["id"], ""))) >= 25]
    if len(parca) < 8 or len(uzun) < 4:
        return None
    k = (no * 7 + deneme * 3) % (len(uzun) // 2)
    source_units, target_unit = uzun[k], uzun[k + len(uzun) // 2]
    if _sade(source_units["text"]).lower() == _sade(target_unit["text"]).lower():
        return None
    yer = (no * 13 + deneme * 5) % len(parca)
    return {"id": str(90000 + no * 10 + deneme), "kind": "dialogue", "style": source_units["style"], "text": source_units["text"],
            "start": source_units["start"], "end": source_units["end"], "translation": ceviri[target_unit["id"]], "position": yer}


def _incele_istek(a, parca, ceviri, rehber, seri, tuzak=None, onceki=(), sonraki=()):
    liste = list(parca)
    if tuzak:
        liste.insert(tuzak["position"], tuzak)
        ceviri = {**ceviri, tuzak["id"]: tuzak["translation"]}
    satirlar = [f'{b["id"]} {birim_basligi(b) if "end" in b else "[" + b["kind"] + "|" + b["style"] + "]"}\n  SOURCE: {b["text"]}'
                f'\n  TRANSLATION: {ceviri[b["id"]]}' for b in liste]
    baglam = lambda xs: "\n".join(f'  SOURCE: {b["text"]} / TRANSLATION: {ceviri.get(b["id"], "")}' for b in xs) or "  (none)"
    istem = (f"{rehber_rolu(rehber, True)}\n\n---- SERIES GUIDE ----\n{seri}\n\n"
             "You are an independent reviewer. Check every SOURCE and TRANSLATION pair from beginning to end "
             "using the reviewer checklist. Return only real errors in `corrections` with categories: "
             f"{', '.join(KATEGORILER)}. Synonym preferences are not errors. A translation shortened to fit its duration is not "
             "an omission if every meaning unit survives. Each line header is [kind|style|flags|duration|limit|name|speaker → "
             "listener]; speaker tags are hints; explicit source meaning wins. `new` contains "
             "the complete corrected line. `last_reviewed_id` is the last ID you actually read. No tools.\n\n"
             "Previous lines (context only, not for review):\n" + baglam(onceki) + "\n\nREVIEW:\n" + "\n".join(satirlar)
             + "\n\nNext lines (context only, not for review):\n" + baglam(sonraki))
    cevap, kullanim = model_cagir(a["model_review"], istem, INCELEME_SEMA, a["timeout_seconds"])
    ids = {b["id"] for b in parca}
    duz = [d for d in cevap.get("corrections", []) if d.get("id") in ids and d.get("new", "").strip()]
    if tuzak is None:
        return (duz, None), cevap.get("last_reviewed_id"), kullanim
    yakalandi = any(str(d.get("id")) == tuzak["id"] for d in cevap.get("corrections", []))
    return (duz, yakalandi), cevap.get("last_reviewed_id"), kullanim


def _sansur_istek(a, satirlar):
    istem = ("Prepare content warnings from subtitle dialogue (id [time] text). Identify romantic/sexual kissing, "
             "nudity, bed scenes, sexual innuendo or sexual tension. Exclude ordinary violence and family kisses "
             "on cheek/forehead. Do not include uncertain guesses. Return first_id, last_id and a brief "
             f"reason in {a.get('warning_language') or 'English'} (it is shown on screen) for each scene, or an empty list. No tools.\n\n" + "\n".join(satirlar))
    cevap, _ = model_cagir(a["model_warnings"], istem, SANSUR_SEMA, a["timeout_seconds"])
    return cevap.get("scenes", [])


def sansur_tara(a, birimler, is_dir) -> dict:
    dosya = is_dir / "warning-scan.json"
    if dosya.exists():
        v = joku(dosya)
        return v if "status" in v else {"status": "complete", "scenes": v.get("scenes", []), "unscanned": []}
    satirlar = [f'{b["id"]} [{sn_ass(b["start"])}] {b["text"]}' for b in birimler if b["kind"] == "dialogue"]
    ids = [b["id"] for b in birimler if b["kind"] == "dialogue"]
    sahneler, taranamayan, kuyruk = [], [], [(0, len(satirlar))] if satirlar else []
    while kuyruk:
        i, j = kuyruk.pop(0)
        try:
            sahneler += _sansur_istek(a, satirlar[i:j])
        except GuvenlikEngeli:
            if j - i > 40:
                orta = (i + j) // 2
                kuyruk[:0] = [(i, orta), (orta, j)]
            else:
                taranamayan.append({"first_id": ids[i], "last_id": ids[j - 1], "reason": LABELS["scan_unavailable"]})
        except ModelHatasi as e:
            log(f"Content warning scan unavailable: {e}")
            return {"status": "failed", "scenes": [], "unscanned": [], "error": str(e)[:300]}
    durum = "partial" if taranamayan else "complete"
    sonuc = {"status": durum, "scenes": sahneler, "unscanned": taranamayan}
    jyaz(dosya, sonuc)
    if taranamayan:
        log(f"Content warning scan partial: {len(taranamayan)} ranges blocked by content safety; these ranges will have warnings.")
    return sonuc


def metin_oku(yol: Path) -> str:
    ham = yol.read_bytes()
    # UTF-16 only with a byte-order mark: without one, any even-length legacy file would "decode" as UTF-16 garbage.
    for kod in ("utf-8-sig",) + (("utf-16",) if ham[:2] in (b"\xff\xfe", b"\xfe\xff") else ()) + ("cp1252", "latin-1"):
        try:
            return ham.decode(kod)
        except UnicodeDecodeError:
            continue
    return ham.decode("utf-8", "replace")


def target_tagged(name: str) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(code) + r"(?![a-z])", name.lower()) for code in TARGET["codes"])


def translation_sanity(text: str, source: str) -> bool:
    def plain(value):
        try:
            value = " ".join(x[2] for x in _diyaloglar(Ass(value)))
        except (ValueError, IndexError):
            value = ETIKET.sub("", value)
        return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))
    return bool(plain(text)) and plain(text) != plain(source)


def _ass_yap(yol: Path, hedef: Path) -> Path:
    """External .ass/.ssa/.srt as a UTF-8 ASS file (encoding detected by metin_oku)."""
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f"{hedef.stem}.utf8{yol.suffix.lower()}")  # ffmpeg recognizes the format by extension
    gecici.write_text(metin_oku(yol), encoding="utf-8")
    if yol.suffix.lower() == ".ass":
        gecici.replace(hedef)
        return hedef
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-sub_charenc", "UTF-8", "-i", str(gecici), str(hedef)], check=True)
    finally:
        gecici.unlink(missing_ok=True)
    return hedef


def insan_adaylari(video: Path | None, sezon: int, no: int | None, is_dir: Path, dosyalar: bool = True) -> list[dict]:
    """Target-language subtitles for this episode: files beside the video (up to two levels down) and embedded tracks."""
    adaylar, gomulu = [], []
    if video is None:
        return adaylar
    for f in sorted(video.parent.rglob("*")) if dosyalar else []:
        if f.suffix.lower() not in (".ass", ".srt", ".ssa") or len(f.relative_to(video.parent).parts) > 3:
            continue
        ad = f"{f.parent.name}/{f.stem}"
        sz = sezon_no(f.stem) or sezon_no(f.parent.name) if f.parent != video.parent else sezon_no(f.stem)
        if (sz is not None and sz != sezon) or (no is not None and bolum_no(f.stem) != no) or kismi_iz(f.stem):
            continue
        try:
            if not target_tagged(ad):
                continue
        except OSError:
            continue
        adaylar.append({"source": str(f), "kind": "file"})
    for akis in ffprobe(video):
        dil = (akis.get("tags") or {}).get("language", "").lower()
        baslik = (akis.get("tags") or {}).get("title", "")
        if akis.get("codec_type") == "subtitle" and dil in TARGET["codes"] and akis.get("codec_name") in ("ass", "ssa", "subrip", "mov_text") \
                and not kismi_iz(baslik, akis):
            hedef = is_dir / "human" / f"embedded-{akis['index']}.ass"
            if not hedef.exists():
                hedef.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", f"0:{akis['index']}", str(hedef)], check=True)
            gomulu.append({"source": str(hedef), "kind": "embedded track", "track": akis["index"], "title": baslik,
                           "events": olay_sayisi(hedef)})
    # Several embedded tracks: the one with the most dialogue events first (stable for equal counts).
    return adaylar + sorted(gomulu, key=lambda x: -x["events"])


def _diyaloglar(ass: "Ass") -> list[tuple[float, float, str]]:
    cikti = []
    for o in ass.olaylar:
        t = ass.metin(o)
        if CIZIM.search(t) or KARAOKE.search(t):
            continue
        duz = re.sub(r"\s+", " ", ETIKET.sub("", t).replace("\\N", " ").replace("\\n", " ")).strip()
        if duz:
            cikti.append((ass.bas(o), ass.son(o), duz))
    return sorted(cikti)


def hizala(insan: list[tuple[float, float, str]], source_units: list[dict]) -> tuple[float, float]:
    import bisect
    baslar = sorted(b["start"] for b in source_units if b["kind"] == "dialogue")
    if not baslar or not insan:
        return 0.0, 0.0
    def oran(kayma, tol=0.35):
        say = 0
        for bas, _, _ in insan:
            t = bas + kayma
            j = bisect.bisect_left(baslar, t)
            if any(0 <= k < len(baslar) and abs(baslar[k] - t) <= tol for k in (j - 1, j)):
                say += 1
        return say / len(insan)
    kaba = max((x / 10 for x in range(-300, 301)), key=lambda k: (oran(k), -abs(k)))

    def ortanca_fark(kayma):
        farklar = []
        for bas, _, _ in insan:
            t = bas + kayma
            j = bisect.bisect_left(baslar, t)
            farklar.append(min(abs(baslar[k] - t) for k in (j - 1, j) if 0 <= k < len(baslar)))
        return sorted(farklar)[len(farklar) // 2]
    en_iyi = oran(kaba)
    ince = min((kaba + x / 100 for x in range(-40, 41) if oran(kaba + x / 100) >= en_iyi - 0.01), key=ortanca_fark)
    return round(ince, 2), round(oran(ince), 3)


INSAN_SEMA = {"type": "object", "properties": {
    "score": {"type": "number"}, "meaning_error_percent": {"type": "number"},
    "invented_slang": {"type": "integer"}, "careless_spelling": {"type": "boolean"},
    "examples": {"type": "array", "items": {"type": "object", "properties": {
        "source": {"type": "string"}, "translation": {"type": "string"}, "issue": {"type": "string"}}, "required": ["source", "translation", "issue"]}},
    "summary": {"type": "string"}, "decision": {"type": "string", "enum": ["sufficient", "insufficient"]}},
    "required": ["score", "meaning_error_percent", "invented_slang", "careless_spelling", "examples", "summary", "decision"]}


def insan_degerlendir(a: dict, aday: dict, birimler: list[dict], rehber: str, is_dir: Path, sira: int) -> dict:
    dosya = is_dir / "human" / f"evaluation-{sira}.json"
    if dosya.exists():
        return joku(dosya)
    yol = _ass_yap(Path(aday["source"]), is_dir / "human" / f"candidate-{sira}.ass") if aday["kind"] == "file" else Path(aday["source"])
    candidate_text = yol.read_text(encoding="utf-8", errors="replace")
    source_file = is_dir / "source.ass"
    source_text = source_file.read_text(encoding="utf-8", errors="replace") if source_file.exists() else " ".join(b["text"] for b in birimler)
    if not translation_sanity(candidate_text, source_text):
        return {**aday, "ass": str(yol), "decision": "insufficient", "reason": "Translation copies source or is empty",
                "timing_match": 0, "coverage": 0}
    insan = _diyaloglar(Ass(candidate_text))
    kayma, oran = hizala(insan, birimler)
    diyalog = [b for b in birimler if b["kind"] == "dialogue"]

    kapsanan = sum(1 for b in diyalog if any(ib + kayma < b["end"] and is_ + kayma > b["start"] for ib, is_, _ in insan))
    kapsam = round(kapsanan / max(1, len(diyalog)), 3)
    sonuc = {**aday, "ass": str(yol), "lines": len(insan), "offset_seconds": kayma, "timing_match": oran, "coverage": kapsam}
    if oran < 0.6:
        sonuc.update({"decision": "insufficient", "reason": f"timing does not match video ({oran*100:.0f}% of lines match)"})
        jyaz(dosya, sonuc)
        return sonuc

    ciftler = []
    for ib, is_, target_unit in insan:
        source_units = " ".join(_sade(b["text"]) for b in diyalog if b["start"] < is_ + kayma and b["end"] > ib + kayma)
        if source_units:
            ciftler.append((sn_ass(ib + kayma)[:-3], source_units, target_unit))
    adim = max(1, len(ciftler) // 220)
    ornek = ciftler[::adim][:220]
    istem = (f"{rehber}\n\nEvaluate this human translation against the source using the guide's quality criteria. "
             "Pairs are time | SOURCE | TRANSLATION, aligned by time overlap. The translation may come directly "
             "from the original language; do not call a plausible alternate reading an error. Count only clear "
             "meaning errors, omissions/additions, reversed negation, invented slang and careless spelling. "
             "score is 0-10 (10 professional); examples are the worst 5-8 lines. decision is sufficient or insufficient. "
             "No tools.\n\n" + "\n".join(f"{z} | {e} | {t}" for z, e, t in ornek))
    try:
        cevap, kullanim = model_cagir(a["model_review"], istem, INSAN_SEMA, a["timeout_seconds"])
    except ModelHatasi as e:
        sonuc.update({"decision": "insufficient", "reason": f"could not evaluate: {e}"[:300]})
        jyaz(dosya, sonuc)
        return sonuc
    sonuc.update(cevap); sonuc["usage"] = kullanim; sonuc["evaluated_pairs"] = len(ornek)
    jyaz(dosya, sonuc)
    return sonuc


# Streaming-platform tag in an embedded track title, or (when the title is neutral) in the video filename.
# Short codes match uppercase only. Crunchyroll/HIDIVE count in a track title but not in a filename: their rips
# often carry fan translations, and CR/HIDIVE short codes are not used at all.
PROFESYONEL = re.compile(r"(?<![A-Za-z0-9])(?:NF|AMZN|DSNP|ATVP|HMAX)(?![A-Za-z0-9])|"
                         r"(?i:netflix|amazon|prime video|disney|crunchyroll|hidive|apple tv)")
DOSYA_PLATFORM = re.compile(r"(?<![A-Za-z0-9])(?:NF|AMZN|DSNP|ATVP|HMAX)(?![A-Za-z0-9])|(?i:netflix|amazon|prime video|disney|apple tv)")


def notr_baslik(baslik: str) -> bool:
    """A track title that only names the target language (or is empty) says nothing about its origin."""
    adlar = {"", TARGET["name"], TARGET.get("display", ""), LANGUAGES.get(TARGET["code"], {}).get("name", ""), *TARGET["codes"]}
    return fold_latin(baslik.strip()).casefold() in {fold_latin(x).casefold() for x in adlar}


def profesyonel_iz(a: dict, video: Path | None, sezon: int, no: int | None, is_dir: Path) -> dict | None:
    """Default rule while scoring is off: a target-language track from a streaming platform is delivered, not translated.
    Downloaded files beside the video are ignored; an embedded track without a platform tag (fansub) does not stop
    translation and stays in the MKV."""
    adaylar = insan_adaylari(video, sezon, no, is_dir, dosyalar=False)
    for x in sorted(adaylar, key=lambda x: -x.get("events", 0)):
        iz = PROFESYONEL.search(x.get("title", "")) or (notr_baslik(x.get("title", "")) and DOSYA_PLATFORM.search(video.name))
        if iz:
            secim = {**x, "ass": x["source"], "offset_seconds": 0.0, "score": None, "decision": "professional track",
                     "professional": iz.group(0), "use": True}
            jyaz(is_dir / "human" / "selection.json", {"candidates": adaylar, "selected": x["source"], "use": True, "rule": "professional track"})
            log(f"Professional {TARGET['name']} track found ({iz.group(0)}, track {x['track']}); no translation needed.")
            return secim
    if adaylar:
        log(f"{len(adaylar)} embedded {TARGET['name']} tracks without a platform tag; translating, and they stay in the MKV.")
    return None


def insan_secimi(a: dict, video: Path | None, sezon: int, no: int | None, birimler: list[dict], rehber: str, is_dir: Path) -> dict | None:
    """Best existing human translation; `use` True means no translation is needed."""
    if not a.get("human_scoring"):
        return profesyonel_iz(a, video, sezon, no, is_dir) if video else None
    adaylar = insan_adaylari(video, sezon, no, is_dir)
    if not adaylar:
        return None
    log(f"{len(adaylar)} human translation candidates found; evaluating.")
    sonuclar = [insan_degerlendir(a, x, birimler, rehber, is_dir, k) for k, x in enumerate(adaylar, 1)]
    for r in sonuclar:
        log(f"Human translation: {Path(r['source']).name} · score {r.get('score', '-')} · timing match %{r['timing_match']*100:.0f} · "
            f"coverage %{r['coverage']*100:.0f} · {r.get('decision')}" + (f" ({r['reason']})" if r.get("reason") else ""))
    kullanilabilir = [r for r in sonuclar if "score" in r]
    if not kullanilabilir:
        en_iyi = max(sonuclar, key=lambda r: r["timing_match"])
        return {**en_iyi, "use": False}
    en_iyi = max(kullanilabilir, key=lambda r: (r["score"], r["coverage"]))
    kullan = (en_iyi["decision"] == "sufficient" and en_iyi["score"] >= a["human_threshold"] and en_iyi["coverage"] >= 0.9
              and en_iyi["timing_match"] >= 0.7)
    jyaz(is_dir / "human" / "selection.json", {"candidates": sonuclar, "selected": en_iyi["source"], "use": kullan, "threshold": a["human_threshold"]})
    return {**en_iyi, "use": kullan}


def ass_kaydir(metin: str, kayma: float) -> str:
    if not kayma:
        return metin
    ass = Ass(metin)
    satirlar = list(ass.satirlar)
    for o in ass.olaylar:
        al = list(o["fields"])
        al[ass.i_bas] = sn_ass(ass.bas(o) + kayma)
        al[ass.i_son] = sn_ass(ass.son(o) + kayma)
        satirlar[o["index"]] = "Dialogue: " + ",".join(al)
    return "\n".join(satirlar)


OGRENME_SEMA = {"type": "object", "properties": {
    "cefr": {"type": "string", "enum": ["A2", "A2-B1", "B1", "B1-B2", "B2", "B2-C1", "C1", "C1-C2", "C2"]},
    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    "suitability": {"type": "string", "enum": ["comfortable", "productive_challenge", "substantial_support"]},
    "summary": {"type": "string"},
    "difficulties": {"type": "array", "items": {"type": "string"}},
    "evidence": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "quote": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["id", "quote", "reason"]}},
    "expressions": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "quote": {"type": "string"}, "kind": {"type": "string"},
        "meaning": {"type": "string"}, "usefulness": {"type": "string"}},
        "required": ["id", "quote", "kind", "meaning", "usefulness"]}}},
    "required": ["cefr", "confidence", "suitability", "summary", "difficulties", "evidence", "expressions"]}
CONFIDENCE_LABELS = {"low": "low", "medium": "medium", "high": "high"}
SUITABILITY_LABELS = {"comfortable": "comfortable viewing", "productive_challenge": "challenging but useful", "substantial_support": "substantial support recommended"}


def _sade(metin: str) -> str:
    return re.sub(r"\s+", " ", ISARET.sub("", metin).replace("\\N", " ").replace("\\n", " ")).strip()


def okuma_olcumu(birimler: list[dict]) -> dict:
    diyalog = [b for b in birimler if b["kind"] == "dialogue" and _sade(b["text"])]
    if not diyalog:
        return {}
    cps = sorted(columns(_sade(b["text"])) / max(0.5, b["end"] - b["start"]) for b in diyalog)
    kelimeler = [k.lower() for b in diyalog for k in re.findall(r"[^\W_]+(?:'[^\W_]+)?", _sade(b["text"]))]
    dakika = max(1.0, (diyalog[-1]["end"] - diyalog[0]["start"]) / 60)
    yuzde = lambda p: round(cps[min(len(cps) - 1, int(len(cps) * p))], 1)
    return {"lines": len(diyalog), "words": len(kelimeler), "unique_words": len(set(kelimeler)),
            "words_per_minute": round(len(kelimeler) / dakika), "cps_median": yuzde(0.5), "cps_p90": yuzde(0.9),
            "fast_line_percent": round(100 * sum(c > BACKEND_CONFIG.get("reading_speed_threshold", 20) for c in cps) / len(cps))}


def ogrenme_raporu(a: dict, birimler: list[dict], is_dir: Path, etiket: str) -> dict:
    dosya = is_dir / "level.json"
    if dosya.exists():
        return joku(dosya)
    diyalog = [b for b in birimler if b["kind"] in ("dialogue", "song") and _sade(b["text"])]
    olcum = okuma_olcumu(birimler)
    istem = (f"Learner profile: {a['learner_profile'] or 'Not specified; assess content difficulty without personal assumptions.'}\n"
             f"Assess the source subtitles for reading comprehension. Write the report in {a.get('report_language') or 'English'}. Give approximate "
             "CEFR, confidence, suitability (comfortable, productive_challenge, substantial_support), a two-sentence "
             "summary, concrete difficulties, 3-5 evidence quotes and 8-12 useful expressions appropriate to the "
             "profile. Without a profile, describe suitability generally. Every quote must occur verbatim in its "
             "source line; include ID, kind, meaning (in the report language) and usefulness. You cannot assess unseen audio/video. "
             f"Local reading measurements: {json.dumps(olcum, ensure_ascii=False)}\nNo tools.\n\n"
             + "\n".join(f'{b["id"]}: {_sade(b["text"])}' for b in diyalog))
    try:
        cevap, kullanim = model_cagir(a["model_level"], istem, OGRENME_SEMA, a["timeout_seconds"])
    except ModelHatasi as e:
        log(f"Level report unavailable: {e}")
        return {"error": str(e), "measurements": olcum}
    bul = {b["id"]: _sade(b["text"]).lower() for b in diyalog}
    gecerli = lambda x: x.get("id") in bul and _sade(x.get("quote", "")).lower() in bul[x["id"]] and x.get("quote", "").strip()
    rapor = {**cevap, "evidence": [k for k in cevap.get("evidence", []) if gecerli(k)],
             "expressions": [n for n in cevap.get("expressions", []) if gecerli(n)],
             "rejected_quotes": sum(not gecerli(x) for x in cevap.get("evidence", []) + cevap.get("expressions", [])),
             "measurements": olcum, "profile": a["learner_profile"], "model": a["model_level"], "episode": etiket,
             "usage": kullanim, "note": "Approximate content assessment; not a personal test or CEFR certificate."}
    jyaz(dosya, rapor)
    (is_dir / "level.md").write_text(ogrenme_md(rapor, birimler), encoding="utf-8")
    log(f"Level report: {rapor['cefr']}, {SUITABILITY_LABELS.get(rapor['suitability'], rapor['suitability'])}.")
    return rapor


def ogrenme_md(r: dict, birimler: list[dict]) -> str:
    zaman = {b["id"]: sn_ass(b["start"])[:-3] for b in birimler}
    o = r.get("measurements", {})
    t = REPORT
    s = [f"# {t['title'].format(episode=r.get('episode', ''))}", "",
         f"**{r['cefr']}** · {t['suitability'].get(r['suitability'], r['suitability'])} · {t['confidence']}: "
         f"{t['confidence_levels'].get(r['confidence'], r['confidence'])}", "", r["summary"], ""]
    if o:
        s += [t["reading_load"].format(wpm=o["words_per_minute"], median=o["cps_median"], p90=o["cps_p90"],
                                       fast=o["fast_line_percent"], unique=o["unique_words"]), ""]
    if r.get("difficulties"):
        s += [f"**{t['difficulties']}:** " + "; ".join(r["difficulties"]), ""]
    s += [f"## {t['expressions']}", "", "| " + " | ".join(t["expression_columns"]) + " |", "|---|---|---|---|---|"]
    for n in r.get("expressions", []):
        s.append(f"| {zaman.get(n['id'], '')} | {n['quote']} | {n['kind']} | {n['meaning']} | {n['usefulness']} |".replace("\n", " "))
    s += ["", f"## {t['evidence']}", ""] + [f"- {zaman.get(k['id'], '')} “{k['quote']}” — {k['reason']}" for k in r.get("evidence", [])]
    s += ["", f"_{t['note']} {t['profile']}: {r['profile']}_", ""]
    return "\n".join(s)


def uyari_olaylari(birimler: list[dict], sahneler: list[dict], bicim: list[str]) -> tuple[list[str], list[dict]]:
    bul = {b["id"]: b for b in birimler}
    araliklar = []
    for s in sahneler:
        b1, b2 = bul.get(str(s.get("first_id"))), bul.get(str(s.get("last_id")))
        if b1:
            araliklar.append([b1["start"], max(b1["end"], (b2 or b1)["end"]), s.get("reason") or LABELS["sensitive_scene"]])
    araliklar.sort()
    birlesik = []
    for bas, son, neden in araliklar:
        if birlesik and bas - birlesik[-1][1] < 20:
            birlesik[-1][1] = max(birlesik[-1][1], son)
            if neden not in birlesik[-1][2]:
                birlesik[-1][2].append(neden)
        else:
            birlesik.append([bas, son, [neden]])
    olaylar, kayit = [], []
    for bas, son, nedenler in birlesik:
        bitis = son + 5
        gosterim_bas = max(0, bas - 4)
        metin = LABELS["warning"].format(reasons=", ".join(nedenler)[:40], until=f"{int(bitis // 60)}:{int(bitis % 60):02d}")
        alan = {"layer": "9", "start": sn_ass(gosterim_bas), "end": sn_ass(bitis), "style": "ContentWarning",
                "name": "", "marginl": "0", "marginr": "0", "marginv": "0", "effect": "", "text": metin}
        olaylar.append("Dialogue: " + ",".join(alan.get(k, "") for k in bicim))
        kayit.append({"start": round(bas, 2), "end": round(son, 2), "skip_until": round(bitis, 2), "reasons": nedenler,
                      "method": "inferred from dialogue"})
    return olaylar, kayit


def uyari_katmani(a: dict, birimler: list[dict], tarama: dict, ass: "Ass") -> tuple[list[str], list[dict], str | None]:
    """Warning events, record ranges and the overlay style for a finished scan (an unavailable scan stays loud)."""
    gecerli = [s for s in tarama["scenes"] if "error" not in s] + tarama.get("unscanned", [])
    if birimler and tarama["status"] == "failed":
        gecerli = [{"first_id": birimler[0]["id"], "last_id": birimler[0]["id"], "reason": LABELS["scan_unavailable_episode"]}]
    if not gecerli:
        return [], [], None
    ek_olaylar, kayit = uyari_olaylari(birimler, gecerli, ass.bicim)
    boyut = max(12, round(ass.play_res_y() * 0.042))
    ek_stil = ass.stil_satiri("ContentWarning", {"fontsize": boyut, "primarycolour": "&H0000E5FF", "bold": -1,
                                                 "outline": max(1, boyut // 18), "alignment": 8, "marginv": max(10, boyut // 2)})
    return ek_olaylar, kayit, ek_stil


def not_katmani(a: dict, birimler: list[dict], notlar: dict[str, str], ass: "Ass", uyarilar: list[dict],
                haric: set) -> tuple[list[str], list[dict], str | None]:
    """Translator notes as top-of-screen events: the first NOT_SINIRI by time, each on screen for its unit (at least 2.5 s,
    longer when needed for reading), never into the next note; moved below a warning or top-placed dialogue it overlaps."""
    bul = {b["id"]: b for b in birimler}
    adaylar = sorted((bul[i]["start"], i, t) for i, t in notlar.items() if i in bul and i not in haric)
    if len(adaylar) > NOT_SINIRI:
        log(f"Translator notes: {len(adaylar)} proposed, the first {NOT_SINIRI} kept ({', '.join(i for _, i, _ in adaylar[NOT_SINIRI:])} dropped).")
    adaylar = adaylar[:NOT_SINIRI]
    secik = []
    for x in adaylar:  # two notes less than 0.55 s apart would sit on top of each other
        if secik and x[0] - secik[-1][0] < 0.55:
            log(f"Translator note {x[1]} dropped: it starts within 0.55 s of the previous note.")
            continue
        secik.append(x)
    adaylar = secik
    if not adaylar:
        return [], [], None
    yukseklik = ass.play_res_y()
    boyut, uyari_boyut = max(10, round(yukseklik * 0.034)), max(12, round(yukseklik * 0.042))
    taban = max(10, uyari_boyut // 2)
    stil = ass.stil_satiri("TranslatorNote", {"fontsize": boyut, "italic": -1, "alignment": 8, "marginv": taban,
                                              "outline": max(1, boyut // 18)})
    if stil is None:  # without a Styles section the note would fall back to the bottom default style
        log("Translator notes skipped: the subtitle file has no Styles section.")
        return [], [], None
    ust_stil = ass.ust_stiller()
    i_katman = ass.bicim.index("layer") if "layer" in ass.bicim else None
    ustte = [(ass.bas(o), ass.son(o), o["fields"][i_katman].strip() if i_katman is not None else "0") for o in ass.olaylar
             if re.search(r"\\an[789]|\\a[567](?!\d)", ass.metin(o)) or ass.stil(o) in ust_stil]
    ustte += [(max(0, u["start"] - 4), u["skip_until"], "9") for u in uyarilar]
    cps = a.get("target_cps", 17) or 17
    olaylar, kayit = [], []
    for k, (bas, i, metin) in enumerate(adaylar):
        son = max(bas + 2.5, bul[i]["end"], bas + columns(metin) / cps)
        if k + 1 < len(adaylar):
            son = min(son, adaylar[k + 1][0] - 0.05)
        son = max(son, bas + 0.5)
        katmanlar = {katman for b0, b1, katman in ustte if b0 < son and b1 > bas}
        cakisma = bool(katmanlar)
        # One overlapped layer: share it, so the renderer stacks the note below that line. Several: move it down by hand.
        katman = next(iter(katmanlar)) if len(katmanlar) == 1 else "8"
        alan = {"layer": katman, "start": sn_ass(bas), "end": sn_ass(son), "style": "TranslatorNote", "name": "",
                "marginl": "0", "marginr": "0", "marginv": str(taban + round(uyari_boyut * 1.6)) if len(katmanlar) > 1 else "0",
                "effect": "", "text": satir_kir(metin, a.get("satir_sinir", 42))}
        olaylar.append("Dialogue: " + ",".join(alan.get(c, "") for c in ass.bicim))
        kayit.append({"id": i, "start": round(bas, 2), "text": metin, "moved": cakisma})
    return olaylar, kayit, stil


def bolum_no(ad: str) -> int | None:

    temiz = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", ad)
    temiz = re.sub(r"(?<![A-Za-z0-9])(?:x26[45]|h[.]?26[45]|(?:480|720|1080|2160)p|10-?bit|(?:AAC|DDP)\d+(?:[.]\d+)?)(?![A-Za-z0-9])",
                   " ", temiz, flags=re.I)
    son = r"(?:v\d+)?(?![A-Za-z0-9])"
    sezon = r"(?<![A-Za-z0-9])S\d+[ _.-]*E(\d{1,3})" + son
    episode = r"(?<![A-Za-z0-9])Episode[ _.]*(\d{1,3})" + son
    ep = r"(?<![A-Za-z0-9])EP?[ _.]*(\d{1,3})" + son
    tire = r"[ _-]-[ _]*(\d{1,3})" + son
    for metin, desenler in ((temiz, (sezon, episode, ep, tire)), (ad, (sezon, ep, episode))):
        for desen in desenler:
            m = re.search(desen, metin, re.I)
            if m:
                return int(m.group(1))
    m = re.search(r"\[\s*(\d{1,3})(?:v\d+)?\s*\]|\(\s*(\d{1,3})(?:v\d+)?\s*\)", ad, re.I)
    if m:
        return int(m.group(1) or m.group(2))
    sayilar = re.findall(r"(?<![A-Za-z0-9])(\d{2,3})" + son, temiz, re.I)
    return int(sayilar[-1]) if sayilar else None


def sezon_no(ad: str) -> int | None:
    """Season number in a file or folder name (S02E05, Season 2, Season_02), or None."""
    m = re.search(r"(?<![A-Za-z0-9])S(\d{1,2})[ _.-]*E\d{1,3}", ad, re.I) or re.search(r"(?<![A-Za-z0-9])Season[ _.-]*(\d{1,2})(?![0-9])", ad, re.I)
    return int(m.group(1)) if m else None


def klasor_adi(ad: str) -> str:
    """A title used as a folder name never contains a path separator or a parent reference."""
    ad = re.sub(r"\s+", " ", re.sub(r"[/\\]+|\.\.+", " ", ad)).strip(" .-")
    return ad or "Untitled"


def bolum_isle(a: dict, eser: str, sezon: int, no: int | None, video: Path | None, kaynak_ass: Path | None,
               rehber: str, seri_dosyasi: Path, mux: bool, ses: str | None, insan: dict | None = None) -> dict:
    global HATA_DOSYASI
    etiket = f"S{sezon:02d}E{no:02d}" if no is not None else "Movie"
    is_dir = a["work_dir"] / eser / etiket
    is_dir.mkdir(parents=True, exist_ok=True)
    HATA_DOSYASI = is_dir / "errors.jsonl"
    baslangic = run_start(is_dir)
    ass, iz = kaynagi_hazirla(is_dir, video, kaynak_ass)
    if a.get("honorific_comments") is True and onursal_uygula(ass):
        log("Honorific comments unwrapped into the source text.")
    birimler, esleme = birimleri_cikar(ass)
    eski_birim = joku(is_dir / "units.json")
    if eski_birim is not None and [(b["id"], b["text"]) for b in eski_birim] != [(b["id"], b["text"]) for b in birimler] \
            and any(any((is_dir / "translations").glob(desen)) for desen in
                    ("[0-9][0-9][0-9].json", "[0-9][0-9][0-9].partial.json")):

        # Never apply completed chunks to newly numbered source units.
        raise BolumHatasi("Source units changed after this job started (code or source changed); stopped to prevent mixed "
                          "translations. Use --redo to archive this job and restart.")
    jyaz(is_dir / "units.json", birimler)
    seri = seri_dosyasi.read_text(encoding="utf-8")
    sansur_acik = a["content_warnings"] is True
    sarki_onbellek_yolu = seri_dosyasi.parent / "songs.json"
    sarki_onbellek = joku(sarki_onbellek_yolu, {})

    plan_yolu = is_dir / "plan.json"
    # Freeze cached songs and chunk boundaries so later settings cannot shift saved IDs.
    plan = joku(plan_yolu, None)
    if plan is None:
        eski_is = (is_dir / "translations").exists() and any((is_dir / "translations").glob("[0-9][0-9][0-9].json"))
        plan = {"cached": {} if eski_is else {b["id"]: sarki_onbellek[b["text"]] for b in birimler
                                                   if b["kind"] == "song" and b["text"] in sarki_onbellek},
                "chunks": [40, 60] if eski_is else [a["translate_chunk"], a["review_chunk"]]}
        jyaz(plan_yolu, plan)

    parca_ceviri, parca_inceleme = plan.get("chunks", [40, 60])
    ceviri: dict[str, str] = dict(plan["cached"])
    yapilacak = [b for b in birimler if b["id"] not in ceviri]
    log(f"{eser} {etiket}: {len(ass.olaylar)} events, {len(birimler)} unique units, {len(yapilacak)} to translate.")

    hafiza = hafiza_yukle(a, eser, seri_dosyasi.parent)
    baglam = None
    eski_is = (is_dir / "translations").exists() and any((is_dir / "translations").glob("[0-9][0-9][0-9].json")) and not (is_dir / "episode-context.json").exists()
    if yapilacak and not eski_is:
        try:
            baglam = bolum_baglami(a, ass, birimler, seri, hafiza, rehber, is_dir, etiket)
        except GuvenlikEngeli as e:
            log(f"Episode context blocked by safety; using series guide and memory ({e})")
        # The context is a delta: remembered decisions of earlier episodes go to translators, reviewers and the gate too.
        hafiza_yazi = hafiza_metni(hafiza, etiket)
        if hafiza_yazi:
            seri = seri + "\n\n---- SERIES MEMORY (decisions of earlier episodes) ----\n" + hafiza_yazi
        if baglam:
            if baglam_metni(baglam):
                seri = seri + "\n\n---- EPISODE CONTEXT (binding for all chunks) ----\n" + baglam_metni(baglam)
            konusmaci_ata(birimler, baglam.get("turns", []))

    parcalar = sahne_parcala(yapilacak, parca_ceviri)
    kullanim, cevrilemedi, filtre, notlar = [], [], [], {}
    with cf.ThreadPoolExecutor(a["parallel"]) as havuz:
        isler, bas_i = [], 0
        for k, p in enumerate(parcalar):
            onceki = yapilacak[max(0, bas_i - 6):bas_i]
            sonraki = yapilacak[bas_i + len(p):bas_i + len(p) + 4]
            isler.append(havuz.submit(cevir_parca, a, k + 1, p, onceki, sonraki, rehber, seri, is_dir))
            bas_i += len(p)
        sansur_isi = havuz.submit(sansur_tara, a, birimler, is_dir) if sansur_acik else None
        ogrenme_isi = havuz.submit(ogrenme_raporu, a, birimler, is_dir, f"{eser} {etiket}") if a["level_report"] else None
        for f in isler:
            s = f.result()
            ceviri.update(s["translations"]); kullanim += s["usage"]; cevrilemedi += s["untranslated"]; filtre += s.get("blocked", [])
            notlar.update(s.get("notes", {}))
        tarama = sansur_isi.result() if sansur_isi else {"status": "off", "scenes": [], "unscanned": []}
        ogrenme = ogrenme_isi.result() if ogrenme_isi else None
    if len(cevrilemedi) > max(3, len(birimler) // 50):
        for f in (is_dir / "translations").glob("[0-9][0-9][0-9].json"):
            if joku(f).get("untranslated"):
                parca_yarima_al(f, kullanim_devami=True)
        raise BolumHatasi(f"{len(cevrilemedi)} units untranslated (model error); rerun the same command")

    for i in filtre:
        ceviri[i] = next(b["text"] for b in birimler if b["id"] == i)
    incelenecek = [b for b in birimler if b["id"] in ceviri and b["id"] in {x["id"] for x in yapilacak} and b["id"] not in filtre]
    iparcalar = sahne_parcala(incelenecek, parca_inceleme)
    duzeltmeler, incelenemedi, filtre_inceleme, tuzaklar, eksik_okuma = [], 0, [], [], 0
    with cf.ThreadPoolExecutor(a["parallel"]) as havuz:
        isler, bas_i = [], 0
        for k, p in enumerate(iparcalar):
            isler.append(havuz.submit(incele_parca, a, k + 1, p, ceviri, rehber, seri, is_dir,
                                      incelenecek[max(0, bas_i - 3):bas_i], incelenecek[bas_i + len(p):bas_i + len(p) + 3]))
            bas_i += len(p)
        for f, p in zip(isler, iparcalar):
            try:
                s = f.result()
                duzeltmeler += s["corrections"]; kullanim += s["usage"]; filtre_inceleme += s.get("blocked", []); tuzaklar.append(s.get("trap", [])); eksik_okuma += bool(s.get("possibly_incomplete"))
            except ModelHatasi as e:
                incelenemedi += len(p)
                log(f"Review chunk unavailable: {e}")
    if incelenemedi:
        raise BolumHatasi(f"{incelenemedi} units unreviewed; rerun the same command")
    bul = {b["id"]: b for b in birimler}
    uygulanan, reddedilen = [], []
    for d in duzeltmeler:
        b = bul[d["id"]]
        yeni_metin = metin_temizle(d["new"])
        if _sade(yeni_metin) == _sade(ceviri[d["id"]]):
            reddedilen.append({**d, "rejected": "no change"})
            continue
        if ISARET.findall(yeni_metin) != ISARET.findall(b["text"]) or (not cjk_allowed() and CJK.search(yeni_metin)):
            reddedilen.append({**d, "rejected": "broken format marker or invalid script"})
            continue
        uygulanan.append({"id": d["id"], "category": d.get("category"), "source": b["text"], "before": ceviri[d["id"]],
                          "after": yeni_metin, "reason": d["reason"]})
    son_d = {d["id"]: d for d in uygulanan}  # two corrections for one unit: the last one stays, counted and gated once
    reddedilen += [{**d, "rejected": "superseded by a later correction of the same unit"} for d in uygulanan if son_d[d["id"]] is not d]
    uygulanan = list(son_d.values())
    kapi = (anlam_kapisi(a, uygulanan, rehber, is_dir, seri, birimler)
            if a.get("meaning_gate", True) else {"status": "off", "rejected": {}})
    reddedilen += [{**d, "rejected": f"meaning gate: {kapi['rejected'][d['id']]}"} for d in uygulanan if d["id"] in kapi["rejected"]]
    uygulanan = [d for d in uygulanan if d["id"] not in kapi["rejected"]]
    for d in uygulanan:
        ceviri[d["id"]] = d["after"]
    jyaz(is_dir / "corrections.json", {"applied": uygulanan, "rejected": reddedilen, "meaning_gate": kapi["status"]})
    for i in cevrilemedi:
        ceviri[i] = bul[i]["text"]


    yeni, isaret_uyari, hizli = {}, 0, 0
    for sira, e in esleme.items():
        b = bul[e["id"]]
        metin, uyari = olaya_yerlestir(ceviri[e["id"]], e, b["kind"], a["satir_sinir"])
        yeni[sira] = metin
        isaret_uyari += uyari
    uzatilan = sure_uzat(ass, esleme, {b["id"]: b["kind"] for b in birimler}, yeni, a.get("target_cps", 17), a.get("max_extension_seconds", 1.5))
    for o in ass.olaylar:  # the fast-line counter and break gaps see the extended end (first event of each unit)
        b = bul[esleme[o["index"]]["id"]] if o["index"] in esleme else None
        if b and abs(ass.bas(o) - b["start"]) < 0.005:
            b["end"] = max(b["end"], ass.son(o))
    for b in birimler:
        sure = max(0.3, b["end"] - b["start"])
        if b["kind"] == "dialogue" and columns(ISARET.sub("", ceviri[b["id"]]).replace("\\N", " ")) / sure > a.get("reading_speed_threshold", 20):
            hizli += 1
    ek_olaylar, sansur_kayit, ek_stil = uyari_katmani(a, birimler, tarama, ass) if sansur_acik else ([], [], None)
    secilen_notlar = []
    if a.get("translator_notes") is True and notlar:
        not_ev, secilen_notlar, not_stil = not_katmani(a, birimler, notlar, ass, sansur_kayit, set(cevrilemedi) | set(filtre))
        ek_olaylar += not_ev
        ek_stil = "\n".join(x for x in (ek_stil, not_stil) if x) or None
    jyaz(is_dir / "warnings.json", {"level": a["content_warnings"], "status": tarama["status"], "ranges": sansur_kayit, "scan": tarama})
    final = is_dir / "final.ass"
    final_metin = ass.yaz(yeni, ek_olaylar, ek_stil)
    font_degisen = []
    if video:
        final_metin, font_degisen = font_duzelt(final_metin, video_fontlari(video))
        if font_degisen:
            log(f"Font adjustments ({len(font_degisen)}): " + "; ".join(font_degisen))
    final.write_text(final_metin, encoding="utf-8")
    untranslated_ids = set(cevrilemedi) | set(filtre)
    for b in birimler:
        if b["kind"] == "song" and b["id"] not in untranslated_ids and _sade(ceviri[b["id"]]).lower() != _sade(b["text"]).lower():
            sarki_onbellek[b["text"]] = ceviri[b["id"]]
    jyaz(sarki_onbellek_yolu, sarki_onbellek)
    if baglam:
        hafiza_guncelle(seri_dosyasi.parent, baglam, etiket)


    ad, arsiv_ass = kutuphaneye_koy(a, eser, sezon, no, etiket, final)
    paket = None
    if mux and video:
        ek = []
        if insan and insan.get("timing_match", 0) >= 0.7:
            hizali = is_dir / "human" / "aligned.ass"
            hizali.write_text(ass_kaydir(Path(insan["ass"]).read_text(encoding="utf-8", errors="replace"), insan["offset_seconds"]), encoding="utf-8")
            ek = [(hizali, LABELS["human_track"].format(language=TARGET.get("display", TARGET["name"])))]
        molalar = []
        if a["break_chapters"]:
            molalar = mola_sec(durak_adaylari(a, birimler, is_dir, baglam), birimler, video_suresi(video))
            jyaz(is_dir / "breaks.json", {"selected": molalar})
            log(f"Viewing breaks: " + (", ".join(f"{int(m['t'] // 60)}:{int(m['t'] % 60):02d} ({m['reason']})" for m in molalar)
                                      if molalar else "no suitable break found; none added."))
        paket = paketle(video, final, a["watch"] / eser / f"{ad}.mkv", ses, yedek_font=bool(font_degisen), ek=ek, molalar=molalar)
        if a["level_report"] and (is_dir / "level.md").exists():
            shutil.copyfile(is_dir / "level.md", a["watch"] / eser / f"{ad} - {LABELS['level_file']}.md")
    toplam = {k: sum(kullanim_sayilari(u)[k] for u in kullanim) for k in ("input_tokens", "output_tokens", "thinking_tokens")}
    kayit = {"version": SURUM, "date": dt.datetime.now().isoformat(timespec="seconds"), "title": eser, "episode": etiket,
             "source": str(video or kaynak_ass), "source_language": SOURCE["code"], "target_language": TARGET["code"], "track": iz, "guide_hash": sha(rehber), "series_hash": sha(seri),
             "models": {"model_" + r: a.get("model_" + r) for r in ROLES},
             "backend": a.get("backend"), "chunks": [parca_ceviri, parca_inceleme],
             "events": len(ass.olaylar), "units": len(birimler), "translated_count": len(yapilacak),
             "cached_songs": len(birimler) - len(yapilacak), "correction_count": len(uygulanan),
             "rejected_corrections": len(reddedilen), "meaning_gate": {"status": kapi["status"], "rejected": len(kapi["rejected"])},
             "untranslated": cevrilemedi, "blocked_translation": filtre, "blocked_review": filtre_inceleme,
             "review_traps": {"inserted": sum(1 for t in tuzaklar if t), "missed_first": sum(1 for t in tuzaklar if t and t[0] is False),
                                "missed_twice": sum(1 for t in tuzaklar if len(t) > 1 and t[-1] is False),
                                "possibly_unread": eksik_okuma},
             "fast_lines": hizli, "extended_lines": uzatilan, "translator_notes": secilen_notlar,
             "broken_markers": isaret_uyari,
             "human_translation": ({k: insan.get(k) for k in ("source", "score", "decision", "coverage", "timing_match", "reason", "summary")}
                                if insan else None), "font_changes": font_degisen, "warning_count": len(sansur_kayit), "warning_status": tarama["status"], "usage": toplam,
             "episode_context": "present" if baglam else ("resumed job" if eski_is else "failed"),
             "level_report": ({"cefr": ogrenme["cefr"], "suitability": ogrenme["suitability"]} if ogrenme and "cefr" in ogrenme
                         else ({"error": ogrenme.get("error")} if ogrenme else None)),
             "minutes": run_minutes(is_dir), "minutes_this_run": round((time.time() - baslangic) / 60, 1),
             "library_dir": str(arsiv_ass), "package": paket,
             "receipts": receipt_summary(is_dir.parent / "receipts.jsonl", etiket, joku(is_dir / "runs.json")[0]["start"])}
    jyaz(is_dir / "record.json", kayit)
    hedef_arsiv = a["jobs_dir"] / eser / etiket
    hedef_arsiv.mkdir(parents=True, exist_ok=True)
    is_arsivini_yedekle(hedef_arsiv, final)
    for f in ("source.ass", "final.ass", "units.json", "plan.json", "episode-context.json", "corrections.json", "meaning-gate.json", "warnings.json", "warning-scan.json", "level.json", "level.md", "breaks.json", "break-candidates.json",
              "record.json", "track.json", "errors.jsonl", "runs.json"):
        if (is_dir / f).exists():
            shutil.copyfile(is_dir / f, hedef_arsiv / f)
    for alt in ("translations", "review", "human"):
        if (is_dir / alt).exists():
            shutil.copytree(is_dir / alt, hedef_arsiv / alt, dirs_exist_ok=True)
    shutil.copyfile(seri_dosyasi, hedef_arsiv / "series.md")
    if (is_dir.parent / "receipts.jsonl").exists():  # every call of the title, tagged by episode
        shutil.copyfile(is_dir.parent / "receipts.jsonl", hedef_arsiv.parent / "receipts.jsonl")
    if (seri_dosyasi.parent / "memory.json").exists():
        shutil.copyfile(seri_dosyasi.parent / "memory.json", hedef_arsiv / "memory.json")
    log(f"DONE {eser} {etiket}: {len(birimler)} units, {len(uygulanan)} corrections, {len(sansur_kayit)} warnings. "
        f"ASS: {arsiv_ass}" + (f" · MKV: {paket['file']}" if paket else ""))
    if ogrenme and "cefr" in ogrenme:
        ogrenme_ozeti(a, eser, sezon if no is not None else None)
    return kayit


def video_suresi(video: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True)
    return float(p.stdout.strip() or 0)


def kutuphaneye_koy(a: dict, eser: str, sezon: int, no: int | None, etiket: str, final: Path) -> tuple[str, Path]:
    ad = f"{eser} {etiket} [{TARGET['code'].upper()}]" if no is not None else f"{eser} [{TARGET['code'].upper()}]"
    sezon_dir = a["library_dir"] / eser / (f"Season {sezon:02d}" if no is not None else "")
    sezon_dir.mkdir(parents=True, exist_ok=True)
    arsiv_ass = sezon_dir / f"{ad}.ass"
    if arsiv_ass.exists() and sha(arsiv_ass) != sha(final):

        onceki_dir = a["jobs_dir"] / eser / etiket / "previous"
        onceki_dir.mkdir(parents=True, exist_ok=True)
        damga = dt.datetime.fromtimestamp(arsiv_ass.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
        shutil.move(str(arsiv_ass), onceki_dir / f"{ad} {damga}.ass")
        log(f"Previous ASS moved to job archive: {onceki_dir}")
    shutil.copyfile(final, arsiv_ass)
    return ad, arsiv_ass


def is_arsivini_yedekle(hedef_arsiv: Path, final: Path) -> None:
    if (hedef_arsiv / "final.ass").exists() and sha(hedef_arsiv / "final.ass") != sha(final):

        kopya = hedef_arsiv / "previous" / f"job-{dt.datetime.fromtimestamp((hedef_arsiv / 'final.ass').stat().st_mtime):%Y%m%d-%H%M%S}"
        if kopya.exists():
            kopya = kopya.with_name(f"{kopya.name}-{time.time_ns()}")
        shutil.copytree(hedef_arsiv, kopya, ignore=shutil.ignore_patterns("previous"), dirs_exist_ok=True)


def insan_teslim(a: dict, eser: str, sezon: int, no: int | None, video: Path, secim: dict, ses: str | None, mux: bool) -> dict:
    global HATA_DOSYASI
    etiket = f"S{sezon:02d}E{no:02d}" if no is not None else "Movie"
    is_dir = a["work_dir"] / eser / etiket
    HATA_DOSYASI = is_dir / "errors.jsonl"
    baslangic = run_start(is_dir)
    final = is_dir / "final.ass"
    metin = ass_kaydir(Path(secim["ass"]).read_text(encoding="utf-8", errors="replace"), secim["offset_seconds"])
    kaynak_var = (is_dir / "source.ass").exists()  # without a source track, breaks and the level report are skipped
    tarama, sansur_kayit = {"status": "off", "scenes": [], "unscanned": []}, []
    if a.get("content_warnings") is True:
        insan_ass = Ass(metin)
        taranan = Ass((is_dir / "source.ass").read_text(encoding="utf-8", errors="replace")) if kaynak_var else insan_ass
        tb, _ = birimleri_cikar(taranan)
        tarama = sansur_tara(a, tb, is_dir)
        ek_olaylar, sansur_kayit, ek_stil = uyari_katmani(a, tb, tarama, insan_ass)
        if ek_olaylar:
            metin = insan_ass.yaz({}, ek_olaylar, ek_stil)
        jyaz(is_dir / "warnings.json", {"level": a["content_warnings"], "status": tarama["status"], "ranges": sansur_kayit, "scan": tarama})
    metin, font_degisen = font_duzelt(metin, video_fontlari(video))
    final.write_text(metin, encoding="utf-8")
    ad, arsiv_ass = kutuphaneye_koy(a, eser, sezon, no, etiket, final)
    molalar = []
    if mux and a["break_chapters"] and kaynak_var:
        kb, _ = birimleri_cikar(Ass((is_dir / "source.ass").read_text(encoding="utf-8", errors="replace")))
        molalar = mola_sec(durak_adaylari(a, kb, is_dir, None), kb, video_suresi(video))
        jyaz(is_dir / "breaks.json", {"selected": molalar})
    paket = paketle(video, final, a["watch"] / eser / f"{ad}.mkv", ses, yedek_font=bool(font_degisen), molalar=molalar) if mux else None
    ogrenme = None
    if a["level_report"] and kaynak_var:
        birimler, _ = birimleri_cikar(Ass((is_dir / "source.ass").read_text(encoding="utf-8", errors="replace")))
        ogrenme = ogrenme_raporu(a, birimler, is_dir, f"{eser} {etiket}")
        if paket and (is_dir / "level.md").exists():
            shutil.copyfile(is_dir / "level.md", a["watch"] / eser / f"{ad} - {LABELS['level_file']}.md")
    kayit = {"version": SURUM, "date": dt.datetime.now().isoformat(timespec="seconds"), "title": eser, "episode": etiket,
             "source_type": "human translation", "models": {"model_" + r: a.get("model_" + r) for r in ROLES},
             "human": {k: secim.get(k) for k in ("source", "kind", "score", "professional", "offset_seconds", "timing_match",
                                                                                  "coverage", "summary", "examples")},
             "source": str(video), "font_changes": font_degisen, "library_dir": str(arsiv_ass), "package": paket,
             "level_report": {"cefr": ogrenme["cefr"], "suitability": ogrenme["suitability"]} if ogrenme and "cefr" in ogrenme else None,
             "units": 0, "correction_count": 0, "warning_count": len(sansur_kayit), "warning_status": tarama["status"],
             "untranslated": [], "minutes": run_minutes(is_dir),
             "minutes_this_run": round((time.time() - baslangic) / 60, 1),
             "receipts": receipt_summary(is_dir.parent / "receipts.jsonl", etiket, joku(is_dir / "runs.json")[0]["start"])}
    jyaz(is_dir / "record.json", kayit)
    hedef = a["jobs_dir"] / eser / etiket
    hedef.mkdir(parents=True, exist_ok=True)
    is_arsivini_yedekle(hedef, final)
    for f in ("source.ass", "final.ass", "record.json", "track.json", "level.json", "level.md", "breaks.json", "break-candidates.json", "runs.json",
              "warnings.json", "warning-scan.json", "errors.jsonl"):
        if (is_dir / f).exists():
            shutil.copyfile(is_dir / f, hedef / f)
    shutil.copytree(is_dir / "human", hedef / "human", dirs_exist_ok=True)
    if (is_dir.parent / "receipts.jsonl").exists():
        shutil.copyfile(is_dir.parent / "receipts.jsonl", hedef.parent / "receipts.jsonl")
    if secim["kind"] == "file":
        shutil.copyfile(secim["source"], hedef / "human" / ("original-" + Path(secim["source"]).name))
    if ogrenme and "cefr" in ogrenme:
        ogrenme_ozeti(a, eser, sezon if no is not None else None)
    log(f"DONE {eser} {etiket}: human translation used ({secim.get('professional') or 'score ' + str(secim['score'])}, offset {secim['offset_seconds']} seconds). ASS: {arsiv_ass}"
        + (f" · MKV: {paket['file']}" if paket else ""))
    return kayit


def kaynagi_hazirla(is_dir: Path, video: Path | None, kaynak_ass: Path | None) -> tuple["Ass", dict]:
    RECEIPT[:] = [is_dir.parent / "receipts.jsonl", is_dir.name]
    kaynak = is_dir / "source.ass"
    iz = {}
    if not kaynak.exists():
        gecici = is_dir / "source.writing.ass"
        if gecici.exists():
            gecici.rename(gecici.with_name(f"source.writing-{time.time_ns()}.ass"))
        if kaynak_ass:
            _ass_yap(kaynak_ass, gecici)
        else:
            iz = altyazi_sec(video, gecici)
        iz = {**iz, "video": str(video) if video else None, "video_size": video.stat().st_size if video else None,
              "external_source": str(kaynak_ass) if kaynak_ass else None,
              "external_source_sha": sha(kaynak_ass) if kaynak_ass else None}
        jyaz(is_dir / "track.json", iz)
        os.replace(gecici, kaynak)
    else:
        iz = joku(is_dir / "track.json", {})
        # A changed source subtitle would otherwise resume silently on the old one.
        if kaynak_ass and iz and (iz.get("external_source_sha") != sha(kaynak_ass) if iz.get("external_source_sha")
                                  else iz.get("external_source") != str(kaynak_ass)):
            raise BolumHatasi(f"The source subtitle differs from the one this job started with ({iz.get('external_source') or 'embedded track'}); "
                              "use --redo to archive this job and restart with the new file")
    if video and iz.get("video_size") and iz["video_size"] != video.stat().st_size:
        raise BolumHatasi(f"This job directory belongs to a different video ({iz.get('video')}); two videos may share an episode number")
    return Ass(kaynak.read_text(encoding="utf-8", errors="replace")), iz


def duzey_isle(a: dict, eser: str, sezon: int, no: int | None, video: Path | None, kaynak_ass: Path | None) -> dict:
    etiket = f"S{sezon:02d}E{no:02d}" if no is not None else "Movie"
    is_dir = a["work_dir"] / eser / etiket
    is_dir.mkdir(parents=True, exist_ok=True)
    RECEIPT[:] = [is_dir.parent / "receipts.jsonl", is_dir.name]
    ass, _ = kaynagi_hazirla(is_dir, video, kaynak_ass)
    if a.get("honorific_comments") is True:
        onursal_uygula(ass)
    birimler, _ = birimleri_cikar(ass)
    r = ogrenme_raporu(a, birimler, is_dir, f"{eser} {etiket}")
    if "cefr" not in r:
        raise BolumHatasi(f"Level report unavailable: {r.get('error')}")
    hedef = a["jobs_dir"] / eser / etiket
    hedef.mkdir(parents=True, exist_ok=True)
    if (is_dir.parent / "receipts.jsonl").exists():
        shutil.copyfile(is_dir.parent / "receipts.jsonl", hedef.parent / "receipts.jsonl")
    for f in ("level.json", "level.md"):
        shutil.copyfile(is_dir / f, hedef / f)
    ogrenme_ozeti(a, eser, sezon if no is not None else None)
    return {"episode": etiket, "cefr": r["cefr"], "suitability": r["suitability"], "report": str(hedef / "level.md")}


def ogrenme_ozeti(a: dict, eser: str, sezon: int | None) -> Path:
    satirlar = []
    desen = f"S{sezon:02d}E*/level.json" if sezon else "Movie/level.json"
    for f in sorted((a["jobs_dir"] / eser).glob(desen)):
        r = joku(f)
        if "cefr" in r:
            o = r.get("measurements", {})
            satirlar.append(f"| {f.parent.name} | {r['cefr']} | {REPORT['suitability'].get(r['suitability'], r['suitability'])} | "
                            f"{o.get('words_per_minute', '')} | {o.get('cps_p90', '')} | {r['summary']} |".replace("\n", " "))
    hedef_dir = a["library_dir"] / eser / (f"Season {sezon:02d}" if sezon else "")
    hedef_dir.mkdir(parents=True, exist_ok=True)
    yol = hedef_dir / f"{LABELS['level_file']}.md"
    yol.write_text("\n".join([f"# {REPORT['season_title'].format(title=eser)}", "",
                              "| " + " | ".join(REPORT["season_columns"]) + " |",
                              "|---|---|---|---|---|---|", *satirlar, "",
                              f"_{REPORT['season_note']}_", ""]),
                   encoding="utf-8")
    return yol


BACKENDS = ("openai", "agy", "codex", "claude-code")
CLI_NAMES = {"agy": "agy", "codex": "codex", "claude-code": "claude"}
MODEL_EXAMPLES = {"openai": "gpt-4.1-mini", "agy": "gemini-2.5-flash", "codex": "gpt-5:medium", "claude-code": "sonnet"}
RUN_STATS = {"stage_tokens": {}, "errors": set()}
ERROR_CATEGORIES = frozenset(("quota", "safety_block", "schema_invalid", "timeout", "mux_failed", "authentication", "configuration", "connection", "other"))
STAGES = ("translate", "review", "gate", "series", "context", "warnings", "level", "breaks", "human")
FEATURES = ("level_report", "content_warnings", "break_chapters", "human_check")
ISSUE_URL = "https://github.com/Abdulaziz-kiran/dragoman/issues/new"


def config_path(config=None) -> Path:
    return Path(config).expanduser() if config else KOK / "config.json"


def update_config(changes: dict, config=None) -> None:
    path = config_path(config)
    existing = joku(path, {})
    if not isinstance(existing, dict):
        raise ValueError("Config must be a JSON object; fix it before running --setup")
    jyaz(path, {**existing, **changes})


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def error_category(error) -> str:
    text = str(error).lower()
    if isinstance(error, GuvenlikEngeli) or any(x in text for x in GUVENLIK):
        return "safety_block"
    if any(x in text for x in ("quota", "429", "rate limit", "exhaust")):
        return "quota"
    if any(x in text for x in ("timeout", "timed out")):
        return "timeout"
    if any(x in text for x in ("schema", "required key", "json", "reply must", "invalid reply")):
        return "schema_invalid"
    if any(x in text for x in ("mux", "package verification", "ffmpeg", "ffprobe")):
        return "mux_failed"
    if any(x in text for x in ("sign in", "signed in", "logged in", "login", "authentication", "unauth", "401", "403", "api key", "api_key")):
        return "authentication"
    if any(x in text for x in (*YAPILANDIRMA, "configuration", "cli not found", "backend and model")):
        return "configuration"
    if any(x in text for x in ("unreachable", "connection", "urlopen", "name or service", "url error")):
        return "connection"
    return "other"


def provider_fix(error, a: dict) -> str | None:
    """Known provider failures have one actionable line, without provider payloads or secrets."""
    text = str(error).lower()
    backend = a.get("backend")
    tool = CLI_NAMES.get(backend, "provider")
    if isinstance(error, FileNotFoundError) and backend in CLI_NAMES:
        return f"{tool} CLI not found; install {tool}, sign in, and run --setup again."
    if any(x in text for x in ("not logged in", "not signed in", "please log in", "please login", "login required", "authentication required", "unauthenticated", "no credentials", "please run claude /login", "please run codex login", "please run agy login", "please run /login", "invalid api key", "invalid bearer token", "token expired", "authentication failed", "unauthorized")):
        if backend == "openai":
            return "API authentication failed; check the configured API key environment variable and provider access, then run --setup again."
        return f"{tool} is not signed in; sign in to {tool}, then run --setup again."
    if "api key environment variable is empty" in text:
        env = a.get("api_key_env", "OPENAI_API_KEY")
        return f"API key environment variable {env} is empty; set it before running, or use --setup to select another variable (empty name for local servers)."
    if "http 401" in text or "http 403" in text or "invalid_api_key" in text:
        if backend == "openai":
            return "API authentication failed; check the configured API key environment variable and provider access, then run --setup again."
        return f"{tool} is not signed in; sign in to {tool}, then run --setup again."
    if any(x in text for x in YAPILANDIRMA):
        return "Unknown or unavailable model; choose an accessible model for this backend with --setup or --model."
    if backend == "openai" and isinstance(error, (urllib.error.URLError, ConnectionError, TimeoutError)) and not isinstance(error, urllib.error.HTTPError):
        return "Unreachable base_url; check the endpoint and connection, or start the local server, then run --setup again."
    return None


def backend_check(a: dict) -> tuple[bool, str]:
    """The same one-request diagnostic is used by setup and check_backend.py."""
    try:
        configure(dict(a), "en", "en")
        result, _ = model_cagir(a["model"], 'Return {"ok":true}. No tools.',
                                {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                 "required": ["ok"], "additionalProperties": False}, 60, deneme=1)
        if result != {"ok": True}:
            raise ValueError("Unexpected structured reply; choose a model with JSON-schema support using --setup")
    except (ValueError, OSError, ModelHatasi) as error:
        fix = provider_fix(error, a)
        if not fix:
            fix = {
                "quota": "Provider quota exhausted; wait for reset or choose another backend with --setup.",
                "safety_block": "Provider blocked the diagnostic; choose another accessible model with --setup.",
                "schema_invalid": "Provider returned an invalid structured reply; select a JSON-schema capable model with --setup.",
                "timeout": "Provider timed out; check the service and connection, then rerun --setup.",
                "configuration": "Backend and model are required; run --setup and select both.",
            }.get(error_category(error), "Backend check failed; verify provider access and JSON-schema support, then rerun --setup.")
        return False, fix
    return True, "OK"


def setup(config=None) -> bool:
    print("Provider setup (model availability depends on your provider/account).")
    for backend in BACKENDS:
        detected = bool(os.environ.get("OPENAI_API_KEY")) if backend == "openai" else bool(shutil.which(CLI_NAMES[backend]))
        detail = "OPENAI_API_KEY " + ("set" if detected else "not set") if backend == "openai" else "PATH executable: " + CLI_NAMES[backend]
        print(f"- {backend}: {'detected' if detected else 'not detected'} ({detail}); example model: {MODEL_EXAMPLES[backend]}")
    try:
        backend = input("Backend [openai/agy/codex/claude-code]: ").strip().lower()
        if backend not in BACKENDS:
            print("FAIL: choose one of the four backend names and rerun --setup.")
            return False
        model = input(f"Model name (example: {MODEL_EXAMPLES[backend]}): ").strip()
        if not model:
            print("FAIL: a model name is required; rerun --setup.")
            return False
        changes = {"backend": backend, "model": model}
        if backend == "openai":
            print("Endpoint examples: OpenAI https://api.openai.com/v1; Gemini https://generativelanguage.googleapis.com/v1beta/openai; OpenRouter https://openrouter.ai/api/v1; local Ollama http://localhost:11434/v1")
            base_url = input("base_url [https://api.openai.com/v1]: ").strip() or "https://api.openai.com/v1"
            if not re.fullmatch(r"https?://[^/@?&#\s]+(?:/[^?#\s]*)?", base_url):
                print("FAIL: use an http:// or https:// endpoint without embedded credentials or query parameters; rerun --setup.")
                return False
            env = input("API key environment variable name [OPENAI_API_KEY; '-' for local servers]: ").strip() or "OPENAI_API_KEY"
            # An empty name deliberately supports local servers; no credential is ever requested.
            if env == "-":
                env = ""
            if env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
                print("FAIL: enter an environment variable name, never a key value; rerun --setup.")
                return False
            changes.update(base_url=base_url, api_key_env=env)
            print("Selected API key variable: " + ("set" if env and os.environ.get(env) else "not set") + "; no key is stored.")
        update_config(changes, config)
        a = ayarlar(str(config_path(config)))
        ok, message = backend_check(a)
        print("OK" if ok else "FAIL: " + message)
        return ok
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled; rerun --setup when ready.")
        return False
    except (ValueError, OSError) as error:
        print("FAIL: could not save/read configuration; check config.json permissions and JSON syntax, then rerun --setup.")
        return False


def _safe_count(value) -> int:
    # Only bounded numeric primitives can enter the public report.
    return max(0, min(value, 10**12)) if type(value) is int else 0


def _safe_minutes(value) -> float:
    import math
    return round(min(max(value, 0), 10**6), 2) if type(value) in (float, int) and math.isfinite(value) else 0.0


def stage_of(sema: dict) -> str | None:
    return next((name for name, schema in (("translate", CEVIRI_SEMA), ("translate", CEVIRI_NOT_SEMA), ("review", INCELEME_SEMA), ("gate", KAPI_SEMA),
                 ("series", SERI_SEMA), ("context", BAGLAM_SEMA), ("warnings", SANSUR_SEMA),
                 ("level", OGRENME_SEMA), ("breaks", DURAK_SEMA), ("human", INSAN_SEMA)) if sema == schema), None)


def record_usage(stage: str, usage: dict) -> None:
    if stage not in STAGES or not isinstance(usage, dict):
        return
    n = kullanim_sayilari(usage)
    values = {"input": n["input_tokens"], "output": n["output_tokens"], "reasoning": n["thinking_tokens"]}
    with _yaz_kilidi:  # parallel chunks update the same counters
        bucket = RUN_STATS["stage_tokens"].setdefault(stage, {"input": 0, "output": 0, "reasoning": 0})
        for key, value in values.items():
            bucket[key] += _safe_count(value)


def anonymous_report(a: dict, jobs: list[dict], elapsed: float, errors=(), stats=None) -> dict:
    """Construct fresh fields only; never merge config, job dictionaries or exception text."""
    import platform
    stats = RUN_STATS if stats is None else stats
    backend = a.get("backend") if a.get("backend") in BACKENDS else "unknown"
    code = lambda value: value if isinstance(value, str) and re.fullmatch(r"[a-z]{2,3}", value) else "und"
    total = sum(_safe_count((job.get("review_traps") or {}).get("inserted")) + _safe_count((job.get("review_traps") or {}).get("missed_first")) for job in jobs)
    missed = sum(_safe_count((job.get("review_traps") or {}).get("missed_first")) + _safe_count((job.get("review_traps") or {}).get("missed_twice")) for job in jobs)
    categories = {error_category(error) for error in errors}
    categories.update(x for x in stats.get("errors", ()) if x in ERROR_CATEGORIES)
    for job in jobs:
        if job.get("blocked_translation") or job.get("blocked_review"):
            categories.add("safety_block")
        if job.get("warning_status") in ("partial", "failed"):
            categories.add("safety_block" if job.get("warning_status") == "partial" else "other")
    stages = {}
    for stage in STAGES:
        bucket = stats.get("stage_tokens", {}).get(stage)
        if isinstance(bucket, dict):
            stages[stage] = {key: _safe_count(bucket.get(key)) for key in ("input", "output", "reasoning")}
    system = platform.system()
    return {"tool_version": SURUM, "os": system if system in ("Darwin", "Linux", "Windows", "FreeBSD") else "Other",
            "python": f"{sys.version_info.major}.{sys.version_info.minor}", "backend": backend,
            "source_language": code(SOURCE["code"]), "target_language": code(TARGET["code"]),
            "episode_count": len(jobs) + len(errors), "unit_count": sum(_safe_count(job.get("units")) for job in jobs),
            "review_corrections": sum(_safe_count(job.get("correction_count")) for job in jobs),
            "trap_lines_caught": max(0, total - missed), "trap_lines_total": total, "stage_tokens": stages,
            "elapsed_minutes": _safe_minutes(elapsed), "feature_flags": {key: a.get(key) is True for key in FEATURES},
            "error_categories": sorted(categories)}


def report_text(report: dict) -> str:
    return json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)


def _urlquote(text: str) -> str:
    # Pure URL encoding: the report flow does not use socket or urllib at all.
    safe = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    return "".join(chr(byte) if byte in safe else f"%{byte:02X}" for byte in text.encode("utf-8"))


def issue_url(report: dict) -> str:
    body = report_text(report)
    make_url = lambda body: ISSUE_URL + "?title=" + _urlquote("Anonymous dragoman run report") + "&body=" + _urlquote(body)
    url = make_url(body)
    if len(url) >= 6000:
        # Drop per-stage detail first; all other fields are bounded by construction.
        body = report_text({key: value for key, value in report.items() if key != "stage_tokens"})
        url = make_url(body)
    return url


def share_report(a: dict, jobs: list[dict], elapsed: float, errors=(), *, config=None, detached=False, level_only=False) -> None:
    if detached or level_only or a.get("share_prompt", True) is False or not interactive():
        return
    report = anonymous_report(a, jobs, elapsed, errors)
    url = issue_url(report)
    # Display exactly the text prefilled in the issue, including size-based omissions.
    visible = report if len(ISSUE_URL + "?title=" + _urlquote("Anonymous dragoman run report") + "&body=" + _urlquote(report_text(report))) < 6000 else {key: value for key, value in report.items() if key != "stage_tokens"}
    print("\nAnonymous report:\n" + report_text(visible))
    print("This would be posted publicly as a GitHub issue under your own account. Nothing is sent by this program; you submit it yourself.")
    try:
        answer = input("Share this anonymous report with the developer? [y/N/never] ").strip().lower()
        if answer == "never":
            update_config({"share_prompt": False}, config)
        elif answer == "y":
            print(url)
            if input("Open in browser? [y/N] ").strip().lower() == "y":
                import webbrowser
                webbrowser.open(url)
    except (EOFError, KeyboardInterrupt):
        print("\nReport not shared.")
    except (ValueError, OSError):
        print("Could not save share_prompt; use --no-share-prompt or set share_prompt to false in config.json.")


def save_run_summary(seri_dir: Path, lines: list[str]) -> None:
    path = seri_dir / "run-summary.txt"
    if path.exists():
        archived = seri_dir / "previous"
        archived.mkdir(exist_ok=True)
        shutil.copyfile(path, archived / f"run-summary-{time.time_ns()}.txt")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def failed_job_report(a: dict, eser: str, sezon: int, no: int | None, error) -> None:
    """Keep actionable failures locally as well as in the console summary."""
    etiket = f"S{sezon:02d}E{no:02d}" if no is not None else "Movie"
    folder = a["work_dir"] / eser / etiket
    units = joku(folder / "units.json", [])
    report = {"version": SURUM, "title": eser, "episode": etiket, "status": "failed",
              "source_language": SOURCE["code"], "target_language": TARGET["code"],
              "backend": a.get("backend"), "units": len(units) if isinstance(units, list) else 0,
              "error": _redact(str(error)), "error_categories": [error_category(error)]}
    for path in (folder / "record.json", a["jobs_dir"] / eser / etiket / "record.json"):
        if path.exists():
            shutil.copyfile(path, path.with_name(f"record-previous-{time.time_ns()}.json"))
        jyaz(path, report)


INCELEME_BLOGU = re.compile(r"<!-- review-only -->.*?<!-- /review-only -->\n?", re.S)


def rehber_rolu(rehber: str, inceleme: bool) -> str:
    """Guide for one role: review-only blocks are kept (markers removed) for review and the gate, dropped otherwise."""
    if inceleme:
        return re.sub(r"<!-- /?review-only -->\n?", "", rehber)
    return INCELEME_BLOGU.sub("", rehber)


def rehber_metni(a: dict) -> str:
    """Prompt guide: guide.md + guides/<target>.md (or one replacement file in "guide"), then "guide_extra" files."""
    if a.get("guide"):  # a complete replacement guide instead of guide.md + guides/<target>.md
        rehber = Path(a["guide"]).expanduser().read_text(encoding="utf-8")
    else:
        rehber = (KOK / "guide.md").read_text(encoding="utf-8")
        addendum = KOK / "guides" / (TARGET["code"] + ".md")
        if addendum.exists():
            rehber += "\n\n" + addendum.read_text(encoding="utf-8")
    for ek in guide_extras(a):  # the user's own additions (audience, taste) after the shipped guide
        rehber += "\n\n" + Path(ek).expanduser().read_text(encoding="utf-8")
    return (f"Source language: {SOURCE['name']} ({SOURCE['code']}). "
            f"Target language: {TARGET['name']} ({TARGET['code']}).\n\n" + rehber)


def main() -> None:
    ap = argparse.ArgumentParser(prog="dragoman", description="Translate and review subtitles, then verify and mux an MKV")
    ap.add_argument("girdi", nargs="?", metavar="INPUT", help="video, video directory, or ASS/SRT file")
    ap.add_argument("--target", help="target ISO 639-1 or 639-2 code (required unless config sets \"target\")")
    ap.add_argument("--source", help="source language code (default: config \"source\", else en)")
    ap.add_argument("--source-name", help="English name for an unknown source code")
    ap.add_argument("--target-name", help="English name for an unknown target code")
    ap.add_argument("--setup", action="store_true", help="configure a provider interactively and check it")
    ap.add_argument("--config", help="configuration JSON (default: config.json beside script)")
    ap.add_argument("--backend", choices=["openai", "agy", "codex", "claude-code"])
    ap.add_argument("--model", help="model for all roles (role settings in config take precedence)")
    ap.add_argument("--output", help="output root (default: ~/dragoman/)")
    ap.add_argument("--fallback-font", action="append", help="fallback font path; repeat to set preference order")
    ap.add_argument("--title", dest="eser", metavar="TITLE", help="production title (default: inferred from input)")
    ap.add_argument("--season", dest="sezon", metavar="SEASON", type=int,
                    help="season number (default: from S02E05 or 'Season 2' in the input name, else 1)")
    ap.add_argument("--episodes", dest="bolum", metavar="EPISODES", help="episodes/ranges in a directory: 1,3-5,7")
    ap.add_argument("--movie", dest="film", action="store_true", help="single movie without episode number")
    ap.add_argument("--episode", dest="no", metavar="EPISODE", type=int, help="episode number for subtitle-only input")
    ap.add_argument("--source-subtitle", dest="kaynak", metavar="FILE", help="external source ASS/SRT for a single video")
    ap.add_argument("--series-source", dest="seri_kaynak", metavar="DIR", help="extra directory of series context subtitles/videos")
    ap.add_argument("--no-mux", dest="paketleme", action="store_true", help="deliver ASS without an MKV")
    ap.add_argument("--audio-lang", dest="ses", metavar="CODE", help="preferred default audio language; otherwise preserve source flags")
    ap.add_argument("--no-level-report", action="store_true", help="disable the language-level report (default: on)")
    ap.add_argument("--no-content-warnings", action="store_true", help="disable scene warning overlays (default: on)")
    ap.add_argument("--no-break-chapters", action="store_true", help="disable viewing-break chapters (default: on)")
    ap.add_argument("--no-share-prompt", action="store_true", help="suppress the optional anonymous-report question")
    ap.add_argument("--redo", dest="yeniden", action="store_true", help="archive previous job and restart")
    ap.add_argument("--accept-ocr", dest="ocr_kabul", action="store_true", help="accept source subtitles with raw OCR artifacts")
    ap.add_argument("--detach", dest="arka_plan", action="store_true", help="run independently of this session and print log path")
    ap.add_argument("--no-human-check", dest="insan_yok", action="store_true", help="skip checking existing target-language translations")
    ap.add_argument("--level-only", dest="duzey", action="store_true", help="assess source language level without translation")
    ap.add_argument("--languages", action="store_true", help="list target languages with a built-in guide and labels")
    x = ap.parse_args()
    if x.languages:
        for code in builtin_languages():
            print(f"{code}  {LANGUAGES.get(code, {}).get('name', code)} ({locale(code).get('native_name', '')})"
                  + ("" if (KOK / "guides" / f"{code}.md").exists() else "  [labels only]"))
        return
    if x.setup:
        if not interactive():
            ap.error("--setup needs an interactive terminal; run it in a terminal, or configure backend/model in config.json")
        sys.exit(0 if setup(x.config) else 2)
    try:
        a = ayarlar(x.config) if x.config else ayarlar()
    except (ValueError, OSError):
        ap.error("Could not read configuration; fix config.json syntax/permissions or choose --config PATH")
    x.target = x.target or a.get("target")
    x.source = x.source or a.get("source") or "en"
    if not x.girdi or not x.target:
        ap.error("INPUT and --target (or \"target\" in config) are required for translation; use --setup to configure a provider")
    for key, value in (("backend", x.backend), ("model", x.model), ("output_dir", x.output)):
        if value is not None:
            a[key] = value
    if x.output:
        root = Path(x.output).expanduser()
        a.update({key: root / folder for key, folder in (("work_dir", "work"), ("library_dir", "library"), ("jobs_dir", "jobs"), ("watch", "watch"))})
    if x.fallback_font:
        a["fallback_fonts"] = x.fallback_font
    if not a.get("backend") or not a.get("model"):
        if interactive():
            try:
                start_setup = input("Backend/model missing. Run --setup now? [y/N] ").strip().lower() == "y"
            except (EOFError, KeyboardInterrupt):
                start_setup = False
            if start_setup:
                if not setup(x.config):
                    raise SystemExit(2)
                configured = ayarlar(str(config_path(x.config)))
                # Preserve current command-line overrides and output paths.
                for key in ("backend", "model", "base_url", "api_key_env"):
                    if (key == "backend" and x.backend) or (key == "model" and x.model):
                        continue
                    a[key] = configured[key]
        if not a.get("backend") or not a.get("model"):
            ap.error("Backend and model are required; run --setup or use: python3 dragoman.py INPUT --target es --backend openai --model gpt-4.1-mini")
    try:
        configure(a, x.source, x.target, x.source_name, x.target_name)
    except ValueError as error:
        ap.error(str(error))
    for key in ("level_report", "content_warnings", "break_chapters"):
        if getattr(x, "no_" + key):
            a[key] = False
    if x.no_share_prompt:
        a["share_prompt"] = False
    if x.duzey:
        a["level_report"] = True
    a["redo"] = x.yeniden
    x.ses = x.ses or a.get("audio_lang")
    if x.arka_plan:
        log_dir = a["work_dir"] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_yolu = log_dir / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^\w-]+', '_', x.eser or 'is')}.log"
        with open(log_yolu, "a", encoding="utf-8") as f:
            p = subprocess.Popen([sys.executable, os.path.abspath(__file__), *[k for k in sys.argv[1:] if k != "--detach"], "--no-share-prompt"],
                                 stdin=subprocess.DEVNULL, stdout=f, stderr=f, start_new_session=True)
        print(f"Started in background (pid {p.pid}). Log: {log_yolu}")
        return
    RUN_STATS["stage_tokens"] = {}
    RUN_STATS["errors"] = set()
    run_started = time.monotonic()
    if shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    girdi = Path(os.path.expanduser(x.girdi)).resolve()
    rehber = rehber_metni(a)

    def temiz_ad(s: str) -> str:
        s = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", s)
        s = re.sub(r"[_.]+", " ", s)
        return re.sub(r"\s+", " ", s).strip(" -") or "Untitled"

    videolar: list[tuple[int | None, Path]] = []
    kaynak_ass = None
    atlanan = []
    if girdi.is_dir():
        for v in sorted(girdi.iterdir()):
            if v.suffix.lower() not in (".mkv", ".mp4"):
                continue
            if re.search(r"\bNC(OP|ED)?\b|extra|special|preview|trailer|\bSP\d*\b|\bOVA\b|\bOAD\b", v.name, re.I):
                atlanan.append(v.name)
                continue
            videolar.append((bolum_no(v.stem), v))
        if atlanan:
            log(f"Skipped specials/extras ({len(atlanan)}): " + "; ".join(atlanan[:8])
                + (" …" if len(atlanan) > 8 else "") + " — pass a file individually to translate it.")
        eser = x.eser or temiz_ad(girdi.name)
    elif girdi.suffix.lower() in (".ass", ".srt", ".ssa"):
        kaynak_ass = girdi
        eser = x.eser or temiz_ad(girdi.stem)
    else:
        videolar.append((None if x.film else bolum_no(girdi.stem), girdi))
        eser = x.eser or temiz_ad(girdi.parent.name if not x.film else girdi.stem)

    eser = klasor_adi(eser)
    if x.sezon is not None and girdi.is_dir():
        videolar = [(n, v) for n, v in videolar if sezon_no(v.stem) in (None, x.sezon)]
        if not videolar:
            raise SystemExit(f"No video of season {x.sezon} in {girdi}")
    secili = videolar
    if x.bolum:
        istenen = set()
        try:
            for p in x.bolum.split(","):
                if "-" in p:
                    b, s = p.split("-"); istenen |= set(range(int(b), int(s) + 1))
                else:
                    istenen.add(int(p))
        except ValueError:
            ap.error(f"Invalid --episodes value {x.bolum!r}; use episode numbers and ranges such as 1,3-5,7")
        secili = [(n, v) for n, v in videolar if n in istenen]
        if not secili:
            raise SystemExit(f"Requested episode not found: {x.bolum}")

    if not x.film:
        sayac: dict = {}
        for n, v in secili:
            sayac.setdefault(n, []).append(v.name)
        sorunlu = {n: adlar for n, adlar in sayac.items() if n is None or len(adlar) > 1}
        if sorunlu:

            raise SystemExit("Missing or duplicate episode numbers; select with --episodes or fix filenames:\n"
                             + "\n".join(f"  {n}: {', '.join(adlar)}" for n, adlar in sorunlu.items()))
    # Season: --season, else S02E05 / "Season 2" in the input name (file, or folder and its videos); a conflict stops.
    adlar = [girdi.stem if girdi.is_file() else girdi.name] + [v.stem for _, v in secili if v != girdi]
    if girdi.is_file() and sezon_no(girdi.stem) is None:
        adlar.append(girdi.parent.name)
    bulunan = sorted({n for n in map(sezon_no, adlar) if n is not None})
    if x.sezon is not None and bulunan and bulunan != [x.sezon]:
        raise SystemExit(f"--season {x.sezon} conflicts with the season in the input name (season {', '.join(map(str, bulunan))}); "
                         "fix --season or the filenames")
    if x.sezon is None:
        if len(bulunan) > 1:
            raise SystemExit(f"Input names contain several seasons ({', '.join(map(str, bulunan))}); select one with --season")
        x.sezon = bulunan[0] if bulunan else 1
        if bulunan:
            log(f"Season {x.sezon} (from the input name).")
    dis = Path(os.path.expanduser(x.kaynak)).resolve() if x.kaynak else None
    if dis and len(secili) != 1:
        raise SystemExit("--source-subtitle requires one video (select with --episodes)")
    for dis_ in (d for d in (dis, kaynak_ass) if d and not x.ocr_kabul and not x.duzey):
        ham = metin_oku(dis_)
        iz_ = len(re.findall(r"'[^'\"\n]{1,60}\"", ham)) + (20 if "pysubs2" in ham else 0)
        if iz_ >= 20:
            raise SystemExit(f"{dis_.name} has raw OCR artifacts (mismatched quotes or letters); errors may propagate into the translation. "
                             "Clean the source first, or explicitly accept with --accept-ocr.")
    isler = ([(x.no, None, kaynak_ass)] if kaynak_ass else []) + [(None if x.film else n, v, dis) for n, v in secili]
    requested_count = len(isler)
    seri_dir = a["work_dir"] / eser
    seri_dir.mkdir(parents=True, exist_ok=True)
    import fcntl
    kilit = open(seri_dir / ".lock", "w")
    try:
        fcntl.flock(kilit, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # Concurrent writers would mix chunk records and series memory.
        raise SystemExit(f"'{eser}' already has another run in progress; retry after it finishes.")
    pair_path = seri_dir / "languages.json"
    pair = {"source": SOURCE["code"], "target": TARGET["code"]}
    if pair_path.exists() and joku(pair_path) != pair:
        raise SystemExit("This title's work directory uses another language pair; choose a different --output root")
    jyaz(pair_path, pair)
    if a.get("redo") and not x.duzey:
        for n, v, k_ass in isler:
            etiket = f"S{x.sezon:02d}E{n:02d}" if n is not None else "Movie"
            is_dir = a["work_dir"] / eser / etiket
            if is_dir.exists() and any(is_dir.iterdir()):
                kenar = is_dir.with_name(f"{etiket}-previous-{dt.datetime.now():%Y%m%d-%H%M%S-%f}")
                shutil.move(str(is_dir), kenar)
                log(f"Previous job archived: {kenar}")
    if x.duzey:
        hata = 0
        level_summary = []
        for n, v, k_ass in isler:
            try:
                d = duzey_isle(a, eser, x.sezon, n, v, k_ass)
                level_summary.append(f"- {d['episode']}: {d['cefr']}, {SUITABILITY_LABELS.get(d['suitability'])} · {d['report']}")
            except (BolumHatasi, ModelHatasi, SystemExit, OSError, subprocess.CalledProcessError, ValueError) as e:
                hata += 1
                failed_job_report(a, eser, x.sezon, n, e)
                level_summary.append(f"- {n}: FAILED — {e}")
        level_summary.append(f"Summary table: {a['library_dir'] / eser}")
        save_run_summary(seri_dir, level_summary)
        print("\n".join(level_summary))
        sys.exit(2 if hata else 0)

    insan_bilgi, insan_bitti, basarisiz = {}, [], []
    if a["human_check"] and not x.insan_yok:
        for n, v, k_ass in list(isler):
            if v is None:
                continue
            etiket = f"S{x.sezon:02d}E{n:02d}" if n is not None else "Movie"
            is_dir = a["work_dir"] / eser / etiket
            is_dir.mkdir(parents=True, exist_ok=True)
            try:
                try:
                    bir = birimleri_cikar(kaynagi_hazirla(is_dir, v, k_ass)[0])[0]
                except SystemExit as e:  # while scoring is off no source track is needed: a platform track alone can be delivered
                    if a.get("human_scoring"):
                        raise
                    log(f"No source subtitles ({etiket}): {e}; checking only for a professional {TARGET['name']} track."); bir = []
                secim = insan_secimi(a, v, x.sezon, n, bir, rehber, is_dir)
            except (BolumHatasi, SystemExit, subprocess.CalledProcessError, ValueError) as e:
                log(f"Human translation check unavailable ({etiket}): {e}")
                continue
            if not secim:
                continue
            if secim["use"]:
                try:
                    insan_bitti.append(insan_teslim(a, eser, x.sezon, n, v, secim, x.ses, not x.paketleme))
                except (ModelHatasi, SystemExit, OSError, subprocess.CalledProcessError, ValueError) as e:
                    log(f"FAILED {eser} {etiket}: {e}")
                    basarisiz.append((etiket, str(e)))
                    failed_job_report(a, eser, x.sezon, n, e)
                isler.remove((n, v, k_ass))
            else:
                insan_bilgi[n] = secim
    seri_dosyasi = seri_dir / "series.md"
    if isler and not seri_dosyasi.exists():
        kaynaklar = []
        # The episode given with --source-subtitle is read from that file, not from its embedded track.
        okunacak = [(n, v) for n, v in videolar if not (dis and v == secili[0][1])]
        if x.seri_kaynak:
            ek = Path(os.path.expanduser(x.seri_kaynak))
            okunacak += [(bolum_no(v.stem), v) for v in sorted(ek.iterdir()) if v.suffix.lower() in (".mkv", ".mp4", ".ass", ".srt", ".ssa")]
        # Labels carry the season so episode 1 of season 2 never replaces episode 1 of season 1.
        okunacak = [(sezon_no(v.stem) or x.sezon, n, v) for n, v in okunacak]
        for sz, n, v in sorted({str(v): (sz, n, v) for sz, n, v in okunacak}.values(), key=lambda t: (t[1] is None, t[0], t[1] or 0)):
            etiket = f"S{sz:02d}E{n:02d}" if n is not None else v.stem
            hedef = seri_dir / "series-source" / f"{etiket}.ass"
            if not hedef.exists():
                hedef.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if v.suffix.lower() in (".ass", ".srt", ".ssa"):
                        _ass_yap(v, hedef)
                    else:
                        altyazi_sec(v, hedef)
                except (SystemExit, subprocess.CalledProcessError) as e:
                    log(f"Series source skipped {v.name}: {e}")
                    continue
            if etiket not in dict(kaynaklar):  # one entry per episode (a video and a series-source file may share it)
                kaynaklar.append((etiket, hedef))
        girdiler = []
        if kaynak_ass:
            girdiler.append((f"S{x.sezon:02d}E{x.no:02d}" if x.no else "source", kaynak_ass))
        if dis:
            girdiler.append((f"S{x.sezon:02d}E{secili[0][0]:02d}" if secili[0][0] is not None and not x.film else "source", dis))
        for source_label, source_path in girdiler:  # read with encoding detection, converted to UTF-8 ASS; replaces a same-label entry
            kaynaklar = [k for k in kaynaklar if k[0] != source_label]
            kaynaklar.append((source_label, _ass_yap(source_path, seri_dir / "series-source" / f"{source_label}.input.ass")))
        if not kaynaklar:
            raise SystemExit("No subtitles available for series guide")
        RECEIPT[:] = [seri_dir / "receipts.jsonl", "series"]
        try:
            seri_hazirla(a, eser, kaynaklar, seri_dir, rehber)
        except ModelHatasi as e:
            for n, v, k_ass in isler:
                label = f"S{x.sezon:02d}E{n:02d}" if n is not None else "Movie"
                basarisiz.append((label, str(e)))
                failed_job_report(a, eser, x.sezon, n, e)
            isler = []

    sonuclar = list(insan_bitti)
    for n, v, k_ass in isler:
        ad = f"E{n:02d}" if n is not None else (v or k_ass).name
        try:
            sonuclar.append(bolum_isle(a, eser, x.sezon, n, v, k_ass, rehber, seri_dosyasi,
                                       (not x.paketleme) and v is not None, x.ses, insan_bilgi.get(n)))
        except (BolumHatasi, ModelHatasi, SystemExit, OSError, subprocess.CalledProcessError, ValueError) as e:
            log(f"FAILED {eser} {ad}: {e}")
            basarisiz.append((ad, str(e)))
            failed_job_report(a, eser, x.sezon, n, e)
    summary_lines = []
    summary_lines.append(f"\nSUMMARY — {eser}: requested {requested_count} episodes, delivered {len(sonuclar)}, failed {len(basarisiz)}")
    for k in sonuclar:
        if k.get("source_type") == "human translation":
            summary_lines.append(f"- {k['episode']}: human translation used ({k['human'].get('professional') or 'score ' + str(k['human']['score'])}), "
                  f"{k.get('warning_count', 0)} content warnings · {k['library_dir']}"
                  + (f" · {k['package']['file']}" if k.get("package") else "")
                  + (f"\n  ⚠ content warning scan {k['warning_status']}" if k.get("warning_status") in ("partial", "failed") else ""))
            continue
        summary_lines.append(f"- {k['episode']}: {k['units']} units, {k['correction_count']} corrections, {k['warning_count']} content warnings, "
              f"{len(k['untranslated'])} untranslated, "
              + (f"{len(k['blocked_translation'])} source lines retained due to content safety, " if k.get("blocked_translation") else "")
              + (f"{len(k['blocked_review'])} unreviewed due to content safety, " if k.get("blocked_review") else "")
              + (f"{len(k['translator_notes'])} translator notes, " if k.get("translator_notes") else "")
              + f"{k['minutes']} minutes · {k['library_dir']}"
              + (f"\n  ⚠ content warning scan {k['warning_status']}" if k.get("warning_status") in ("partial", "failed") else "")
              + (f"\n  ⚠ low review confidence: {k['review_traps']['missed_twice']} chunks missed the reviewer trap twice"
                 if (k.get("review_traps") or {}).get("missed_twice") else "")
              + (f"\n  ⚠ {k['review_traps']['possibly_unread']} review chunks may not have been read to the end"
                 if (k.get("review_traps") or {}).get("possibly_unread") else "")
              + ("\n  ⚠ episode context unavailable (translated using series guide only)" if k.get("episode_context") == "failed" else "")
              + (f" · {k['package']['file']}" if k.get("package") else " · no MKV"))
    for ad, e in basarisiz:
        summary_lines.append(f"- {ad}: FAILED — {e[:300]}")
    save_run_summary(seri_dir, summary_lines)
    print("\n".join(summary_lines))
    share_report(a, sonuclar, (time.monotonic() - run_started) / 60, [error for _, error in basarisiz],
                 config=x.config, detached=x.arka_plan, level_only=x.duzey)
    if basarisiz:
        sys.exit(2)


if __name__ == "__main__":
    main()
