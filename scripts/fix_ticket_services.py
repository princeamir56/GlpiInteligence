"""One-off maintenance script: assign a requester (user + department Group)
to every existing GLPI ticket that doesn't have one, so the dashboard's
"Services" tab stops bucketing everything into "Sans service".

Context
-------
``scripts/populate_glpi.py`` creates demo tickets via ``POST /Ticket`` with
``_users_id_requester`` / ``_groups_id_requester`` set on the input payload.
Investigation (see conversation) showed this GLPI instance's REST endpoint
silently ignores those underscore-prefixed actor fields on create: the
``glpi_tickets_users`` / ``glpi_groups_tickets`` tables are essentially
empty (0 requester rows) even though 2500 tickets exist. There is therefore
no original per-ticket requester to "recover" from GLPI — one has to be
assigned.

This script re-derives a requester for every ticket the same way
``populate_glpi.py`` originally chose one: a uniformly random end-user (see
``ensure_users()`` there), whose department is read from that user's
``Group_User`` membership. For each ticket missing a requester it creates:

  * ``Ticket_User``  {tickets_id, users_id, type=1}   — requester *user*
  * ``Group_Ticket`` {tickets_id, groups_id, type=1}  — requester *group*

so the user and the group are consistent with each other, and both the
"Services" tab (grouped by ``groups_id_requester``) and "Top requesters"
(grouped by ``user_requester``) get populated. Tickets that already have a
requester (user and/or group) are left untouched — only what's missing is
added.

Usage
-----
    # 1. Ensure .env has GLPI_BASE_URL, GLPI_APP_TOKEN, GLPI_USER_TOKEN
    # 2. From GlpiInteligence/:
    python scripts/fix_ticket_services.py --dry-run     # preview only
    python scripts/fix_ticket_services.py                # apply

Flags
-----
    --dry-run     log what would change, no writes
    --seed N      make the random assignment reproducible
    --env-file    path to a specific .env file
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Any

import requests
from dotenv import load_dotenv

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(message)s",
)
log = logging.getLogger("fix_ticket_services")

TYPE_REQUESTER = 1  # CommonITILActor::REQUESTER — used by both
                     # Ticket_User.type and Group_Ticket.type
BATCH_SIZE = 200


# ============================================================================
# Thin GLPI REST client — dependency-free, mirrors populate_glpi.py's Glpi.
# ============================================================================


@dataclass
class Glpi:
    base_url: str
    app_token: str
    user_token: str
    verify_ssl: bool = True
    timeout: float = 30.0
    page_size: int = 200
    session_token: str | None = None
    _s: requests.Session = field(default_factory=requests.Session)

    def __enter__(self) -> "Glpi":
        self._s.verify = self.verify_ssl
        r = self._s.get(
            f"{self.base_url}/initSession",
            headers={
                "App-Token": self.app_token,
                "Authorization": f"user_token {self.user_token}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        self.session_token = r.json()["session_token"]
        log.info("GLPI session opened.")
        return self

    def __exit__(self, *a) -> None:
        if self.session_token:
            try:
                self._s.get(f"{self.base_url}/killSession", headers=self._h(), timeout=self.timeout)
            except Exception:
                pass
            log.info("GLPI session closed.")

    def _h(self) -> dict[str, str]:
        return {
            "App-Token": self.app_token,
            "Session-Token": self.session_token or "",
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        r = self._s.get(f"{self.base_url}{path}", headers=self._h(), params=params, timeout=self.timeout)
        if r.status_code == 401:
            self.__enter__()  # session expired mid-run — reopen once and retry
            r = self._s.get(f"{self.base_url}{path}", headers=self._h(), params=params, timeout=self.timeout)
        r.raise_for_status()
        return r

    def create_batch(self, itemtype: str, inputs: list[dict[str, Any]]) -> list[int]:
        if not inputs:
            return []
        r = self._s.post(
            f"{self.base_url}/{itemtype}",
            headers=self._h(),
            json={"input": inputs},
            timeout=self.timeout * 3,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"POST batch {itemtype} {r.status_code}: {r.text[:500]}")
        body = r.json()
        if isinstance(body, dict):
            body = [body]
        ids = []
        for x in body:
            try:
                ids.append(int(x["id"]))
            except (KeyError, TypeError, ValueError):
                log.warning("Batch %s item failed: %s", itemtype, x)
        return ids

    def list_items(self, itemtype: str) -> list[dict[str, Any]]:
        """Paginated GET /{itemtype} — returns raw objects with real column
        names (unlike /search, which renders FK columns as display strings)."""
        out: list[dict[str, Any]] = []
        start = 0
        while True:
            end = start + self.page_size - 1
            r = self.get(f"/{itemtype}", {"range": f"{start}-{end}", "expand_dropdowns": "false"})
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            if len(batch) < self.page_size:
                break
            start += self.page_size
        return out

    def group_members(self, group_id: int) -> list[int]:
        r = self.get(f"/Group/{group_id}/Group_User")
        rows = r.json()
        if not isinstance(rows, list):
            return []
        return [int(row["users_id"]) for row in rows if row.get("users_id")]


# ============================================================================
# Main logic
# ============================================================================


def build_candidates(g: Glpi) -> list[tuple[int, int, str]]:
    """(user_id, group_id, group_name) for every user in a 'department'
    group — i.e. every group except the IT/technician teams, which are
    assignment pools, not requester departments."""
    groups = g.list_items("Group")
    dept_groups = [gr for gr in groups if not str(gr.get("name", "")).startswith("IT -")]
    log.info(
        "Found %d groups total, %d treated as 'department' (requester) groups: %s",
        len(groups), len(dept_groups), ", ".join(str(gr.get("name")) for gr in dept_groups),
    )

    candidates: list[tuple[int, int, str]] = []
    for gr in dept_groups:
        gid = int(gr["id"])
        name = str(gr.get("name"))
        members = g.group_members(gid)
        candidates.extend((uid, gid, name) for uid in members)
        log.debug("Group '%s' (id=%d): %d members", name, gid, len(members))
    log.info("Built %d (user, department) candidate pairs.", len(candidates))
    return candidates


def fix_tickets(g: Glpi, candidates: list[tuple[int, int, str]], dry_run: bool, seed: int | None) -> None:
    if seed is not None:
        random.seed(seed)

    log.info("Fetching ticket ids...")
    ticket_ids = [int(t["id"]) for t in g.list_items("Ticket")]
    log.info("%d tickets total.", len(ticket_ids))

    log.info("Fetching existing requester links (Group_Ticket / Ticket_User)...")
    has_group_requester = {
        int(r["tickets_id"]) for r in g.list_items("Group_Ticket") if int(r.get("type") or 0) == TYPE_REQUESTER
    }
    has_user_requester = {
        int(r["tickets_id"]) for r in g.list_items("Ticket_User") if int(r.get("type") or 0) == TYPE_REQUESTER
    }

    group_ticket_inputs: list[dict[str, Any]] = []
    ticket_user_inputs: list[dict[str, Any]] = []
    per_group_count: dict[str, int] = {}

    for tid in ticket_ids:
        needs_group = tid not in has_group_requester
        needs_user = tid not in has_user_requester
        if not needs_group and not needs_user:
            continue

        uid, gid, gname = random.choice(candidates)
        if needs_group:
            group_ticket_inputs.append({"tickets_id": tid, "groups_id": gid, "type": TYPE_REQUESTER})
            per_group_count[gname] = per_group_count.get(gname, 0) + 1
        if needs_user:
            ticket_user_inputs.append({"tickets_id": tid, "users_id": uid, "type": TYPE_REQUESTER})

    log.info("Tickets needing a requester GROUP: %d", len(group_ticket_inputs))
    log.info("Tickets needing a requester USER:  %d", len(ticket_user_inputs))

    if dry_run:
        for name, count in sorted(per_group_count.items(), key=lambda kv: -kv[1]):
            log.info("  [dry] -> %-30s %d", name, count)
        log.info("Dry run — no writes performed.")
        return

    created_groups = 0
    for i in range(0, len(group_ticket_inputs), BATCH_SIZE):
        chunk = group_ticket_inputs[i:i + BATCH_SIZE]
        created_groups += len(g.create_batch("Group_Ticket", chunk))
        log.info("Group_Ticket progress: %d/%d", created_groups, len(group_ticket_inputs))

    created_users = 0
    for i in range(0, len(ticket_user_inputs), BATCH_SIZE):
        chunk = ticket_user_inputs[i:i + BATCH_SIZE]
        created_users += len(g.create_batch("Ticket_User", chunk))
        log.info("Ticket_User progress: %d/%d", created_users, len(ticket_user_inputs))

    log.info("=" * 60)
    log.info("Requester groups created: %d", created_groups)
    log.info("Requester users created:  %d", created_users)
    for name, count in sorted(per_group_count.items(), key=lambda kv: -kv[1]):
        log.info("  -> %-30s %d", name, count)
    log.info("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()

    load_dotenv(dotenv_path=args.env_file, override=False)
    base_url = os.getenv("GLPI_BASE_URL", "").strip().rstrip("/")
    app_token = os.getenv("GLPI_APP_TOKEN", "").strip()
    user_token = os.getenv("GLPI_USER_TOKEN", "").strip()
    verify_ssl = os.getenv("GLPI_VERIFY_SSL", "true").lower() != "false"
    if not (base_url and app_token and user_token):
        log.error("Missing GLPI_BASE_URL / GLPI_APP_TOKEN / GLPI_USER_TOKEN in .env")
        return 2

    with Glpi(base_url=base_url, app_token=app_token, user_token=user_token, verify_ssl=verify_ssl) as g:
        candidates = build_candidates(g)
        if not candidates:
            log.error("No department groups / members found — aborting (nothing to assign).")
            return 1
        fix_tickets(g, candidates, args.dry_run, args.seed)

    if args.dry_run:
        log.info("Dry run complete — no changes were made. Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
