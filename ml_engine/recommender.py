"""3.4 Recommendation engine — rule engine over the ML outputs.

Combines the outputs of 3.1 (profiles), 3.2 (forecast + SLA risk) and 3.3
(clusters) into actionable rows for the `recommendations` table. All thresholds
live in `rules.yaml`; this module only implements the logic.

Pure-ish: no Airflow/DB imports. It takes already-computed DataFrames + the raw
tickets frame so it is fully unit-testable.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

RULES_PATH = Path(__file__).parent / "rules.yaml"

RECO_COLUMNS = [
    "id", "type", "target_user_id", "target_group_id", "target_category_id",
    "severity", "title", "description", "evidence", "created_at", "expires_at",
]

INCIDENT_TYPE = 1


def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    import yaml

    p = Path(path) if path else RULES_PATH
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _reco_id(rtype: str, *parts: Any) -> str:
    raw = "|".join([rtype, *[str(p) for p in parts]])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _incident_concentration(tickets: pd.DataFrame, user_id: int, max_cats: int) -> tuple[float, list[int]]:
    """Return (pct on top-`max_cats` categories, those category ids) for a user's
    incidents."""
    sub = tickets[
        (tickets["user_requester"] == user_id)
        & (pd.to_numeric(tickets.get("type"), errors="coerce") == INCIDENT_TYPE)
    ]
    if sub.empty:
        return 0.0, []
    vc = pd.to_numeric(sub["itilcategories_id"], errors="coerce").dropna().astype(int).value_counts()
    if vc.empty:
        return 0.0, []
    top = vc.head(max_cats)
    pct = float(top.sum() / vc.sum() * 100.0)
    return pct, [int(c) for c in top.index.tolist()]


def generate_recommendations(
    *,
    tickets: pd.DataFrame,
    profiles: pd.DataFrame | None = None,
    forecasts: pd.DataFrame | None = None,
    sla_risk: pd.DataFrame | None = None,
    clusters: pd.DataFrame | None = None,
    rules: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> pd.DataFrame:
    rules = rules or load_rules()
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    expires = now + timedelta(days=int(rules.get("expires_days", 14)))
    rcfg = rules.get("rules", {})
    profiles = profiles if profiles is not None else pd.DataFrame()
    forecasts = forecasts if forecasts is not None else pd.DataFrame()
    sla_risk = sla_risk if sla_risk is not None else pd.DataFrame()
    clusters = clusters if clusters is not None else pd.DataFrame()

    recos: list[dict[str, Any]] = []

    def add(rtype, severity, title, desc, evidence, *, user=None, group=None, cat=None):
        recos.append(
            {
                "id": _reco_id(rtype, user, group, cat),
                "type": rtype,
                "target_user_id": user,
                "target_group_id": group,
                "target_category_id": cat,
                "severity": severity,
                "title": title,
                "description": desc,
                "evidence": evidence,
                "created_at": now,
                "expires_at": expires,
            }
        )

    # ---- FORMATION: critique user, incidents concentrated on <=2 categories --
    fr = rcfg.get("formation", {})
    if fr.get("enabled") and not profiles.empty and not tickets.empty:
        crit = profiles[profiles["profile"] == fr.get("profile", "critique")]
        for _, row in crit.iterrows():
            uid = int(row["user_id"])
            pct, cats = _incident_concentration(tickets, uid, int(fr.get("max_categories", 2)))
            if pct >= float(fr.get("incident_concentration_pct", 80)) and cats:
                add(
                    fr["type"], fr.get("severity", "ÉLEVÉ"),
                    f"Formation ciblée pour l'utilisateur {uid}",
                    f"{pct:.0f}% des incidents sur les catégories {cats}. Formation recommandée.",
                    {"profile": "critique", "concentration_pct": round(pct, 1), "categories": cats},
                    user=uid, cat=cats[0],
                )

    # ---- AUTOMATISATION: user with too many repetitive tickets ---------------
    au = rcfg.get("automatisation", {})
    if au.get("enabled") and not profiles.empty:
        min_rep = int(au.get("min_repetitive", 30))
        for _, row in profiles.iterrows():
            snap = row.get("features_snapshot") or {}
            rep = int(snap.get("repetitive_count", 0)) if isinstance(snap, dict) else 0
            if rep > min_rep:
                uid = int(row["user_id"])
                add(
                    au["type"], au.get("severity", "MODÉRÉ"),
                    f"Automatiser les demandes répétitives de l'utilisateur {uid}",
                    f"{rep} tickets répétitifs. Privilégier l'automatisation/process au lieu de la formation.",
                    {"repetitive_count": rep},
                    user=uid,
                )

    # ---- SURCHARGE: predicted volume spike + low team SLA --------------------
    su = rcfg.get("surcharge", {})
    if su.get("enabled") and not forecasts.empty:
        mult = float(su.get("volume_multiplier", 1.5))
        sla_threshold = float(su.get("sla_threshold_pct", 90.0))
        # current team SLA proxy: mean historical SLA across technicians.
        team_sla = (
            float(sla_risk["historical_sla_pct"].mean())
            if not sla_risk.empty and "historical_sla_pct" in sla_risk
            else _global_sla_pct(tickets)
        )
        # per-category average of the predicted horizon vs its own mean
        agg = forecasts.groupby("category_id")["predicted_count"]
        peak = agg.max()
        avg = agg.mean()
        for cat in peak.index:
            if avg[cat] > 0 and peak[cat] > mult * avg[cat] and team_sla < sla_threshold:
                add(
                    su["type"], su.get("severity", "CRITIQUE"),
                    f"Surcharge prévue sur la catégorie {int(cat)}",
                    f"Volume prévu {peak[cat]:.0f} > {mult}× la moyenne, SLA équipe {team_sla:.0f}% < {sla_threshold:.0f}%.",
                    {"predicted_peak": round(float(peak[cat]), 1),
                     "avg_predicted": round(float(avg[cat]), 1),
                     "team_sla_pct": round(team_sla, 1)},
                    cat=int(cat),
                )

    # ---- CAUSE_RACINE: dense cluster over the last window --------------------
    cr = rcfg.get("cause_racine", {})
    if cr.get("enabled") and not clusters.empty:
        algo = cr.get("algorithm", "dbscan")
        min_t = int(cr.get("min_tickets", 100))
        window = int(cr.get("window_days", 30))
        cutoff = pd.Timestamp(now) - pd.Timedelta(days=window)
        for _, c in clusters.iterrows():
            if c.get("algorithm") != algo:
                continue
            last_seen = pd.to_datetime(c.get("last_seen"), errors="coerce")
            recent = pd.isna(last_seen) or last_seen >= cutoff
            if int(c.get("ticket_count", 0)) >= min_t and recent:
                add(
                    cr["type"], cr.get("severity", "CRITIQUE"),
                    f"Cause racine détectée (cluster {int(c['cluster_id'])})",
                    f"{int(c['ticket_count'])} tickets similaires. Mots-clés: {c.get('top_keywords')}.",
                    {"cluster_id": int(c["cluster_id"]),
                     "ticket_count": int(c["ticket_count"]),
                     "sample_titles": c.get("sample_titles"),
                     "top_keywords": c.get("top_keywords")},
                )

    out = pd.DataFrame(recos, columns=RECO_COLUMNS)
    logger.info("generate_recommendations: %d recommendations", len(out))
    return out


def _global_sla_pct(tickets: pd.DataFrame) -> float:
    """Fallback team SLA when no sla_risk frame: share of resolved tickets that
    met the `time_to_resolve` deadline."""
    if tickets is None or tickets.empty or "time_to_resolve" not in tickets.columns:
        return 100.0
    ttr = pd.to_datetime(tickets.get("time_to_resolve"), errors="coerce")
    done = pd.to_datetime(tickets.get("solvedate"), errors="coerce").fillna(
        pd.to_datetime(tickets.get("closedate"), errors="coerce")
    )
    mask = done.notna() & ttr.notna()
    if not mask.any():
        return 100.0
    met = (done[mask] <= ttr[mask]).mean()
    return float(met * 100.0)


def evidence_to_json(df: pd.DataFrame) -> pd.DataFrame:
    """Serialise the `evidence` column to JSON strings (for DB load)."""
    if df.empty:
        return df
    df = df.copy()
    df["evidence"] = df["evidence"].map(lambda v: json.dumps(v, default=str, ensure_ascii=False))
    return df
