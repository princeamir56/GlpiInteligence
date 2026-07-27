"""Shared synthetic fixtures — no live Postgres/GPU needed."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_tickets(n_users: int = 40, per_user: int = 6, seed: int = 42) -> pd.DataFrame:
    """Build a dim_tickets_enriched-shaped frame with varied user behaviours so
    the rule labeler produces all four classes."""
    rng = np.random.default_rng(seed)
    base = pd.Timestamp("2026-01-01")
    rows = []
    tid = 1
    for u in range(1, n_users + 1):
        # vary behaviour by user id bucket
        if u % 4 == 0:            # heavy / dependant
            k, prio_hi, rep = 25, 0.1, True
        elif u % 4 == 1:          # critique
            k, prio_hi, rep = 8, 0.6, False
        elif u % 4 == 2:          # autonome
            k, prio_hi, rep = 3, 0.0, False
        else:                     # standard
            k, prio_hi, rep = per_user, 0.1, False
        for i in range(k):
            resolved = rng.random() > 0.2
            status = int(rng.choice([5, 6])) if resolved else int(rng.choice([1, 2, 4]))
            priority = int(rng.choice([5, 6])) if rng.random() < prio_hi else int(rng.choice([2, 3]))
            date = base + pd.Timedelta(days=int(rng.integers(0, 120)))
            solve = date + pd.Timedelta(days=float(rng.uniform(0.1, 8)))
            title = "imprimante hs" if rep else f"probleme divers {i % 5}"
            rows.append(
                {
                    "id": tid,
                    "name": title,
                    "content": f"bonjour {title} merci de resoudre urgent",
                    "status": status,
                    "type": int(rng.choice([1, 2])),
                    "priority": priority,
                    "itilcategories_id": int(rng.integers(1, 6)),
                    "date": date,
                    "date_mod": solve,
                    "solvedate": solve if resolved else pd.NaT,
                    "closedate": solve if status == 6 else pd.NaT,
                    "time_to_resolve": date + pd.Timedelta(days=3),
                    "user_requester": u,
                    "user_assign": int(rng.integers(101, 110)),
                    "entities_id": 0,
                    "groups_id_requester": 1,
                    "urgency": 3,
                    "impact": 3,
                    "is_resolved": resolved,
                    "is_high_priority": priority >= 5,
                    "resolution_days": (solve - date).total_seconds() / 86400.0 if resolved else np.nan,
                    "name_normalized": title,
                }
            )
            tid += 1
    return pd.DataFrame(rows)


@pytest.fixture
def tickets() -> pd.DataFrame:
    return _make_tickets()


@pytest.fixture
def tiny_tickets() -> pd.DataFrame:
    return _make_tickets(n_users=3, per_user=2)


@pytest.fixture
def text_tickets() -> pd.DataFrame:
    """A corpus with clearly repeated themes for clustering tests."""
    themes = [
        ("panne imprimante", "l imprimante ne fonctionne plus impossible d imprimer"),
        ("acces vpn", "je n arrive pas a me connecter au vpn depuis chez moi"),
        ("mot de passe oublie", "j ai oublie mon mot de passe merci de le reinitialiser"),
    ]
    rows = []
    tid = 1
    base = pd.Timestamp("2026-06-01")
    for theme_idx, (name, content) in enumerate(themes):
        for i in range(12):
            rows.append(
                {
                    "id": tid, "name": name, "content": content,
                    "itilcategories_id": theme_idx + 1,
                    "date": base + pd.Timedelta(days=i),
                    "status": 6, "type": 1, "priority": 3,
                    "user_requester": i + 1, "user_assign": 101,
                    "name_normalized": name,
                    "solvedate": base + pd.Timedelta(days=i, hours=2),
                    "closedate": pd.NaT, "time_to_resolve": base + pd.Timedelta(days=i + 3),
                    "resolution_days": 0.1,
                }
            )
            tid += 1
    return pd.DataFrame(rows)
