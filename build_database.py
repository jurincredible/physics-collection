#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ehita ülesannete andmebaas (olympiaad_ulesanded.csv) ülesannete .tex failidest.

MIKS SEE FAIL OLEMAS ON
-----------------------
CSV oli varem tehtud käsitsi ja seal oli viga, mis jäi kuudeks märkamata:
609 ülesandest 201 puhul olid vihje- ja lahendusevälja lõppu kaasa tulnud
lähtefaili ingliskeelsed osad koos tokenitega \\probeng, \\hinteng ja
\\solueng. Tunnikonspekti mall neid käske ei tunne, seega iga lahendustega
tunnikomplekt lõppes veaga "Undefined control sequence" ja lahenduslehte ei
saanud üldse teha.

Nüüd sünnib CSV ainult siit ja see skript teeb kaks asja, mis seda viga
uuesti tekkida ei lase:

1. **Tokeniseerib** ülesande faili õigesti. Fail koosneb metaandmetest
   (\\setAuthor jne) ja järjestikustest osadest, mille algust märgib token:
   \\prob{pealkiri} -> \\hint -> \\solu -> \\probeng{title} -> \\hinteng ->
   \\solueng -> \\probend. Eestikeelne osa lõpeb esimese ingliskeelse tokeni
   juures. Miski ei satu "üle serva".
2. **Valideerib** iga välja enne kirjutamist: tokenite jääke ei ole, loogsulud
   ja dollarid on paaris, iga \\begin{} on suletud, viidatud joonisefail on
   olemas. Vea korral lõpetab nullist erineva koodiga ja CSV-d ei kirjutata.

Kasutus (hoidla juurest):
    python build_database.py             # ehita CSV uuesti
    python build_database.py --check     # ainult kontrolli, ära kirjuta
    python build_database.py --report    # lisaks statistika kategooriate kaupa

