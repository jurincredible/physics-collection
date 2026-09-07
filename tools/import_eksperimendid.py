#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Loe Eesti füüsikaolümpiaadi eksperimendiülesannete kogu PDF-ist sisse.

Allikas: "EESTI FÜÜSIKAOLÜMPIAADI EKSPERIMENDI ÜLESANNETE KOGU", koostas
Rael Kalda, 2023. 181 ülesannet aastatest 1996--2022, piirkonna- ja
lõppvoorust, nii põhikooli- (P) kui gümnaasiumiastmest (G), mõni ühine (K).
Ülesanded on PDF-i lk 4--33, lahendused lk 34--144.

See skript teeb ainult MEHAANILISE osa: eraldab tekstikihist ülesannete ja
lahenduste plokid, parsib päised, ühendab poolitatud sõnad ja kirjutab
mustandid kausta problems-exp/. Kaks asja jäävad käsitsi teha, sest
tekstikihis neid ei ole:

  * RASKUS. Kogumik märgib raskust kuni viie tärniga (★) pealkirja järel.
    Tärn on sümbolifondi glüüf ja pdftotext ei anna teda üldse. Tärnid tuleb
    lugeda leheküljepiltidelt ja panna faili tarnid.csv.
  * JOONISED. Osa ülesandeid on vektorjoonisega, mida tekstikihis ei ole.
    Joonis lõigatakse leheküljepildilt eraldi failiks ja lisatakse
    \\includegraphics-käsuga. Nimekiri on failis joonised.csv.

Kasutus:
    python tools/import_eksperimendid.py --pdf "C:/.../Eksperimendi_kogu.pdf"
    python tools/import_eksperimendid.py --pdf ... --dry-run
