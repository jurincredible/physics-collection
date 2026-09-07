# Andmebaas ja tunnikomplektid

Selle faili sisu ei ole osa algsest kogumike hoidlast, vaid kirjeldab
Tallinna Reaalkooli olümpiaadiringi töövoogu: kuidas ülesannete andmebaas
sünnib ja kuidas sellest tunnikomplekt tehakse.

## Kolm sammu

```bash
# 1. loe eksperimendiülesanded kogumiku PDF-ist sisse (teeb problems-exp/)
python tools/import_eksperimendid.py --pdf "C:/.../Eksperimendi_kogu.pdf"

# 2. ehita andmebaas ülesannete .tex failidest
python build_database.py                 # kirjutab olympiaad_ulesanded.csv
python build_database.py --check         # ainult kontroll
python build_database.py --report        # + statistika
python build_database.py --smoke         # KÕIK ülesanded ühte PDF-i, kompileeri

# 3. tee ühe kohtumise komplekt
python lesson-papers/build_lesson.py --config lesson-papers/2026-09-08/lesson.yml --compile
python lesson-papers/build_lesson.py --config lesson-papers/2026-09-08-sol/lesson.yml --compile
```

## Mis kus on

| Asi | Koht | Kes teeb |
|---|---|---|
| Teooriaülesanded (608) | `problems/`, `probs_b3/` | kogumike koostajad |
| Eksperimendiülesanded (181) | `problems-exp/` | `tools/import_eksperimendid.py` |
| Kategooria, alamteema, lahendusvõtted | `metaandmed.csv` | käsitsi, id järgi |
| Tärnid ja teemad kogumiku järgi | `tools/tarnid.csv`, `tools/teemad.csv` | käsitsi, ülesande nr järgi |
| Joonised ja nende laius | `tools/joonised.csv` | käsitsi, ülesande nr järgi |
| Käsitsi parandatud ülesanne | `tools/kasitsi/<id>.tex` | käsitsi |
| Käsitsi kirjutatud lahendus | `tools/kasitsi_lahendus/<id>.tex` | käsitsi |
| **Andmebaas** | `olympiaad_ulesanded.csv` | `build_database.py`, **ära muuda käsitsi** |
| Ühine tunnimall | `lesson-papers/lesson_template.tex` | käsitsi |
| Ühe tunni valik | `lesson-papers/<kaust>/lesson.yml` | käsitsi |

CSV on **tuletatud fail**. Kõik käsitsi tehtud muudatused lähevad ülesande
`.tex` faili või ühte kõrvalfaili, mitte CSV-sse.

## Miks build_database.py olemas on

CSV oli varem käsitsi kokku pandud ja seal olid vead, mis jäid kuudeks
märkamata:

1. **609 rea seas oli üks olematu ülesanne.** Rida `lainejuht` oli tekkinud
   joonisefailist `probs_b3/lainejuht.tex`; tal oli kategooria ja
   lahendusvõtted, aga tühi ülesandetekst. Filtriga tehtud komplekti oleks ta
   sattunud tühja ülesandena.
2. **201 ülesandel oli vihje- ja lahendusevälja lõpus ingliskeelne pool**
   koos tokenitega `\probeng`, `\hinteng`, `\solueng`. Neid käske mallis ei
   ole, seega **ükski lahendustega komplekt ei kompileerunud**.
3. **`\include{lainejuht.tex}`** ülesandes 2021-v2g-08 otsis faili
   `lainejuht.tex.tex` ja `\include` ei tohi olla `figure` sees. Selle
   ülesande graafikut ei olnud kunagi näha, ka kogumikus mitte. Parandatud
   `\input{lainejuht}`-iks.
4. **Mall ei tundnud makrosid**, mida ülesanded kasutavad: `\enquote`
   (48 kohta), `\pp` ja `\p` (žürii punktid, 258 kohta), `\dv`, `\setstretch`,
   `\DeclareSIUnit\aasta`, pgfplots ja üheksa TikZ-teeki. Kõik on nüüd mallis.

Nüüd on kaks kaitset. `--check` valideerib iga välja (tokenite jäägid,
sulgude ja dollarite tasakaal, keskkonnad, viidatud joonised, raskuse skaala
tüübi järgi) ja keeldub CSV-d kirjutamast, kui midagi on katki. `--smoke`
laob **kõik 789 ülesannet koos vihjete ja lahendustega** ühte dokumenti ja
kompileerib selle sama malliga, mida tund kasutab. Kui suitsutest annab
0 viga, ei saa ükski tunnikomplekt LaTeXi vea otsa joosta.

## Veerud

Lisaks varasematele on CSV-s nüüd:

