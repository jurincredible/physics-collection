#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, sys, textwrap, random
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
        q = q[q["kategooria"].str.lower() == str(flt["kategooria"]).lower()]
    if "aastad" in flt and isinstance(flt["aastad"], (list, tuple)) and len(flt["aastad"]) == 2:
        q = q[(q["aasta"] >= flt["aastad"][0]) & (q["aasta"] <= flt["aastad"][1])]
    if "raskus" in flt and isinstance(flt["raskus"], (list, tuple)) and len(flt["raskus"]) == 2:
        q = q[(q["raskus"] >= flt["raskus"][0]) & (q["raskus"] <= flt["raskus"][1])]

    q = q.sort_values(["aasta","number"], ascending=[False, True])
    if "max" in flt and as_int(flt["max"]):
        q = q.head(int(flt["max"]))
    return q

def make_problem_block(row, include_hints=False, include_solutions=False):
    pid    = s(row.get("id"))
    aasta  = s(row.get("aasta"))
    raskus = s(row.get("raskus"))
    pealk  = s(row.get("pealkiri"))
    kateg  = s(row.get("kategooria"))
    stmt   = cut_eng(s(row.get("statement_tex")))
    hint   = cut_eng(s(row.get("vihje_tex")))
    solu   = cut_eng(s(row.get("lahendus_tex")))

    header = f"\\ProblemHeader{{{pid} — {pealk}}}{{{kateg}}}{{{raskus}}}\n"
    parts = [header, stmt, "\n"]

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

    # Load template and fill
    tpl_path = cfg_path.parent / "lesson_template.tex"
    tpl = tpl_path.read_text(encoding="utf-8")
    filled = (
        tpl.replace("__TITLE__", cfg.get("title", "Tunnikonspekt"))
           .replace("__DATE__",  cfg.get("date",  ""))
           .replace("__CLASS__", cfg.get("class", ""))
           .replace("__PROBLEMS_BLOCK__", problems_tex)
    )

    today_str = date.today().strftime("%Y%m%d")
    base_name = f"{today_str}_füüsika"

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