"""

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eksperimendi_tekst import convert, has_sqrt    # noqa: E402

# Märgid, mille järgi tuntakse ära, et lahenduse tekstikiht on tabeli või
# joonise tõttu loetamatuks muutunud.
RIKUTUD_MARGID = {
    "tabel": re.compile(r"\bTabel\b"),
    "joonis": re.compile(r"\bJoonis\b"),
    "hindamisskeem": re.compile(r"Hindamis"),
    "numbrijada": re.compile(r"(?:\d[\d,.]*\s+){6,}"),
    # Murd, mis läks katki. Kaks kindlat märki: "= =" tekib siis, kui
    # murrujoone kohal ja all olev tekst satub kõrvuti, ja "rho" tekib siis,
    # kui \rho jäi fondi tõttu tähtedena kirja (nii on Ü150 lahenduses).
    "katkine murd": re.compile(r"=\s*="),
    "makronimi tekstis": re.compile(r"\b(?:rho|alpha|beta|lambda|sqrt|frac)\b"),
}

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "problems-exp"
TOOLS = Path(__file__).resolve().parent

YL_LK = (4, 33)      # ülesannete leheküljed PDF-is
LAH_LK = (34, 144)   # lahenduste leheküljed

ROUND_TOKEN = {"piirkonnavoor": "v2g", "lõppvoor": "v3g", "lahtine": "lahg"}

# Päis: "Ü12 Pall   Autor: EFO žürii, piirkonnavoor, 2005, P E1"
# Pealkiri võib olla mitmesõnaline, autori nimi samuti. Vooru nimi, aasta,
# tase ja number on lõpus kindlas järjekorras.
YL_PAIS = re.compile(
    r"^Ü(?P<nr>\d+)\s+(?P<pealkiri>.+?)\s{2,}"
    r"Autor:\s*(?P<autor>.+?),\s*"
    r"(?P<voor>piirkonnavoor|lõppvoor|lahtine),\s*"
    r"(?P<aasta>\d{4}),\s*"
    r"(?P<tase>P/G|[PGK])\s*E(?P<enr>\d+)\s*$")

# Lahenduse päis: "L4 Keha mass (10 p)   Autor: ..., piirkonnavoor, 1998, P E2"
LAH_PAIS = re.compile(
    r"^L(?P<nr>\d+)\s+(?P<pealkiri>.+?)(?:\s*\((?P<punktid>[\d,\.]+)\s*p\))?\s{2,}"
    r"Autor:\s*(?P<autor>.+?),\s*"
    r"(?P<voor>piirkonnavoor|lõppvoor|lahtine),?\s*"
    r"(?P<aasta>\d{4})?,?\s*"
    r"(?P<tase>P/G|[PGK])?\s*(?:E(?P<enr>\d+))?\s*$")


def pdf_text(pdf, first, last):
    """pdftotext -layout, et veerud ja topelttühikud päises alles jääksid."""
    out = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", "-layout", "-f", str(first), "-l", str(last),
         str(pdf), "-"],
        capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def pdf_text_pages(pdf, first, last):
    """Sama, aga tagastab (leheküljenumber, read) paarid.

    Lahenduse juurde tuleb kirja panna, mis leheküljel ta kogumikus on, et
    õpetaja leiaks originaali üles ka siis, kui imporditud tekst on toores.
    """
    tekst = pdf_text(pdf, first, last)
    lehed = tekst.split("\f")
    return [(first + i, lk.splitlines()) for i, lk in enumerate(lehed) if lk.strip()]


def clean_lines(text):
    """Viska välja leheküljenumbrid ja üleliigsed tühikud rea algusest."""
    out = []
    for rida in text.splitlines():
        r = rida.rstrip()
        if re.fullmatch(r"\s*\d{1,3}\s*", r):      # leheküljenumber omal real
            continue
        if r.strip() == "Ülesanded" or r.strip() == "Lahendused":
            continue
        out.append(r)
    return out


# Sildid, mis kogumikus alustavad alati uut rida. Tühja rida nende ette ei
# ole, seega tekstikihis satuvad nad muidu eelmise lõigu sisse: nii kadus
# "Katsevahendid:" ülesande teksti sisse ja \setVahendid jäi tühjaks.
UUS_LOIK_RE = re.compile(
    r"^(Katsevahendid|Vahendid|Katsevahendeid|Märkus|Märkused|Märkusi|NB|"
    r"Vihje|Vihjed|Näpunäited|Näpunäide|Lisainfo|Kasutusjuhend|Hoiatused|"
    r"Hoiatus|Teooria|Mõõtmised|Arvutused|Hindamisskeem|Hindamine)\b")


def join_paragraph(lines):
    """Ühenda read lõiguks: poolitus maha, tühjad read lõigupiiriks.

    Kogumik on laotud LaTeXiga ja poolitatud sõnade lõpus on U+2010
    (HYPHEN), mitte tavaline miinus. Tavalise sidekriipsuga sõnu (nt
    "üles-alla") ei tohi kokku liita.
    """
    loigud = []
    praegune = ""
    for rida in lines:
        r = rida.strip()
        if not r:
            if praegune:
                loigud.append(praegune)
                praegune = ""
            continue
        if UUS_LOIK_RE.match(r) and praegune:
            loigud.append(praegune)
            praegune = r
            continue
        if praegune.endswith("\u2010"):
            praegune = praegune[:-1] + r
        elif praegune:
            praegune += " " + r
        else:
            praegune = r
    if praegune:
        loigud.append(praegune)
    return loigud


def split_blocks(lines, pais_re):
    """Tükelda read plokkideks päise järgi. Tagastab [(match, read), ...].

    Päis on tavaliselt ühel real, aga kui pealkiri on pikk, murdub ta kaheks
    (nii on Ü119 "Taskulambipirni töötemperatuur", kus "2019, P E2" jäi
    järgmisele reale). Seepärast proovime mittevastavuse korral järgmist rida
    juurde liita.
    """
    plokid = []
    praegune = None
    i = 0
    while i < len(lines):
        rida = lines[i].strip()
        m = None
        if rida.startswith(("Ü", "L")) and re.match(r"^[ÜL]\d+\b", rida):
            m = pais_re.match(rida)
            jargmine_soodud = False
            if not m and "Autor:" in rida and i + 1 < len(lines):
                m = pais_re.match(rida + " " + lines[i + 1].strip())
                jargmine_soodud = bool(m)
            if m and jargmine_soodud:
                i += 1
        if m:
            if praegune:
                plokid.append(praegune)
            praegune = (m, [])
        elif praegune:
            praegune[1].append(lines[i])
        i += 1
    if praegune:
        plokid.append(praegune)
    return plokid


VAHENDID_RE = re.compile(r"^(Katsevahendid|Vahendid|Katsevahendeid)\s*:?\s*(.*)$")
# Sildistatud lõigud, mis kogumikus on kaldkirjas või rasvaselt. Need jäävad
# ülesande teksti juurde, sest nad on osa ülesandest, aga silt tuleb alles
# hoida, sest ta ütleb, kas tegu on märkuse, vihje või hoiatusega.
SILT_RE = re.compile(
    r"^(Märkus|Märkused|Märkusi|NB|Vihje|Vihjed|Näpunäited|Näpunäide|"
    r"Lisainfo|Kasutusjuhend|Hoiatused|Hoiatus)\s*:?\s*!?\s*(.*)$")


def parse_statement_body(loigud):
    """Eralda ülesande tekst, katsevahendid ja sildistatud lõigud."""
    tekst, vahendid, sildid = [], "", []
    for lg in loigud:
        m = VAHENDID_RE.match(lg)
        if m:
            vahendid = m.group(2).strip()
            continue
        m = SILT_RE.match(lg)
        if m:
            sildid.append((m.group(1), m.group(2).strip()))
            continue
        tekst.append(lg)
    return tekst, vahendid, sildid


def load_kasitsi(pid):
    """Käsitsi parandatud ülesande tekst, kui see on olemas.

    Osal ülesannetel on kogumikus joonis teksti kõrval (wrapfigure) ja siis
    satuvad joonise sildid PDF-i tekstikihis lause sisse: "moodustatud
    Kollane tähtühendus... kae- RK tud." Seda ei saa automaatselt lahti
    harutada, seega on need ülesanded käsitsi ümber kirjutatud faili
    tools/kasitsi/<id>.tex. Esimene rida on kujul

        %VAHENDID: <katsevahendite loend>

    ja ülejäänud fail on ülesande tekst LaTeXina, koos joonisega. Import
    kasutab seda muutmata kujul, seega uuesti importimine käsitsi tehtut ära
    ei kaota.
    """
    p = TOOLS / "kasitsi" / f"{pid}.tex"
    if not p.exists():
        return None
    read = p.read_text(encoding="utf-8").splitlines()
    vahendid = ""
    if read and read[0].startswith("%VAHENDID:"):
        vahendid = read[0].split(":", 1)[1].strip()
        read = read[1:]
    return vahendid, "\n".join(read).strip()


def load_extra(nimi):
    """Loe käsitsi täidetud kõrvalfail (tarnid.csv, joonised.csv, teemad.csv)."""
    p = TOOLS / nimi
    if not p.exists():
        return {}
    with p.open(encoding="utf-8", newline="") as f:
        return {r["nr"]: r for r in csv.DictReader(f)}


def prob_id(aasta, voor, tase, enr):
    """1998-v2g-ge1 kujul. Tase on id-s sees, sest sama voorus on nii P kui G."""
    return f"{aasta}-{ROUND_TOKEN[voor]}-{tase.lower().replace('/', '')}e{enr}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        sys.exit(f"PDF puudub: {pdf}")

    yl_lines = clean_lines(pdf_text(pdf, *YL_LK))
    lah_lines = clean_lines(pdf_text(pdf, *LAH_LK))

    yl_blocks = split_blocks(yl_lines, YL_PAIS)
    lah_blocks = split_blocks(lah_lines, LAH_PAIS)
    print(f"Ülesandeid leitud: {len(yl_blocks)}")
    print(f"Lahendusi leitud: {len(lah_blocks)}")

    # Mis leheküljel iga lahendus algab
    lah_lk = {}
    for lk, read in pdf_text_pages(pdf, *LAH_LK):
        for rida in read:
            m = re.match(r"^\s*L(\d+)\b", rida)
            if m and m.group(1) not in lah_lk:
                lah_lk[m.group(1)] = lk

    lahendused = {}
    for m, read in lah_blocks:
        lahendused[m.group("nr")] = (m, join_paragraph(read))

    tarnid = load_extra("tarnid.csv")
    joonised = load_extra("joonised.csv")
    teemad = load_extra("teemad.csv")

    puudu_tarn, puudu_teema, vajab_katt, juurega = [], [], [], []
    kasitsi_arv = []
    tundmatud = []
    seisud = {}
    DEST.mkdir(exist_ok=True)

    for m, read in yl_blocks:
        nr = m.group("nr")
        loigud = join_paragraph(read)
        tekst, vahendid, sildid = parse_statement_body(loigud)
        tekst = [convert(t, tundmatud) for t in tekst]
        vahendid = convert(vahendid, tundmatud)
        sildid = [(s, convert(v, tundmatud)) for s, v in sildid]

        aasta, voor = m.group("aasta"), m.group("voor")
        tase, enr = m.group("tase"), m.group("enr")
        pid = prob_id(aasta, voor, tase, enr)

        raskus = (tarnid.get(nr) or {}).get("tarne", "")
        if not raskus:
            puudu_tarn.append(nr)
        teema = (teemad.get(nr) or {}).get("kategooria", "")
        if not teema:
            puudu_teema.append(nr)

        lah = lahendused.get(nr)
        toorik = " ".join(lah[1]) if lah else ""
        # Kas toores tekst on kasutatav? Tabel, joonis, hindamisskeem ja pikad
        # numbrijadad tulevad tekstikihist loetamatult välja (tabeli read
        # lähevad ühte ritta, graafik kaob sootuks). Neid EI impordita, vaid
        # märgitakse käsitsi tegemiseks. Ülejäänud on puhas proosa.
        rikutud = [nimi for nimi, muster in RIKUTUD_MARGID.items()
                   if muster.search(toorik)]
        punktid = (lah[0].group("punktid") or "") if lah else ""
        lahendus_puudub = any("Lahendus puudub" in v for _, v in sildid)

        if lahendus_puudub:
            seis, lah_tekst = "puudub", ""
        elif rikutud:
            seis, lah_tekst = "kasitsi", ""
            vajab_katt.append((nr, ",".join(rikutud)))
        else:
            seis = "toores"
            lah_tekst = "\n\n".join(convert(x) for x in lah[1])
        if has_sqrt(toorik) or any(has_sqrt(x) for x in loigud):
            juurega.append(nr)

        joonis = (joonised.get(nr) or {}).get("fail", "")
        joonise_kood = ""
        if joonis:
            pealdis = (joonised[nr].get("pealdis") or "").strip()
            joonise_kood = (
                "\\begin{center}\n"
                f"\\includegraphics[width={(joonised[nr].get('laius') or '0.45')}"
                f"\\linewidth]{{{joonis}}}\n"
                + (f"\\\\[2pt]{{\\footnotesize {pealdis}}}\n" if pealdis else "")
                + "\\end{center}")

        sisu = []
        sisu.append("% Imporditud: tools/import_eksperimendid.py")
        sisu.append("% Allikas: Eesti füüsikaolümpiaadi eksperimendi ülesannete")
        sisu.append(f"%   kogu (Rael Kalda, 2023), ülesanne Ü{nr}, lahendus L{nr}.")
        sisu.append(f"\\setAuthor{{{m.group('autor').strip()}}}")
        sisu.append(f"\\setRound{{{voor}}}")
        sisu.append(f"\\setYear{{{aasta}}}")
        sisu.append(f"\\setNumber{{{tase} E{enr}}}")
        sisu.append(f"\\setDifficulty{{{raskus}}}")
        sisu.append(f"\\setTopic{{{teema}}}")
        kasitsi = load_kasitsi(pid)
        if kasitsi:
            kasitsi_arv.append(pid)
            if kasitsi[0]:
                vahendid = kasitsi[0]
        sisu.append(f"\\setVahendid{{{vahendid.rstrip('.')}}}")
        if punktid:
            sisu.append(f"\\setPunktid{{{punktid}}}")
        sisu.append(f"\\setAllikas{{Eksperimendi kogu Ü{nr}, lahendus lk "
                    f"{lah_lk.get(nr, '?')}}}")
        sisu.append(f"\\setLahendusseis{{{seis}}}")
        seisud[seis] = seisud.get(seis, 0) + 1
        sisu.append("")
        sisu.append(f"\\prob{{{convert(m.group('pealkiri').strip())}}}")
        if kasitsi:
            sisu.append(kasitsi[1])
        else:
            sisu.append("\n\n".join(tekst))
            if joonise_kood:
                sisu.append(joonise_kood)
            for silt, vaartus in sildid:
                if "Lahendus puudub" in vaartus:
                    continue    # see läheb lahenduse poolele, mitte ülesandesse
                sisu.append(f"\\textit{{{silt}:}} {vaartus}")
        sisu.append("")
        sisu.append("\\hint")
        sisu.append("")
        sisu.append("\\solu")
        # Käsitsi ümber kirjutatud lahendus, kui see on olemas. Sama mõte, mis
        # tools/kasitsi juures: käsitsi tehtu ei kao uuesti importimisel.
        kasitsi_lah = TOOLS / "kasitsi_lahendus" / f"{pid}.tex"
        if kasitsi_lah.exists():
            seis = "kasitsi_tehtud"
            sisu[[i for i, x in enumerate(sisu)
                  if x.startswith("\\setLahendusseis")][0]] = \
                "\\setLahendusseis{kasitsi_tehtud}"
            sisu.append(kasitsi_lah.read_text(encoding="utf-8").strip())
        elif seis == "puudub":
            sisu.append("\\textit{Kogumikus lahendus puudub.}")
        elif seis == "kasitsi":
            sisu.append(
                f"\\textit{{Lahendus on kogumikus lk {lah_lk.get(nr, '?')}. "
                f"Siia ei ole seda veel ümber kirjutatud, sest originaalis on "
                f"tabel või joonis, mis PDF-i tekstikihist loetavalt välja ei "
                f"tule.}}")
        elif lah_tekst:
            sisu.append(lah_tekst)
        sisu.append("\\probend")

        tekst_valmis = "\n".join(sisu) + "\n"
        if not args.dry_run:
            (DEST / f"{pid}.tex").write_text(tekst_valmis, encoding="utf-8")

    print(f"\nKirjutatud kausta {DEST}" if not args.dry_run else "\n(dry-run)")
    print(f"Tärnid puuduvad {len(puudu_tarn)} ülesandel: {' '.join(puudu_tarn[:20])}")
    print(f"Kategooria puudub {len(puudu_teema)} ülesandel")
    print(f"Lahenduste seis: {seisud}")
    print(f"Käsitsi ümber kirjutada {len(vajab_katt)} lahendus:")
    for nr, pohjus in vajab_katt:
        print(f"    Ü{nr}  ({pohjus})")
    print(f"Kaesitsi parandatud ulesandeid: {len(kasitsi_arv)}")
    from collections import Counter
    if tundmatud:
        print("Valja visatud margid (ei ole SYMBOL-tabelites):",
              dict(Counter(hex(ord(c)) for c in tundmatud)))
    print(f"Ruutjuur tekstis, kontrolli käsitsi {len(juurega)} ülesannet: "
          f"{' '.join(juurega)}")


if __name__ == "__main__":
    main()
