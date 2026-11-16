
"""Subtitle pipeline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import dragoman as A
from unittest.mock import patch
import socket

# Fail closed: every process or network transport must be explicitly faked by a test.
unexpected_external_calls = []
def forbidden_external(*args, **kwargs):
    unexpected_external_calls.append("unmocked external call")
    raise AssertionError("Unmocked process/network transport is forbidden in this suite")
_guard_popen = patch.object(A.subprocess, "Popen", side_effect=forbidden_external)
_guard_run = patch.object(A.subprocess, "run", side_effect=forbidden_external)
_guard_http = patch.object(A.urllib.request, "urlopen", side_effect=forbidden_external)
_guard_socket = patch.object(socket, "socket", side_effect=forbidden_external)
_guard_quota = patch.object(A, "_kota_bekle", return_value=False)
for _guard in (_guard_popen, _guard_run, _guard_http, _guard_socket, _guard_quota):
    _guard.start()

import tempfile
_fixture_dir = tempfile.TemporaryDirectory()
ORN = Path(_fixture_dir.name)
SYNTHETIC_ASS = ("[Script Info]\nPlayResY: 720\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize\n"
                 "Style: Default,Arial,40\nStyle: Romaji,Arial,40\nStyle: Kanji,Arial,40\n"
                 "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                 "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello, {\\i1}world{\\i0}!\n"
                 "Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,Where are we going?\n"
                 "Dialogue: 0,0:00:07.00,0:00:09.00,Default,,0,0,0,,I will meet you tomorrow.\n"
                 "Dialogue: 0,0:00:10.00,0:00:12.00,Kanji,,0,0,0,,明日は晴れる\n"
                 "Dialogue: 0,0:00:13.00,0:00:15.00,Romaji,,0,0,0,,ashita wa hareru\n"
                 "Dialogue: 0,0:00:16.00,0:00:18.00,Default,,0,0,0,,{\\p1}m 0 0 l 10 10{\\p0}\n")
(ORN / "synthetic.ass").write_text(SYNTHETIC_ASS, encoding="utf-8")
A.configure(dict(A.VARSAYILAN, backend="agy", model="fake", model_translate="fake", model_review="fake", model_series="fake", model_warnings="fake", model_level="fake"), "en", "tr")
hata = 0


def kontrol(ad, kosul):
    global hata
    print(("OK   " if kosul else "FAIL ") + ad)
    hata += not kosul


for f in sorted(ORN.glob("*.ass")):
    t = f.read_text(encoding="utf-8")
    ass = A.Ass(t)
    bir, es = A.birimleri_cikar(ass)
    bul = {b["id"]: b for b in bir}
    yeni = {s: A.olaya_yerlestir(bul[e["id"]]["text"], e, bul[e["id"]]["kind"], 10**6)[0]
            for s, e in es.items() if not e["merged"]}
    kontrol('Identity translation preserves ASS exactly', ass.yaz(yeni, [], None) == t.replace("\r\n", "\n"))
    kontrol('Non-CJK extraction skips retained script lines', not any(A.CJK.search(b["text"]) for b in bir))
    kontrol('Unique units never exceed events', len(bir) <= len(ass.olaylar))
    ek, _ = A.uyari_olaylari(bir, [{"first_id": "2", "last_id": "3", "reason": "öpüşme"}], ass.bicim)
    kontrol('Warnings are separate ASS events', len(ek) == 1 and "ContentWarning" in ek[0])

kontrol('Wrap fits forty-two columns', all(len(x) <= 42 for x in A.satir_kir(
    "Bu neredeyse Uyuyan Güzel'in şatosu gibi görünüyor, gerçekten de öyle.", 42).split("\\N")))
kontrol('Short lines remain unwrapped', A.satir_kir("Teşekkürler.", 42) == "Teşekkürler.")
kontrol('Episode number in release filename', A.bolum_no("[DB]Puella Magi Madoka Magica_-_01_(Dual Audio_10bit_BD1080p_x265)") == 1)
kontrol('Episode number after separator', A.bolum_no("[Anime Time] Monster - 57") == 57)
kontrol('Season/episode filename', A.bolum_no("Hyouka S01E03") == 3)
e = {"parts": ["{\\i1}", "Hello", "{\\i0}", " world"], "nonempty": [1, 3], "merged": False}
kontrol('Formatting markers place translated parts', A.olaya_yerlestir("Merhaba⟦1⟧ dünya", e, "dialogue", 42)[0] == "{\\i1}Merhaba{\\i0} dünya")
kontrol('Broken markers use safe placement', A.olaya_yerlestir("Merhaba dünya", e, "dialogue", 42)[1] is True)


kap = A.font_kapsami(A.YEDEK_DOSYALAR)
kontrol('Bundled fallback covers Turkish characters', A.YEDEK_FONT.lower() in kap and all(ord(c) in kap[A.YEDEK_FONT.lower()] for c in set("çÇğĞıİöÖşŞüÜ")))
ornek = ("[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Sarki,EksikFont,40\nStyle: Diyalog,BilinmeyenFont,40\n"
         "Style: Sign-Runes,EksikFont,40\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
         "Dialogue: 0,0:00:01.00,0:00:02.00,Sarki,,0,0,0,,Göğe koş\n"
         "Dialogue: 0,0:00:01.00,0:00:02.00,Diyalog,,0,0,0,,Şimdi {\\fnEksikFont}değil\n"
         "Dialogue: 0,0:00:01.00,0:00:02.00,Sign-Runes,,0,0,0,,Cennette Öndeyiş\n")
kapsam = {"eksikfont": set(range(32, 127))}
yeni, deg = A.font_duzelt(ornek, kapsam)
kontrol('Missing glyphs select fallback style font', "Style: Sarki,Source Sans 3,40" in yeni)
kontrol('Unknown embedded-font coverage stays unchanged', "Style: Diyalog,BilinmeyenFont,40" in yeni)
kontrol('Inline font overrides receive fallback', "{\\fnSource Sans 3}değil" in yeni)
kontrol('Decorative Latin style folds accents', "Style: Sign-Runes,EksikFont,40" in yeni and "Cennette Ondeyis" in yeni)
kontrol('Covered characters require no font changes', A.font_duzelt(ornek.replace("Göğe koş", "Kos").replace("Şimdi", "Simdi").replace("Öndeyiş", "Ondeyis").replace("değil", "degil"), kapsam)[1] == [])


import tempfile, json as _j
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    b = {"terms": [{"source": "Rose Mansion", "translation": "Gül Konağı", "note": ""}],
         "addresses": [{"from": "Lunge", "to": "Tenma", "register": "siz", "address": "Doktor", "note": "resmî"}],
         "voices": [{"character": "Lunge", "note": "soğuk, resmî"}], "recurring": [], "uncertainties": ["12: muhatap belirsiz"]}
    m = A.baglam_metni(b)
    kontrol('Context contains locked terms and directional register', "Rose Mansion → Gül Konağı" in m and "Lunge → Tenma: siz" in m)
    A.jyaz(td / "memory.json", {"terms": {"rose mansion": {"source": "Rose Mansion", "translation": "Güllü Konak", "note": "", "episode": "eski"}},
                                "addresses": {}, "voices": {}})
    A.hafiza_guncelle(td, b, "S01E50")
    h = A.joku(td / "memory.json")
    kontrol('Episode decisions update series memory', h["terms"]["rose mansion"]["translation"] == "Gül Konağı"
            and h["terms"]["rose mansion"]["episode"] == "S01E50")
    kontrol('Memory records the originating episode', "(S01E50) Rose Mansion → Gül Konağı" in A.hafiza_metni(h))

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    bir = [{"id": "1", "kind": "dialogue", "style": "D", "text": "I'll be ⟦1⟧right there.", "start": 1.0, "end": 3.0},
           {"id": "2", "kind": "dialogue", "style": "D", "text": "I didn't care about the movie at all, you know.", "start": 4.0, "end": 5.0},
           {"id": "3", "kind": "sign", "style": "S", "text": "EXIT", "start": 6.0, "end": 7.0}]
    o = A.okuma_olcumu(bir)
    kontrol('Reading measurements count dialogue only', o["lines"] == 2 and o["words"] == 14 and o["fast_line_percent"] == 50)
    sahte = {"cefr": "B1-B2", "confidence": "medium", "suitability": "productive_challenge", "summary": "İzlenir.", "difficulties": ["deyim"],
             "evidence": [{"id": "1", "quote": "right there", "reason": "kalıp"}],
             "expressions": [{"id": "2", "quote": "care about", "kind": "phrasal", "meaning": "önemsemek", "usefulness": "sık"},
                          {"id": "2", "quote": "uydurma ifade", "kind": "x", "meaning": "-", "usefulness": "-"}]}
    eski_cagir = A.model_cagir
    A.model_cagir = lambda *x, **k: (sahte, {"input_tokens": 10})
    try:
        ayar = {"model_level": "m", "learner_profile": "B2", "timeout_seconds": 1, "jobs_dir": td / "is", "library_dir": td / "ass"}
        (td / "is" / "Seri" / "S01E01").mkdir(parents=True)
        r = A.ogrenme_raporu(ayar, bir, td / "is" / "Seri" / "S01E01", "Seri S01E01")
    finally:
        A.model_cagir = eski_cagir
    kontrol('Invented learning quotes are rejected', len(r["expressions"]) == 1 and r["rejected_quotes"] == 1)
    md = (td / "is" / "Seri" / "S01E01" / "level.md").read_text(encoding="utf-8")
    kontrol('English level report includes timestamps and expressions', "0:00:04" in md and "care about" in md and "challenging but useful" in md)
    tablo = A.ogrenme_ozeti(ayar, "Seri", 1).read_text(encoding="utf-8")
    kontrol('Season summary includes episode result', "| S01E01 | B1-B2 |" in tablo)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    parca = [{"id": str(i), "kind": "dialogue", "style": "D", "text": f"line {i}", "start": i, "end": i + 1} for i in range(100)]
    cagri = []
    def sahte_istek(a, p, *x):
        cagri.append(len(p))
        if any(b["id"] == "37" for b in p):
            raise A.GuvenlikEngeli("previous response was blocked by content safety filters")
        return {b["id"]: "satır " + b["id"] for b in p}, {}
    eski = A._cevir_istek
    A._cevir_istek = sahte_istek
    try:
        (td / "translations").mkdir()
        r = A.cevir_parca({}, 1, parca, [], [], "", "", td)
    finally:
        A._cevir_istek = eski
    kontrol('Safety block isolates only the blocked unit', r["blocked"] == ["37"] and len(r["translations"]) == 99 and not r["untranslated"])
    kontrol('Chunk splitting limits repeated calls', len(cagri) <= 16)
    eski_run = A.subprocess.Popen
    class SahteP:
        pid = 999999
        def __init__(s, *a, **k): pass
        def communicate(s, *a, **k):
            return '{"event":"result","result":{"status":"ERROR","error":"The prompt contains sensitive words that violate Google\'s Generative AI Prohibited Use policy"}}', ""
    A.subprocess.Popen = SahteP
    try:
        try:
            A.model_cagir("m", "x", {}, 1); sonuc = "yok"
        except A.GuvenlikEngeli:
            sonuc = "engel"
    finally:
        A.subprocess.Popen = eski_run
    kontrol('Prohibited prompt fails without waiting', sonuc == "engel")

with tempfile.TemporaryDirectory() as td:
    td = Path(td); (td / "review").mkdir()
    parca = [{"id": str(i), "kind": "dialogue", "style": "D", "text": f"This is a fairly long English line number {i}.", "start": i, "end": i + 1}
             for i in range(20)]
    cev = {b["id"]: f"Bu, {b['id']} numaralı oldukça uzun bir Türkçe satır." for b in parca}
    istemler = []
    def sahte(model, istem, sema, z):
        istemler.append(istem)
        tid = re.findall(r"^(9\d{4}) \[", istem, re.M)
        yakala = len(istemler) == 2  
        d = [{"id": "3", "category": "meaning_error", "new": "düzeltilmiş", "reason": "x"}]
        if yakala and tid:
            d.append({"id": tid[0], "category": "meaning_error", "new": "-", "reason": "eşleşmiyor"})
        return {"corrections": d, "last_reviewed_id": "19"}, {}
    import re
    eski = A.model_cagir; A.model_cagir = sahte
    try:
        r = A.incele_parca({"model_review": "m", "timeout_seconds": 1}, 1, parca, cev, "", "", td)
    finally:
        A.model_cagir = eski
    kontrol('Reviewer trap appears only in prompt', re.search(r"^9\d{4} \[", istemler[0], re.M) is not None)
    kontrol('Missed reviewer trap causes one repeat', len(istemler) == 2 and r["trap"] == [False, True])
    kontrol('Trap corrections never enter subtitles', all(not d["id"].startswith("9") for d in r["corrections"]) and len(r["corrections"]) == 1)

import random as _r
_r.seed(4); _t = 10.0; en = []
for i in range(80):
    _t += _r.uniform(1.2, 7.0); en.append({"id": str(i), "kind": "dialogue", "style": "D", "text": "x", "start": _t, "end": _t + 1.8})
insan = [(b["start"] - 2.35, b["end"] - 2.35, "satır") for b in en[5:70]]
kayma, oran = A.hizala(insan, en)
kontrol('Timing alignment finds constant offset', abs(kayma - 2.35) < 0.06 and oran > 0.95)
kontrol('Target tags and source-copy sanity', A.target_tagged("Show.tr.ass") and not A.target_tagged("Show.en.ass")
        and A.translation_sanity("Different words", "This is the source")
        and not A.translation_sanity("This is the source", "This is the source"))

k = A.ass_kaydir("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                 "Dialogue: 0,0:00:10.00,0:00:12.50,D,,0,0,0,,Merhaba, dünya", 2.35)
kontrol('ASS shifting preserves text', "0:00:12.35,0:00:14.85,D,,0,0,0,,Merhaba, dünya" in k)

kontrol('Model output strips unsafe tags and newlines', A.metin_temizle("Bir\niki {\\i1}üç\\n dört \\N beş") == "Bir iki üç dört \\N beş")
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    bir = [{"id": str(i), "kind": "dialogue", "style": "D", "text": f"line {i}", "start": i * 2.0, "end": i * 2.0 + 1} for i in range(200)]
    eski = A._sansur_istek
    def sahte(a, satirlar):
        if any(x.startswith("77 ") for x in satirlar):
            raise A.GuvenlikEngeli("blocked by content safety filters")
        return [{"first_id": "150", "last_id": "152", "reason": "öpüşme"}] if any(x.startswith("150 ") for x in satirlar) else []
    A._sansur_istek = sahte
    try:
        t = A.sansur_tara({}, bir, td)
    finally:
        A._sansur_istek = eski
    kontrol('Content scan splits safety-blocked ranges',
            t["status"] == "partial" and len(t["unscanned"]) == 1 and t["scenes"][0]["first_id"] == "150")
    ol, kay = A.uyari_olaylari(bir, t["scenes"] + t["unscanned"], ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"])
    kontrol('Unscanned ranges receive visible warnings', len(ol) == 2 and any("scan unavailable" in o for o in ol))
eski_run = A.subprocess.Popen
class SahteP2:
    pid = 999999
    def __init__(s, *a, **k): s.n = 0
    def communicate(s, *a, **k):
        s.n += 1
        if s.n == 1:
            raise A.subprocess.TimeoutExpired("agy", 1)
        return '{"event":"result","result":{"status":"SUCCESS","structured_output":{"ok":1},"usage":{}}}', ""
A.subprocess.Popen = SahteP2
try:
    r, _ = A.model_cagir("m", "x", {}, 1)
finally:
    A.subprocess.Popen = eski_run
kontrol('Agy result survives a hanging CLI', r == {"ok": 1})
class SahteP3(SahteP2):
    def communicate(s, *a, **k):
        return '{"event":"result","result":{"status":"ERROR","error":"Unknown model: gemini-yok"}}', ""
A.subprocess.Popen = SahteP3
try:
    try:
        A.model_cagir("m", "x", {}, 1); sonuc = "devam"
    except A.ModelHatasi as e:
        sonuc = "durdu" if "Unknown or unavailable model" in str(e) else "başka"
finally:
    A.subprocess.Popen = eski_run
kontrol('Unknown model fails fast', sonuc == "durdu")

bir = []
_t = 0.0
for i in range(400):
    _t += 3.0 if i not in (60, 140, 160, 300) else 9.0  
    bir.append({"id": str(i), "kind": "dialogue", "style": "D", "text": "x", "start": _t, "end": _t + 2.5})
sure = bir[-1]["end"] + 30
ad = [{"last_id": "59", "reason": "a"}, {"last_id": "139", "reason": "b"}, {"last_id": "159", "reason": "c"},
      {"last_id": "299", "reason": "d"}, {"last_id": "50", "reason": "konuşma sürüyor"}, {"last_id": "10", "reason": "baş"}]
m = A.mola_sec(ad, bir, sure)
kontrol('All valid natural break points retained', [x["last_id"] for x in m] == ["59", "139", "159", "299"]
        and all(bir[int(x["last_id"])]["end"] < x["t"] < bir[int(x["last_id"]) + 1]["start"] for x in m))
kontrol('No break during dialogue or opening minutes', A.mola_sec([ad[4], ad[5]], bir, sure) == [])
kontrol('Nearby break points are merged', len(A.mola_sec([{"last_id": "59", "reason": ""}, {"last_id": "59", "reason": ""}], bir, sure)) == 1)
kontrol('Names and interjections may remain unchanged', not A.untranslated_line("Hey, Kiriyama⟦1⟧!") and not A.untranslated_line("Bodoro, Bodoro!")
        and A.untranslated_line("I don't want to lose."))

for ad, no in [
    ("[SubsPlease] Monster - 57 (1080p) [A1B2C3E4]", 57),
    ("[Group] Anime - 12 [3F8E05]", 12),
    ("[Erai-raws] Ao no Hako Season 2 - 05 [1080p NF WEBRip HEVC EAC3][MultiSub][EDB9FC02]", 5),
    ("[MiniMTBB] March Comes in Like a Lion - 01 (BD 1080p) [4B6CBF2E]", 1),
    ("[Anime Time] Monster - 57", 57),
    ("[DB]Puella Magi Madoka Magica_-_02_(Dual Audio_10bit_BD1080p_x265)", 2),
    ("Mob Psycho 100 - 03 [x265]", 3), ("Show S02E07 1080p", 7),
    ("Show EP12", 12), ("Anime [01]", 1), ("Anime (02)", 2),
    ("Anime [1080p] [3F8E05]", None), ("Anime A1B2C3E4", None),
    ("[Group] Mob Psycho 100 [E03]", 3),
    ("[Group] Mob Psycho 100 [S01E03][1080p]", 3),
    ("[Group] 86 Eighty Six (Ep 05)", 5),
    ("[Group] Title [E05]", 5), ("[Group] Title [S01E05]", 5),
    ("[Group] Title [Episode 05]", 5), ("Mob Psycho 100 [03]", 3),
    ("[SubsPlease] 86 - Eighty Six (03) [1080p]", 3),
    ("Mob Psycho 100 03", 3), ("86 05", 5), ("Show_EP12_1080p", 12),
    ("[Group]_Anime_EP05_[1080p]", 5), ("Anime_05_1080p", 5),
    ("Show EP12v2", 12), ("Anime [01v2]", 1), ("Title Episode 5", 5),
    ("Show 05 H.264", 5),
    ("[Group] Title - 12 (BD 1920x1080 HEVC FLAC) [E5A1B2C3]", 12),
    ("[SubsPlease] Frieren - 28 (1080p) [ABCD1234]", 28),
    ("Title.2019.05.1080p", 5),
    ("Show E05abc", None), ("Show AEP05", None), ("Show A05", None),
    ("Show 05abc", None), ("Show 05v2", 5), ("Show 5", None),
    ("Show x264 x265 H.264 H.265 1080p 720p 480p 2160p 10bit 10-bit AAC2.0 DDP5.1", None),
    ("Anime [01] - 12", 12),
]:
    kontrol('Episode parser ignores technical and checksum numbers', A.bolum_no(ad) == no)

from unittest.mock import patch
from contextlib import ExitStack
_bos_ass = "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    f = td / "translations" / "001.json"
    partial = f.with_suffix(".partial.json")
    eski = {"translations": {"1": "eski", "2": "korunan"}, "untranslated": ["3"], "blocked": [], "usage": [{"input_tokens": 1}]}
    A.jyaz(partial, eski)
    A.jyaz(f, {"translations": {"1": "new"}, "untranslated": ["2", "3"], "blocked": [], "usage": []})
    A.parca_yarima_al(f)
    kontrol('Partial records merge and preserve prior conflicts',
            not f.exists() and A.joku(partial)["translations"] == {"1": "new", "2": "korunan"}
            and any(A.joku(x) == eski for x in f.parent.glob("001.partial-*.json")))
    parca = [{"id": str(i)} for i in range(1, 4)]
    with patch.object(A, "_cevir_istek", return_value=({"3": "complete"}, {})) as istek:
        r = A.cevir_parca({}, 1, parca, [], [], "", "", td)
    kontrol('Resume retries only missing units',
            istek.call_count == 1 and istek.call_args.args[1] == [{"id": "3"}]
            and r["translations"] == {"1": "new", "2": "korunan", "3": "complete"} and not r["untranslated"]
            and r["usage"] == [{"input_tokens": 1}, {}])
    kontrol('Successful resume keeps the partial archive', partial.exists())


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    partial = td / "translations" / "001.partial.json"
    eski = {"translations": {"1": "complete", "dis": "yabancı"}, "untranslated": ["3"],
            "blocked": ["2", "dis"], "usage": [{"input_tokens": 7}]}
    A.jyaz(partial, eski)
    parca = [{"id": str(i)} for i in range(1, 5)]
    with patch.object(A, "_cevir_istek", side_effect=[({"3": "new"}, {"input_tokens": 4}), A.ModelHatasi("ağ")]) as istek:
        try:
            A.cevir_parca({}, 1, parca, [], [], "", "", td)
            durdu = False
        except A.ModelHatasi:
            durdu = True
    kontrol('Resume excludes successful and blocked units',
            istek.call_args_list[0].args[1] == [{"id": "3"}, {"id": "4"}]
            and istek.call_args_list[1].args[1] == [{"id": "4"}])
    kayit = A.joku(partial)
    kontrol('Model errors preserve partial history and usage',
            durdu and any(A.joku(x) == eski for x in partial.parent.glob("001.partial-*.json"))
            and kayit["translations"]["3"] == "new" and kayit["untranslated"] == []
            and kayit["usage"] == [{"input_tokens": 7}, {"input_tokens": 4}])
    with patch.object(A, "_cevir_istek", return_value=({"4": "end"}, {"input_tokens": 2})) as istek:
        r = A.cevir_parca({}, 1, parca, [], [], "", "", td)
    kontrol('Resume scopes blocks and counts usage once',
            istek.call_args.args[1] == [{"id": "4"}] and r["blocked"] == ["2"]
            and r["translations"] == {"1": "complete", "3": "new", "4": "end"}
            and r["usage"] == [{"input_tokens": 7}, {"input_tokens": 4}, {"input_tokens": 2}])


for yol in ("ass", "srt", "video"):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        is_dir = td / "is"; is_dir.mkdir()
        dis = td / ("girdi." + (yol if yol != "video" else "mkv"))
        dis.write_text("tam kaynak", encoding="utf-8")
        def kes(*args, **kwargs):
            hedef = Path(args[0][-1]) if yol == "srt" else Path(args[1])
            hedef.write_text("yarıda", encoding="utf-8")
            raise RuntimeError("kesinti")
        def tamam(*args, **kwargs):
            hedef = Path(args[0][-1]) if yol == "srt" else Path(args[1])
            kontrol('Final source is invisible before successful preparation', not (is_dir / "source.ass").exists())
            hedef.write_text(_bos_ass, encoding="utf-8")
            return {} if yol == "video" else None
        nesne, ad = (A.shutil, "copyfile") if yol == "ass" else ((A.subprocess, "run") if yol == "srt" else (A, "altyazi_sec"))
        with patch.object(nesne, ad, side_effect=kes):
            try:
                A.kaynagi_hazirla(is_dir, dis if yol == "video" else None, None if yol == "video" else dis)
            except RuntimeError:
                pass
        kontrol('Interrupted source writes remain temporary', not (is_dir / "source.ass").exists()
                and (is_dir / "source.writing.ass").read_text() == "yarıda")
        with patch.object(nesne, ad, side_effect=tamam) as hazirla:
            A.kaynagi_hazirla(is_dir, dis if yol == "video" else None, None if yol == "video" else dis)
        kontrol('Interrupted source is archived before rebuilding',
                hazirla.call_count == 1 and (is_dir / "source.ass").read_text() == _bos_ass
                and any(x.read_text() == "yarıda" for x in is_dir.glob("source.writing-*.ass")))


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    a = {"work_dir": td / "work", "jobs_dir": td / "jobs", "library_dir": td / "ass", "level_report": False}
    is_dir = a["work_dir"] / "Seri" / "S01E01"
    (is_dir / "human").mkdir(parents=True)
    secim = {"ass": str(is_dir / "human" / "aday.ass"), "offset_seconds": 0, "kind": "mkv", "score": 9}
    Path(secim["ass"]).write_text("new", encoding="utf-8")
    for ad in ("breaks.json", "break-candidates.json"):
        A.jyaz(is_dir / ad, {"koru": ad})
    hedef = a["jobs_dir"] / "Seri" / "S01E01"; hedef.mkdir(parents=True)
    (hedef / "final.ass").write_text("eski", encoding="utf-8")
    A.jyaz(hedef / "record.json", {"eski": True})
    with patch.object(A, "video_fontlari", return_value={}):
        A.insan_teslim(a, "Seri", 1, 1, td / "video.mkv", secim, None, False)
    yedekler = list((hedef / "previous").iterdir())
    kontrol('Human delivery archives previous final and records', len(yedekler) == 1
            and (yedekler[0] / "final.ass").read_text() == "eski"
            and A.joku(yedekler[0] / "record.json") == {"eski": True})
    kontrol('Human delivery archives break records and candidates', all((hedef / ad).exists()
            for ad in ("breaks.json", "break-candidates.json", "human/aday.ass")))
    A.is_arsivini_yedekle(hedef, is_dir / "final.ass")
    kontrol('Identical final is not archived twice', list((hedef / "previous").iterdir()) == yedekler)
    (hedef / "final.ass").write_text("eski", encoding="utf-8")
    A.is_arsivini_yedekle(hedef, is_dir / "final.ass")
    kontrol('Archive timestamps never overwrite another backup', len(list((hedef / "previous").iterdir())) == 2)


import fcntl
for secenekler in (["--redo"], ["--level-only", "--redo"], []):
    with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
        td = Path(td)
        a = dict(A.VARSAYILAN, backend="agy", model="fake", model_translate="fake", model_review="fake", model_series="fake", model_warnings="fake", model_level="fake")
        a["work_dir"] = td / "work"
        a["human_check"] = True
        is_dir = a["work_dir"] / "Seri" / "S01E01"
        is_dir.mkdir(parents=True)
        (is_dir / "eski.txt").write_text("koru", encoding="utf-8")
        girdi = td / "Show - 01.mkv"; girdi.touch()
        kilit = stack.enter_context(open(is_dir.parent / ".lock", "w"))
        fcntl.flock(kilit, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stack.enter_context(patch.object(A, "ayarlar", return_value=a))
        stack.enter_context(patch.object(A.shutil, "which", return_value=None))
        stack.enter_context(patch.object(sys, "argv", ["dragoman", str(girdi), "--target", "tr", "--title", "Seri"] + secenekler))
        tasima = stack.enter_context(patch.object(A.shutil, "move"))
        kaynak = stack.enter_context(patch.object(A, "kaynagi_hazirla"))
        insan = stack.enter_context(patch.object(A, "insan_secimi"))
        duzey = stack.enter_context(patch.object(A, "duzey_isle"))
        try:
            A.main()
            mesaj = ""
        except SystemExit as e:
            mesaj = str(e)
        kontrol('Existing title lock blocks all work and moves',
                "another run in progress" in mesaj and not tasima.called
                and not kaynak.called and not insan.called and not duzey.called
                and (is_dir / "eski.txt").read_text() == "koru"
                and not list(is_dir.parent.glob("S01E01-previous-*")))


with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
    td = Path(td)
    a = dict(A.VARSAYILAN, backend="agy", model="fake", model_translate="fake", model_review="fake", model_series="fake", model_warnings="fake", model_level="fake")
    a.update(work_dir=td / "work", library_dir=td / "ass")
    is_dir = a["work_dir"] / "Seri" / "S01E01"; is_dir.mkdir(parents=True)
    (is_dir / "eski.txt").write_text("koru", encoding="utf-8")
    girdi = td / "Show - 01.mkv"; girdi.touch()
    def duzey(*args):
        with open(is_dir.parent / ".lock", "w") as ikinci:
            try:
                fcntl.flock(ikinci, fcntl.LOCK_EX | fcntl.LOCK_NB)
                kilitli = False
            except BlockingIOError:
                kilitli = True
        kontrol('Level-only processing holds title lock', kilitli)
        return {"episode": "S01E01", "cefr": "B2", "suitability": next(iter(A.SUITABILITY_LABELS)), "report": "test"}
    stack.enter_context(patch.object(A, "ayarlar", return_value=a))
    stack.enter_context(patch.object(A.shutil, "which", return_value=None))
    stack.enter_context(patch.object(A, "duzey_isle", side_effect=duzey))
    insan = stack.enter_context(patch.object(A, "insan_secimi"))
    stack.enter_context(patch.object(sys, "argv", ["dragoman", str(girdi), "--target", "tr", "--title", "Seri", "--level-only", "--redo"]))
    try:
        A.main()
        cikis = None
    except SystemExit as e:
        cikis = e.code
    kontrol('Level-only redo preserves translation work', cikis == 0 and not insan.called
            and (is_dir / "eski.txt").read_text() == "koru"
            and not list(is_dir.parent.glob("S01E01-previous-*")))


for kullan in (True, False):
    with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
        td = Path(td)
        a = dict(A.VARSAYILAN, backend="agy", model="fake", model_translate="fake", model_review="fake", model_series="fake", model_warnings="fake", model_level="fake")
        a.update({k: td / k for k in ("work_dir", "jobs_dir", "library_dir", "watch")})
        a.update(content_warnings=False, level_report=False, break_chapters=False)
        is_dir = a["work_dir"] / "Seri" / "S01E01"; is_dir.mkdir(parents=True)
        (is_dir / "eski.txt").write_text("koru", encoding="utf-8")
        (is_dir.parent / "series.md").write_text("series", encoding="utf-8")
        girdi = td / "Show - 01.mkv"; girdi.touch()
        def kaynak(is_dir, *args):
            kontrol('Redo archives before source preparation',
                    not (is_dir / "eski.txt").exists() and len(list(is_dir.parent.glob("S01E01-previous-*"))) == 1)
            return A.Ass(_bos_ass), {}
        def sec(a, v, sezon, n, bir, rehber, is_dir):
            (is_dir / "human").mkdir()
            aday = is_dir / "human" / "aday.ass"; aday.write_text("human", encoding="utf-8")
            return {"ass": str(aday), "use": kullan, "timing_match": 1, "offset_seconds": 0}
        def teslim(*args):
            secim = args[5] if kullan else args[-1]
            kontrol('Redo retains human subtitle path and one backup',
                    Path(secim["ass"]).read_text() == "human" and len(list(is_dir.parent.glob("S01E01-previous-*"))) == 1)
            return {"episode": "S01E01", "source_type": "human translation", "human": {"score": 9}, "library_dir": "test"}
        def paketle(video, final, hedef, ses, **kw):
            kontrol('Episode flow reads retained human subtitle',
                    kw["ek"][0][0].read_text() == "human"
                    and len(list(is_dir.parent.glob("S01E01-previous-*"))) == 1)
            return {"file": str(hedef)}
        if kullan:
            stack.enter_context(patch.object(A, "insan_teslim", side_effect=teslim))
        else:
            paket = stack.enter_context(patch.object(A, "paketle", side_effect=paketle))
            stack.enter_context(patch.object(A, "video_fontlari", return_value={}))
        for nesne, ad, kw in [
            (A, "ayarlar", {"return_value": a}), (A.shutil, "which", {"return_value": None}),
            (A, "kaynagi_hazirla", {"side_effect": kaynak}), (A, "insan_secimi", {"side_effect": sec}),
            (sys, "argv", {"new": ["dragoman", str(girdi), "--target", "tr", "--title", "Seri", "--redo"] + (["--no-mux"] if kullan else [])}),
        ]:
            stack.enter_context(patch.object(nesne, ad, **kw))
        A.main()
        if not kullan:
            kontrol('Redo reaches mux delivery', paket.call_count == 1)
        kontrol('Redo preserves previous work', next(is_dir.parent.glob("S01E01-previous-*" )).joinpath("eski.txt").read_text() == "koru")



with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
    td = Path(td)
    a = dict(A.VARSAYILAN, backend="agy", model="fake", model_translate="fake", model_review="fake", model_series="fake", model_warnings="fake", model_level="fake")
    a.update({k: td / k for k in ("work_dir", "jobs_dir", "library_dir")})
    a.update(content_warnings=False, level_report=False, break_chapters=False, redo=True)
    is_dir = a["work_dir"] / "Seri" / "S01E01"; is_dir.mkdir(parents=True)
    seri = is_dir.parent / "series.md"; seri.write_text("series", encoding="utf-8")
    (is_dir / "source.ass").write_text(_bos_ass, encoding="utf-8")
    (is_dir / "human").mkdir(); (is_dir / "human" / "aday.ass").write_text("human", encoding="utf-8")
    partial = is_dir / "translations" / "001.partial.json"
    once = {"translations": {"1": "korunan"}, "untranslated": ["2"], "blocked": [], "usage": [{"input_tokens": 7}]}
    A.jyaz(partial, once)
    A.jyaz(is_dir / "translations" / "not.json", {"untranslated": ["dokunma"]})
    A.jyaz(is_dir / "units.json", [{"id": "eski", "text": "eski"}])
    bir = [{"id": str(i), "text": f"line {i}", "kind": "dialogue"} for i in range(1, 6)]
    def parca(*args):
        r = {"translations": {"1": "new"}, "untranslated": ["2", "3", "4", "5"], "blocked": [],
             "usage": [{"input_tokens": 7}, {"input_tokens": 4}]}
        A.jyaz(is_dir / "translations" / "001.json", r)
        return r
    stack.enter_context(patch.object(A, "HATA_DOSYASI", None))
    stack.enter_context(patch.object(A, "birimleri_cikar", return_value=(bir, {})))
    baglam = stack.enter_context(patch.object(A, "bolum_baglami", return_value=None))
    stack.enter_context(patch.object(A, "cevir_parca", side_effect=parca))
    with patch.object(A, "cevir_parca") as cevir:
        try:
            A.bolum_isle(a, "Seri", 1, 1, None, None, "", seri, False, None)
            durdu = False
        except A.BolumHatasi as e:
            durdu = "Source units" in str(e)
        kontrol('Changed source units stop before model work',
                durdu and not cevir.called and not baglam.called
                and A.joku(is_dir / "units.json") == [{"id": "eski", "text": "eski"}]
                and A.joku(partial) == once)
    A.jyaz(is_dir / "units.json", bir)
    try:
        A.bolum_isle(a, "Seri", 1, 1, None, None, "", seri, False, None)
        durdu = False
    except A.BolumHatasi:
        durdu = True
    kontrol('Incomplete chunk moves to partial without deletion', durdu and not (partial.parent / "001.json").exists()
            and A.joku(partial)["translations"] == {"1": "new"} and (partial.parent / "not.json").exists())
    kontrol('Partial recovery does not double-count usage',
            A.joku(partial)["usage"] == [{"input_tokens": 7}, {"input_tokens": 4}])
    kontrol('Partial and backup files are not completed chunks', baglam.call_count == 1
            and A.joku(is_dir / "plan.json")["chunks"] == [a["translate_chunk"], a["review_chunk"]])
    
    A.jyaz(is_dir / "units.json", [])
    stack.enter_context(patch.object(A, "birimleri_cikar", return_value=([], {})))
    A.bolum_isle(a, "Seri", 1, 1, None, None, "", seri, False, None)
    kontrol('Episode delivery archives human folder without another move',
            (a["jobs_dir"] / "Seri" / "S01E01" / "human" / "aday.ass").read_text() == "human"
            and not list(is_dir.parent.glob("S01E01-previous-*")))


# Public configuration and multilingual behavior.
A.HATA_DOSYASI = None
import contextlib
import io
import copy
import os
from types import SimpleNamespace
import urllib.error

for code in ("ger", "deu", "de"):
    kontrol("German bibliographic and terminological aliases", A.language(code)["code"] == "de" and A.language(code)["iso3"] == "deu")
kontrol("At least fifty common languages", len({x["code"] for x in A.LANGUAGES.values()}) >= 50)
kontrol("French and Chinese aliases", A.language("fre") == A.language("fra") and A.language("chi") == A.language("zho"))
try:
    A.language("xyz")
    unknown_rejected = False
except ValueError:
    unknown_rejected = True
kontrol("Unknown language requires an explicit name", unknown_rejected and A.language("xyz", "Example language")["iso3"] == "xyz")
kontrol("Named unknown two-letter codes remain usable", A.language("xx", "Example language")["iso3"] == "und")
kontrol("No default backend/model; reports and warnings default on", A.VARSAYILAN["backend"] is None and A.VARSAYILAN["model"] is None
        and all(A.VARSAYILAN[k] is True for k in ("content_warnings", "break_chapters", "level_report"))
        and A.VARSAYILAN["learner_profile"] == "intermediate learner of the source language" and A.VARSAYILAN["human_check"])
for args, expected in ((["missing.ass"], "--target"), (["missing.ass", "--target", "es"], "Backend and model"),
                       (["missing.ass", "--target", "es", "--backend", "agy"], "Backend and model"),
                       (["missing.ass", "--target", "es", "--model", "fake"], "Backend and model")):
    stderr = io.StringIO()
    with patch.object(sys, "argv", ["dragoman", *args]), patch.object(A, "ayarlar", return_value=dict(A.VARSAYILAN)), contextlib.redirect_stderr(stderr), patch.object(A.subprocess, "Popen") as proc:
        try:
            A.main()
            rejected = False
        except SystemExit as error:
            rejected = error.code == 2
    kontrol("Required CLI configuration fails before work: " + expected, rejected and expected in stderr.getvalue() and not proc.called)
with patch.object(sys, "argv", ["dragoman", "--help"]), contextlib.redirect_stdout(io.StringIO()) as help_output:
    try:
        A.main()
    except SystemExit as error:
        help_ok = error.code == 0
kontrol("English CLI help", help_ok and "SOURCE_SUBTITLE" not in help_output.getvalue() and "--target TARGET" in help_output.getvalue() and "--setup" in help_output.getvalue())

with tempfile.TemporaryDirectory() as td:
    config = Path(td) / "settings.json"
    config.write_text(_j.dumps({"output_dir": td, "backend": "codex", "model": "fake", "model_review": "reviewer"}))
    settings = A.ayarlar(str(config))
    A.configure(settings, "ger", "ja")
    kontrol("Output root derives all four directories", [settings[k].name for k in ("work_dir", "library_dir", "jobs_dir", "watch")] == ["work", "library", "jobs", "watch"])
    kontrol("Role models inherit with explicit override", settings["model_review"] == "reviewer" and settings["model_translate"] == "fake")

for source_code, target_code, has_kanji in (("en", "es", False), ("ja", "en", True), ("en", "ja", True)):
    A.configure(dict(A.VARSAYILAN, backend="agy", model="fake"), source_code, target_code)
    units, mapping = A.birimleri_cikar(A.Ass(SYNTHETIC_ASS))
    # Target CJK permits CJK text in ordinary styles, while source-style exclusions remain source-dependent.
    ordinary = SYNTHETIC_ASS.replace(",Kanji,", ",Default,")
    ordinary_units, _ = A.birimleri_cikar(A.Ass(ordinary))
    kontrol("CJK extraction for " + source_code + " -> " + target_code,
            any("明日" in b["text"] for b in ordinary_units) == has_kanji)
    kontrol("Japanese source permits kanji and romaji styles", any("ashita" in b["text"] for b in units) == (source_code == "ja"))
    packet = [{"id": "1", "text": "A source sentence", "kind": "dialogue", "style": "Default"}]
    with patch.object(A, "model_cagir", return_value=({"translations": {"1": "明日は晴れる"}}, {})):
        reply, _ = A._cevir_istek({"model_translate": "fake", "timeout_seconds": 1}, packet, [], [], "", "")
    kontrol("CJK output acceptance for " + source_code + " -> " + target_code, bool(reply) == has_kanji)

wrapped = A.satir_kir("明日は晴れるので出かけましょう", 16)
kontrol("Wide-character wrap preserves text", wrapped.replace("\\N", "") == "明日は晴れるので出かけましょう" and "\\N" in wrapped)
kontrol("Wide-character width counts two columns", A.columns("ab界") == 4 and A.columns("e\u0301") == 1)
kontrol("Unspaced wrap does not split markers", A.satir_kir("明日⟦1⟧晴天晴天晴天", 10).count("⟦1⟧") == 1)
A.configure(dict(A.VARSAYILAN, backend="agy", model="fake"), "de", "es")
kontrol("Untranslated detection is source-neutral", A.untranslated_line("Guten Morgen zusammen", "Guten Morgen zusammen") and not A.untranslated_line("Buenos dias", "Guten Morgen"))
A.configure(dict(A.VARSAYILAN, backend="agy", model="fake"), "en", "es")
kontrol("Copied English sentence detection preserves names", A.untranslated_line("We are here.", "We are here!") and not A.untranslated_line("Alice Smith", "Alice Smith"))

# Font coverage uses actual translated characters, including non-Latin scripts.
font_fixture = ("[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Default,Limited,40\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Привет\n")
fixed, changes = A.font_duzelt(font_fixture, {"limited": set(range(32,127))})
kontrol("Cyrillic coverage selects the bundled fallback", "Style: Default,Source Sans 3,40" in fixed and bool(changes))
with patch.object(A, "log") as logs:
    fixed, changes = A.font_duzelt(font_fixture.replace("Привет", "明日"), {"limited": set(range(32,127))})
kontrol("Unsupported CJK fallback keeps the font and warns", "Style: Default,Limited,40" in fixed and not changes
        and "U+" in " ".join(str(c) for c in logs.call_args_list))
with tempfile.TemporaryDirectory() as td:
    first, second = Path(td)/"first.otf", Path(td)/"second.otf"
    first.write_bytes(b"first"); second.write_bytes(b"second")
    coverage = set(map(ord, "Привет"))
    def fake_coverage(paths):
        return {("First" if f == first else "Second").lower(): coverage for f in paths if f in (first,second)}
    with patch.object(A, "FALLBACK_PATHS", [first, second]), patch.object(A, "font_kapsami", side_effect=fake_coverage), patch.object(A, "_font_oku", side_effect=lambda data: ("First" if data == b"first" else "Second", coverage)):
        fixed, _ = A.font_duzelt(font_fixture, {"limited": set(range(32,127))})
    kontrol("User fallback fonts are checked in preference order", "Style: Default,First,40" in fixed)
A.configure(dict(A.VARSAYILAN, backend="agy", model="fake"), "en", "ja")
with patch.object(A, "log"):
    fixed, _ = A.font_duzelt(font_fixture.replace("Привет", "é"), {"limited": set(range(32,127))})
kontrol("Non-Latin target never folds decorative text", "é" in fixed)

# Source track selection honors source aliases, skips signs and picks the fullest track.
A.configure(dict(A.VARSAYILAN, backend="agy", model="fake"), "ger", "es")
with tempfile.TemporaryDirectory() as td:
    target = Path(td)/"source.ass"
    streams = [{"index": i, "codec_type": "subtitle", "codec_name": "ass", "tags": {"language": lang, "title": title}}
               for i,lang,title in ((0,"eng","Full"),(1,"ger","Signs"),(2,"deu","Full"),(3,"ger","Fuller"))]
    def fake_extract(cmd, **kwargs):
        count = 5 if cmd[cmd.index("-map")+1] == "0:3" else 2
        Path(cmd[-1]).write_text("\nDialogue:" * count)
        return SimpleNamespace(returncode=0)
    with patch.object(A, "ffprobe", return_value=streams), patch.object(A.subprocess, "run", side_effect=fake_extract):
        selected = A.altyazi_sec(Path(td)/"video.mkv",target)
    kontrol("Fullest source-language subtitle track", selected["track"] == 3 and selected["events"] == 5)

# All model transports are fake. No model CLI or HTTP connection is invoked.
small_schema = {"type":"object", "properties":{"ok":{"type":"boolean"}}, "required":["ok"]}
for backend in ("agy", "codex", "claude-code"):
    A.configure(dict(A.VARSAYILAN, backend=backend, model="fake"), "en", "es")
    captured = {}
    def fake_cli(cmd, **kwargs):
        captured.update(cmd=cmd, kwargs=kwargs)
        if backend == "codex":
            schema = _j.loads(Path(cmd[cmd.index("--output-schema")+1]).read_text())
            captured["schema"] = schema
            Path(cmd[cmd.index("-o")+1]).write_text('{"ok":true}')
            return SimpleNamespace(returncode=0,stdout="",stderr="")
        return SimpleNamespace(returncode=0, stdout='{"structured_output":{"ok":true},"usage":{"input_tokens":3}}', stderr="")
    class FakeAgy:
        pid = 999999
        def __init__(self, cmd, **kwargs):
            captured.update(cmd=cmd, kwargs=kwargs)
        def communicate(self, message=None, **kwargs):
            captured["stdin"] = message
            return '{"event":"result","result":{"status":"SUCCESS","structured_output":{"ok":true},"usage":{"input_tokens":3}}}', ""
    with patch.object(A.subprocess, "run", side_effect=fake_cli), patch.object(A.subprocess, "Popen", FakeAgy), patch.object(A.os, "killpg"), patch.object(A, "_kota_bekle") as quota:
        reply, usage = A.model_cagir("fake:medium" if backend == "codex" else "fake", "test prompt", small_schema, 1, deneme=1)
    kontrol("Structured adapter: " + backend, reply == {"ok":True} and not quota.called)
    if backend == "codex":
        kontrol("Codex ephemeral read-only invocation and effort", "--ephemeral" in captured["cmd"] and "read-only" in captured["cmd"] and "model_reasoning_effort=medium" in captured["cmd"] and captured["kwargs"]["input"] == "test prompt")
        kontrol("Codex strict copy leaves input schema unchanged", captured["schema"]["additionalProperties"] is False and "additionalProperties" not in small_schema)
    elif backend == "claude-code":
        kontrol("Claude tools disabled with stdin prompt", captured["cmd"][captured["cmd"].index("--tools")+1] == "" and captured["kwargs"]["input"] == "test prompt")
    else:
        kontrol("Agy stream input is passed on stdin", _j.loads(captured["stdin"])["message"]["content"] == "test prompt")

nested = {"type":"object","properties":{"nested":{"type":"object","properties":{"x":{"type":"string"}}},"list":{"type":"array","items":{"type":"object","properties":{"y":{"type":"number"}}}}}}
strict = A._strict_schema(nested)
kontrol("Codex recursively requires every property", strict["required"] == ["nested","list"] and strict["properties"]["nested"]["required"] == ["x"] and strict["properties"]["list"]["items"]["additionalProperties"] is False and "required" not in nested)
A.configure(dict(A.VARSAYILAN, backend="codex", model="fake"), "en", "es")
def fake_translation_cli(cmd, **kwargs):
    strict = _j.loads(Path(cmd[cmd.index("--output-schema")+1]).read_text())
    kontrol("Codex dynamic translation IDs survive strict schemas", strict["properties"]["translations"]["required"] == ["1","2"])
    Path(cmd[cmd.index("-o")+1]).write_text('{"translations":{"1":"Hola","2":"Adios"}}')
    return SimpleNamespace(returncode=0,stdout="",stderr="")
with patch.object(A.subprocess, "run", side_effect=fake_translation_cli):
    reply, _ = A.model_cagir("fake", "TRANSLATE:\n1 [dialogue|D]: Hello\n2 [dialogue|D]: Goodbye\n\nNext lines", A.CEVIRI_SEMA, 1, deneme=1)
kontrol("Codex receives complete keyed translations", len(reply["translations"]) == 2)

# An in-memory HTTP peer exercises urllib request/status handling without network access.
class FakeHTTPResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
http_requests = []
http_statuses = [400, 429, 200]
def fake_http(req, timeout):
    body = _j.loads(req.data)
    http_requests.append(body)
    status = http_statuses.pop(0)
    if status != 200:
        raise urllib.error.HTTPError(req.full_url, status, "synthetic error", {"Retry-After":"7"}, io.BytesIO(b'schema not supported' if status == 400 else b'rate limited'))
    return FakeHTTPResponse(b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}],"usage":{"prompt_tokens":5}}')
A.configure(dict(A.VARSAYILAN, backend="openai", model="fake", base_url="http://127.0.0.1:1/v1", api_key_env=""), "en", "es")
with patch.object(A.urllib.request, "urlopen", side_effect=fake_http), patch.object(A.time, "sleep") as sleep, patch.object(A, "_kota_bekle") as quota:
    reply, usage = A.model_cagir("fake", "test prompt", small_schema, 1, deneme=2)
kontrol("OpenAI 400 falls back to json_object with schema", http_requests[0]["response_format"]["type"] == "json_schema" and http_requests[1]["response_format"]["type"] == "json_object" and '"required"' in http_requests[1]["messages"][0]["content"])
kontrol("OpenAI honors Retry-After without agy quota checks", sleep.call_args.args == (7.0,) and not quota.called and reply == {"ok":True} and usage == {"prompt_tokens":5})
with tempfile.TemporaryDirectory() as td:
    error_file = Path(td)/"errors.jsonl"
    # Synthetic secret supplied only by this test; no real credential is read.
    synthetic_key = "synthetic-" + "credential-value"
    A.configure(dict(A.VARSAYILAN, backend="openai", model="fake", api_key_env="LLM_TEST_KEY"), "en", "es")
    def key_error(req, timeout):
        kontrol("API authorization sent only to transport", req.get_header("Authorization") == "Bearer " + synthetic_key)
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(("invalid key " + synthetic_key).encode()))
    output = io.StringIO()
    with patch.dict(os.environ, {"LLM_TEST_KEY":synthetic_key}), patch.object(A, "HATA_DOSYASI", error_file), patch.object(A.urllib.request,"urlopen",side_effect=key_error), contextlib.redirect_stdout(output):
        try:
            A.model_cagir("fake", "test", small_schema, 1, deneme=1)
            message = "unexpected success"
        except A.ModelHatasi as error:
            message = str(error)
    kontrol("API keys never occur in errors or logs", synthetic_key not in message + output.getvalue() + error_file.read_text() and "API authentication failed" in message)
for backend, transport in (("openai","_openai"),("agy","_agy"),("codex","_cli"),("claude-code","_cli")):
    A.configure(dict(A.VARSAYILAN, backend=backend, model="fake"), "en", "es")
    with patch.object(A,transport, return_value=({},{})), patch.object(A.time,"sleep"):
        try:
            A.model_cagir("fake","test",small_schema,1,deneme=1)
            rejected=False
        except A.ModelHatasi:
            rejected=True
    kontrol("Shared required-key validation: " + backend,rejected)
    with patch.object(A,transport,side_effect=A.ModelHatasi("unknown model")) as call, patch.object(A.time,"sleep") as sleep, patch.object(A,"_kota_bekle") as quota:
        try:
            A.model_cagir("fake","test",small_schema,1)
        except A.ModelHatasi:
            pass
    kontrol("Configuration errors fail fast: " + backend,call.call_count == 1 and not sleep.called and not quota.called)
    with patch.object(A,transport,side_effect=A.ModelHatasi("sensitive words prohibited use")), patch.object(A.time,"sleep") as sleep:
        try:
            A.model_cagir("fake","test",small_schema,1)
            blocked=False
        except A.GuvenlikEngeli:
            blocked=True
    kontrol("Shared safety handling: " + backend,blocked and not sleep.called)

# Verify mux flags and metadata with a fake media toolchain, retaining actual verification logic.
A.configure(dict(A.VARSAYILAN,backend="agy",model="fake"),"en","deu")
for preferred_audio in (None,"ja"):
    with tempfile.TemporaryDirectory() as td:
        td=Path(td);video=td/"video.mkv";video.write_bytes(b"source video")
        subtitle=td/"final.ass";subtitle.write_text(SYNTHETIC_ASS)
        human=td/"human.ass";human.write_text(SYNTHETIC_ASS)
        output=td/"result.mkv";output.write_bytes(b"previous delivery")
        streams=[{"index":0,"codec_type":"video","codec_name":"av1"},
                 {"index":1,"codec_type":"audio","tags":{"language":"eng"},"disposition":{"default":1}},
                 {"index":2,"codec_type":"audio","tags":{"language":"jpn"},"disposition":{"default":0}}]
        new_streams=streams+[{"index":3,"codec_type":"subtitle","tags":{"language":"deu"}}]
        mux_cmd=[]
        def fake_media(cmd, **kwargs):
            if cmd[0] == "ffprobe":
                return SimpleNamespace(stdout="100.0",returncode=0)
            if "-map" in cmd and cmd[cmd.index("-map")+1] == "0:v":
                mux_cmd.extend(cmd);Path(cmd[-1]).write_bytes(b"new delivery")
            else:
                Path(cmd[-1]).write_text(SYNTHETIC_ASS)
            return SimpleNamespace(stdout="",returncode=0)
        with patch.object(A,"ffprobe",side_effect=[streams,new_streams]), patch.object(A.subprocess,"run",side_effect=fake_media), patch.object(A,"akis_hash",return_value=["v,SHA256=valid","a,SHA256=valid"]), patch.object(A,"altyazi_ic_ice",return_value=True):
            result=A.paketle(video,subtitle,output,preferred_audio,ek=[(human,"German (human translation)")])
        kontrol("Non-Turkish mux metadata", "language=deu" in mux_cmd and "title=German" in mux_cmd and "title=German (human translation)" in mux_cmd)
        kontrol("AV1 dual-input and packet verification retained", result["av1_dual_input"] and result["identical_av"] and "+noparse+nofillin" in mux_cmd)
        kontrol("Audio dispositions preserved unless requested", any(x.startswith("-disposition:a") for x in mux_cmd) == bool(preferred_audio))
        kontrol("Previous MKV delivery archived", any(f.read_bytes()==b"previous delivery" for f in (td/"previous").iterdir()))


# End-to-end subtitle-only pipeline, including real prompt assembly, review, archives and resume.
A.HATA_DOSYASI = None
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    source_file = td / "source.ass"
    source_file.write_text(SYNTHETIC_ASS)
    output = td / "output"
    cli_args = ["dragoman", str(source_file), "--target", "es", "--backend", "agy", "--model", "fake",
                "--title", "Example series", "--episode", "1", "--output", str(output), "--no-mux", "--no-level-report", "--no-content-warnings", "--no-break-chapters", "--no-share-prompt"]
    calls = []
    def fake_pipeline_model(model, prompt, schema, timeout, **kwargs):
        calls.append((prompt, schema))
        if schema == A.SERI_SEMA:
            return {"series": "register table\n" + "Consistent terminology and character voice. " * 60}, {}
        if schema == A.BAGLAM_SEMA:
            return {key: [] for key in schema["required"]}, {}
        if schema == A.CEVIRI_SEMA:
            ids = re.findall(r"^(\d+) \[", prompt.split("TRANSLATE:\n")[1], re.M)
            return {"translations": {key: "Traduccion de la frase " + key for key in ids}}, {}
        if schema == A.INCELEME_SEMA:
            ids = re.findall(r"^(\d+) \[", prompt, re.M)
            return {"corrections": [{"id": ids[1], "category": "meaning_error", "new": "Una frase corregida.", "reason": "Meaning restored"}], "last_reviewed_id":ids[-1]}, {}
        raise AssertionError("Unexpected opt-in model call")
    def run_pipeline(args):
        with patch.object(sys, "argv", args), patch.object(A, "ayarlar", return_value=dict(A.VARSAYILAN)), patch.object(A.shutil, "which", return_value=None), patch.object(A, "model_cagir", side_effect=fake_pipeline_model), contextlib.redirect_stdout(io.StringIO()):
            A.main()
    run_pipeline(cli_args)
    job = output / "work" / "Example series" / "S01E01"
    record = A.joku(job / "record.json")
    final = (job / "final.ass").read_text()
    kontrol("End-to-end multilingual subtitle delivery", "Una frase corregida." in final and "明日は晴れる" in final and "ashita wa hareru" in final and record["correction_count"] == 1)
    kontrol("Target-code library tag and English work filenames", (output / "library" / "Example series" / "Season 01" / "Example series S01E01 [ES].ass").exists()
            and (output / "jobs" / "Example series" / "S01E01" / "record.json").exists())
    kontrol("Explicit opt-outs disable report and warning calls", len(calls) == 4 and record["warning_status"] == "off" and record["level_report"] is None)
    previous_calls = len(calls)
    run_pipeline(cli_args)
    kontrol("Completed translation and review resume without model calls", len(calls) == previous_calls)
    alternate_args = list(cli_args); alternate_args[alternate_args.index("--target")+1] = "de"
    try:
        run_pipeline(alternate_args)
        mismatch_rejected=False
    except SystemExit as error:
        mismatch_rejected="another language pair" in str(error)
    kontrol("Language-pair mismatch cannot reuse cached decisions", mismatch_rejected and len(calls) == previous_calls)
A.HATA_DOSYASI = None

# The backend diagnostic is schema-constrained and makes one logical request.
import check_backend
for succeed in (True, False):
    stdout = io.StringIO()
    with patch.object(sys, "argv", ["check_backend.py", "--backend", "agy", "--model", "fake"]), patch.object(A, "ayarlar", return_value=dict(A.VARSAYILAN)), patch.object(A, "model_cagir", return_value=({"ok":succeed},{})) as call, contextlib.redirect_stdout(stdout):
        code=check_backend.main()
    kontrol("Backend diagnostic prints a truthful result", code == (0 if succeed else 1) and stdout.getvalue().startswith("OK" if succeed else "FAIL") and call.call_count == 1 and call.call_args.kwargs["deneme"] == 1)

# Language addenda retain every required example verbatim.
original_guide = Path(__file__).parent / "_yerel" / "rehber-kaynak.md"
if original_guide.exists():
    original = original_guide.read_text()
    table = original[original.index("| Kaynak |"):original.index("## Biçim")]
    kontrol("Turkish counterexample table preserved exactly", table in (Path(__file__).parent / "guides" / "tr.md").read_text())


# Task 2: safe interactive setup and actionable errors.
A.HATA_DOSYASI = None
setup_secret = "synthetic-" + "setup-credential"
for backend in A.BACKENDS:
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.json"
        A.jyaz(cfg, {"parallel": 7, "share_prompt": False})
        answers = [backend, "example-model"]
        if backend == "openai":
            answers += ["http://127.0.0.1:11434/v1", "SETUP_TEST_KEY"]
        stdout = io.StringIO()
        with patch.object(A.shutil, "which", side_effect=lambda name: "/fake/" + name if name in ("agy", "claude") else None), patch.dict(os.environ, {"OPENAI_API_KEY": setup_secret, "SETUP_TEST_KEY": setup_secret}), patch("builtins.input", side_effect=answers), patch.object(A, "model_cagir", return_value=({"ok": True}, {})) as diagnostic, contextlib.redirect_stdout(stdout):
            ok = A.setup(cfg)
        saved = A.joku(cfg)
        kontrol("Setup writes provider and preserves other keys: " + backend,
                ok and saved["backend"] == backend and saved["model"] == "example-model" and saved["parallel"] == 7 and saved["share_prompt"] is False and diagnostic.call_count == 1)
        kontrol("Setup detects all backends without displaying credentials: " + backend,
                all(name + ":" in stdout.getvalue() for name in A.BACKENDS) and "OPENAI_API_KEY set" in stdout.getvalue()
                and "codex: not detected" in stdout.getvalue() and setup_secret not in stdout.getvalue() + cfg.read_text())
        if backend == "openai":
            kontrol("Setup stores only the API key variable name", saved["api_key_env"] == "SETUP_TEST_KEY")

with tempfile.TemporaryDirectory() as td:
    cfg = Path(td)/"config.json"
    with patch("builtins.input", side_effect=["openai", "fake", "http://127.0.0.1:11434/v1", "-"]), patch.object(A.shutil, "which", return_value=None), patch.object(A, "model_cagir", return_value=({"ok": True},{})), contextlib.redirect_stdout(io.StringIO()):
        ok=A.setup(cfg)
    kontrol("Local setup can deliberately omit an API key", ok and A.joku(cfg)["api_key_env"] == "")

# Main's setup-only command needs neither subtitle input nor a target language.
for tty in (True, False):
    stderr = io.StringIO()
    with patch.object(sys, "argv", ["dragoman", "--setup"]), patch.object(A, "interactive", return_value=tty), patch.object(A, "setup", return_value=True) as setup_call, contextlib.redirect_stderr(stderr):
        try:
            A.main()
        except SystemExit as error:
            code=error.code
    kontrol("Setup-only CLI respects terminal availability", code == (0 if tty else 2) and setup_call.called == tty)

# Missing provider configuration: offer setup on a TTY; show complete instructions otherwise.
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    source=td/"source.ass";source.write_text(SYNTHETIC_ASS)
    args=["dragoman",str(source),"--target","es","--title","Provider test","--episode","1","--output",str(td/"output"),"--no-share-prompt"]
    for tty in (False, True):
        questions=[]; stderr=io.StringIO()
        def decline(question):
            questions.append(question);return ""
        with patch.object(sys,"argv",args), patch.object(A,"ayarlar",return_value=dict(A.VARSAYILAN)), patch.object(A,"interactive",return_value=tty), patch("builtins.input",side_effect=decline), contextlib.redirect_stderr(stderr):
            try:
                A.main()
            except SystemExit as error:
                code=error.code
        kontrol("Missing-backend TTY offer or non-TTY example", code == 2 and bool(questions) == tty and "--setup" in stderr.getvalue()
                and "python3 dragoman.py INPUT --target es --backend openai --model" in stderr.getvalue())
    # Complete the offered setup and continue the same translation run.
    settings=dict(A.VARSAYILAN,backend="agy",model="fake")
    results=[]
    def finished(a,*args):
        results.append(a)
        return {"episode":"S01E01","units":0,"correction_count":0,"warning_count":0,"untranslated":[],"minutes":0,"library_dir":"local","warning_status":"complete"}
    def prepare_series(a,title,sources,path,guide):
        (path/"series.md").write_text("series");return path/"series.md"
    with patch.object(sys,"argv",args), patch.object(A,"ayarlar",side_effect=[dict(A.VARSAYILAN),dict(settings)]), patch.object(A,"interactive",return_value=True), patch("builtins.input",return_value="y"), patch.object(A,"setup",return_value=True) as setup_call, patch.object(A.shutil,"which",return_value=None), patch.object(A,"seri_hazirla",side_effect=prepare_series), patch.object(A,"bolum_isle",side_effect=finished), contextlib.redirect_stdout(io.StringIO()):
        A.main()
    kontrol("TTY setup can continue the original translation", setup_call.called and len(results)==1 and results[0]["model_translate"]=="fake")
    kontrol("All three reports/features default on", all(results[0][key] for key in ("level_report","content_warnings","break_chapters")))
    for kind in ("flags","config"):
        results.clear()
        overrides={key:False for key in ("level_report","content_warnings","break_chapters")}
        configured=dict(settings,**(overrides if kind=="config" else {}))
        disabled=args+["--backend","agy","--model","fake"]+(["--no-level-report","--no-content-warnings","--no-break-chapters"] if kind=="flags" else [])
        with patch.object(sys,"argv",disabled), patch.object(A,"ayarlar",return_value=configured), patch.object(A.shutil,"which",return_value=None), patch.object(A,"bolum_isle",side_effect=finished), contextlib.redirect_stdout(io.StringIO()):
            A.main()
        kontrol("Default features can be disabled with " + kind, all(results[0][key] is False for key in overrides))
    kontrol("Local summary is written even with reports disabled", (td/"output"/"work"/"Provider test"/"run-summary.txt").read_text().startswith("\nSUMMARY"))

for backend, tool in A.CLI_NAMES.items():
    A.configure(dict(A.VARSAYILAN, backend=backend, model="fake"),"en","es")
    transport="_agy" if backend=="agy" else "_cli"
    with patch.object(A,transport,side_effect=FileNotFoundError("missing executable")), patch.object(A.time,"sleep") as sleep:
        try:
            A.model_cagir("fake","prompt",small_schema,1)
        except A.ModelHatasi as error:
            message=str(error)
    kontrol("CLI-not-found errors name installation and sign-in fix: " + tool, tool in message and "install" in message and "sign in" in message and not sleep.called and "\n" not in message)
    with patch.object(A,transport,side_effect=A.ModelHatasi("not logged in")), patch.object(A.time,"sleep") as sleep:
        try:
            A.model_cagir("fake","prompt",small_schema,1)
        except A.ModelHatasi as error:
            message=str(error)
    kontrol("Sign-in failures are actionable and do not retry: " + tool, tool in message and "sign in" in message and not sleep.called)
A.configure(dict(A.VARSAYILAN,backend="openai",model="fake",api_key_env="ABSENT_TEST_KEY"),"en","es")
with patch.dict(os.environ,{},clear=True), patch.object(A.urllib.request,"urlopen") as http, patch.object(A.time,"sleep") as sleep:
    try:
        A.model_cagir("fake","prompt",small_schema,1)
    except A.ModelHatasi as error:
        message=str(error)
kontrol("Missing API key names variable without a request", "ABSENT_TEST_KEY" in message and "empty" in message and not http.called and not sleep.called)
A.configure(dict(A.VARSAYILAN,backend="openai",model="fake",api_key_env=""),"en","es")
with patch.object(A.urllib.request,"urlopen",side_effect=urllib.error.URLError("connection refused")), patch.object(A.time,"sleep") as sleep:
    try:
        A.model_cagir("fake","prompt",small_schema,1)
    except A.ModelHatasi as error:
        message=str(error)
kontrol("Unreachable endpoint gives a one-line fix", "base_url" in message and "local server" in message and "\n" not in message and not sleep.called)

# Per-stage usage accepts provider aliases but never arbitrary keys.
A.RUN_STATS={"stage_tokens":{},"errors":set()}
A.record_usage("translate",{"prompt_tokens":12,"completion_tokens":7,"completion_tokens_details":{"reasoning_tokens":3},"hostname":"PRIVATE"})
A.record_usage("unknown-stage",{"input_tokens":999})
kontrol("Per-stage token totals use fixed numeric fields", A.RUN_STATS["stage_tokens"]=={"translate":{"input":12,"output":7,"reasoning":3}})

# The share flow must never make a socket or urllib call, under any answer.
private_values=["DISTINCTIVE_PRIVATE_TITLE","/private/hidden/subtitles/example.ass","DISTINCTIVE_SUBTITLE_LINE","DISTINCTIVE_RAW_ERROR","local-secret-model","http://private-host:123/v1","private-user"]
private_job={"title":private_values[0],"source":private_values[1],"text":private_values[2],"error":private_values[3],"models":{"translate":private_values[4]},"base_url":private_values[5],"username":private_values[6],"units":15,"correction_count":4,"review_traps":{"inserted":3,"missed_first":2,"missed_twice":1},"usage":{"other":private_values[2]}}
share_settings=dict(A.VARSAYILAN,backend="agy",model=private_values[4],base_url=private_values[5],share_prompt=True)
A.configure(share_settings,"de","es")
allowed_report_fields={"tool_version","os","python","backend","source_language","target_language","episode_count","unit_count","review_corrections","trap_lines_caught","trap_lines_total","stage_tokens","elapsed_minutes","feature_flags","error_categories"}
report=A.anonymous_report(share_settings,[private_job],2.25,[private_values[3]])
encoded_report=A.report_text(report)
kontrol("Anonymous report is constructed only from allow-listed fields", set(report)==allowed_report_fields and all(value not in encoded_report for value in private_values)
        and report["unit_count"]==15 and report["trap_lines_total"]==5 and report["trap_lines_caught"]==2 and set(report["error_categories"])<=A.ERROR_CATEGORIES)
contaminated=A.anonymous_report(dict(share_settings,backend=private_values[4]),[dict(private_job,units=private_values[0],correction_count=private_values[2])],float("inf"),stats={"stage_tokens":{"unknown":{"input":private_values[2]},"translate":{"input":private_values[0],"output":17,"reasoning":True}},"errors":[private_values[3],"timeout"]})
kontrol("Report sanitizes even contaminated allowed values", all(value not in A.report_text(contaminated) for value in private_values)
        and contaminated["backend"]=="unknown" and contaminated["unit_count"]==0 and contaminated["elapsed_minutes"]==0)

for answer in ("", "N", "yes", "anything", "y", "never"):
    with tempfile.TemporaryDirectory() as td:
        cfg=Path(td)/"config.json";A.jyaz(cfg,{"parallel":9})
        stdout=io.StringIO()
        responses=[answer,"n"] if answer=="y" else [answer]
        with patch.object(A,"interactive",return_value=True), patch("builtins.input",side_effect=responses) as ask, patch("webbrowser.open") as browser, patch.object(socket,"socket",side_effect=AssertionError("share must not use sockets")), patch.object(A.urllib.request,"urlopen",side_effect=AssertionError("share must not request URLs")), patch.object(A.urllib.request,"Request",side_effect=AssertionError("share must not construct HTTP requests")), contextlib.redirect_stdout(stdout):
            A.share_report(share_settings,[private_job],2.25,[private_values[3]],config=cfg)
        output=stdout.getvalue()
        kontrol("Share preview contains no private fields: " + repr(answer), all(value not in output for value in private_values) and "publicly" in output and "own account" in output and "Nothing is sent" in output)
        kontrol("Share only prepares a link for exact y: " + repr(answer), (A.ISSUE_URL+"?title=" in output)==(answer=="y") and ask.call_count==(2 if answer=="y" else 1) and not browser.called)
        kontrol("Never preference is persisted without losing config: " + repr(answer), A.joku(cfg)["parallel"]==9 and (A.joku(cfg).get("share_prompt") is False)==(answer=="never"))
        if answer=="y":
            from urllib.parse import parse_qs, urlsplit
            url=next(line for line in output.splitlines() if line.startswith(A.ISSUE_URL))
            body=parse_qs(urlsplit(url).query)["body"][0]
            kontrol("Displayed report exactly matches prefilled issue body", body in output and len(url)<6000)

with patch.object(A,"interactive",return_value=True), patch("builtins.input",side_effect=["y","y"]), patch("webbrowser.open") as browser, contextlib.redirect_stdout(io.StringIO()):
    A.share_report(share_settings,[private_job],1)
kontrol("Browser opens only after a second explicit y", browser.call_count==1 and browser.call_args.args[0].startswith(A.ISSUE_URL))
for options in ({"tty":False},{"tty":True,"share_prompt":False},{"tty":True,"detached":True},{"tty":True,"level_only":True}):
    config=dict(share_settings,share_prompt=options.get("share_prompt",True))
    stdout=io.StringIO()
    with patch.object(A,"interactive",return_value=options["tty"]), patch("builtins.input") as ask, patch("webbrowser.open") as browser, contextlib.redirect_stdout(stdout):
        A.share_report(config,[private_job],1,detached=options.get("detached",False),level_only=options.get("level_only",False))
    kontrol("No share prompt in suppressed flows: " + str(options), not ask.called and not browser.called and not stdout.getvalue())
# Force a large numeric-only stage section to exercise the drop-detail path.
large=dict(report,stage_tokens={stage:{key:10**300 for key in ("input","output","reasoning")} for stage in A.STAGES})
url=A.issue_url(large)
from urllib.parse import parse_qs, urlsplit
body=_j.loads(parse_qs(urlsplit(url).query)["body"][0])
kontrol("Share URL stays under limit by dropping stage details first", len(url)<6000 and "stage_tokens" not in body and body["unit_count"]==report["unit_count"])


# Default-on stages execute in the real pipeline with fake model replies; warning failures stay loud.
with tempfile.TemporaryDirectory() as td:
    td=Path(td);source=td/"source.ass";source.write_text(SYNTHETIC_ASS)
    out=td/"output"
    argv=["dragoman",str(source),"--target","es","--backend","agy","--model","fake","--title","Default features","--episode","1","--output",str(out),"--no-share-prompt"]
    def default_models(model,prompt,schema,timeout,**kwargs):
        if schema==A.OGRENME_SEMA:
            return {"cefr":"B1","confidence":"medium","suitability":"productive_challenge","summary":"Readable with support.","difficulties":[],"evidence":[],"expressions":[]},{}
        if schema==A.SANSUR_SEMA:
            raise A.GuvenlikEngeli("content safety refusal")
        return fake_pipeline_model(model,prompt,schema,timeout,**kwargs)
    stdout=io.StringIO()
    with patch.object(sys,"argv",argv), patch.object(A,"ayarlar",return_value=dict(A.VARSAYILAN)), patch.object(A.shutil,"which",return_value=None), patch.object(A,"model_cagir",side_effect=default_models), contextlib.redirect_stdout(stdout):
        A.main()
    folder=out/"work"/"Default features"/"S01E01"
    report=A.joku(folder/"record.json")
    kontrol("Default level report is generated and recorded locally", (folder/"level.md").exists() and report["level_report"]["cefr"]=="B1")
    kontrol("Partial default warning scan is visible in console, ASS and saved summary", report["warning_status"]=="partial" and report["warning_count"]==1
            and "content warning scan partial" in stdout.getvalue()
            and "ContentWarning" in (folder/"final.ass").read_text()
            and "content warning scan partial" in (folder.parent/"run-summary.txt").read_text())
    # A later failed run must save its report and preserve the previous record.
    with patch.object(sys,"argv",argv), patch.object(A,"ayarlar",return_value=dict(A.VARSAYILAN)), patch.object(A.shutil,"which",return_value=None), patch.object(A,"bolum_isle",side_effect=A.ModelHatasi("timeout while translating")), contextlib.redirect_stdout(io.StringIO()):
        try:
            A.main()
        except SystemExit as error:
            failed_exit=error.code
    failed=A.joku(folder/"record.json")
    kontrol("Failed jobs always retain a local run report and summary", failed_exit==2 and failed["status"]=="failed" and failed["error_categories"]==["timeout"]
            and list(folder.glob("record-previous-*.json")) and "failed 1" in (folder.parent/"run-summary.txt").read_text())
    kontrol("Summary history is archived", bool(list((folder.parent/"previous").glob("run-summary-*.txt"))))
A.HATA_DOSYASI=None

with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    argv=["dragoman","unused.ass","--target","es","--backend","agy","--model","fake","--output",str(td),"--detach"]
    with patch.object(sys,"argv",argv), patch.object(A,"ayarlar",return_value=dict(A.VARSAYILAN)), patch.object(A,"interactive",return_value=True), patch.object(A.subprocess,"Popen",return_value=SimpleNamespace(pid=123)) as launch, patch("builtins.input") as ask, contextlib.redirect_stdout(io.StringIO()):
        A.main()
    kontrol("Detached child always suppresses sharing", "--no-share-prompt" in launch.call_args.args[0] and "--detach" not in launch.call_args.args[0] and not ask.called)

with tempfile.TemporaryDirectory() as td:
    td=Path(td);source=td/"source.ass";source.write_text(SYNTHETIC_ASS)
    argv=["dragoman",str(source),"--target","es","--backend","agy","--model","fake","--output",str(td/"out"),"--level-only"]
    with patch.object(sys,"argv",argv), patch.object(A,"ayarlar",return_value=dict(A.VARSAYILAN)), patch.object(A,"interactive",return_value=True), patch.object(A.shutil,"which",return_value=None), patch.object(A,"duzey_isle",return_value={"episode":"Movie","cefr":"B1","suitability":"comfortable","report":"local"}), patch("builtins.input") as ask, patch.object(A,"share_report") as share, contextlib.redirect_stdout(io.StringIO()):
        try:
            A.main()
        except SystemExit as error:
            code=error.code
    kontrol("Level-only terminal runs never reach sharing", code==0 and not ask.called and not share.called)

# Track usage at the actual common adapter boundary, without making a real call.
A.RUN_STATS={"stage_tokens":{},"errors":set()}
A.configure(dict(A.VARSAYILAN,backend="agy",model="fake"),"en","es")
with patch.object(A,"_agy",return_value=({"scenes":[]},{"input_tokens":21,"output_tokens":4})):
    A.model_cagir("fake","test",A.SANSUR_SEMA,1,deneme=1)
kontrol("Actual adapter replies feed stage totals", A.RUN_STATS["stage_tokens"]=={"warnings":{"input":21,"output":4,"reasoning":0}})

# Preview and encoded body stay identical even when stage detail must be omitted.
with patch.object(A,"anonymous_report",return_value=large), patch.object(A,"interactive",return_value=True), patch("builtins.input",side_effect=["y","n"]), contextlib.redirect_stdout(io.StringIO()) as preview:
    A.share_report(share_settings,[private_job],1)
link=next(line for line in preview.getvalue().splitlines() if line.startswith(A.ISSUE_URL))
body=parse_qs(urlsplit(link).query)["body"][0]
kontrol("Oversized report preview matches the shortened issue", body in preview.getvalue() and len(link)<6000 and "stage_tokens" not in body)


# A one-request setup diagnostic cannot enter quota waits or retry a safety block.
A.HATA_DOSYASI=None
A.configure(dict(A.VARSAYILAN,backend="agy",model="fake"),"en","es")
for failure,expected in (("quota exhausted","wait for reset"),("content safety refusal","another accessible model")):
    with patch.object(A,"_agy",side_effect=A.ModelHatasi(failure)) as transport, patch.object(A,"_kota_bekle") as quota, patch.object(A.time,"sleep") as sleep:
        ok,message=A.backend_check(dict(A.VARSAYILAN,backend="agy",model="fake"))
    kontrol("Setup diagnostic stays one request and gives a fix: " + failure, not ok and transport.call_count==1 and not quota.called and not sleep.called and expected in message)

# Scan every shipped text artifact, excluding documented local-only coordination files.
root=Path(__file__).resolve().parent
local_names={"CLAUDE.md","DURUM.md","KARARLAR.md"}
needles=["Abdul"+"aziz", "tor"+"rent", "Ka"+"sım", "F"+"CE", "Second"+"Brain", "/"+"Users/"]
ui_words=["altya"+"zı", "çevi"+"risi", "başa"+"rısız", "yapıla"+"madı", "kulla"+"nıcı", "incele"+"yici"]
def trace_findings(relative, text):
    account = "Abdul" + "aziz-kiran"
    holder = "Abdul" + "aziz Kıran"
    if relative == "LICENSE":
        text = re.sub(r"(?m)^(Copyright \(c\) \d{4}(?:-\d{4})? )" + re.escape(holder) + r"(?=\s*$)",
                      lambda m: m.group(1) + "<copyright holder>", text)
    # Replace only the account component, leaving repository names and the rest of each URL scanned.
    repo_url = r"((?:https?://github\.com/|ssh://git@github\.com/|git@github\.com:))" + re.escape(account) + r"(?=/[A-Za-z0-9_.-]+(?:[/?#\s)'\"<>]|$))"
    text = re.sub(repo_url, lambda m: m.group(1) + "<repository-account>", text)
    checks = needles if relative == "guides/tr.md" else needles + ui_words
    return [needle for needle in checks if needle.casefold() in text.casefold()]

account = "Abdul" + "aziz-kiran"
holder = "Abdul" + "aziz Kıran"
kontrol("License exemption covers the copyright holder only",
        not trace_findings("LICENSE", "Copyright (c) 2026 " + holder)
        and bool(trace_findings("LICENSE", "Unrelated mention: " + holder))
        and bool(trace_findings("elsewhere.txt", "Copyright (c) 2026 " + holder)))
kontrol("Repository URL exemption covers exactly the account",
        not trace_findings("example.md", "https://github.com/" + account + "/dragoman/issues/new")
        and bool(trace_findings("example.md", account))
        and bool(trace_findings("example.md", "https://example.com/" + account + "/repo"))
        and bool(trace_findings("example.md", "https://github.com/" + account + "-extra/repo"))
        and bool(trace_findings("example.md", "https://github.com/" + account + "/" + holder)))
kontrol("Other forbidden text is still detected inside LICENSE",
        bool(trace_findings("LICENSE", "Copyright (c) 2026 " + holder + "\n" + needles[1])))
leaks=[]
for path in root.rglob("*"):
    relative=path.relative_to(root)
    if not path.is_file() or any(part.startswith(".") or part in ("_yerel","__pycache__") for part in relative.parts) or path.name in local_names:
        continue
    if path.suffix.lower() not in (".py",".md",".json",".txt") and path.name not in ("LICENSE",):
        continue
    text=path.read_text(encoding="utf-8")
    if relative.as_posix()=="README.md":
        text=text.split("\n## T\u00fcrk\u00e7e\n")[0]  # intentional short section for search
    for needle in trace_findings(relative.as_posix(), text):
        leaks.append(str(relative)+": "+needle)
kontrol("Shipped text contains no personal traces or Turkish UI", not leaks)
if leaks:
    print("FAIL: "+"; ".join(leaks))
kontrol("No unmocked process or network calls", not unexpected_external_calls)
print(f"Checks failed: {hata}")

sys.exit(1 if hata else 0)
