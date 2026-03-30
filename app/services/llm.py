"""OpenAI API wrapper for language tasks."""
import json
import logging
import time

from ..config import Config

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        api_key = Config._read_openai_key()
        if not api_key:
            raise RuntimeError(
                "OpenAI API key not found. Set OPENAI_API_KEY env var "
                "or put the key in ~/.config/openai_api_key.txt"
            )
        _client = OpenAI(api_key=api_key)
    return _client


def _strip_fences(text: str) -> str:
    """Strip markdown code fences that models add despite being told not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]  # drop opening ```[lang] line
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


def _sanitize(text: str) -> str:
    """Strip null bytes and lone surrogates that make JSON bodies invalid."""
    return text.replace("\x00", "").encode("utf-8", errors="replace").decode("utf-8")


_VERBOSE = None

def _is_verbose() -> bool:
    global _VERBOSE
    if _VERBOSE is None:
        import os
        _VERBOSE = os.environ.get("VERBOSE", "1") == "1"
    return _VERBOSE


def _call(messages: list[dict], model: str, max_tokens: int = 500) -> str | None:
    client = _get_client()
    # Sanitize all message content upfront to avoid invalid JSON request bodies
    messages = [
        {**m, "content": _sanitize(m["content"])} if isinstance(m.get("content"), str) else m
        for m in messages
    ]
    if _is_verbose():
        prompt_preview = " | ".join(
            m["content"][:120].replace("\n", " ") for m in messages if isinstance(m.get("content"), str)
        )
        logger.info("LLM → [%s] %s", model, prompt_preview)
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )
            result = response.choices[0].message.content.strip()
            if _is_verbose():
                logger.info("LLM ← %s", result[:200].replace("\n", " "))
            return result
        except Exception as exc:
            # 400 Bad Request is a deterministic client error — retrying the same
            # payload won't help.  Log at ERROR level and bail immediately.
            status = getattr(exc, "status_code", None)
            if status == 400:
                logger.error("OpenAI bad request (skipping): %s", exc)
                return None
            logger.warning("OpenAI call failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


def generate_extraction_rule(url: str, html_sample: str, purpose: str = "content", existing_rules: list[str] | None = None) -> dict | None:
    """
    Ask the LLM to generate a CSS selector or regex for the given purpose:
    - 'links'  : finds article URLs on a listing/index page
    - 'content': extracts article body text from an article page
    - 'events' : finds event container elements on an agenda page
    Returns {rule_type, rule_definition} or None.
    """
    if purpose == "events":
        return generate_events_rule(url, html_sample)

    avoid_block = ""
    if existing_rules:
        rules_list = "\n".join(f"  - {r}" for r in existing_rules)
        avoid_block = f"\nDe volgende selectors bestaan al — gebruik ze NIET en geef een andere selector:\n{rules_list}\n"

    if purpose == "links":
        prompt = f"""Je krijgt de HTML van een nieuwsoverzichtspagina: {url}

Nieuwssites hebben vaak meerdere secties met verschillende HTML-structuren (uitgelicht artikel, nieuwsgrid, sidebar, gesponsorde content).
Geef een CSS-selector OF een reguliere expressie die artikellinks van deze pagina extraheert.

CSS-selector: target <a>-elementen of containers die een <a> bevatten.
  Voorbeeld: .news-grid a, article.featured a

Reguliere expressie: vang de URL op als groep 1 of als benoemde groep 'url'.
  Voorbeeld: href="(/nieuws/[^"]+)"
  Gebruik regex als de pagina te complex is voor één CSS-selector.
{avoid_block}
Geef je antwoord ALLEEN als JSON:
{{"rule_type": "css_selector", "rule_definition": "<selector>"}}
of
{{"rule_type": "regex", "rule_definition": "<patroon>"}}

Geef alleen de JSON, geen uitleg.

HTML (eerste 8000 tekens):
{html_sample[:8000]}"""
    else:
        prompt = f"""Je krijgt de HTML van een individueel nieuwsartikel van: {url}

Geef een CSS-selector OF reguliere expressie die ALLEEN de hoofdtekst van dit artikel extraheert.
Geen navigatie, geen menu, geen advertenties — alleen de artikeltekst.{avoid_block}
Geef je antwoord ALLEEN als JSON:
{{"rule_type": "css_selector", "rule_definition": "<selector>"}}
of
{{"rule_type": "regex", "rule_definition": "<patroon>"}}

Geef alleen de JSON, geen uitleg.

