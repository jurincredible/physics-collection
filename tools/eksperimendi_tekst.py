# -*- coding: utf-8 -*-
"""PDF-i tekstikihi teisendamine LaTeXiks (eksperimendiülesannete kogu).

Kogumiku tekstikiht on hea sõnade ja numbrite poolest, aga kaotab ära kogu
matemaatika vormingu: ülakirjad lähevad reale (kg/m3), murrud kaovad, ja
kreeka tähed tulevad Unicode'i märkidena, mida T1-kodeeringuga LaTeX
tekstirežiimis laduda ei saa (tuleks viga "Unicode character not set up").

Siin on kolm asja:
  * SYMBOL   -- Unicode -> LaTeXi matemaatika (kreeka tähed, korrutusmärk jne)
  * escape   -- LaTeXi eritähtede kaitsmine (% & _ # $ ~ ^ \\)
  * astmed   -- ülakirja taastamine ühikutes (kg/m3 -> kg/m^3) ja
                kümne astmetes (10 3 -> 10^{3})

Kõik kolm on meelega konservatiivsed: kui muster ei ole kindel, jäetakse tekst
puutumata. Parem loetav lähtetekst kui vale valem.
"""

import re

# --- Unicode -> LaTeX ------------------------------------------------------
# Kreeka tähed ja matemaatikamärgid lähevad matemaatikarežiimi ($...$).
SYMBOL_MATH = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "ϑ": r"\vartheta", "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda",
    "μ": r"\mu", "µ": r"\mu", "ν": r"\nu", "ξ": r"\xi", "π": r"\pi",
    "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\varphi", "ϕ": r"\varphi", "χ": r"\chi", "ψ": r"\psi",
    "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "∆": r"\Delta", "Θ": r"\Theta",
    "Λ": r"\Lambda", "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma",
    "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
    "·": r"\cdot", "⋅": r"\cdot", "×": r"\times", "÷": r"\div",
    "±": r"\pm", "∓": r"\mp", "≈": r"\approx", "≠": r"\neq",
    "≤": r"\leq", "≥": r"\geq", "⇒": r"\Rightarrow", "→": r"\rightarrow",
    "↔": r"\leftrightarrow", "∼": r"\sim", "∞": r"\infty",
    "∑": r"\sum", "∫": r"\int", "∂": r"\partial", "∝": r"\propto",
    "′": r"'", "″": r"''",
    "−": r"-", "∘": r"^\circ", "ℓ": r"\ell",
    # oomi märk tuleb kogumikust kahel kujul: U+03A9 (kreeka Omega) ja
    # U+2126 (OHM SIGN). Mõlemad tuleb katta, muidu jääb 31 kohta katki.
    "Ω": r"\Omega", "Ω": r"\Omega",
    "ϱ": r"\varrho", "∠": r"\angle", "≪": r"\ll", "≫": r"\gg",
    "△": r"\triangle", "∡": r"\angle", "≡": r"\equiv", "∈": r"\in",
}

# Märgid, mis lähevad tekstirežiimis otse.
SYMBOL_TEXT = {
    "‐": "-",      # poolituskriips
    "‑": "-",
    "–": "--",     # en dash
    "—": "---",    # em dash
    "‘": "`", "’": "'",
    "“": "``", "”": "''",
    "„": "„", "…": r"\dots{}",
    " ": " ", " ": " ", " ": " ", "​": "",
    "°": r"$^\circ$",
    # Kraadimärk tuleb tekstikihist kolmel eri kujul; kogumikus on kõige
    # sagedamini U+25E6 (valge täpp), sest see on matemaatikafondi glüüf.
    "◦": r"$^\circ$", "○": r"$^\circ$",
    "‰": r"\textperthousand{}",
    "ﬁ": "fi", "ﬂ": "fl",
}

ESCAPE = {"%": r"\%", "&": r"\&", "#": r"\#", "_": r"\_", "$": r"\$",
          "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
          "^": r"\textasciicircum{}", "\\": r"\textbackslash{}"}


def escape_latex(s):
    return "".join(ESCAPE.get(c, c) for c in s)


def has_sqrt(s):
    """Kas lõigus on ruutjuuremärk?

    Tekstikihis satub √ vale kohta (mitte juuritava ette), seega automaatselt
    teda õigesti laduda ei saa. Need ülesanded tuleb käsitsi üle vaadata.
    """
    return "√" in s


import unicodedata

# Märgid, mida ei ole mõtet ühegi reegliga püüda.
#   U+20D7 on kombineeriv vektorinool (F + U+20D7 = F vektorinoolega)
#   U+F8Ex ja U+F8Fx on Computer Moderni erakasutusala glüüfid: suurte
#     sulgude ja integraalimärkide TÜKID. Tekstikihis on nad prügi.
VEKTORINOOL = "⃗"
PRUGI = {chr(c) for c in range(0xF8E0, 0xF900)} | {
    "̸",   # kombineeriv kaldkriips ("mitte")
    "ˊ",   # modifikaatorakuut
    "﻿", "​",
}

