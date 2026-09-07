#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, re, sys, textwrap, random
from pathlib import Path
import pandas as pd
import yaml
import math
import subprocess
from datetime import date

def s(x: object) -> str:
    """Safe string: NaN/None -> '', else str(x).strip()."""
    if x is None:
        return ""
    # pandas NaN or numpy NaN
    try:
        if pd.isna(x):
            return ""
    except Exception:
        # if pd is not available here or x is weird, fallback:
        if isinstance(x, float) and math.isnan(x):
            return ""
    return str(x).strip()


# CSV-s on 201 ülesande puhul vihje ja lahenduse välja lõppu kaasa tulnud ka
# lähtefaili ingliskeelne pool, mis algab tokeniga \probeng / \hinteng /
# \solueng. Neid käske tunnikonspekti mallis ei ole, seega lahendustega
# variant (include_solutions: true) ei kompileerunud üldse:
# "! Undefined control sequence.  l.87 \probeng".  Lõikame eestikeelse osa
# lõpust ära. Päris parandus kuulub CSV tekitajasse (preprocess_komplekt.py).
ENG_TOKENS = ("\\probeng", "\\hinteng", "\\solueng")


def cut_eng(text: str) -> str:
    """Jäta alles ainult eestikeelne osa, kuni esimese \\...eng tokenini."""
    cut = len(text)
    for tok in ENG_TOKENS:
        i = text.find(tok)
        if i != -1:
            cut = min(cut, i)
    return text[:cut].rstrip()