HTML (eerste 8000 tekens):
{html_sample[:8000]}"""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_STRONG,
        max_tokens=200,
    )
    if not result:
        return None
    try:
        return json.loads(_strip_fences(result))
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for extraction rule: %s", result)
        return None


def generate_events_rule(url: str, html_sample: str) -> dict | None:
    """
    Ask the LLM to generate a CSS selector that selects each individual event
    container element on an agenda page (one element per event).
    Returns {rule_type: "css_selector", rule_definition: "<selector>"} or None.
    """
    prompt = f"""Je krijgt de HTML van een agendapagina: {url}

Geef een CSS-selector die elk afzonderlijk evenement als één element selecteert.
De selector moet één element per evenement opleveren — niet de gehele lijst.

Voorbeeld: .agenda-item, li.event, article.event-card

Geef je antwoord ALLEEN als JSON:
{{"rule_type": "css_selector", "rule_definition": "<selector>"}}

Geef alleen de JSON, geen uitleg.

HTML (eerste 8000 tekens):
{html_sample[:8000]}"""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=150,
    )
    if not result:
        return None
    try:
        return json.loads(_strip_fences(result))
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for events rule: %s", result)
        return None


def parse_event_html(html_fragment: str) -> dict | None:
    """
    Given an HTML fragment from an agenda page, extract the event as a structured dict.
    Returns a dict with keys: title, start_time, end_time, location, description,
    organizer, contact_info — or None if parsing fails.
    start_time and end_time are ISO 8601 strings or null.
    """
    prompt = f"""Je krijgt een HTML-fragment van een agendapagina met één evenement.
Extraheer de evenementgegevens als JSON met de volgende sleutels:
- title (verplicht)
- start_time (ISO 8601 formaat of null)
- end_time (ISO 8601 formaat of null)
- location (of null)
- description (of null)
- organizer (of null)
- contact_info (of null)

Geef ALLEEN de JSON, geen uitleg.

HTML-fragment:
{html_fragment[:3000]}"""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=300,
    )
    if not result:
        return None
    try:
        data = json.loads(_strip_fences(result))
        if not data.get("title"):
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        logger.warning("LLM returned invalid JSON for event parse: %s", result)
        return None


_VALID_GEO_SCOPES = {"local", "region", "province", "national", "intl"}


def rewrite_article(
    title: str,
    extracted_text: str,
    geo_ctx: dict,
    existing_topics: list[str] | None = None,
) -> tuple[str, str, str, list[str]] | None:
    """
    Generate our own title, condense the article into one paragraph in Dutch,
    classify the geographic scope, and assign/suggest topic labels.
    Returns (title, summary, geo_scope, topic_labels) or None on failure.

    topic_labels may contain names from existing_topics (direct match) or
    new free-form labels (will become SuggestedTopics).

    geo_ctx keys: town, province, region_towns (list), province_towns (list).
    """
    town = geo_ctx.get("town", "")
    province = geo_ctx.get("province", "")
    region_towns = geo_ctx.get("region_towns", [])
    province_towns = geo_ctx.get("province_towns", [])

    region_sample = ", ".join(region_towns[:5]) if region_towns else "—"
    province_sample = ", ".join(province_towns[:5]) if province_towns else "—"

    if existing_topics:
        topics_instruction = (
            f'- "topics": kies ALLE toepasselijke onderwerpen uit deze lijst '
            f'(meerdere zijn toegestaan en gewenst): {json.dumps(existing_topics, ensure_ascii=False)}. '
            f'Als het artikel ook over iets gaat dat niet in de lijst staat, voeg dan een kort '
            f'Nederlandstalig label toe. Geef een lege lijst als niets van toepassing is.'
        )
    else:
        topics_instruction = (
            '- "topics": een lijst van relevante Nederlandstalige onderwerpslabels '
            '(meerdere zijn toegestaan; geef een lege lijst als niets van toepassing is)'
        )

    prompt = f"""Je krijgt een nieuwsartikel. Geef je antwoord ALLEEN als JSON met vier sleutels:
- "title": een eigen, neutrale Nederlandstalige kop (maximaal 10 woorden)
- "summary": een samenvatting van één alinea in neutraal Nederlands (maximaal 150 woorden)
- "geo_scope": geografische reikwijdte van het artikel — kies één van: "local", "region", "province", "national", "intl"
{topics_instruction}

Richtlijnen voor geo_scope:
- "local"    — artikel gaat primair over {town}
- "region"   — artikel gaat over nabijgelegen plaatsen zoals {region_sample}
- "province" — artikel gaat over de provincie {province} of plaatsen zoals {province_sample}
- "national" — Nederlands nationaal nieuws
- "intl"     — internationaal nieuws

Geen inleiding, geen uitleg — alleen de JSON.

