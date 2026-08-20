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

Je hebt twee dingen nodig:

- **Git** ([git-scm.com](https://git-scm.com)) — op macOS zit het er meestal al
  op; controleer met `git --version`.
- **Node.js 20.19+ of 22.12+** ([nodejs.org](https://nodejs.org), neem gewoon de
  LTS-versie). Controleer met `node -v`.

Open een terminal en plak dit blok in zijn geheel:

```bash
git clone https://github.com/denizhadzhaoglu/stelz.git stelz
cd stelz/projects/stelz-brand-watch/web
npm install          # eenmalig, duurt ~1 minuut
npm run dev
```

Open daarna **http://localhost:5173** en klik op **Continue with Google**.
Elk Google-account werkt — er hoeft niemand toegang voor je te regelen.

> Zie je een leeg scherm of een foutmelding bij het inloggen? Zet de
> pop-upblokkering uit voor localhost; het inloggen gaat via een pop-upvenster.

---

## 3. Je zit in read-only modus (en dat is expres)

**De tool staat op de echte productiedatabase.** Wat je ziet is live data.

Je account is geen lid van het merk, en dat betekent dat alles wat de data zou
veranderen voor jou uit staat. Je ziet bovenin een balkje **Read-only** dat dit
bevestigt. Concreet ontbreken bij jou:

| Wat je niet ziet | Wat het zou doen |
|---|---|
| De **✕** op een kaart | Die post permanent als fout-positief markeren, voor iedereen |
| De **✕** en de upload bij Settings → Reference images | Een referentiefoto definitief verwijderen — dat verandert hoe de AI Stëlz herkent |
| De knoppen in de **Review**-wachtrij | Goedkeuren/afkeuren van twijfelgevallen |
| De knop **Run scan** | Een nieuwe scan starten. Die kost geld bij de scraping-leverancier |

Dit wordt op de server afgedwongen, niet alleen in het scherm verstopt — je
kunt dus niets stukmaken door ergens op te klikken. **Klik gerust overal.**

Kom je toch een knop tegen die iets lijkt te wijzigen, of krijg je een melding
`Read-only: your account is not a member of this brand` — dan is dát een
bevinding; geef hem door.

> Zie je géén Read-only-balkje en heb je wél een ✕ op de kaarten? Dan staat je
> account als lid geregistreerd. Meld dat even, en behandel de ✕ met beleid:
> gebruik hem hooguit één of twee keer op iets dat overduidelijk géén Stëlz is,
> en blijf van de referentiefoto's in Settings af.

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
| `double-checked` (groen) | Door een tweede AI-controle bevestigd | In de "Worth a check"-band |

- [ ] Kloppen de labels met wat je op de foto ziet?
- [ ] Zie je een kaart met `name only` waar wél een duidelijk leesbaar Stëlz-blik op staat? Noteer die — dat is precies het soort fout dat we willen weten.

### 4d. De sentiment-labels (nieuw)

Naast het merk zelf schat de tool nu ook in **hoe** een post over Stëlz praat.
Dat gebeurt op basis van het **bijschrift**, niet op basis van de foto.

| Label | Betekenis |
|---|---|
| `positive` (groen) | Het bijschrift is enthousiast over het drankje zelf |
| `negative` (rood) | Klacht of kritiek |
| `promo` (grijs) | Een bar, winkel of betaalde samenwerking |
| *(geen label)* | Neutraal — óf nog niet gescoord |

- [ ] Klik een kaart met `positive` open. Staat er in het bijschrift echt iets
      positiefs over het **drankje**? Enthousiasme over het festival of het
      weekend telt niet — dat is precies de fout die we willen vangen.
- [ ] Zie je `promo` op een gewone consument, of juist géén `promo` op een
      duidelijke bar/winkel-post? Beide zijn interessant.
- [ ] In het paneel rechts staat onder **How it's talked about** een zin met de
      onderbouwing. Slaat die ergens op?

> Veel kaarten hebben nog helemaal geen label. Dat is geen bug: het scoren
> gebeurt in batches ná een scan, dus de oude posts komen er geleidelijk bij.
> Belangrijk: een ontbrekend label betekent *nog niet beoordeeld*, niet
> *neutraal*.

### 4e. De filters

- [ ] **Can size**: zet op *Large in frame only*. Worden het er veel minder en duidelijker?
- [ ] **Review**: zet op *Rejected*. Zie je hier eerder afgekeurde items?
- [ ] **Reset** (rechts van de filters): keert alles terug naar Untagged?

### 4f. Het dashboard

- [ ] Bovenaan staat een percentage *"van je hits draagt geen #stelz…"*. Voelt dat getal geloofwaardig?
- [ ] De grafiek **Context tags** — staan daar niet-merk-hashtags in (#vrijmibo, #festival, …)?
      Staat er per ongeluk tóch een #stelz-achtige tag tussen? Dat is een bug.
- [ ] De donut **How we found it** — telt die op tot het totaal?

#### Which scenes the brand lives in (nieuw)

Een blok dat de treffers groepeert naar de **scene** waar ze uit komen:
Vrijdagmiddagborrel, Student life, Festivals & events, Horeca & nightlife…
Makers worden op basis van hun eigen hashtag-geschiedenis in zo'n scene
ingedeeld. Het getal rechts is het aantal posts uit die scene **zonder
merk-hashtag** — dat is het punt: in welke werelden leeft het merk zonder dat
iemand het tagt.

- [ ] Klopt de indeling? Open een paar kaarten uit "Vrijdagmiddagborrel" —
      zijn dat inderdaad borrel-achtige posts, en niet bijvoorbeeld festivals?
- [ ] Iemand kan in meer dan één scene zitten, dus de rijen tellen op tot méér
      dan het totale aantal treffers. Dat staat er ook bij. Klopt die uitleg
      met wat je ziet?
- [ ] Onderaan staat soms *"N further hits couldn't be placed in a scene"*.
      Is dat aantal klein genoeg om de rest geloofwaardig te maken? Als het
      grootste deel daar zit, is het blok nog niet bruikbaar — meld dat.

> Zie je in plaats van namen als "Vrijdagmiddagborrel" alleen algemene groepen
> ("Parties & gatherings", "Nightlife & clubs")? Dan draait het blok op de
> terugvaloptie omdat de scene-indeling nog niet gedraaid is. Meld dat even.

#### How people talk about it (nieuw)

De optelling van de sentiment-labels uit 4d, plus een uitleg van de vier
categorieën.

- [ ] Zegt het percentage bovenin de donut hetzelfde als wat je in de feed ziet?
- [ ] Er staat expliciet hoeveel posts nog **niet** gescoord zijn. Klopt dat met
      hoeveel kaarten zonder label je in de feed tegenkwam?

### 4g. De creator-pagina

Klik in de feed op een `@handle`. Onder het profiel staat een blok
**Why this creator matters** (nieuw).

- [ ] Links staat een **Resonance**-score met de opbouw eronder: Network, Scene
      fit, Engagement, Local, On-brand look, Scene depth. Elke regel heeft een
      uitleg — snap je zonder toelichting waarom deze persoon hoog of laag
      scoort?
- [ ] Rechts staat het publieksprofiel plus **Scenes they post in**. Kloppen die
      scenes met de posts die eronder in de galerij staan?
- [ ] Staat er *"No resonance score … yet"*? Dat mag: scoren is een aparte stap
      na een scan. Meld het alleen als je het bij vrijwel iedereen ziet.

### 4h. Settings → Reference images

Dit zijn de foto's waarmee de AI leert hoe Stëlz eruitziet. Je kunt er niets
aan veranderen (zie §3) — het gaat puur om beoordelen.

- [ ] Staat er bij maximaal 8 foto's het label **"in use"**, en zijn de overige vager weergegeven?
- [ ] **Kijk elke "in use"-foto goed na:** is het onmiskenbaar een Stëlz-product?
      Een sfeerfoto waar toevallig een blikje van een ander merk op staat, leert
      de AI dat dát ook Stëlz is. Noteer alles wat twijfelachtig is.

---

## 4x. Nieuw: Sounds, Projects en custom zoektermen

Drie nieuwe onderdelen sinds de vorige testronde:

**Sounds** — klik op het Briefing-dashboard in de kaart *Top sounds* op een
sound, of op *All sounds →*.
- [ ] Telt de lijst op /sounds hetzelfde als de dashboardkaart?
- [ ] Opent een sound een detailpagina met creators en een trendgrafiek?

**Projects** — open een detectie en klik **Track in project** (alleen zichtbaar
voor members; testers zien de knop niet — dat is expres).
- [ ] Verschijnt het project als chip op de Creators-tab, met een eigen pagina?
- [ ] Zie je op de projectpagina ook leden *zonder* hits? (bewust: stilte is informatie)
- [ ] Members: probeer meer dan 25 creators totaal te tracken — de foutmelding
      hoort uit te leggen waarom er een limiet is (scankosten).

**Custom zoektermen** — Settings → Hashtags (alleen members kunnen toevoegen).
- [ ] Krijgt een nieuwe tag automatisch het label `custom` en een cap van 200?
- [ ] Staat rechtsboven een kostenschatting voor de volgende scan?

## 5. Wat wel en niet werkt

### Wat sinds kort wél werkt

Deze dingen stonden in een eerdere versie van dit document als "nog niet
uitgerold". Dat klopt niet meer — ze draaien nu mee:

| Werkt nu | Waar je het ziet |
|---|---|
| **Tweede AI-controle** op twijfelgevallen | Het groene `double-checked`-label. De foto wordt opnieuw bekeken op 1024px in plaats van 512px, en zo nodig uitgesneden rond het blikje |
| **Terugkoppeling van afwijzingen** | Elke ✕ wordt als tegenvoorbeeld meegestuurd bij die tweede controle. De knop verbetert dus daadwerkelijk toekomstige scans |
| **Ruimere hashtag-selectie** | Lifestyle-tags (#vrijmibo, #huisfeest, #studentenleven, #festivalseizoen…) zitten in de scanlijst, te zien in Settings → Hashtags |
| **Meer videoframes** | Het aantal frames schaalt nu mee met de lengte van de video in plaats van een vaste 6 |
| **Sentiment** | De labels uit §4d |

Als je hier iets van *niet* terugziet, is dat een bevinding — dan is de
uitrol niet compleet.

### Wat nog steeds niet werkt

| Nog niet | Gevolg |
|---|---|
| Automatische scans | Er draait geen dagelijkse scan. Nieuwe data komt er alleen als iemand met beheerrechten op **Run scan** drukt |
| Sentiment op de hele historie | Het scoren loopt in porties van 400 posts. De oudere treffers krijgen hun label pas na een aantal runs — een kaart zonder label is dus "nog niet beoordeeld", niet "neutraal" |
| Uitnodigingen per e-mail | Toegang geven gaat via Settings → Access, en alleen voor iemand die al een keer heeft ingelogd. Er wordt geen mail verstuurd |

## 6. Wat we graag terugkrijgen

Het meest waardevol, in deze volgorde:

1. **De lijst van 10 gecontroleerde kaarten** uit 4a — per kaart: is het echt
   Stëlz, en klopt het label.
2. **Elke foto waar geen Stëlz op staat maar de tool zegt van wel.** Graag met de
   link naar de originele post erbij (via *Open original ↗*).
3. **Elke twijfelachtige referentiefoto** uit 4h.
4. **Sentiment-labels die er naast zitten** (4d) — vooral `positive` op een post
   die alleen over het uitje enthousiast is, en gemiste `promo` op bars.
5. Alles wat je zonder uitleg niet begreep. Als een label of een scherm niet
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