def load_yaml(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def as_int(x):
    try:
        return int(x)
    except Exception:
        return None

def pick_by_filters(df, flt):
    q = df.copy()
    if "voor" in flt and flt["voor"]:
        # map YAML-i inimloetav -> id token
        voor_map = {
            "piirkonnavoor": "v2g",
            "lõppvoor": "v3g",
            "lahtised": "lahg",
            "v2g": "v2g",
            "v3g": "v3g",
            "lahg": "lahg",
        }

        def token(v):
            return voor_map.get(str(v).strip().lower(), str(v).strip().lower())

        if isinstance(flt["voor"], (list, tuple, set)):
            toks = [token(v) for v in flt["voor"]]
            q = q[q["id"].astype(str).str.contains(r"-(%s)-" % "|".join(map(__import__("re").escape, toks)),
                                                 case=False, na=False, regex=True)]
        else:
            t = token(flt["voor"])
            q = q[q["id"].astype(str).str.contains(f"-{t}-", case=False, na=False)]
    if "kategooria" in flt and flt["kategooria"]:
        kat = flt["kategooria"]
        if isinstance(kat, (list, tuple, set)):
            lubatud = {str(k).lower() for k in kat}
            q = q[q["kategooria"].str.lower().isin(lubatud)]
        else:
            q = q[q["kategooria"].str.lower() == str(kat).lower()]
    # tüüp: T = teooriaülesanne, E = eksperimendiülesanne.
    # YAML-is võib kirjutada nii "tüüp" kui ASCII-ohutult "tyyp".
    tyyp = flt.get("tüüp") or flt.get("tyyp")
    if tyyp:
        q = q[q["tüüp"].astype(str).str.upper() == str(tyyp).upper()]
    # tase: G = gümnaasium, P = põhikool, K = ühine
    if flt.get("tase"):
        q = q[q["tase"].astype(str).str.upper() == str(flt["tase"]).upper()]
    if "aastad" in flt and isinstance(flt["aastad"], (list, tuple)) and len(flt["aastad"]) == 2:
        q = q[(q["aasta"] >= flt["aastad"][0]) & (q["aasta"] <= flt["aastad"][1])]
    if "raskus" in flt and isinstance(flt["raskus"], (list, tuple)) and len(flt["raskus"]) == 2:
        q = q[(q["raskus"] >= flt["raskus"][0]) & (q["raskus"] <= flt["raskus"][1])]

    q = q.sort_values(["aasta","number"], ascending=[False, True])
    if "max" in flt and as_int(flt["max"]):
        q = q.head(int(flt["max"]))
    return q

def lesson_date_str(cfg, cfg_path):
    """Millise kuupäevaga failinimi tuleb.

    Varem oli see alati date.today(), mistõttu 8. septembri tunnikomplekt
    sai nimeks 20260907_füüsika.tex, kui ta 7. septembril valmis tehti.
    Nüüd on järjekord selline:
      1. lesson.yml võti `failinimi:` (kui tahad nime ise määrata)
      2. kausta nimes olev kuupäev, nt lesson-papers/2026-09-08/
      3. lesson.yml võti `date:`, kui see on kuupäev (08.09.2026 või 2026-09-08)
      4. tänane kuupäev
    """
    if cfg.get("failinimi"):
        return str(cfg["failinimi"])

    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", cfg_path.parent.name)
    if m:
        return "".join(m.groups())

    d = str(cfg.get("date", "")).strip()
    for pat, order in ((r"^(\d{2})\.(\d{2})\.(\d{4})$", (2, 1, 0)),
                       (r"^(\d{4})-(\d{2})-(\d{2})$", (0, 1, 2))):
        m = re.match(pat, d)
        if m:
            g = m.groups()
            return f"{g[order[0]]}{g[order[1]]}{g[order[2]]}"

    return date.today().strftime("%Y%m%d")


def make_problem_block(row, include_hints=False, include_solutions=False):
    pid    = s(row.get("id"))
    aasta  = s(row.get("aasta"))
    raskus = s(row.get("raskus"))
    pealk  = s(row.get("pealkiri"))
    kateg  = s(row.get("kategooria"))
    stmt   = cut_eng(s(row.get("statement_tex")))
    hint   = cut_eng(s(row.get("vihje_tex")))
    solu   = cut_eng(s(row.get("lahendus_tex")))
    vahend = s(row.get("katsevahendid"))

    header = f"\\ProblemHeader{{{pid} — {pealk}}}{{{kateg}}}{{{raskus}}}\n"
    parts = [header, stmt, "\n"]

    # Eksperimendiülesandel on katsevahendid andmebaasis eraldi väljas.
    if vahend:
        parts += ["\\Vahendid{", vahend, "}\n"]

    if include_hints and hint:
        parts += ["\\begin{Hint}\n", hint, "\n\\end{Hint}\n"]
    if include_solutions and solu:
        parts += ["\\begin{Solution}\n", solu, "\n\\end{Solution}\n"]

    return "".join(parts)

def main():
    ap = argparse.ArgumentParser(description="Koosta tunnikonspekt valitud ülesannetest (CSV+YAML).")
    ap.add_argument("--config", required=True, help="Path to lesson.yml")
    ap.add_argument("--compile", action="store_true", help="Käivita ka latexmk -pdf")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_yaml(cfg_path)

    csv_path = Path(cfg["csv_path"]).resolve()
    df = pd.read_csv(csv_path)

    # de-dup & clean
    df = df.drop_duplicates(subset=["id"]).copy()

    # seed list from explicit IDs (preserve order)
    selected = []
    id_list = (cfg.get("problems", {}) or {}).get("ids", []) or []
    for pid in id_list:
        hit = df.loc[df["id"] == pid]
        if not hit.empty:
            selected.append(hit.iloc[0])

    # add from filters
    for flt in (cfg.get("problems", {}) or {}).get("filters", []) or []:
        add = pick_by_filters(df, flt)
        for _, r in add.iterrows():
            if not any(r["id"] == s["id"] for s in selected):
                selected.append(r)

    if cfg.get("shuffle"):
        random.shuffle(selected)

    if not selected:
        print("Ühtegi ülesannet ei valitud – kontrolli lesson.yml.", file=sys.stderr)
        sys.exit(2)

    # Build problems TeX block
    include_hints = bool(cfg.get("include_hints", False))
    include_solutions = bool(cfg.get("include_solutions", False))
    blocks = [make_problem_block(r, include_hints, include_solutions) for r in selected]
    problems_tex = "\n\\bigskip\n\\hrule\\bigskip\n".join(blocks)

    # Load template and fill.
    # Mall otsitakse kõigepealt tunni enda kaustast (nii saab üksik tund oma
    # kujundust muuta), muidu võetakse ühine mall lesson-papers/ juurest.
    # Varem oli igas tunnikaustas oma koopia, 20 tükki, ja nad olid juba
    # lahku jooksnud: kahes vanemas puudus circuitikz.
    tpl_path = cfg_path.parent / "lesson_template.tex"
    if not tpl_path.exists():
        tpl_path = Path(__file__).resolve().parent / "lesson_template.tex"
    if not tpl_path.exists():
        print(f"Malli ei leitud: {tpl_path}", file=sys.stderr)
        sys.exit(2)
    print(f"Mall: {tpl_path}")
    tpl = tpl_path.read_text(encoding="utf-8")
    filled = (
        tpl.replace("__TITLE__", cfg.get("title", "Tunnikonspekt"))
           .replace("__DATE__",  cfg.get("date",  ""))
           .replace("__CLASS__", cfg.get("class", ""))
           .replace("__PROBLEMS_BLOCK__", problems_tex)
    )

    base_name = f"{lesson_date_str(cfg, cfg_path)}_füüsika"

    out_tex = cfg_path.parent / f"{base_name}.tex"
    out_tex.write_text(filled, encoding="utf-8")
    print(f"Wrote {out_tex}")

    if args.compile:
        # latexmk on mugav, aga kui seda pole VÕI see kukub läbi (nt perl puudub),
        # siis kuku automaatselt pdflatex x2 peale.
        try:
            subprocess.check_call(
                ["latexmk", "-pdf", "-interaction=nonstopmode", f"{base_name}.tex"],
                cwd=str(cfg_path.parent)
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("latexmk puudub või ebaõnnestus; proovin pdflatex x2 …")
            subprocess.check_call(
                ["pdflatex", "-interaction=nonstopmode", f"{base_name}.tex"],
                cwd=str(cfg_path.parent)
            )
            subprocess.check_call(
                ["pdflatex", "-interaction=nonstopmode", f"{base_name}.tex"],
                cwd=str(cfg_path.parent)
            )
        print("PDF valmis.")

        
if __name__ == "__main__":
    main()