Originele kop: {title}

Tekst:
{extracted_text[:4000]}"""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=500,
    )
    if not result:
        return None
    try:
        data = json.loads(_strip_fences(result))
        t = (data.get("title") or "").strip()
        s = (data.get("summary") or "").strip()
        if not t or not s:
            return None
        geo_scope = (data.get("geo_scope") or "").strip()
        if geo_scope not in _VALID_GEO_SCOPES:
            geo_scope = "national"
        raw_topics = data.get("topics") or []
        topic_labels = [
            lbl.strip() for lbl in raw_topics
            if isinstance(lbl, str) and lbl.strip()
        ]
        return t, s, geo_scope, topic_labels
    except (json.JSONDecodeError, TypeError):
        logger.warning("rewrite_article returned invalid JSON: %s", result)
        return None


def summarize_story(articles_text: list[str]) -> str | None:
    """
    Summarize multiple article texts into a short Dutch summary (max ~200 words).
    Only called when 2+ sources cover the same story.
    """
    combined = "\n\n---\n\n".join(articles_text[:5])
    prompt = f"""Hieronder staan {len(articles_text)} nieuwsberichten over hetzelfde onderwerp.
Schrijf een neutrale samenvatting in het Nederlands van maximaal 200 woorden.
Geef alleen de samenvatting, geen inleiding of uitleg.

{combined[:6000]}"""

    return _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=300,
    )


def describe_story(summaries: list[str]) -> tuple[str, str] | None:
    """Generate a short title and synthesized description for a story from 2+ article summaries.

    Returns (title, description) or None on failure.
    Title: max 10 words, neutral Dutch headline.
    Description: max 150 words, neutral Dutch paragraph synthesizing all sources.
    Duplicate information across sources is merged, not repeated.
    """
    combined = "\n\n---\n\n".join(summaries[:8])
    prompt = f"""Hieronder staan {len(summaries)} nieuwssamenvattingen over hetzelfde onderwerp, afkomstig van verschillende bronnen.

Geef je antwoord ALLEEN als JSON met twee sleutels:
- "title": een neutrale Nederlandstalige kop van maximaal 10 woorden
- "description": een synthetische samenvatting van maximaal 150 woorden in neutraal Nederlands — verwerk de informatie uit alle bronnen, herhaal geen identieke feiten

Geen inleiding, geen uitleg — alleen de JSON.

Samenvattingen:
{combined[:5000]}"""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=350,
    )
    if not result:
        return None
    try:
        data = json.loads(_strip_fences(result))
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        if not title or not description:
            return None
        return title, description
    except (json.JSONDecodeError, TypeError):
        logger.warning("describe_story returned invalid JSON: %s", result)
        return None


def suggest_topics(title: str, summary: str, existing_topics: list[str]) -> list[str]:
    """
    Select ALL applicable topic names from existing_topics for a given article.
    Returns a list of matching topic names (may be multiple).
    """
    if not existing_topics:
        return []
    topics_json = json.dumps(existing_topics, ensure_ascii=False)
    prompt = f"""Welke van de volgende onderwerpen zijn van toepassing op dit nieuwsartikel?
Kies ALLE toepasselijke onderwerpen — een artikel kan over meerdere onderwerpen gaan.

Beschikbare onderwerpen: {topics_json}

Kop: {title}
Samenvatting: {summary[:500]}

Geef de toepasselijke onderwerpen terug als JSON-lijst met exacte namen uit de lijst hierboven.
Voorbeeld: ["Gezondheid", "Milieu"]
Geef een lege lijst [] als geen enkel onderwerp van toepassing is.
Geef alleen de JSON terug, geen uitleg."""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=100,
    )
    if not result:
        return []
    try:
        suggestions = json.loads(_strip_fences(result))
        return [t for t in suggestions if t in existing_topics]
    except (json.JSONDecodeError, TypeError):
        return []


_DEFAULT_FRONTPAGE_PROMPT = """Je bent redacteur van een lokale nieuwssite. Beoordeel of het volgende nationale nieuwsbericht relevant genoeg is voor de voorpagina van een lokale nieuwssite.

Criteria voor plaatsing op de voorpagina:
- Het bericht heeft directe gevolgen voor het dagelijks leven (bijv. wet- en regelgeving, gezondheid, veiligheid, wonen, werk)
- Het bericht gaat over een onderwerp dat lokaal sterk speelt of herkenbaar is
- Het bericht is substantieel nieuws, geen sensatie of entertainment

Antwoord ALLEEN met JSON: {{"worthy": true}} of {{"worthy": false}}

