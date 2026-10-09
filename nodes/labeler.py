"""Labels each item with a kind (new model, feature, skill...) and the company that made it,
both picked from fixed lists in config.py, with prompts/labeler.md defining each one.

A cheap model does it, before the sorter, so the sorter can concentrate on whether the item
is worth posting. Anything the model answers that is not exactly on a list is stored as
"other", and a model failure labels the item "other" rather than holding it up.
"""

from __future__ import annotations

import config
from utils import db, logger as log_setup, openrouter

log = log_setup.get("labeler")

PROMPT = config.LABELER_PROMPT_PATH.read_text()

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "company", "reason"],
    "properties": {
        "kind": {"type": "string", "enum": list(config.KINDS)},
        "company": {"type": "string", "enum": list(config.COMPANIES)},
        "reason": {"type": "string"},
    },
}

_COMPANY_BY_LOWER = {name.lower(): name for name in config.COMPANIES}

# Everything on skills.sh is a skill, whatever its name suggests ("agents-cli-observability"
# was called a tool 1 run in 2). Decided here so it never depends on the model.
SKILL_SOURCES = ("skills_trending", "skills_official")


def clean(kind, company) -> tuple[str, str]:
    """The answer forced onto the lists: exact (any capitals) or "other"."""
    kind = str(kind or "").strip().lower()
    company = _COMPANY_BY_LOWER.get(str(company or "").strip().lower(), "other")
    return (kind if kind in config.KINDS else "other"), company


def user_message(item) -> str:
    """What the labeler reads: where it came from, the headline and the start of the text."""
    keys = item.keys()
    article = ((item["article_text"] if "article_text" in keys else "") or "").strip()
    text = article if article and item["origin"] == "x" else \
        f"{item['body'] or ''}\n\n{article}".strip()
    origin = "a post on X" if item["origin"] == "x" else "a news article"
    return (f"Source: {item['source_name']} ({origin})\n\n"
            f"Headline: {item['title'] or ''}\n\nText: {text[:1800]}")


async def execute(item) -> dict:
    """{kind, company, reason, failed} for one item. Never raises."""
    try:
        answer = await openrouter.chat_json(
            model=config.LABELER_MODEL, system=PROMPT, user=user_message(item),
            schema=SCHEMA, schema_name="labels", temperature=0.0, max_tokens=300)
    except Exception as error:  # noqa: BLE001 - a missing label must not hold the item up
        log.warning("Labeling failed for item %s: %s", item["id"], error)
        db.bump_counter("label_failed")
        return {"kind": "other", "company": "other", "reason": f"labeler failed: {error}"[:200],
                "failed": True}
    kind, company = clean(answer.get("kind"), answer.get("company"))
    if item["source_name"] in SKILL_SOURCES:
        kind = "skill"
    return {"kind": kind, "company": company, "reason": str(answer.get("reason", ""))[:200],
            "failed": False}
