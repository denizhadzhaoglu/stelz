# STËLZ Brand Watch — testinstructies

Voor een collega die de tool doorloopt en bevindingen terugkoppelt.
Je hebt geen developer-ervaring nodig; wel een terminal en een Google-account.

---

## 1. Waar dit voor is

De tool zoekt op Instagram en TikTok naar posts waar een **Stëlz-blikje in beeld
staat**. Het punt is niet de posts die `#stelz` gebruiken — die kan iedereen
gratis volgen. Het punt is de posts **zonder merk-hashtag en zonder @vermelding**,
die het merk zelf nooit had kunnen vinden. Daarom opent de feed standaard op
**Untagged**.

Waar je vooral op let bij het testen:

1. Staat er écht een Stëlz-blikje op de foto's die de tool toont? (niet White
   Claw, Bavaria, Heineken, Red Bull…)
2. Klopt het label dat de tool eraan hangt — "no tag", "small in frame", "name only"?
3. Is de indeling begrijpelijk zonder dat iemand het je uitlegt?

---

## 2. Opstarten (± 5 minuten)

Je hebt **Node.js 20.19+ of 22.12+** nodig ([nodejs.org](https://nodejs.org),
neem gewoon de LTS-versie). Controleer met `node -v`.

```bash
cd "<pad-naar-de-map>/projects/stelz-brand-watch/web"
npm install          # eenmalig, duurt ~1 minuut
npm run dev
```

Open daarna **http://localhost:5173** en klik op **Continue with Google**.
Elk Google-account werkt — er hoeft niemand toegang voor je te regelen.

> Zie je een leeg scherm of een foutmelding bij het inloggen? Zet de
> pop-upblokkering uit voor localhost; het inloggen gaat via een pop-upvenster.

---

## 3. ⚠️ Lees dit vóór je klikt

**De tool staat op de echte productiedatabase.** Wat je ziet is live data, en
twee acties schrijven daar ook echt naartoe:

| Actie | Gevolg |
|---|---|
| **✕** op een kaart (verschijnt bij hover) | Markeert die post permanent als fout-positief, voor iedereen |
| **✕** op een foto in Settings → Reference images | **Verwijdert die referentiefoto definitief.** Dit verandert hoe de AI Stëlz herkent |

Wil je de ✕ op een kaart uitproberen: doe dat één of twee keer op iets dat
overduidelijk géén Stëlz is, en noteer welke. Blijf van de referentiefoto's in
Settings af tenzij je expliciet met Lukas hebt afgestemd dat je daar mag opruimen.

Alle andere knoppen (filters, tabs, zoeken, kaarten openen) zijn veilig — die
lezen alleen.

---

## 4. Wat je test

### 4a. De feed — het hoofdscherm

Bovenaan staan vier knoppen: **Untagged** · Tagged · Brand accounts · All.
Untagged staat standaard aan en dat is bewust.

- [ ] Klopt het aantal bij elke knop, en tellen Untagged + Tagged + Brand accounts op tot All?
- [ ] Wissel tussen de vier — verandert de inhoud logisch mee?
- [ ] Klik een kaart aan. Opent het paneel rechts met details?
- [ ] Klik in dat paneel op **Open original ↗**. **Dit is de belangrijkste check:**
      staat er op de echte Instagram-post een Stëlz-blikje? En als de kaart
      "no tag" zegt, klopt het dan dat er géén #stelz of @drinkstelz op staat?

Doe die laatste check op **10 kaarten** en noteer per kaart: blikje echt Stëlz
(ja/nee), en label klopt (ja/nee). Dat is verreweg de nuttigste output van deze
test.

### 4b. De twee banden

De feed is in tweeën gedeeld. Bovenaan de duidelijke treffers. Daaronder een kop
**"Worth a check"** met uitleg.

- [ ] Staat er een kop met uitleg tussen de twee groepen?
- [ ] Zitten er in de bovenste groep zichtbaar duidelijkere blikjes dan in de onderste?
- [ ] Is de onderste groep merkbaar vaker fout? (dat is verwacht en staat er ook bij)
- [ ] Staat er onder de kop soms een link *"Show N hits whose labels read as
      another brand"*? Klik die aan — staan daar inderdaad andere merken tussen?

### 4c. De labels op de kaarten

| Label | Betekenis | Waar te verwachten |
|---|---|---|
| `no tag` (rood) | Geen #stelz, geen @drinkstelz | Untagged-weergave |
| `in text` | Merk staat wel in het bijschrift, maar niet als tag | Af en toe |
| `tagged` / `brand acct` | Wel gevonden via hashtag / eigen account | Tagged- en Brand-weergave |
| `small in frame` (oranje) | Blikje klein of ver weg | "Worth a check" |
| `name only` (oranje) | Alleen het woord STËLZ gelezen, geen labeltekst eromheen | "Worth a check" |
| `reads "heineken"` (rood) | Het label noemt een ander merk | Achter de link uit 4b |
| `double-checked` (groen) | Door een tweede AI-controle bevestigd | **Nog niet zichtbaar** — zie §5 |

- [ ] Kloppen de labels met wat je op de foto ziet?
- [ ] Zie je een kaart met `name only` waar wél een duidelijk leesbaar Stëlz-blik op staat? Noteer die — dat is precies het soort fout dat we willen weten.

### 4d. De filters

- [ ] **Can size**: zet op *Large in frame only*. Worden het er veel minder en duidelijker?
- [ ] **Review**: zet op *Rejected*. Zie je hier eerder afgekeurde items?
- [ ] **Reset** (rechts van de filters): keert alles terug naar Untagged?

### 4e. Het dashboard

- [ ] Bovenaan staat een percentage *"van je hits draagt geen #stelz…"*. Voelt dat getal geloofwaardig?
- [ ] De grafiek **Context tags** — staan daar niet-merk-hashtags in (#vrijmibo, #festival, …)?
      Staat er per ongeluk tóch een #stelz-achtige tag tussen? Dat is een bug.
- [ ] De donut **How we found it** — telt die op tot het totaal?

### 4f. Settings → Reference images

Dit zijn de foto's waarmee de AI leert hoe Stëlz eruitziet.

- [ ] Staat er bij maximaal 8 foto's het label **"in use"**, en zijn de overige vager weergegeven?
- [ ] **Kijk elke "in use"-foto goed na:** is het onmiskenbaar een Stëlz-product?
      Een sfeerfoto waar toevallig een blikje van een ander merk op staat, leert
      de AI dat dát ook Stëlz is. Noteer alles wat twijfelachtig is — **maar
      verwijder niets.**

---

## 5. Wat nog níet werkt (dus geen bug)

Een deel van het werk zit in de backend en is **nog niet uitgerold**. Je ziet het
dus nog niet, ook al staat de code er:

| Nog niet live | Wat je daardoor niet ziet |
|---|---|
| Tweede AI-controle op twijfelgevallen | Het groene `double-checked`-label, en de "Worth a check"-band is nog even rommelig als nu |
| Terugkoppeling van afwijzingen naar de AI | Een ✕ verbetert nog geen toekomstige scans |
| Ruimere hashtag-selectie | Nog geen extra content uit lifestyle-hashtags |
| Meer videoframes | Nog geen extra treffers uit video's |

Ook goed om te weten: er draait **geen automatische scan**. Nieuwe data komt er
alleen als iemand op **Run scan** drukt. Doe dat niet zonder overleg — één scan
kost geld bij de scraping-leverancier.

---

## 6. Wat we graag terugkrijgen

Het meest waardevol, in deze volgorde:

1. **De lijst van 10 gecontroleerde kaarten** uit 4a — per kaart: is het echt
   Stëlz, en klopt het label.
2. **Elke foto waar geen Stëlz op staat maar de tool zegt van wel.** Graag met de
   link naar de originele post erbij (via *Open original ↗*).
3. **Elke twijfelachtige referentiefoto** uit 4f.
4. Alles wat je zonder uitleg niet begreep. Als een label of een scherm niet
   vanzelf spreekt, is dat een bevinding — geen gebrek aan kennis.

Een screenshot met een zin erbij is genoeg. Geen formulier nodig.

---

## 7. Achtergrond (optioneel)

Hoe de tool nu presteert, gemeten op een handmatig gelabelde set van 72 beelden
(echte Stëlz-blikjes plus lastige tegenvoorbeelden: White Claw, Truly, Heineken,
Red Bull, feestfoto's, blik-vormige voorwerpen):

- Van de beelden die de tool accepteert is **86% correct**.
- Met de tweede AI-controle erbij (nog niet uitgerold) wordt dat **100%**, zonder
  dat er echte blikjes verloren gaan.
- De fouten zitten vrijwel allemaal in de **"Worth a check"**-band. De bovenste
  band was in die test volledig correct.

Dat is 72 beelden, geen 5.000 — daarom is jouw handmatige controle uit 4a de
enige manier om te weten of dit ook op de echte data klopt.

Ontwikkelaars die de testsuite willen draaien:

```bash
cd projects/stelz-brand-watch/web && npm test    # 67 frontend-tests
cd firebase/functions && python3 -m unittest discover -s tests   # 177 backend-tests
```