Kop: {title}
Samenvatting: {summary}"""


def evaluate_frontpage_worthy(title: str, summary: str, custom_prompt: str | None = None) -> bool | None:
    """Ask LLM if a national article is worthy of the local front page.
    Returns True/False, or None on failure."""
    template = custom_prompt or _DEFAULT_FRONTPAGE_PROMPT
    prompt = template.format(title=title, summary=summary[:500])

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=20,
    )
    if not result:
        return None
    try:
        data = json.loads(_strip_fences(result))
        worthy = data.get("worthy")
        if isinstance(worthy, bool):
            return worthy
        return None
    except (json.JSONDecodeError, TypeError):
        logger.warning("evaluate_frontpage_worthy returned invalid JSON: %s", result)
        return None


def parse_event_raw(text: str) -> dict | None:
    """Parse arbitrary text (pasted content, fetched URL body) into a structured event dict.
    Returns keys: title, start_time, end_time, location, description, organizer,
    contact_info, source_url — or None on failure.
    start_time/end_time are ISO 8601 strings or null.
    """
    prompt = f"""Je krijgt een stuk tekst over een evenement (kopieerplak, webpagina of iets anders).
Extraheer de evenementgegevens als JSON met de volgende sleutels:
- title (verplicht)
- start_time (ISO 8601 formaat, bijv. "2026-04-15T19:30:00", of null)
- end_time (ISO 8601 formaat of null)
- location (adres of plaatsnaam, of null)
- description (korte omschrijving max 3 zinnen, of null)
- organizer (organiserende partij, of null)
- contact_info (e-mail, telefoon of website, of null)
- source_url (alleen als er een duidelijke website-URL in de tekst staat, anders null)

Geef ALLEEN de JSON, geen uitleg.

Tekst:
{text[:4000]}"""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=400,
    )
    if not result:
        return None
    try:
        data = json.loads(_strip_fences(result))
        if not data.get("title"):
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        logger.warning("parse_event_raw returned invalid JSON: %s", result)
        return None


def parse_event_image(image_bytes: bytes, mime_type: str) -> dict | None:
    """Parse an event flyer/image using the OpenAI vision API.
    No local OCR model needed — processing is server-side.
    Returns same structure as parse_event_raw, or None on failure.
    """
    import base64
    b64 = base64.b64encode(image_bytes).decode()

    prompt_text = """Dit is een afbeelding van een evenementaankondiging of flyer.
Extraheer de evenementgegevens als JSON met de volgende sleutels:
- title (verplicht)
- start_time (ISO 8601 formaat, bijv. "2026-04-15T19:30:00", of null)
- end_time (ISO 8601 formaat of null)
- location (adres of plaatsnaam, of null)
- description (korte omschrijving max 3 zinnen, of null)
- organizer (organiserende partij, of null)
- contact_info (e-mail, telefoon of website, of null)
- source_url (null)

Geef ALLEEN de JSON, geen uitleg."""

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
        ],
    }]

    client = _get_client()
    if _is_verbose():
        logger.info("LLM → [%s] vision: event image parse (%d bytes)", Config.OPENAI_MODEL_DEFAULT, len(image_bytes))

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=Config.OPENAI_MODEL_DEFAULT,
                messages=messages,
                max_tokens=400,
                temperature=0.2,
            )
            result = response.choices[0].message.content.strip()
            if _is_verbose():
                logger.info("LLM ← %s", result[:200].replace("\n", " "))
            break
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 400:
                logger.error("OpenAI bad request (vision, skipping): %s", exc)
                return None
            logger.warning("OpenAI vision call failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2 ** attempt)
    else:
        return None

    try:
        data = json.loads(_strip_fences(result))
        if not data.get("title"):
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        logger.warning("parse_event_image returned invalid JSON: %s", result)
        return None


def evaluate_source(url: str, html_sample: str) -> dict | None:
    """
    Ask the LLM whether a URL looks like a useful local news source.
    Returns {is_useful: bool, reason: str} or None.
    """
    prompt = f"""Beoordeel of de volgende URL een nuttige lokale nieuwsbron is voor een
lokale nieuwsaggregator. Geef je antwoord ALLEEN als JSON:
{{"is_useful": true/false, "reason": "<korte uitleg in het Nederlands>"}}

URL: {url}
HTML (eerste 3000 tekens):
{html_sample[:3000]}"""

    result = _call(
        [{"role": "user", "content": prompt}],
        model=Config.OPENAI_MODEL_DEFAULT,
        max_tokens=150,
    )
    if not result:
        return None
    try:
        return json.loads(_strip_fences(result))
    except json.JSONDecodeError:
        return None