# Mis tohib jääda: ASCII, eesti tähed ja muu ladina kiri (autorite nimed).
LUBATUD_MUU = set("„“”‘’")


def puhasta_tundmatud(s, teade=None):
    """Viska välja märgid, mida LaTeX T1-kodeeringus laduda ei saa.

    See on turvavõrk: kui kogumikku tuleb juurde uus sümbol, mida SYMBOL-
    tabelites ei ole, siis dokument ei jää kompileerimata, vaid märk kaob ja
    tema kohta tuleb teade. Ilma selle võrguta lõppes suitsutest 49 veaga
    "Unicode character not set up for use with LaTeX".
    """
    valja = []
    tulem = []
    for c in s:
        if ord(c) < 0x80 or c in LUBATUD_MUU:
            tulem.append(c)
            continue
        if unicodedata.category(c).startswith("L") and ord(c) < 0x250:
            tulem.append(c)          # ladina täht, sh äöüõšž
            continue
        valja.append(c)
    if valja and teade is not None:
        teade.extend(valja)
    return "".join(tulem)


def convert(s, teade=None):
    """Teisenda PDF-ist tulnud lõik LaTeXi-kõlblikuks tekstiks.

    Ruutjuuremärk visatakse välja, sest ta on tekstikihis vale koha peal ja
    tekitaks vale valemi. Vt has_sqrt: need ülesanded loetletakse eraldi.
    """
    s = s.replace("√", "")
    for c in PRUGI:
        s = s.replace(c, "")
    # F⃗ -> $\vec{F}$
    s = re.sub(r"([A-Za-z])" + VEKTORINOOL, r"$\\vec{\1}$", s)
    s = s.replace(VEKTORINOOL, "")
    s = escape_latex(s)
    for k, v in SYMBOL_TEXT.items():
        s = s.replace(k, v)
    for k, v in SYMBOL_MATH.items():
        s = s.replace(k, f"${v}$")
    # Kõrvuti sattunud matemaatikatükid kokku: $\rho$$\approx$ -> $\rho\approx$
    s = re.sub(r"\$\$", "", s)
    s = re.sub(r"\$ \$", " ", s)
    s = astmed(s)
    s = puhasta_tundmatud(s, teade)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


# Ühikud, kus lõppu sattunud 2 või 3 on tegelikult ülakiri. Nimekiri on
# lühike ja kindel; midagi muud ei puudutata.
UNIT_BASE = r"(?:m|cm|mm|km|dm|m/s|kg/m|g/cm|g/m|kg/dm|N/m|W/m|J/m|mL|ml)"

# Alaindeksiks tehtavad täht+number paarid. Füüsikatekstis on "n1", "R2",
# "T1" praktiliselt alati alaindeks, aga paar erandit on olemas ja need
# tuleb nimeliselt välja jätta, muidu saab A4 paberist $A_4$.
ALAINDEKSI_ERANDID = {"A3", "A4", "A5", "M6", "M8"}


def astmed(s):
    # kg/m3 -> kg/m$^3$   (ainult siis, kui järgneb sõnapiir)
    s = re.sub(rf"\b({UNIT_BASE})([23])\b", r"\1$^\2$", s)
    # kg m-1, N m-1 -> kg m$^{-1}$
    s = re.sub(r"\b(m|kg|s|N|A|V)\s?\$-\$\s?(\d)\b", r"\1$^{-\2}$", s)
    # 10 3 või 103 vahetult korrutusmärgi järel -> 10^{3}
    s = re.sub(r"(\$\\cdot\$\s*)10\s?(\d{1,2})\b", r"\1$10^{\2}$", s)
    # 10−3 kujul (miinus juba teisendatud) -> 10^{-3}
    s = re.sub(r"\b10\s?-\s?(\d{1,2})\b", r"$10^{-\1}$", s)
    # $\alpha$1 -> $\alpha_1$ (kreeka täht sai juba matemaatikaks)
    s = re.sub(r"\$(\\[A-Za-z]+)\$(\d)\b", r"$\1_\2$", s)
    # "1, 29" -> "1,29". Kogumikus on kümnendkoma matemaatikarežiimis, kus
    # LaTeX paneb koma järele tühiku; tekstis on see lihtsalt viga.
    s = re.sub(r"(?<=\d), (?=\d)", ",", s)
    # n1 -> $n_1$
    def alaindeks(m):
        if m.group(0) in ALAINDEKSI_ERANDID:
            return m.group(0)
        return f"${m.group(1)}_{m.group(2)}$"
    s = re.sub(r"\b([A-Za-z])(\d)\b", alaindeks, s)
    return s