| Veerg | Tähendus |
|---|---|
| `tüüp` | `T` teooriaülesanne, `E` eksperimendiülesanne |
| `tase` | `G` gümnaasium, `P` põhikool, `K` või `P/G` ühine |
| `katsevahendid` | eksperimendiülesande vahendite loend (eraldi väljas, mitte teksti sees) |
| `punktid` | žürii maksimumpunktid (eksperimendiülesannetel) |
| `lahendusseis` | vt allpool |
| `allikas` | viide kogumikule ja lahenduse leheküljele |

**Raskuse skaala on tüübiti erinev.** Teooriaülesannetel on kogumike hinnang
1 kuni 10, eksperimendiülesannetel kogumiku tärnid 1 kuni 5. `build_database.py`
kontrollib mõlemat vahemikku eraldi. Filtrit `raskus: [2, 6]` kirjutades
pea seda meeles.

## Eksperimendiülesannete lahenduste seis

Kogumiku PDF-i tekstikiht annab sõnad ja numbrid hästi kätte, aga kaotab ära
tabelid, graafikud ja murrud. Seepärast on iga lahendus märgistatud:

| `lahendusseis` | Mitu | Tähendus |
|---|---|---|
| `toores` | 151 | tekstikihist imporditud proosa; loetav, aga ülakirjad ja murrud on lihtsustatud |
| `kasitsi` | 17 | originaalis on tabel, graafik või hindamisskeem; teksti EI ole imporditud, faili sees on viide kogumiku leheküljele |
| `kasitsi_tehtud` | 1 | käsitsi ümber kirjutatud, vt `tools/kasitsi_lahendus/` |
| `puudub` | 12 | kogumik ise ütleb, et lahendus puudub |

Miks nii: pool-loetav lahendus andmebaasis on hullem kui aus viide
originaalile. Kui mõnda neist 17-st on tunniks vaja, kirjutatakse ta
`tools/kasitsi_lahendus/<id>.tex` sisse ja import ei kaota seda enam ära.

## Eksperimendiülesannete import: mis on käsitsi

Kolm asja ei ole PDF-i tekstikihis olemas ja need on kõrvalfailides:

* **Tärnid** (`tools/tarnid.csv`). Kogumik märgib raskust kuni viie tärniga,
  aga tärn on sümbolifondi glüüf, mida `pdftotext` ei anna. Tärnid on loetud
  leheküljepiltidelt: 1 tärn kuni Ü32, 2 kuni Ü74, 3 kuni Ü125, 4 kuni Ü159,
  5 kuni Ü181.
* **Kategooria ja alamteema** (`tools/teemad.csv`). Sama sõnavara, mis
  teooriaülesannetel.
* **Joonised** (`tools/joonised.csv`). 16 ülesandel on joonis. Need on
  vektorgraafika, mille lähtekoodi ei ole, seega lõigatakse nad
  leheküljelt 300 dpi pildiks: `tools/loika_joonis.py`. Lõiget tuleb
  **vaadata**: selle masina `pdftotext` on Xpdf 4.00, mis kasti-lippe ei
  toeta, seega automaatselt kontrollida ei saa, kas kasti jäi ka teksti.

Ja üks asi ei ole automaatselt lahendatav: kui kogumikus on joonis teksti
kõrval (`wrapfigure`), satuvad **joonise sildid PDF-i tekstikihis lause
sisse**. Nii tuli Ü107 tekst kujul „moodustatud Kollane tähtühendus\dots{}
kae- RK tud''. Need üheksa ülesannet on käsitsi ümber kirjutatud kausta
`tools/kasitsi/`: Ü33, Ü20, Ü62, Ü71, Ü107, Ü117, Ü121, Ü159, Ü175.

## Tunnikomplekti mall

Malle oli varem 20 tükki, igas tunnikaustas oma koopia, ja nad olid juba
lahku jooksnud (kahes vanemas puudus `circuitikz`). Nüüd on üks ühine mall
`lesson-papers/lesson_template.tex`. Kui mõni tund vajab oma kujundust, pane
mall sellesse kausta ja `build_lesson.py` eelistab seda.

Failinimi tuleb **kohtumise**, mitte tänase kuupäevaga: kausta nimest
(`2026-09-08`), muidu `lesson.yml` võtmest `failinimi:` või `date:`.
Varem oli see alati `date.today()`, mistõttu 8. septembri komplekt sai
7. septembril tehtuna nimeks `20260907_füüsika.tex`.

`lesson.yml` filtrid: `voor`, `kategooria` (üksik või loend), `aastad`,
`raskus`, `tüüp` (`T` või `E`), `tase`, `max`. Näiteks kõik
piirkonnavooru eksperimendiülesanded gümnaasiumile:

```yaml
problems:
  filters:
    - { voor: piirkonnavoor, tüüp: E, tase: G }
```
