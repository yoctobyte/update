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


def _call(messages: list[dict], model: str, max_tokens: int = 500) -> str | None:
    client = _get_client()
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
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


def rewrite_article(title: str, extracted_text: str, geo_ctx: dict) -> tuple[str, str, str, list[str]] | None:
    """
    Generate our own title, condense the article into one paragraph in Dutch,
    classify the geographic scope, and suggest 1-3 topic labels.
    Returns (title, summary, geo_scope, topic_labels) or None on failure.

    geo_ctx keys: town, province, region_towns (list), province_towns (list).
    """
    town = geo_ctx.get("town", "")
    province = geo_ctx.get("province", "")
    region_towns = geo_ctx.get("region_towns", [])
    province_towns = geo_ctx.get("province_towns", [])

    region_sample = ", ".join(region_towns[:5]) if region_towns else "—"
    province_sample = ", ".join(province_towns[:5]) if province_towns else "—"

    prompt = f"""Je krijgt een nieuwsartikel. Geef je antwoord ALLEEN als JSON met vier sleutels:
- "title": een eigen, neutrale Nederlandstalige kop (maximaal 10 woorden)
- "summary": een samenvatting van één alinea in neutraal Nederlands (maximaal 150 woorden)
- "geo_scope": geografische reikwijdte van het artikel — kies één van: "local", "region", "province", "national", "intl"
- "topics": een lijst van 1 tot 3 korte Nederlandstalige onderwerpslabels (bijv. ["politiek", "verkeer", "duurzaamheid"])

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
        max_tokens=450,
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
            lbl.strip().lower() for lbl in raw_topics
            if isinstance(lbl, str) and lbl.strip()
        ][:3]
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


def suggest_topics(title: str, short_text: str, existing_topics: list[str]) -> list[str]:
    """
    Suggest relevant topic names from the existing list for a given article.
    Returns a list of matching topic names.
    """
    if not existing_topics:
        return []
    topics_str = ", ".join(existing_topics)
    prompt = f"""Gegeven de volgende nieuwskop en samenvatting, welke van deze onderwerpen zijn van toepassing?
Onderwerpen: {topics_str}

Kop: {title}
Samenvatting: {short_text[:300]}

Geef alleen de toepasselijke onderwerpen terug als JSON-lijst, bijv. ["politiek", "cultuur"].
Geef alleen de JSON terug."""

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