MIDA SKRIPT EI TEA
------------------
Väljad `alamteema` ja `lahendusvotted` ei ole ülesande .tex failides, need on
CSV-sse hiljem juurde kirjutatud. Neid EI genereerita, vaid kantakse vanast
CSV-st id järgi üle. Kui ülesanne on uus, jäävad need tühjaks.
"""

import argparse
import csv
import os
import re
import sys
from glob import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "olympiaad_ulesanded.csv"

# Kõrvalfail nende väljadega, mida ülesande .tex failist ei saa. Seda hoitakse
# käsitsi (või rikastatakse eraldi) ja build_database liidab ta id järgi
# külge. Ilma selleta kaoks 161 ülesande kategooria ära, sest nende .tex
# failis on \setTopic{TODO}.
META_PATH = ROOT / "metaandmed.csv"

# .tex failid ülesannete kaustades, mis EI OLE ülesanded. Nimekiri on
# meelega selgesõnaline: nii ei kao ükski päris ülesanne kogemata vaikselt ära.
NOT_A_PROBLEM = {
    "probs_b3/lainejuht.tex",   # pgfplots joonis, mille kasutab 2021-v2g-08
}

# \setTopic väärtused, mis tähendavad "ei ole täidetud".
TOPIC_PLACEHOLDERS = {"", "todo", "teema"}

# Kaustad, kust ülesandeid otsitakse, ja mida nad tähendavad.
#   problems, probs_b3  -- teooriaülesanded (tüüp T), kogumikud üks ja kolm
#   problems-exp        -- eksperimendiülesanded (tüüp E)
SOURCE_DIRS = [
    ("problems", "T"),
    ("probs_b3", "T"),
    ("problems-exp", "E"),
]

# Osade tokenid failis, järjekorras. Eestikeelne osa lõpeb esimese
# ingliskeelse tokeni juures ja ingliskeelset osa CSV-sse ei panda.
EST_MARKERS = [r"\prob", r"\hint", r"\solu"]
ENG_MARKERS = [r"\probeng", r"\hinteng", r"\solueng"]
END_MARKER = r"\probend"

# Väljad, mida ükski CSV lahter enam sisaldada ei tohi.
FORBIDDEN_IN_FIELDS = EST_MARKERS + ENG_MARKERS + [END_MARKER]

ROUND_TO_TOKEN = {"piirkonnavoor": "v2g", "lõppvoor": "v3g", "lahtine": "lahg"}

COLUMNS = [
    "id", "aasta", "voor", "tase", "number", "pealkiri", "raskus",
    "kategooria", "tüüp", "alamteema", "autor",
    "statement_tex", "vihje_tex", "lahendus_tex", "lahendusvotted",
    "katsevahendid", "punktid", "lahendusseis", "allikas", "allikas_failitee",
    "allikas_kaust",
]

# raskuse skaala on tüübiti erinev ja seda ei tohi ära segada:
#   T -- kogumike hinnang 1..10
#   E -- eksperimendikogu tärnid 1..5
RASKUS_VAHEMIK = {"T": (1, 10), "E": (1, 5)}


class Viga(Exception):
    """Andmeviga, mis peab ehituse peatama."""


# --------------------------------------------------------------------------
# Tokeniseerimine
# --------------------------------------------------------------------------

def read_braced(text, start):
    """Loe alates positsioonist start (kus on '{') tasakaalus sulgude sisu.

    Tagastab (sisu, indeks pärast sulgevat looksulgu).
    """
    assert text[start] == "{", text[start:start + 20]
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\":            # \{ ja \} ei loe sulgudeks
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    raise Viga("sulg jäi sulgemata")


def find_marker(text, marker, pos=0):
    """Leia token nii, et \\prob ei leiaks \\probeng ega \\probend."""
    pat = re.compile(re.escape(marker) + r"(?![A-Za-z])")
    m = pat.search(text, pos)
    return m.start() if m else -1


def parse_problem_file(path):
    """Loe üks ülesande .tex fail ja tagasta sõnastik osadega.

    Tagastab: meta (dict \\setXxx väärtustest), pealkiri, statement, hint,
    solu, ja mitu ingliskeelset osa faili lõpust välja jäeti.
    """
    text = Path(path).read_text(encoding="utf-8")

    # 1. Metaandmed. \setAuthor{...}, \setRound{...} jne, ükskõik mis järjekorras.
    meta = {}
    for m in re.finditer(r"\\set([A-Za-zÀ-ÿ]+)\s*\{", text):
        key = m.group(1)
        value, _ = read_braced(text, m.end() - 1)
        meta[key] = value.strip()

    # 2. Eestikeelse osa algus: \prob{pealkiri}
    i_prob = find_marker(text, r"\prob")
    if i_prob == -1:
        raise Viga(r"\prob puudub")
    brace = text.index("{", i_prob)
    pealkiri, after_title = read_braced(text, brace)

    # 3. Kõik ülejäänud tokenid oma positsioonidega.
    positions = []
    for marker in EST_MARKERS[1:] + ENG_MARKERS + [END_MARKER]:
        i = find_marker(text, marker, after_title)
        if i != -1:
            positions.append((i, marker))
    positions.sort()

    def segment(marker):
        """Tekst tokeni järelt kuni järgmise tokenini."""
        for idx, (i, mk) in enumerate(positions):
            if mk != marker:
                continue
            start = i + len(marker)
            if marker in ENG_MARKERS:      # ingliskeelsel osal on veel pealkiri
                pass
            end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
            return text[start:end]
        return ""

    first_eng = next((i for i, mk in positions if mk in ENG_MARKERS), None)
    statement_end = positions[0][0] if positions else len(text)
    statement = text[after_title:statement_end]

    return {
        "meta": meta,
        "pealkiri": pealkiri.strip(),
        "statement": statement,
        "hint": segment(r"\hint"),
        "solu": segment(r"\solu"),
        "eng_dropped": first_eng is not None,
    }


def tidy(s):
    """Trimmi servad ja võta ära üksikud tühjad read algusest ja lõpust."""
    return s.strip().strip("\n").strip()


# --------------------------------------------------------------------------
# Valideerimine
# --------------------------------------------------------------------------

def check_field(name, value, probleemid, pid):
    if not value:
        return
    for token in FORBIDDEN_IN_FIELDS:
        if re.search(re.escape(token) + r"(?![A-Za-z])", value):
            probleemid.append(f"{pid}: väli {name} sisaldab tokenit {token}")
    # Loogsulud. Varjestatud \{ ja \} ei ole sulud, vaid trükimärgid, seega
    # tuleb nad enne loendamist ära visata. Ilma selleta annab iga
    # \left\{ ... \right. vale hoiatuse (nii juhtus 2007-v2g-03 ja
    # 2018-v2g-03 puhul, kus tegelikult viga ei olnud).
    ilma_varjeta = re.sub(r"\\[{}]", "", value)
    if ilma_varjeta.count("{") != ilma_varjeta.count("}"):
        probleemid.append(
            f"{pid}: väli {name} loogsulud ei ole paaris "
            f"({ilma_varjeta.count('{')} vs {ilma_varjeta.count('}')})")
    # $ paaris. $$ loeb kaheks, see on samuti paaris arv.
    if len(re.findall(r"(?<!\\)\$", value)) % 2:
        probleemid.append(f"{pid}: väli {name} dollarimärgid ei ole paaris")
    begins = re.findall(r"\\begin\{([^}]+)\}", value)
    ends = re.findall(r"\\end\{([^}]+)\}", value)
    if sorted(begins) != sorted(ends):
        probleemid.append(
            f"{pid}: väli {name} keskkonnad ei klapi: {begins} vs {ends}")


def check_graphics(value, probleemid, pid, kaust):
    for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", value or ""):
        nimi = m.group(1)
        kandidaadid = glob(str(ROOT / kaust / (Path(nimi).stem + ".*")))
        if not kandidaadid:
            probleemid.append(f"{pid}: joonis {nimi} puudub kaustas {kaust}")


# --------------------------------------------------------------------------
# Rea koostamine
# --------------------------------------------------------------------------

def build_row(path, kaust, tyyp, parsed, enrich):
    pid = Path(path).stem
    meta = parsed["meta"]
    number_raw = meta.get("Number", "")
    # \setNumber{G 3} -> tase G, number 3;  \setNumber{G E1} -> tase G, number E1
    tase, number = "", number_raw
    osad = number_raw.split()
    if len(osad) == 2:
        tase, number = osad[0], osad[1]

    voor = meta.get("Round", "")
    vana = enrich.get(pid, {})

    # Kategooria: kõrvalfail on ülem, sest paljudes .tex failides on
    # \setTopic{TODO}. Kui kõrvalfailis kirjet ei ole, võtame \setTopic.
    topic = meta.get("Topic", "").strip().lower()
    kategooria = vana.get("kategooria", "") or (
        "" if topic in TOPIC_PLACEHOLDERS else topic)

    return {
        "id": pid,
        "aasta": meta.get("Year", ""),
        "voor": voor,
        "tase": tase,
        "number": number,
        "pealkiri": parsed["pealkiri"],
        "raskus": meta.get("Difficulty", ""),
        "kategooria": kategooria,
        "tüüp": tyyp,
        "alamteema": vana.get("alamteema", ""),
        "autor": meta.get("Author", ""),
        "statement_tex": tidy(parsed["statement"]),
        "vihje_tex": tidy(parsed["hint"]),
        "lahendus_tex": tidy(parsed["solu"]),
        "lahendusvotted": vana.get("lahendusvotted", ""),
        "katsevahendid": meta.get("Vahendid", ""),
        "punktid": meta.get("Punktid", ""),
        "lahendusseis": meta.get("Lahendusseis", ""),
        "allikas": meta.get("Allikas", ""),
        "allikas_failitee": f"physics-collection/{kaust}/{pid}.tex",
        "allikas_kaust": kaust,
    }


def load_enrichment():
    """Loe kõrvalfailist need väljad, mida ülesande .tex failist ei saa."""
    enrich = {}
    if not META_PATH.exists():
        print(f"HOIATUS: {META_PATH.name} puudub, kategooriad tulevad ainult "
              f"\\setTopic-ist.", file=sys.stderr)
        return enrich
    with META_PATH.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            enrich[r["id"]] = {
                "kategooria": (r.get("kategooria") or "").strip(),
                "alamteema": (r.get("alamteema") or "").strip(),
                "lahendusvotted": (r.get("lahendusvotted") or "").strip(),
            }
    return enrich


def smoke_test(rows):
    """Kompileeri kõik ülesanded ühte dokumenti sama malliga, mida tund kasutab.

    See on ainus kontroll, mis tõesti garanteerib, et tunnikomplekt ei kuku
    läbi: leiab puuduvad makrod, puuduvad joonised, katkise matemaatika ja
    keskkonnad, mis ei sulgu. Kaust on lesson-papers/_smoke, sest malli
    \\graphicspath ja \\input@path on kirjutatud selle sügavuse jaoks.
    """
    import subprocess

    smoke_dir = ROOT / "lesson-papers" / "_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    tpl = (ROOT / "lesson-papers" / "lesson_template.tex").read_text(encoding="utf-8")

    plokid = []
    for r in rows:
        plokid.append(
            f"\\ProblemHeader{{{r['id']} — {r['pealkiri']}}}"
            f"{{{r['kategooria']}}}{{{r['raskus']}}}\n"
            + r["statement_tex"] + "\n"
            + (f"\\Vahendid{{{r['katsevahendid']}}}\n" if r["katsevahendid"] else "")
            + (f"\\begin{{Hint}}\n{r['vihje_tex']}\n\\end{{Hint}}\n" if r["vihje_tex"] else "")
            + (f"\\begin{{Solution}}\n{r['lahendus_tex']}\n\\end{{Solution}}\n" if r["lahendus_tex"] else "")
        )
    body = "\n\\bigskip\n\\hrule\\bigskip\n".join(plokid)

    filled = (tpl.replace("__TITLE__", "Suitsutest: koik ulesanded")
                 .replace("__DATE__", "")
                 .replace("__CLASS__", "")
                 .replace("__PROBLEMS_BLOCK__", body))
    tex = smoke_dir / "koik.tex"
    tex.write_text(filled, encoding="utf-8")
    print(f"\nSuitsutest: {len(rows)} ülesannet failis {tex}")

    try:
        subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "koik.tex"],
                       cwd=str(smoke_dir), capture_output=True, timeout=1800)
    except FileNotFoundError:
        print("latexmk puudub, suitsutesti ei saa teha.", file=sys.stderr)
        return 1

    log = (smoke_dir / "koik.log")
    if not log.exists():
        print("Logi ei tekkinud.", file=sys.stderr)
        return 1
    read_log = log.read_text(encoding="utf-8", errors="replace").splitlines()
    vead = [(i, l) for i, l in enumerate(read_log) if l.startswith("!")]
    puuduvad = [l for l in read_log if "not found" in l or "No file" in l]
    pdf = smoke_dir / "koik.pdf"

    def ascii_safe(s):
        return s.encode("ascii", "replace").decode("ascii")

    # Määratlemata käsud kokku, sest 500 rida logi ei ütle midagi, aga
    # nimekiri "\enquote 41 korda, \dv 12 korda" ütleb kõik.
    from collections import Counter
    undefined = Counter()
    muud = Counter()
    for i, rida in vead:
        if "Undefined control sequence" in rida:
            saba = " ".join(read_log[i + 1:i + 3])
            m = re.findall(r"\\([A-Za-z@]+)\s*$", saba.split("|")[0].rstrip())
            if not m:
                m = re.findall(r"\\([A-Za-z@]+)", saba)[-1:]
            undefined[("\\" + m[0]) if m else "(tundmatu)"] += 1
        else:
            muud[ascii_safe(rida.strip())[:110]] += 1

    print(f"  LaTeXi vigu kokku: {len(vead)}")
    print(f"  puuduvaid faile: {len(puuduvad)}")
    if pdf.exists():
        print(f"  PDF: {pdf} ({pdf.stat().st_size // 1024} kB)")
    if undefined:
        print("  Määratlemata käsud:")
        for k, n in undefined.most_common(30):
            print(f"    {n:4d}  {ascii_safe(k)}")
    if muud:
        print("  Muud vead:")
        for k, n in muud.most_common(15):
            print(f"    {n:4d}  {k}")
    for l in puuduvad[:10]:
        print("   " + ascii_safe(l.strip())[:180])
    return 1 if vead else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="ainult kontrolli, CSV-d ümber ei kirjutata")
    ap.add_argument("--report", action="store_true",
                    help="näita statistikat kategooriate ja tüüpide kaupa")
    ap.add_argument("--smoke", action="store_true",
                    help="lao KÕIK ülesanded koos vihjete ja lahendustega ühte "
                         "dokumenti ja kompileeri. Kui see läbib, ei saa ükski "
                         "tunnikomplekt enam LaTeXi vea otsa joosta.")
    args = ap.parse_args()

    enrich = load_enrichment()
    read = []
    probleemid = []
    eng_dropped = 0

    for kaust, tyyp in SOURCE_DIRS:
        d = ROOT / kaust
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.tex")):
            if f"{kaust}/{path.name}" in NOT_A_PROBLEM:
                continue
            try:
                parsed = parse_problem_file(path)
            except Viga as e:
                probleemid.append(f"{path.stem}: {e}")
                continue
            eng_dropped += bool(parsed["eng_dropped"])
            read.append(build_row(path, kaust, tyyp, parsed, enrich))

    # Kohustuslikud väljad ja unikaalne id
    nahtud = {}
    for row in read:
        pid = row["id"]
        if pid in nahtud:
            probleemid.append(f"{pid}: id on kaks korda ({nahtud[pid]}, {row['allikas_kaust']})")
        nahtud[pid] = row["allikas_kaust"]
        for kohustuslik in ("aasta", "voor", "pealkiri", "statement_tex",
                            "kategooria"):
            if not row[kohustuslik]:
                probleemid.append(f"{pid}: väli {kohustuslik} on tühi")
        if row["voor"] not in ROUND_TO_TOKEN:
            probleemid.append(f"{pid}: tundmatu voor {row['voor']!r}")
        if row["tüüp"] == "E" and not row["katsevahendid"]:
            probleemid.append(f"{pid}: eksperimendiülesandel puudub \\setVahendid")
        lo, hi = RASKUS_VAHEMIK[row["tüüp"]]
        try:
            r = int(float(row["raskus"]))
            if not lo <= r <= hi:
                probleemid.append(
                    f"{pid}: raskus {r} ei ole vahemikus {lo}..{hi} "
                    f"(tüüp {row['tüüp']})")
        except (TypeError, ValueError):
            probleemid.append(f"{pid}: raskus {row['raskus']!r} ei ole arv")
        for veerg in ("statement_tex", "vihje_tex", "lahendus_tex", "pealkiri"):
            check_field(veerg, row[veerg], probleemid, pid)
        check_graphics(row["statement_tex"], probleemid, pid, row["allikas_kaust"])
        check_graphics(row["lahendus_tex"], probleemid, pid, row["allikas_kaust"])

    print(f"Loetud {len(read)} ülesannet "
          f"({sum(1 for r in read if r['tüüp'] == 'T')} teooria, "
          f"{sum(1 for r in read if r['tüüp'] == 'E')} eksperiment).")
    print(f"Ingliskeelne osa jäeti välja {eng_dropped} failis.")
    puuduv_lahendus = sum(1 for r in read if not r["lahendus_tex"])
    print(f"Lahenduse tekst puudub {puuduv_lahendus} ülesandel.")
    from collections import Counter as _C
    seisud = _C(r["lahendusseis"] for r in read if r["lahendusseis"])
    if seisud:
        print("Eksperimendiülesannete lahenduste seis: "
              + ", ".join(f"{k} {v}" for k, v in sorted(seisud.items())))

    if args.report:
        from collections import Counter
        print("\nKategooriad:")
        for k, n in Counter(r["kategooria"] for r in read).most_common():
            print(f"  {n:4d}  {k or '(tühi)'}")
        print("\nVoorud:", dict(Counter(r["voor"] for r in read)))
        print("Tasemed:", dict(Counter(r["tase"] for r in read)))
        # Need on need eksperimendiülesanded, mille lahendus tuleb käsitsi
        # ümber kirjutada (originaalis on tabel, graafik või hindamisskeem).
        vaja = [r for r in read if r["lahendusseis"] == "kasitsi"]
        if vaja:
            print(f"\nLahendus tuleb käsitsi ümber kirjutada ({len(vaja)} tk). "
                  f"Kirjuta fail tools/kasitsi_lahendus/<id>.tex:")
            for r in sorted(vaja, key=lambda x: x["id"]):
                print(f"  {r['id']:16} {r['pealkiri']:28} {r['allikas']}")

    if probleemid:
        print(f"\n{len(probleemid)} PROBLEEMI:", file=sys.stderr)
        for p in probleemid[:60]:
            print("  " + p, file=sys.stderr)
        if len(probleemid) > 60:
            print(f"  ... ja veel {len(probleemid) - 60}", file=sys.stderr)
        print("\nCSV-d ei kirjutatud.", file=sys.stderr)
        return 1

    if args.smoke:
        return smoke_test(read)

    if args.check:
        print("\nKontroll läbitud, CSV-d ei kirjutatud (--check).")
        return 0

    # Järjestus: aasta kahanevalt, siis voor, siis number. Sama, mis vanas CSV-s
    # ei olnud, aga nii on faili diff loetav ja stabiilne.
    def sort_key(r):
        return (r["tüüp"], -int(float(r["aasta"] or 0)), r["voor"], r["tase"], r["number"])

    read.sort(key=sort_key)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(read)
    print(f"\nKirjutatud {CSV_PATH} ({len(read)} rida, {len(COLUMNS)} veergu).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
