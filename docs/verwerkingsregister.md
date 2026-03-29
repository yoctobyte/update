# Register van verwerkingsactiviteiten
**AVG artikel 30 — intern document, niet voor publicatie**

---

## Verwerkingsverantwoordelijke

| | |
|---|---|
| **Naam** | *(zie towns.json / config.json: contact.name)* |
| **Adres** | *(zie towns.json / config.json: contact.address)* |
| **E-mail** | *(zie towns.json / config.json: contact.email)* |
| **Land** | Nederland |

Er is geen functionaris voor gegevensbescherming (FG) aangesteld. De verwerkingsverantwoordelijke is een natuurlijk persoon die de site beheert als hobbyproject zonder commercieel oogmerk. Op grond van AVG art. 37 is aanstelling van een FG niet verplicht.

---

## Verwerkingsactiviteiten

### 1. Contactformulier

| Veld | Inhoud |
|---|---|
| **Doel** | Beantwoorden van vragen of opmerkingen van bezoekers |
| **Rechtsgrond** | Gerechtvaardigd belang (AVG art. 6 lid 1 sub f) — reageren op een door de betrokkene zelf ingediend verzoek |
| **Categorieën betrokkenen** | Bezoekers van de website die het contactformulier invullen |
| **Categorieën persoonsgegevens** | Naam, e-mailadres (optioneel), inhoud bericht |
| **Ontvangers** | Geen. Gegevens zijn uitsluitend zichtbaar voor de beheerder via het adminpaneel. |
| **Doorgifte buiten EER** | Geen |
| **Bewaartermijn** | 1 jaar na ontvangst; automatisch verwijderd door dagelijkse purge-job |
| **Technische maatregel** | Opgeslagen in versleutelde SQLite-database op eigen hardware in Nederland |

---

### 2. Ingezonden stukken (opinies)

| Veld | Inhoud |
|---|---|
| **Doel** | Publicatie van door bezoekers ingezonden opiniestukken |
| **Rechtsgrond** | Uitvoering overeenkomst (AVG art. 6 lid 1 sub b) — de betrokkene verzoekt zelf om publicatie |
| **Categorieën betrokkenen** | Bezoekers die een stuk inzenden |
| **Categorieën persoonsgegevens** | Schuilnaam (pen name), e-mailadres (optioneel), tekst van het stuk |
| **Ontvangers** | Gepubliceerde stukken zijn openbaar op de website. Ongepubliceerde stukken zijn uitsluitend zichtbaar voor de beheerder. |
| **Doorgifte buiten EER** | Geen |
| **Bewaartermijn** | Gepubliceerde stukken: zolang gepubliceerd (redactionele inhoud). Niet-gepubliceerde / afgewezen stukken: 90 dagen, automatisch verwijderd. |
| **Technische maatregel** | Zie boven |

---

### 3. Verzoek om verwijdering

| Veld | Inhoud |
|---|---|
| **Doel** | Verwerken van AVG-rechtenverzoeken (art. 17 wissing, art. 19 inzage e.d.) en klachten over inhoud |
| **Rechtsgrond** | Wettelijke verplichting (AVG art. 6 lid 1 sub c) — de verwerkingsverantwoordelijke is verplicht verzoeken te registreren en af te handelen |
| **Categorieën betrokkenen** | Personen die een verwijderingsverzoek indienen |
| **Categorieën persoonsgegevens** | Naam, e-mailadres en/of telefoonnummer, communicatie-app (optioneel), beschrijving van het verzoek |
| **Ontvangers** | Geen. Uitsluitend zichtbaar voor de beheerder. |
| **Doorgifte buiten EER** | Geen |
| **Bewaartermijn** | 2 jaar — langer dan overige gegevens om de afhandeling aantoonbaar te maken (accountability, AVG art. 5 lid 2). Automatisch verwijderd na 2 jaar. |
| **Technische maatregel** | Zie boven |

*Noot: dit is de enige categorie waarbij persoonsgegevens worden opgeslagen als rechtstreeks gevolg van een verzoek tot het niet opslaan van gegevens. De verwerkingsverantwoordelijke is zich bewust van deze paradox.*

---

### 4. Serverlogboeken

| Veld | Inhoud |
|---|---|
| **Doel** | Technische beveiliging, foutopsporing en misbruikdetectie |
| **Rechtsgrond** | Gerechtvaardigd belang (AVG art. 6 lid 1 sub f) |
| **Categorieën betrokkenen** | Alle bezoekers van de website |
| **Categorieën persoonsgegevens** | IP-adres, tijdstip van verzoek, opgevraagde URL, HTTP-statuscode, user-agent |
| **Ontvangers** | Geen |
| **Doorgifte buiten EER** | Geen |
| **Bewaartermijn** | 90 dagen — geregeld via logrotate op het besturingssysteem (buiten de applicatie) |
| **Technische maatregel** | Logbestanden op eigen hardware in Nederland; niet gekoppeld aan andere gegevens |

---

## Wat niet wordt verwerkt

- Geen tracking-cookies of analytics van derden
- Geen advertentienetwerken
- Geen profilering
- Geen geautomatiseerde besluitvorming met rechtsgevolgen (AVG art. 22)
- Geen bijzondere categorieën persoonsgegevens (AVG art. 9)

---

## Beveiliging (art. 32)

- Gegevens opgeslagen op eigen hardware in Nederland (geen cloudopslag bij derden)
- SQLite-database met bestandssysteempermissies; toegang uitsluitend voor de beheerder
- Adminpaneel beveiligd met bcrypt-gehashd wachtwoord en sessiecookie (HttpOnly, SameSite=Lax)
- HTTPS aanbevolen via reverse proxy (nginx); `SESSION_COOKIE_SECURE=true` in productie
- `.env`-bestand met secrets: bestandspermissies `600`

---

## Rechten van betrokkenen

Betrokkenen kunnen hun rechten uitoefenen via `/verzoek-verwijdering` of het contactformulier op `/over-ons`. De verwerkingsverantwoordelijke streeft ernaar binnen 30 dagen te reageren (maximaal 3 maanden bij complexe verzoeken, AVG art. 12 lid 3).

---

## Versiehistorie

| Datum | Wijziging |
|---|---|
| 2026-03-29 | Initiële versie opgesteld |

