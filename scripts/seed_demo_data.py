"""Seed the warehouse (dim_*, fact_*, ml_*, recommendations) with demo data
matching the Sartex PDF spec so the Angular frontend lights up end-to-end.

Runs inside the `api` container (asyncpg already installed).
Usage: docker compose exec -T api python /tmp/seed_demo_data.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
from datetime import datetime, timedelta, timezone

import asyncpg

random.seed(42)
NOW = datetime.now(timezone.utc).replace(tzinfo=None)
TODAY = NOW.date()

# ---------- reference data (per PDF: sites, categories, services) ----------
ENTITIES = [
    (1, "Siège Tunis"),
    (2, "Usine A - Ksar Hellal"),
    (3, "Usine B - Monastir"),
    (4, "Dépôt Sousse"),
    (5, "R&D"),
    (6, "Administration"),
]

CATEGORIES = [
    (1,  "ERP - Saisie / Erreur"),
    (2,  "Mot de passe / Compte bloqué"),
    (3,  "Bureautique (Word / Excel)"),
    (4,  "Réseau / WiFi"),
    (5,  "Impression"),
    (6,  "Matériel PC"),
    (7,  "Messagerie Outlook"),
    (8,  "Application Métier"),
]

# Services (groups) - IT teams AND requester departments
GROUPS = [
    (10, "Infrastructure Réseau"),
    (11, "Systèmes"),
    (12, "Support N1"),
    (13, "Équipe ERP"),
    (14, "Sécurité"),
    (20, "Comptabilité"),
    (21, "Production"),
    (22, "Administration"),
    (23, "Commercial"),
    (24, "RH"),
]

# --------- technicians (users who resolve tickets) ---------
TECHS = [
    (1001, "Karim",   "Mansour",  10),
    (1002, "Youssef", "Ben Ali",  11),
    (1003, "Sami",    "Trabelsi", 12),
    (1004, "Nadia",   "Gharbi",   13),
    (1005, "Rania",   "Kacem",    12),
    (1006, "Mehdi",   "Chaabane", 11),
    (1007, "Ines",    "Bouzid",   14),
    (1008, "Amine",   "Sassi",    10),
]

# --------- requesters distributed across departments/sites ---------
# Composed to yield the 4 profiles per PDF Section A.3
FIRST_NAMES = ["Ahmed","Fatma","Mohamed","Leila","Anis","Sonia","Hichem","Mouna",
               "Wassim","Salma","Bilel","Rim","Tarek","Emna","Fares","Nour",
               "Marwen","Yasmine","Slim","Dorra","Hamza","Cyrine","Achraf","Ines",
               "Oussama","Sana","Zied","Amira","Nabil","Hela","Firas","Meriem"]
LAST_NAMES  = ["Ben Salah","Trabelsi","Gharbi","Jaziri","Bouazizi","Khemiri","Nasri",
               "Mansour","Sfar","Hamdi","Zouari","Chaari","Belhaj","Karray","Riahi",
               "Sassi","Ayari","Mahmoud","Bouzid","Kacem","Kefi","Guesmi"]

# volume tiers -> profile (autonome<2/mo, standard 2-5, dependant 5-10, critique >10, per 3-month window)
# We'll spread 30 requesters, each mapped to a profile bucket.
REQUESTERS = []
# 12 autonome, 10 standard, 6 dépendant, 4 critique
plan = [("autonome", 12, (1, 4)),
        ("standard", 10, (6, 14)),
        ("dependant", 6, (18, 28)),
        ("critique",  4, (35, 55))]
uid = 2001
for profile, count, vol_range in plan:
    for _ in range(count):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        ent = random.choice(ENTITIES)[0]
        grp = random.choice([g[0] for g in GROUPS if g[0] >= 20])
        REQUESTERS.append((uid, fn, ln, ent, grp, profile, vol_range))
        uid += 1

# --------- ticket status/type/priority helpers ----------
# GLPI: type 1=incident,2=request; status 5=solved,6=closed
STATUS_OPEN   = [1, 2, 3, 4]       # new / assigned / planned / pending
STATUS_CLOSED = [5, 6]

# category priority bias (some cats trend more critical)
CAT_PRIO_BIAS = {
    1: 4, 2: 2, 3: 2, 4: 4, 5: 2, 6: 3, 7: 2, 8: 3,
}

# category resolution difficulty (in days)
CAT_RES_DAYS = {
    1: 1.5, 2: 0.2, 3: 0.6, 4: 2.0, 5: 0.5, 6: 1.2, 7: 0.4, 8: 1.8,
}

# tech SLA propensity: some are stars, some struggle
TECH_SLA = {1001: 0.72, 1002: 0.94, 1003: 0.88, 1004: 0.91,
            1005: 0.80, 1006: 0.85, 1007: 0.60, 1008: 0.97}


def ticket_title(cat_id: int) -> tuple[str, str]:
    catmap = {
        1: ("Erreur de saisie ERP module comptabilité",
            "Impossible de valider la ligne, message d'erreur bloqué à l'écran, très frustrant."),
        2: ("Mot de passe oublié / compte bloqué",
            "Compte expiré ce matin, oublié le mot de passe. Bloqué depuis 1h."),
        3: ("Problème formule Excel / mise en page Word",
            "La formule ne calcule pas correctement, besoin d'aide urgente."),
        4: ("WiFi bâtiment B lent / déconnexions",
            "Perte de connexion réseau WiFi toutes les 10 min depuis la mise à jour du switch."),
        5: ("Imprimante bureau ne répond pas",
            "Bourrage papier récurrent, driver à réinstaller."),
        6: ("PC lent / écran bleu au démarrage",
            "Poste très lent depuis hier, redémarrages aléatoires."),
        7: ("Outlook ne synchronise plus",
            "Erreur de synchronisation Outlook depuis 2 jours, mails bloqués."),
        8: ("Application interne SAP crash",
            "Application métier plante lors de l'export, erreur 500."),
    }
    return catmap[cat_id]


async def main() -> None:
    dsn = os.environ.get("SEED_DSN") or "postgresql://glpi:glpi@postgres:5432/glpi_dw"
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        print("Truncating existing warehouse tables...")
        for tbl in ["dim_tickets_enriched","dim_users","dim_entities","dim_categories",
                    "dim_groups","fact_kpis_daily","ml_user_profiles","ml_forecasts",
                    "ml_sla_risk","ml_clusters","recommendations"]:
            await conn.execute(f"TRUNCATE TABLE {tbl} RESTART IDENTITY CASCADE")

        # -------- dim_entities ----------
        await conn.executemany(
            "INSERT INTO dim_entities(id,name,completename,entities_id,level) VALUES($1,$2,$3,$4,$5)",
            [(eid, name, f"Sartex > {name}", 0, 1) for eid, name in ENTITIES],
        )
        # -------- dim_categories ----------
        await conn.executemany(
            "INSERT INTO dim_categories(id,name,completename,itilcategories_id) VALUES($1,$2,$3,$4)",
            [(cid, n, n, 0) for cid, n in CATEGORIES],
        )
        # -------- dim_groups ----------
        await conn.executemany(
            "INSERT INTO dim_groups(id,name,completename,groups_id,entities_id) VALUES($1,$2,$3,$4,$5)",
            [(gid, n, n, 0, 1) for gid, n in GROUPS],
        )

        # -------- dim_users: technicians + requesters ----------
        user_rows = []
        for tid, fn, ln, gid in TECHS:
            user_rows.append((tid, f"{fn.lower()}.{ln.lower()}", ln, fn, True, 1, str(gid)))
        for uid_, fn, ln, ent, grp, _prof, _vr in REQUESTERS:
            user_rows.append((uid_, f"{fn.lower()}.{ln.lower()}", ln, fn, True, ent, str(grp)))
        await conn.executemany(
            "INSERT INTO dim_users(id,name,realname,firstname,is_active,entities_id,groups_id) "
            "VALUES($1,$2,$3,$4,$5,$6,$7)",
            user_rows,
        )
        print(f"Inserted {len(ENTITIES)} entities, {len(CATEGORIES)} categories, "
              f"{len(GROUPS)} groups, {len(user_rows)} users.")

        # -------- dim_tickets_enriched ----------
        tickets = []
        tid_seq = 100000
        for uid_, fn, ln, ent, grp, profile, vol_range in REQUESTERS:
            n_tickets_3mo = random.randint(*vol_range)
            for _ in range(n_tickets_3mo):
                # spread over last 90 days, more recent = slightly denser
                days_ago = int(random.triangular(0, 90, 25))
                created = NOW - timedelta(days=days_ago, hours=random.randint(0,23),
                                         minutes=random.randint(0,59))
                # cat: bias critique users to ERP/Réseau/App
                if profile == "critique":
                    cat = random.choice([1, 4, 8, 1, 4])
                elif profile == "dependant":
                    cat = random.choice([1, 3, 7, 2, 3])
                else:
                    cat = random.choice([c[0] for c in CATEGORIES])
                # type: 60% incident 40% request
                t_type = 1 if random.random() < 0.6 else 2
                # priority: bias by category + a bit of noise
                base = CAT_PRIO_BIAS[cat]
                prio = max(1, min(5, base + random.randint(-1, 1)))
                is_high = prio >= 4
                # tech assignment
                tech_id, tfn, tln, tgrp = random.choice(TECHS)
                # resolution
                base_days = CAT_RES_DAYS[cat]
                res_days = max(0.05, random.gauss(base_days, base_days * 0.4))
                # closed vs open decision: 82% resolved
                if random.random() < 0.82:
                    status = random.choice(STATUS_CLOSED)
                    is_resolved = True
                    solvedate = created + timedelta(days=res_days)
                    closedate = solvedate + timedelta(hours=random.randint(1, 48))
                    resolution_days = res_days
                else:
                    status = random.choice(STATUS_OPEN)
                    is_resolved = False
                    solvedate = None
                    closedate = None
                    resolution_days = None
                # SLA deadline: base_days * (1.2 for stars, 0.8 for strugglers) after creation
                sla_multiplier = TECH_SLA.get(tech_id, 0.8) + 0.4  # 1.0..1.34
                time_to_resolve = created + timedelta(days=base_days * sla_multiplier)
                # If resolved and this tech typically misses SLA, some resolutions land past deadline
                if is_resolved and random.random() > TECH_SLA.get(tech_id, 0.8):
                    solvedate = time_to_resolve + timedelta(hours=random.randint(4, 60))
                    resolution_days = (solvedate - created).total_seconds() / 86400.0

                title, content = ticket_title(cat)
                tickets.append((
                    tid_seq, title, content, status, t_type, prio, cat,
                    created, created + timedelta(hours=random.randint(0,2)),
                    solvedate, closedate, time_to_resolve,
                    uid_, tech_id, ent, grp,
                    prio, prio, is_resolved, is_high, resolution_days,
                    title.lower(),
                ))
                tid_seq += 1

        await conn.executemany(
            """INSERT INTO dim_tickets_enriched
               (id,name,content,status,type,priority,itilcategories_id,
                date,date_mod,solvedate,closedate,time_to_resolve,
                user_requester,user_assign,entities_id,groups_id_requester,
                urgency,impact,is_resolved,is_high_priority,resolution_days,name_normalized)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)""",
            tickets,
        )
        print(f"Inserted {len(tickets)} tickets.")

        # -------- fact_kpis_daily (last 90 days) ----------
        # aggregate from tickets
        rows = await conn.fetch(
            """SELECT date::date AS d,
                      COUNT(*) AS total,
                      AVG(CASE WHEN is_resolved THEN 1.0 ELSE 0.0 END) AS resolved_pct,
                      SUM(CASE WHEN is_high_priority THEN 1 ELSE 0 END) AS hp,
                      COALESCE(AVG(resolution_days),0) AS ard
               FROM dim_tickets_enriched GROUP BY d ORDER BY d"""
        )
        await conn.executemany(
            "INSERT INTO fact_kpis_daily(date,total_tickets,resolved_pct,high_priority_count,avg_resolution_days) "
            "VALUES($1,$2,$3,$4,$5)",
            [(r["d"], r["total"], float(r["resolved_pct"]), r["hp"], float(r["ard"])) for r in rows],
        )
        print(f"Inserted {len(rows)} daily KPI rows.")

        # -------- ml_user_profiles ----------
        profile_rows = []
        for uid_, fn, ln, ent, grp, profile, _vr in REQUESTERS:
            profile_rows.append((uid_, profile, round(random.uniform(0.72, 0.98), 3),
                                 json.dumps({"top_category": random.choice(CATEGORIES)[1]}),
                                 NOW))
        await conn.executemany(
            "INSERT INTO ml_user_profiles(user_id,profile,confidence,features_snapshot,computed_at) "
            "VALUES($1,$2,$3,$4::jsonb,$5)",
            profile_rows,
        )
        print(f"Inserted {len(profile_rows)} ml_user_profiles.")

        # -------- ml_forecasts: next 3 days for each of top 5 categories ----------
        top_cats = [1, 4, 3, 2, 8]
        fc_rows = []
        for cid in top_cats:
            base = {1: 14, 4: 12, 3: 9, 2: 8, 8: 7}[cid]
            for d_off in range(0, 3):
                pred = base * random.uniform(0.9, 1.35)
                fc_rows.append((cid, TODAY + timedelta(days=d_off),
                                round(pred,1), round(pred*0.75,1), round(pred*1.25,1),
                                "high" if base >= 10 else "low", "v1.0", NOW))
        await conn.executemany(
            "INSERT INTO ml_forecasts(category_id,forecast_date,predicted_count,lower_bound,upper_bound,confidence,model_version,computed_at) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            fc_rows,
        )

        # -------- ml_sla_risk: per technician ----------
        sla_risk_rows = []
        for tid, fn, ln, _g in TECHS:
            base = TECH_SLA[tid]
            risk = round(1.0 - base + random.uniform(-0.05, 0.15), 3)
            risk = max(0.05, min(0.95, risk))
            next48 = int(risk * random.randint(8, 22))
            sla_risk_rows.append((tid, risk, next48,
                                  "high" if risk > 0.5 else "low", "v1.0", NOW))
        await conn.executemany(
            "INSERT INTO ml_sla_risk(technician_id,risk_score,next_48h_prediction,confidence,model_version,computed_at) "
            "VALUES($1,$2,$3,$4,$5,$6)",
            sla_risk_rows,
        )

        # -------- ml_clusters (repetitive) ----------
        clusters = [
            (1, "dbscan", ["mot","passe","oublié","expiré","bloqué"],
             ["Mot de passe oublié - Compta","Compte bloqué connexion","Reset password ERP"],
             62, "CRITIQUE", 0.71),
            (2, "dbscan", ["wifi","réseau","déconnexion","switch","bâtiment"],
             ["WiFi bâtiment B lent","Perte réseau usine A","Switch instable"],
             48, "ÉLEVÉ", 0.65),
            (3, "kmeans", ["erp","saisie","erreur","validation","module"],
             ["Erreur saisie ERP compta","Blocage validation ERP","Module ERP crash"],
             41, "ÉLEVÉ", 0.58),
            (4, "kmeans", ["excel","formule","word","impression"],
             ["Problème formule Excel","Word mise en page","Impression Word"],
             27, "MODÉRÉ", 0.32),
            (5, "dbscan", ["outlook","messagerie","synchronisation"],
             ["Outlook ne synchronise","Mails bloqués","Erreur messagerie"],
             19, "MODÉRÉ", 0.28),
        ]
        cluster_rows = [(c[0], c[1], json.dumps(c[3]), c[4], json.dumps(c[2]), c[5], c[6],
                         NOW - timedelta(days=random.randint(30, 60)),
                         NOW - timedelta(hours=random.randint(1, 48)),
                         NOW) for c in clusters]
        await conn.executemany(
            "INSERT INTO ml_clusters(cluster_id,algorithm,sample_titles,ticket_count,top_keywords,severity,neg_ratio,first_seen,last_seen,computed_at) "
            "VALUES($1,$2,$3::jsonb,$4,$5::jsonb,$6,$7,$8,$9,$10)",
            cluster_rows,
        )

        # -------- recommendations (per PDF A.5, B.2, D.4) ----------
        def rid(*parts) -> str:
            return hashlib.sha1(":".join(map(str, parts)).encode()).hexdigest()[:16]

        recos = [
            (rid("FORMATION","ERP","dep-compta"), "FORMATION", None, 20, 1, "CRITIQUE",
             "Formation ERP Module Comptabilité (urgent)",
             "Département Comptabilité : 34 tickets ERP en 45 jours (récurrence 73%). "
             "Sentiment de frustration élevé détecté."),
            (rid("SURCHARGE","tech","1001"), "SURCHARGE", 1001, 10, None, "CRITIQUE",
             "Surcharge équipe Infrastructure Réseau",
             "Charge actuelle 91% (Karim Mansour, 16 tickets actifs, MTTR +40%). "
             "Saturation prévue dans 36h. Réaffecter 4 tickets P2 vers Systèmes."),
            (rid("CAUSE_RACINE","switch","bat-B"), "CAUSE_RACINE", None, None, 4, "CRITIQUE",
             "Cause racine détectée : configuration switch bâtiment B",
             "45 tickets variés (réseau, ERP, impression) sur 2 semaines, 80% créés "
             "après la mise à jour du switch principal. Rollback recommandé."),
            (rid("FORMATION","cyber","mdp"), "FORMATION", None, None, 2, "ÉLEVÉ",
             "Session Cybersécurité + Gestionnaire mots de passe",
             "Demandes de réinitialisation mot de passe +60% sur 30 jours "
             "(18% de la charge totale support). Termes NLP : « oublié », « expiré », « bloqué »."),
            (rid("FORMATION","office","admin"), "FORMATION", None, 22, 3, "ÉLEVÉ",
             "Formation collective Microsoft Office 365 - Administration",
             "34 tickets Excel/Word en 60 jours (12 utilisateurs). Tendance +40% sur 3 mois."),
            (rid("AUTOMATISATION","mdp-reset"), "AUTOMATISATION", None, None, 2, "MODÉRÉ",
             "Automatiser la réinitialisation de mot de passe",
             "Volume élevé (18% de la charge), tâche répétitive et automatisable via SSPR Azure AD."),
            (rid("SURCHARGE","tech","1007"), "SURCHARGE", 1007, 14, None, "ÉLEVÉ",
             "Technicien Sécurité en surcharge (Ines Bouzid)",
             "SLA respecté à 60%, MTTR au-dessus de la moyenne équipe. Prévoir renfort."),
            (rid("CAUSE_RACINE","outlook","exchange"), "CAUSE_RACINE", None, None, 7, "MODÉRÉ",
             "Cluster Outlook : synchronisation dégradée",
             "19 tickets similaires 'Outlook ne synchronise plus' regroupés par NLP. "
             "Vérifier les paramètres Exchange / connectivité."),
            (rid("FORMATION","erp","user-critique"), "FORMATION", 2029, None, 1, "ÉLEVÉ",
             "Accompagnement individuel ERP - Utilisateur critique",
             "Utilisateur > 40 tickets/3 mois (profil CRITIQUE). Plan de formation prioritaire."),
        ]
        rec_rows = []
        for r in recos:
            created = NOW - timedelta(hours=random.randint(1, 72))
            rec_rows.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                             json.dumps({"generated_by": "seed", "spec": "sartex-v2"}),
                             created, created + timedelta(days=30)))
        await conn.executemany(
            "INSERT INTO recommendations(id,type,target_user_id,target_group_id,target_category_id,"
            "severity,title,description,evidence,created_at,expires_at) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11)",
            rec_rows,
        )
        print(f"Inserted {len(recos)} recommendations, {len(clusters)} clusters, "
              f"{len(fc_rows)} forecasts, {len(sla_risk_rows)} SLA-risk rows.")
        print("Seed complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
