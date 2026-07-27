"""High-level GLPI extractors with field remapping to readable names."""
from __future__ import annotations

import logging
from typing import Any

from .client import GLPIClient, JSONDict

logger = logging.getLogger(__name__)

# Default GLPI search-option IDs for Ticket. These are the IDs documented by GLPI
# for a stock instance; verify on your tenant with:
#     GET {base_url}/listSearchOptions/Ticket
# and override TICKET_FIELD_MAP if any ID differs.
TICKET_FIELD_MAP: dict[int, str] = {
    2: "id",
    1: "name",
    21: "content",
    12: "status",
    14: "type",
    3: "priority",
    7: "itilcategories_id",
    15: "date",
    19: "date_mod",
    17: "solvedate",
    16: "closedate",
    18: "time_to_resolve",
    4: "_users_id_requester",
    5: "_users_id_assign",
    80: "entities_id",
    71: "_groups_id_requester",
    10: "urgency",
    11: "impact",
}


def _remap(row: JSONDict, field_map: dict[int, str]) -> JSONDict:
    """Convert a raw /search row (keys are stringified option IDs) to a clean dict."""
    out: JSONDict = {}
    for opt_id, name in field_map.items():
        # GLPI returns keys as strings like "2", "12", ...
        value = row.get(str(opt_id), row.get(opt_id))
        out[name] = value
    return out


def extract_tickets(
    client: GLPIClient,
    *,
    field_map: dict[int, str] | None = None,
    criteria: list[dict[str, Any]] | None = None,
) -> list[JSONDict]:
    """Extract all tickets via /search/Ticket with the configured field map."""
    fmap = field_map or TICKET_FIELD_MAP
    forcedisplay = sorted(fmap.keys())
    rows = [
        _remap(row, fmap)
        for row in client.search("Ticket", forcedisplay=forcedisplay, criteria=criteria)
    ]
    logger.info("extract_tickets: %d tickets", len(rows))
    return rows


def _slim(item: JSONDict, keys: tuple[str, ...]) -> JSONDict:
    return {k: item.get(k) for k in keys}


def extract_users(client: GLPIClient) -> list[JSONDict]:
    raw = client.list_items("User", expand_dropdowns=True)
    keys = ("id", "name", "realname", "firstname", "is_active", "entities_id", "groups_id")
    rows = [_slim(u, keys) for u in raw]
    logger.info("extract_users: %d users", len(rows))
    return rows


def extract_entities(client: GLPIClient) -> list[JSONDict]:
    raw = client.list_items("Entity", expand_dropdowns=True)
    keys = ("id", "name", "completename", "entities_id", "level")
    rows = [_slim(e, keys) for e in raw]
    logger.info("extract_entities: %d entities", len(rows))
    return rows


def extract_categories(client: GLPIClient) -> list[JSONDict]:
    raw = client.list_items("ITILCategory", expand_dropdowns=True)
    keys = ("id", "name", "completename", "itilcategories_id")
    rows = [_slim(c, keys) for c in raw]
    logger.info("extract_categories: %d categories", len(rows))
    return rows


def extract_groups(client: GLPIClient) -> list[JSONDict]:
    raw = client.list_items("Group", expand_dropdowns=True)
    keys = ("id", "name", "completename", "groups_id", "entities_id")
    rows = [_slim(g, keys) for g in raw]
    logger.info("extract_groups: %d groups", len(rows))
    return rows


def extract_ticket_followups(client: GLPIClient) -> list[JSONDict]:
    """Extract /ITILFollowup rows. Content is kept as-is (UTF-8) for downstream NLP."""
    # In GLPI 10+ the resource is ITILFollowup. Older 9.x used TicketFollowup;
    # try the modern endpoint first and fall back transparently.
    try:
        raw = client.list_items("ITILFollowup", expand_dropdowns=False)
    except Exception:
        logger.info("ITILFollowup not available, falling back to TicketFollowup")
        raw = client.list_items("TicketFollowup", expand_dropdowns=False)
    keys = ("id", "items_id", "tickets_id", "itemtype", "content", "date", "users_id")
    rows = [_slim(f, keys) for f in raw]
    # Normalize: some installs expose tickets_id via items_id when itemtype=Ticket
    for r in rows:
        if not r.get("tickets_id") and r.get("itemtype") == "Ticket":
            r["tickets_id"] = r.get("items_id")
    logger.info("extract_ticket_followups: %d followups", len(rows))
    return rows
