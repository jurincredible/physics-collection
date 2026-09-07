#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lõika eksperimendiülesannete kogu PDF-ist üks joonis eraldi pildifailiks.

Kogumiku joonised on vektorgraafika (TikZ), mida pdfimages kätte ei saa, ja
originaal .tex faile ei ole olemas. Seega lõigatakse joonis leheküljelt välja
pildina. 300 dpi on trükikvaliteet ja tunnilehel näeb hea välja.

Kasutus:
    python tools/loika_joonis.py --pdf <fail.pdf> --lk 4 \
        --ala 520 330 780 420 --valja problems-exp/1997-v2g-pe1-yl.png

--ala on ligikaudne piirkond leheküljel 105 dpi koordinaatides (nii nagu
leheküljepildil, mille tegi pdftoppm -r 105). Skript leiab selle sees oleva
tindi TÄPSE ümbrise ja lõikab selle järgi, seega ligikaudne ala on piisav.
Kui alasse satub ka teksti, tuleb ala kitsamaks teha.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

DPI_ALA = 105      # koordinaatide dpi (leheküljepildi oma)
DPI_VALJA = 300    # väljundpildi dpi


def loe_pgm(path):
    """Loe binaarne PGM (P5). pdftoppm -gray annab just selle."""
    data = Path(path).read_bytes()
    # päis: P5 <laius> <korgus> <maxval>, vahel kommentaaridega
    osad = []
    i = 0
    while len(osad) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        osad.append(data[i:j])
        i = j
    i += 1
    w, h = int(osad[1]), int(osad[2])
    arr = np.frombuffer(data[i:i + w * h], dtype=np.uint8).reshape(h, w)
    return arr


def naita_kaart(args, samm=10):
    """Trüki lehekülje tindikaart 105 dpi koordinaatides.

    Iga märk on samm x samm piksli ruut: '.' tühi, ':' vähe tinti,
    '#' palju tinti. Tekstiread paistavad ühtlaste triipudena, joonised
    eristuvad blokkidena. Vasakul on y-koordinaat, ülal x.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        eesliide = Path(td) / "lk"
        subprocess.run(["pdftoppm", "-gray", "-r", str(DPI_ALA),
                        "-f", str(args.lk), "-l", str(args.lk),
                        args.pdf, str(eesliide)], check=True)
        pgm = next(Path(td).glob("lk-*.pgm"))
        arr = loe_pgm(pgm)
    h, w = arr.shape
    tint = (arr < args.lavi).astype(np.uint16)
    ry, rx = h // samm, w // samm
    kokku = tint[:ry * samm, :rx * samm].reshape(ry, samm, rx, samm).sum(axis=(1, 3))
    print(f"lehekülg {args.lk}, {w}x{h} px (105 dpi), ruut = {samm} px")
    print("      " + "".join(f"{(x*samm)//100 % 10}" for x in range(rx)))
    for y in range(ry):
        rida = "".join("." if v == 0 else (":" if v < samm * samm * 0.18 else "#")
                       for v in kokku[y])
        if rida.strip("."):
            print(f"{y*samm:5d} {rida}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--lk", type=int, required=True)
    ap.add_argument("--ala", type=int, nargs=4,
                    metavar=("X1", "Y1", "X2", "Y2"),
                    help="ligikaudne ala 105 dpi koordinaatides")
    ap.add_argument("--valja", help="väljundfail; --kaart puhul ei ole vaja")
    ap.add_argument("--kaart", action="store_true",
                    help="ära lõika, vaid näita lehekülje tindikaart, et ala "
                         "kohe õigesti valida")
    ap.add_argument("--aare", type=int, default=10, help="valge äär pikslites")
    ap.add_argument("--lavi", type=int, default=205,
                    help="tindi lävi (halli väärtus, millest väiksem on tint)")
    args = ap.parse_args()

    if args.kaart:
        naita_kaart(args)
        return
    if not args.valja:
        sys.exit("--valja on vajalik")

    tmp = Path(args.valja).with_suffix(".tmp")
    subprocess.run(["pdftoppm", "-gray", "-r", str(DPI_VALJA),
                    "-f", str(args.lk), "-l", str(args.lk),
                    args.pdf, str(tmp)], check=True)
    pgm = next(tmp.parent.glob(tmp.name + "-*.pgm"), None)
    if pgm is None:
        sys.exit("pdftoppm ei andnud PGM-i")

    arr = loe_pgm(pgm)
    h, w = arr.shape
    k = DPI_VALJA / DPI_ALA
    x1, y1, x2, y2 = [int(round(v * k)) for v in args.ala]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    ala = arr[y1:y2, x1:x2]
    tint = ala < args.lavi
    if not tint.any():
        sys.exit("alas ei ole tinti: kontrolli koordinaate")
    read = np.where(tint.any(axis=1))[0]
    veerud = np.where(tint.any(axis=0))[0]
    a = args.aare
    ty1 = max(0, y1 + read[0] - a)
    ty2 = min(h, y1 + read[-1] + 1 + a)
    tx1 = max(0, x1 + veerud[0] - a)
    tx2 = min(w, x1 + veerud[-1] + 1 + a)

    print(f"bbox 300 dpi: x {tx1}..{tx2} ({tx2-tx1} px), "
          f"y {ty1}..{ty2} ({ty2-ty1} px)")
    print(f"bbox 105 dpi: x {tx1/k:.0f}..{tx2/k:.0f}, y {ty1/k:.0f}..{ty2/k:.0f}")

    # NB! Lõiget tuleb VAADATA. Selles masinas on pdftotext Xpdf 4.00, mis
    # -x/-y/-W/-H lippe ei toeta (trükib vaikselt kasutusjuhendi ja väljub
    # nullkoodiga), seega automaatset "kas kasti jäi teksti" kontrolli teha ei
    # saa. Tindi ümbris ütleb ainult seda, kus tint on, mitte kas see on
    # joonis või proosa.
    subprocess.run(["pdftoppm", "-png", "-r", str(DPI_VALJA),
                    "-f", str(args.lk), "-l", str(args.lk),
                    "-x", str(tx1), "-y", str(ty1),
                    "-W", str(tx2 - tx1), "-H", str(ty2 - ty1),
                    args.pdf, str(Path(args.valja).with_suffix(""))], check=True)
    # pdftoppm lisab nime lõppu leheküljenumbri, tõstame õigele nimele
    tehtud = next(Path(args.valja).parent.glob(
        Path(args.valja).stem + "-*.png"), None)
    if tehtud:
        tehtud.replace(args.valja)
    pgm.unlink(missing_ok=True)
    print("kirjutatud", args.valja)


if __name__ == "__main__":
    main()
