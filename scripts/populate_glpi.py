"""Populate a live GLPI instance via its REST API with realistic Sartex-Group demo
data that matches the PDF spec (departments, categories, 4 user profiles,
technicians, tickets with priorities/SLA, followups with sentiment keywords,
6 months of history + seasonality).

The pipeline (glpi_connector -> ETL -> warehouse -> ML -> API -> Angular) then
pulls this real GLPI data in real time — no more warehouse-side static seeding.

Usage
-----
    # 1. Ensure .env has GLPI_BASE_URL, GLPI_APP_TOKEN, GLPI_USER_TOKEN
    # 2. From GlpiInteligence/:
    python scripts/populate_glpi.py                 # large volume (default)
    python scripts/populate_glpi.py --volume small
    python scripts/populate_glpi.py --dry-run       # log what would be sent
    python scripts/populate_glpi.py --wipe-created  # delete rows created by a
                                                    # previous run (uses state
                                                    # file scripts/.populate_state.json)

Flags
-----
    --volume {small,medium,large}   default: large
    --dry-run                       no writes
    --wipe-created                  delete items previously created by this
                                    script and exit
    --skip-reference                skip entities/categories/groups/users
                                    (useful for a top-up ticket run)

Notes
-----
* Uses only GLPI REST endpoints — no direct DB access — so it respects GLPI's
  business logic (history, notifications if enabled, SLA computation, etc.).
* Idempotent-ish for reference data: entities/categories/groups/users are
  looked up by name; only missing ones are created.
* All IDs of items this script creates are tracked in
  ``scripts/.populate_state.json`` so ``--wipe-created`` can undo them.
* Ticket dates are set via ``date`` (created) and closed tickets get
  ``solvedate`` / ``closedate`` so the ETL's temporal features work.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# ----------------------------------------------------------------------------- log
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(message)s",
)
log = logging.getLogger("populate_glpi")

STATE_FILE = Path(__file__).parent / ".populate_state.json"

# ============================================================================
# Reference data — sourced from the PDF (departments, categories, technicians)
# ============================================================================

# Sites / entities. GLPI has a root entity "Root entity" (id 0); we create
# children under it.
ENTITIES = [
    "Siège Tunis",
    "Usine A - Ksar Hellal",
    "Usine B - Monastir",
    "Dépôt Sousse",
    "R&D",
]

# Department / service = we use GLPI Groups (glpi_groups) because GLPI doesn't
# have a first-class "department" concept in a way the connector reads. The
# warehouse layer already reads glpi_groups as department-ish.
DEPARTMENTS = [
    "Comptabilité",
    "Administration",
    "Production",
    "Logistique",
    "Commercial",
    "Ressources Humaines",
    "R&D",
    "Direction",
    "IT - Support N1",     # for technicians
    "IT - Infrastructure Réseau",
    "IT - Systèmes",
]

# ITIL categories — parent -> children (mirrors the PDF vocabulary).
CATEGORIES: dict[str, list[str]] = {
    "ERP": [
        "Erreur saisie ERP",
        "ERP - Module Comptabilité",
        "ERP - Module Stock",
        "ERP - Performance",
        "ERP - Accès refusé",
    ],
    "Bureautique": [
        "Excel",
        "Word",
        "PowerPoint",
        "Outlook",
        "PDF / Impression",
    ],
    "Sécurité": [
        "Réinitialisation mot de passe",
        "Compte bloqué",
        "Accès dossier partagé",
        "Certificat expiré",
    ],
    "Réseau": [
        "WiFi",
        "Câble / Prise réseau",
        "VPN",
        "Switch / Routeur",
        "Lenteur réseau",
    ],
    "Poste de travail": [
        "PC lent",
        "Écran / Clavier / Souris",
        "Installation logiciel",
        "Mise à jour Windows",
    ],
    "Impression": [
        "Imprimante hors ligne",
        "Bourrage papier",
        "Toner / Consommables",
    ],
    "Messagerie": [
        "Envoi impossible",
        "Réception bloquée",
        "Boîte pleine",
    ],
    "Serveur": [
        "Serveur fichiers",
        "Serveur applicatif",
        "Sauvegarde",
    ],
}

# Technician profiles — first name shown in PDF is "Karim M." on the Infra team.
TECHNICIANS = [
    # (login, first, last, group, is_karim_high_load?)
    ("k.mansouri", "Karim", "Mansouri", "IT - Infrastructure Réseau", True),
    ("s.trabelsi", "Sami", "Trabelsi", "IT - Infrastructure Réseau", False),
    ("y.bensalah", "Youssef", "Ben Salah", "IT - Systèmes", False),
    ("h.gharbi", "Hela", "Gharbi", "IT - Systèmes", False),
    ("m.jelassi", "Mehdi", "Jelassi", "IT - Support N1", False),
    ("r.chaabane", "Rania", "Chaabane", "IT - Support N1", False),
    ("f.bouazizi", "Faten", "Bouazizi", "IT - Support N1", False),
    ("a.hammami", "Ahmed", "Hammami", "IT - Support N1", False),
]

# End-user first/last name pool (used to generate a lot of requesters).
FIRST_NAMES = [
    "Ahmed", "Mohamed", "Ali", "Youssef", "Karim", "Sami", "Mehdi", "Anis",
    "Wassim", "Nizar", "Bilel", "Rami", "Hamza", "Skander", "Aymen",
    "Fatma", "Mariem", "Amira", "Sarra", "Rania", "Hela", "Nadia", "Emna",
    "Yasmine", "Salma", "Ines", "Sonia", "Faten", "Leila", "Aicha",
]
LAST_NAMES = [
    "Ben Ali", "Trabelsi", "Bouazizi", "Gharbi", "Jelassi", "Mansouri",
    "Ben Salah", "Chaabane", "Hammami", "Baccar", "Sassi", "Zouari",
    "Ferchichi", "Khelifi", "Mejri", "Amri", "Riahi", "Nasri", "Kefi",
    "Belhaj", "Ayadi", "Slimani", "Ouali", "Kacem", "Ben Youssef", "Meftah",
]

# --------------------------------------------------------------------- volumes
VOLUME_PRESETS = {
    "small":  {"users": 30,  "tickets": 200,  "followups_per_ticket": 2, "history_days": 60},
    "medium": {"users": 80,  "tickets": 800,  "followups_per_ticket": 2, "history_days": 120},
    "large":  {"users": 150, "tickets": 2500, "followups_per_ticket": 2, "history_days": 180},
}

# GLPI enum values -------------------------------------------------------------
# priorities 1=very low, 2=low, 3=medium, 4=high, 5=very high, 6=major
# status:  1=new, 2=processing(assigned), 3=processing(planned), 4=pending,
#          5=solved, 6=closed
STATUS_NEW, STATUS_ASSIGNED, STATUS_PENDING, STATUS_SOLVED, STATUS_CLOSED = 1, 2, 4, 5, 6

# ============================================================================
# Templated ticket titles + bodies per category (French, with sentiment cues).
# ============================================================================

TICKET_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "Erreur saisie ERP": [
        ("Erreur ERP module comptabilité — écriture bloquée",
         "Je n'arrive plus à valider mes écritures dans le module comptabilité. Message: 'référence invalide'. C'est très frustrant, je suis bloqué depuis ce matin."),
        ("ERP: la saisie facture renvoie une erreur",
         "Erreur récurrente lors de la saisie des factures fournisseurs. Cela fait la 3ème fois cette semaine."),
        ("Impossible de clôturer la période dans l'ERP",
         "La clôture mensuelle échoue avec un timeout. Urgent, deadline demain."),
    ],
    "ERP - Module Comptabilité": [
        ("Erreur module comptabilité — solde incohérent",
         "Le solde affiché ne correspond pas aux écritures. Je pense qu'il y a un bug."),
    ],
    "ERP - Module Stock": [
        ("ERP stock: quantité négative après inventaire",
         "Après import de l'inventaire, plusieurs articles apparaissent en quantité négative."),
    ],
    "ERP - Performance": [
        ("ERP très lent en fin de journée",
         "L'ERP devient inutilisable à partir de 16h. Impossible de travailler correctement."),
    ],
    "ERP - Accès refusé": [
        ("Accès refusé ERP module ventes",
         "Message 'accès refusé' depuis ce matin alors que je l'utilisais hier."),
    ],
    "Excel": [
        ("Excel plante à l'ouverture d'un gros fichier",
         "Le fichier de reporting mensuel plante Excel à chaque ouverture."),
        ("Formule Excel ne fonctionne plus",
         "Ma formule RECHERCHEV renvoie #N/A depuis la mise à jour."),
    ],
    "Word": [
        ("Word: mise en forme perdue à l'enregistrement",
         "Toute ma mise en forme saute quand je sauvegarde en .docx."),
    ],
    "PowerPoint": [
        ("PowerPoint refuse d'ouvrir mes fichiers",
         "Erreur à l'ouverture, PowerPoint m'annonce un fichier corrompu."),
    ],
    "Outlook": [
        ("Outlook ne synchronise plus mes mails",
         "Boîte bloquée, aucun nouveau mail depuis 2h."),
    ],
    "PDF / Impression": [
        ("Impossible de générer un PDF depuis Word",
         "L'export PDF échoue silencieusement."),
    ],
    "Réinitialisation mot de passe": [
        ("Mot de passe oublié — accès session Windows",
         "J'ai oublié mon mot de passe, compte bloqué."),
        ("Mot de passe expiré, je suis bloqué",
         "Impossible de me connecter, mon mot de passe a expiré."),
        ("Reset mot de passe — accès ERP bloqué",
         "Accès ERP refusé, message 'mot de passe expiré'."),
    ],
    "Compte bloqué": [
        ("Compte AD bloqué après plusieurs tentatives",
         "Trop de tentatives, mon compte est bloqué. Merci de débloquer."),
    ],
    "Accès dossier partagé": [
        ("Accès refusé au dossier partagé Comptabilité",
         "Je ne peux plus accéder à \\\\serveur\\Compta depuis ce matin."),
    ],
    "Certificat expiré": [
        ("Certificat expiré sur navigateur",
         "Le portail interne affiche une alerte de certificat expiré."),
    ],
    "WiFi": [
        ("WiFi ne fonctionne plus dans le bâtiment B",
         "Aucune connexion WiFi depuis ce matin, plusieurs collègues concernés."),
        ("Connexion WiFi instable — coupures répétées",
         "Le WiFi coupe toutes les 5 minutes. Impossible de travailler."),
    ],
    "Câble / Prise réseau": [
        ("Prise réseau HS bureau 214",
         "Aucun lien détecté sur la prise. Besoin d'une intervention."),
    ],
    "VPN": [
        ("VPN refuse la connexion depuis chez moi",
         "Le client VPN affiche une erreur d'authentification."),
    ],
    "Switch / Routeur": [
        ("Perte réseau intermittente — suspecte un switch",
         "Perte de connectivité par intermittence, ça semble venir du switch d'étage."),
    ],
    "Lenteur réseau": [
        ("Lenteur réseau généralisée bâtiment B",
         "Tout est extrêmement lent, y compris les partages fichiers."),
    ],
    "PC lent": [
        ("Mon PC est devenu très lent",
         "Depuis 2 semaines mon PC met 10 min à démarrer."),
    ],
    "Écran / Clavier / Souris": [
        ("Écran qui scintille en permanence",
         "L'écran clignote, impossible de travailler dessus."),
    ],
    "Installation logiciel": [
        ("Demande installation logiciel métier",
         "Merci d'installer XYZ sur mon poste, requis par mon nouveau projet."),
    ],
    "Mise à jour Windows": [
        ("Windows Update échoue en boucle",
         "La mise à jour KBxxxx refuse de s'installer et redémarre en boucle."),
    ],
    "Imprimante hors ligne": [
        ("Imprimante étage 2 hors ligne",
         "Imprimante inaccessible depuis tous les postes de l'étage."),
    ],
    "Bourrage papier": [
        ("Bourrage papier imprimante RH",
         "Bourrage impossible à retirer, papier coincé au fond."),
    ],
    "Toner / Consommables": [
        ("Toner à remplacer imprimante compta",
         "Toner en fin de vie, impressions illisibles."),
    ],
    "Envoi impossible": [
        ("Impossible d'envoyer un mail avec pièce jointe",
         "Envoi refusé par le serveur pour pièces > 5 Mo."),
    ],
    "Réception bloquée": [
        ("Aucune réception depuis 3 heures",
         "Aucun mail reçu, mes collègues confirment qu'ils m'en ont envoyé."),
    ],
    "Boîte pleine": [
        ("Boîte mail pleine — quota dépassé",
         "Boîte à 100%, je ne peux plus rien recevoir."),
    ],
    "Serveur fichiers": [
        ("Serveur fichiers inaccessible",
         "Le partage \\\\srv-files ne répond plus."),
    ],
    "Serveur applicatif": [
        ("Application interne indisponible",
         "L'appli plante avec erreur 500 depuis 30 min."),
    ],
    "Sauvegarde": [
        ("Sauvegarde échouée hier soir",
         "Le job de sauvegarde s'est terminé en erreur."),
    ],
}

# Follow-up bodies — sentiment varies (frustration / neutre / satisfaction).
FOLLOWUP_TEMPLATES = {
    "requester_frustration": [
        "Toujours pas résolu, c'est bloquant pour mon travail.",
        "Je relance, urgence absolue !",
        "Ça fait 3 jours, aucune nouvelle.",
        "Merci de prioriser, j'ai des livrables aujourd'hui.",
    ],
    "requester_info": [
        "Précision : le problème apparaît seulement le matin.",
        "Voici le code d'erreur exact : ERR_1042.",
        "Le collègue à côté de moi a le même souci.",
        "Test complémentaire : le redémarrage n'a rien changé.",
    ],
    "requester_satisfaction": [
        "Merci, tout est rentré dans l'ordre !",
        "Résolu, super rapide, merci.",
        "Impeccable, je peux reprendre mon travail.",
    ],
    "technician_diagnostic": [
        "Diagnostic en cours, j'analyse les logs.",
        "Reproduction du problème effectuée, cause identifiée.",
        "Escalade vers l'équipe Infrastructure.",
        "Ticket transféré à l'éditeur pour analyse.",
    ],
    "technician_resolution": [
        "Correctif appliqué, merci de tester et confirmer.",
        "Configuration réseau corrigée, retour à la normale.",
        "Compte débloqué, nouveau mot de passe envoyé par mail.",
        "Poste réimagé, tous les logiciels réinstallés.",
    ],
}

# ============================================================================
# GLPI REST client (writes only) — kept dependency-free of glpi_connector to
# avoid pulling read-side extractors.
# ============================================================================


@dataclass
class Glpi:
    base_url: str
    app_token: str
    user_token: str
    verify_ssl: bool = True
    timeout: float = 30.0
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

    # -- write ops ------------------------------------------------------------
    def create(self, itemtype: str, input_dict: dict[str, Any]) -> int:
        """Create one item, return its id."""
        r = self._s.post(
            f"{self.base_url}/{itemtype}",
            headers=self._h(),
            data=json.dumps({"input": input_dict}),
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"POST {itemtype} {r.status_code}: {r.text[:300]}  payload={input_dict}")
        body = r.json()
        # GLPI returns {"id": N, "message": "..."} for a single create,
        # or [ {"id": N}, ...] for batch. We use single here.
        if isinstance(body, list):
            body = body[0]
        return int(body["id"])

    def create_batch(self, itemtype: str, inputs: list[dict[str, Any]]) -> list[int]:
        if not inputs:
            return []
        r = self._s.post(
            f"{self.base_url}/{itemtype}",
            headers=self._h(),
            data=json.dumps({"input": inputs}),
            timeout=self.timeout * 2,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"POST batch {itemtype} {r.status_code}: {r.text[:300]}")
        body = r.json()
        if isinstance(body, dict):
            body = [body]
        return [int(x["id"]) for x in body]

    def delete(self, itemtype: str, item_id: int, *, purge: bool = True) -> None:
        params = {"force_purge": "true"} if purge else None
        r = self._s.delete(
            f"{self.base_url}/{itemtype}/{item_id}",
            headers=self._h(),
            params=params,
            timeout=self.timeout,
        )
        # 200 or 204 = ok; 404 = already gone
        if r.status_code not in (200, 204, 404):
            log.warning("DELETE %s/%s -> %d %s", itemtype, item_id, r.status_code, r.text[:200])

    # -- read helpers ---------------------------------------------------------
    def find_by_name(self, itemtype: str, name: str) -> int | None:
        """Look up an existing item by name using /search.

        For Entity, search-option 1 returns *completename* (e.g. "Root > X"),
        so `equals X` misses. Try `equals` then `contains` as fallback.
        """
        for searchtype in ("equals", "contains"):
            params = {
                "criteria[0][field]": 1,
                "criteria[0][searchtype]": searchtype,
                "criteria[0][value]": name,
                "forcedisplay[0]": 2,
                "range": "0-0",
            }
            r = self._s.get(
                f"{self.base_url}/search/{itemtype}",
                headers=self._h(),
                params=params,
                timeout=self.timeout,
            )
            if r.status_code in (404, 401) or not r.content:
                continue
            try:
                payload = r.json()
            except ValueError:
                continue
            data = payload.get("data") if isinstance(payload, dict) else None
            if not data:
                continue
            row = data[0]
            val = row.get("2", row.get(2))
            try:
                if val is not None:
                    return int(val)
            except (TypeError, ValueError):
                pass
        return None


# ============================================================================
# State (which items we created — for --wipe-created)
# ============================================================================

def load_state() -> dict[str, list[int]]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict[str, list[int]]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def track(state: dict, itemtype: str, item_id: int) -> None:
    state.setdefault(itemtype, []).append(item_id)


# ============================================================================
# Populators
# ============================================================================

def ensure_entities(g: Glpi, state: dict, dry: bool) -> dict[str, int]:
    """Create entities under root (id 0). Return {name: id}."""
    out: dict[str, int] = {}
    for name in ENTITIES:
        existing = None if dry else g.find_by_name("Entity", name)
        if existing:
            log.info("Entity exists: %s (id=%s)", name, existing)
            out[name] = existing
            continue
        if dry:
            log.info("[dry] would create Entity %s", name)
            out[name] = -1
            continue
        eid = g.create("Entity", {"name": name, "entities_id": 0, "comment": "Sartex demo — populate_glpi.py"})
        track(state, "Entity", eid)
        out[name] = eid
        log.info("Created Entity %s (id=%d)", name, eid)
    return out


def ensure_groups(g: Glpi, state: dict, dry: bool) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in DEPARTMENTS:
        existing = None if dry else g.find_by_name("Group", name)
        if existing:
            log.info("Group exists: %s (id=%s)", name, existing)
            out[name] = existing
            continue
        if dry:
            out[name] = -1
            continue
        # is_assign=1 -> can be assigned to tickets (needed for IT groups)
        is_assign = 1 if name.startswith("IT -") else 0
        gid = g.create("Group", {
            "name": name,
            "entities_id": 0,
            "is_recursive": 1,
            "is_assign": is_assign,
            "is_requester": 1,
            "comment": "Sartex demo",
        })
        track(state, "Group", gid)
        out[name] = gid
        log.info("Created Group %s (id=%d)", name, gid)
    return out


def ensure_categories(g: Glpi, state: dict, dry: bool) -> dict[str, int]:
    """Create ITILCategory tree parent -> children. Returns {full_name: id}
    where leaves are keyed by their child name."""
    out: dict[str, int] = {}
    for parent, children in CATEGORIES.items():
        pid = None if dry else g.find_by_name("ITILCategory", parent)
        if not pid and not dry:
            pid = g.create("ITILCategory", {
                "name": parent, "entities_id": 0, "is_recursive": 1,
                "itilcategories_id": 0, "is_incident": 1, "is_request": 1,
            })
            track(state, "ITILCategory", pid)
            log.info("Created Category %s (id=%d)", parent, pid)
        out[parent] = pid or -1
        for child in children:
            cid = None if dry else g.find_by_name("ITILCategory", child)
            if not cid and not dry:
                cid = g.create("ITILCategory", {
                    "name": child, "entities_id": 0, "is_recursive": 1,
                    "itilcategories_id": pid, "is_incident": 1, "is_request": 1,
                })
                track(state, "ITILCategory", cid)
                log.info("Created Category %s > %s (id=%d)", parent, child, cid)
            out[child] = cid or -1
    return out


def ensure_users(g: Glpi, state: dict, dry: bool, n_end_users: int,
                 groups: dict[str, int]) -> tuple[list[dict], list[dict]]:
    """Create technicians + end-user pool. Returns (technicians, end_users)."""
    # ---- technicians
    techs = []
    for login, first, last, group_name, is_karim in TECHNICIANS:
        existing = None if dry else g.find_by_name("User", login)
        if existing:
            uid = existing
        elif dry:
            uid = -1
        else:
            uid = g.create("User", {
                "name": login, "firstname": first, "realname": last,
                "password": "SartexDemo!2026", "password2": "SartexDemo!2026",
                "is_active": 1, "entities_id": 0,
                # profile 6 = "super-admin" doesn't fit; we don't set profile —
                # GLPI assigns default. Group assignment is done via Group_User
                # separately below.
                "comment": "Sartex demo technicien",
            })
            track(state, "User", uid)
            log.info("Created technician %s (id=%d)", login, uid)
        techs.append({"id": uid, "login": login, "group": group_name, "is_karim": is_karim})

    # ---- end users
    end_users = []
    dept_names = [d for d in DEPARTMENTS if not d.startswith("IT -")]
    used_logins: set[str] = set()
    idx = 0
    while len(end_users) < n_end_users:
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        login = f"{first[0].lower()}.{last.lower().replace(' ', '')}{idx if idx else ''}"
        idx += 1
        if login in used_logins:
            continue
        used_logins.add(login)
        dept = random.choice(dept_names)
        if dry:
            uid = -1
        else:
            existing = g.find_by_name("User", login)
            if existing:
                uid = existing
            else:
                uid = g.create("User", {
                    "name": login, "firstname": first, "realname": last,
                    "password": "SartexDemo!2026", "password2": "SartexDemo!2026",
                    "is_active": 1, "entities_id": 0,
                    "comment": f"Sartex demo end user — {dept}",
                })
                track(state, "User", uid)
        end_users.append({"id": uid, "login": login, "first": first, "last": last, "dept": dept})

    # ---- group memberships (Group_User)
    if not dry:
        # techs -> their group
        for t in techs:
            gid = groups.get(t["group"])
            if gid and gid > 0:
                try:
                    guid = g.create("Group_User", {"users_id": t["id"], "groups_id": gid})
                    track(state, "Group_User", guid)
                except Exception as e:
                    log.debug("Group_User (tech) skip: %s", e)
        # end users -> department group
        for u in end_users:
            gid = groups.get(u["dept"])
            if gid and gid > 0:
                try:
                    guid = g.create("Group_User", {"users_id": u["id"], "groups_id": gid})
                    track(state, "Group_User", guid)
                except Exception as e:
                    log.debug("Group_User (user) skip: %s", e)

    log.info("Techs: %d, end-users: %d", len(techs), len(end_users))
    return techs, end_users


# ---------------------------------------------------------------- ticket gen

def _pick_profile() -> str:
    """Weighted user profile choice (matches PDF distribution roughly)."""
    return random.choices(
        ["autonome", "standard", "dependant", "critique"],
        weights=[0.40, 0.35, 0.18, 0.07],
        k=1,
    )[0]


def _tickets_per_month_for_profile(profile: str) -> int:
    return {"autonome": 1, "standard": 3, "dependant": 7, "critique": 12}[profile]


def _priority_for_profile(profile: str) -> int:
    if profile == "critique":
        return random.choices([2, 3, 4, 5], weights=[0.1, 0.3, 0.4, 0.2])[0]
    if profile == "dependant":
        return random.choices([2, 3, 4], weights=[0.3, 0.5, 0.2])[0]
    return random.choices([1, 2, 3, 4], weights=[0.15, 0.45, 0.30, 0.10])[0]


def _dominant_category_for_dept(dept: str) -> str:
    """Bias the dominant category by department (per PDF examples)."""
    mapping = {
        "Comptabilité": ["Erreur saisie ERP", "ERP - Module Comptabilité",
                         "Excel", "Réinitialisation mot de passe"],
        "Administration": ["Excel", "Word", "Outlook", "PDF / Impression",
                           "Réinitialisation mot de passe"],
        "Production": ["Réseau", "Lenteur réseau", "Imprimante hors ligne",
                       "ERP - Module Stock"],
        "Logistique": ["ERP - Module Stock", "Imprimante hors ligne", "WiFi"],
        "Commercial": ["Outlook", "VPN", "PowerPoint", "PDF / Impression"],
        "Ressources Humaines": ["Compte bloqué", "Réinitialisation mot de passe",
                                "PDF / Impression", "Excel"],
        "R&D": ["Installation logiciel", "PC lent", "VPN"],
        "Direction": ["Outlook", "PowerPoint", "VPN"],
    }
    return random.choice(mapping.get(dept, list({leaf for lst in CATEGORIES.values() for leaf in lst})))


def _pick_category(dept: str, all_leaves: list[str]) -> str:
    # 60% dominant / 40% random other → drives the "taux de récurrence" KPI.
    if random.random() < 0.60:
        return _dominant_category_for_dept(dept)
    return random.choice(all_leaves)


def _seasonality_multiplier(day: datetime) -> float:
    """Monday-morning spike (per PDF signal-faible C.3) and end-of-month spike
    (per PDF D.2 example — accounting closes)."""
    m = 1.0
    if day.weekday() == 0 and day.hour < 12:
        m *= 1.8
    if day.day >= 27:
        m *= 1.5
    # weekends much quieter
    if day.weekday() >= 5:
        m *= 0.3
    # off-hours quieter
    if not (7 <= day.hour <= 18):
        m *= 0.4
    return m


def _random_datetime(days_ago_max: int) -> datetime:
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    while True:
        delta_hours = random.randint(0, days_ago_max * 24)
        t = now - timedelta(hours=delta_hours)
        # accept/reject sampling for seasonality
        if random.random() < _seasonality_multiplier(t) / 3.0:
            return t


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _pick_tech(techs: list[dict], category: str) -> dict:
    """Route to a tech: network→Karim's team, sec/passwords→N1, servers→Systèmes."""
    def in_group(t, g): return t["group"] == g
    net = [t for t in techs if in_group(t, "IT - Infrastructure Réseau")]
    n1  = [t for t in techs if in_group(t, "IT - Support N1")]
    sys_ = [t for t in techs if in_group(t, "IT - Systèmes")]
    cat_low = category.lower()
    if any(k in cat_low for k in ["wifi", "réseau", "vpn", "switch", "câble"]):
        pool = net
        # bias to Karim (per PDF: he's the overloaded one)
        if random.random() < 0.55:
            karims = [t for t in pool if t["is_karim"]]
            if karims:
                return karims[0]
        return random.choice(pool)
    if any(k in cat_low for k in ["mot de passe", "compte", "certificat", "accès"]):
        return random.choice(n1 + [t for t in sys_ if not t["is_karim"]])
    if any(k in cat_low for k in ["serveur", "sauvegarde"]):
        return random.choice(sys_)
    # default: N1
    return random.choice(n1)


def create_tickets(g: Glpi, state: dict, dry: bool,
                   entities: dict[str, int],
                   categories: dict[str, int],
                   groups: dict[str, int],
                   techs: list[dict], end_users: list[dict],
                   target_total: int, followups_per_ticket: int,
                   history_days: int) -> None:

    all_leaves = [leaf for lst in CATEGORIES.values() for leaf in lst]
    # per-user profile so the same user has a coherent behavior
    profiles = {u["login"]: _pick_profile() for u in end_users}

    # Tickets go in whichever entities the API user can write to. If the API
    # user's profile is not recursive on child entities, GLPI returns
    # "ERROR_GLPI_ADD ... permission". Setting GLPI_TICKET_ENTITY_ID=0 forces
    # root entity for every ticket (safest default when perms are unclear).
    forced = os.getenv("GLPI_TICKET_ENTITY_ID")
    if forced is not None:
        ent_ids = [int(forced)]
        log.info("Forcing ticket entities_id=%s (GLPI_TICKET_ENTITY_ID)", forced)
    else:
        ent_ids = [v for v in entities.values() if v > 0] or [0]

    created = 0
    while created < target_total:
        user = random.choice(end_users)
        profile = profiles[user["login"]]
        # scale by profile — heavier users generate more tickets in the loop
        weight = _tickets_per_month_for_profile(profile)
        if random.random() > weight / 12.0:
            continue

        category = _pick_category(user["dept"], all_leaves)
        cat_id = categories.get(category)
        tmpl = random.choice(TICKET_TEMPLATES.get(category) or [
            (f"Demande {category}", f"Bonjour, j'ai un souci lié à {category}. Merci d'intervenir.")
        ])
        title, body = tmpl

        created_at = _random_datetime(history_days)
        prio = _priority_for_profile(profile)
        tech = _pick_tech(techs, category)

        # status trajectory
        r = random.random()
        if r < 0.55:
            status = STATUS_CLOSED
            solved_at = created_at + timedelta(hours=random.randint(1, 72))
            closed_at = solved_at + timedelta(hours=random.randint(1, 48))
        elif r < 0.75:
            status = STATUS_SOLVED
            solved_at = created_at + timedelta(hours=random.randint(1, 96))
            closed_at = None
        elif r < 0.90:
            status = STATUS_ASSIGNED
            solved_at = closed_at = None
        else:
            status = STATUS_NEW
            solved_at = closed_at = None

        ent_id = random.choice(ent_ids)
        ticket_input: dict[str, Any] = {
            "name": title,
            "content": body,
            "entities_id": ent_id,
            "status": status,
            "priority": prio,
            "urgency": prio,
            "impact": max(1, min(5, prio - 1 + random.choice([0, 0, 1]))),
            "type": 1,  # 1 = incident, 2 = request
            "itilcategories_id": cat_id if cat_id and cat_id > 0 else 0,
            "_users_id_requester": user["id"] if user["id"] > 0 else 0,
            "_users_id_assign": tech["id"] if tech["id"] > 0 else 0,
            "date": _fmt(created_at),
            "date_creation": _fmt(created_at),
            # SLA deadline = created + (24h for high prio, 72h low prio)
            "time_to_resolve": _fmt(created_at + timedelta(hours=[72, 48, 24, 8, 4][min(prio-1, 4)])),
        }
        if solved_at:
            ticket_input["solvedate"] = _fmt(solved_at)
        if closed_at:
            ticket_input["closedate"] = _fmt(closed_at)

        if dry:
            log.info("[dry] ticket: %s (prio=%d status=%d cat=%s tech=%s user=%s)",
                     title, prio, status, category, tech["login"], user["login"])
            tid = -1
        else:
            try:
                tid = g.create("Ticket", ticket_input)
                track(state, "Ticket", tid)
            except Exception as e:
                log.warning("Ticket create failed (%s): %s", title, e)
                continue

        # ------- followups
        n_fu = max(1, int(random.gauss(followups_per_ticket, 1)))
        n_fu = min(n_fu, 6)
        last_ts = created_at
        for i in range(n_fu):
            last_ts = last_ts + timedelta(hours=random.randint(1, 24))
            if i == n_fu - 1 and status in (STATUS_SOLVED, STATUS_CLOSED):
                who = tech
                content = random.choice(FOLLOWUP_TEMPLATES["technician_resolution"])
            elif random.random() < 0.5:
                who = tech
                content = random.choice(FOLLOWUP_TEMPLATES["technician_diagnostic"])
            else:
                who = user
                if profile in ("dependant", "critique") and random.random() < 0.6:
                    content = random.choice(FOLLOWUP_TEMPLATES["requester_frustration"])
                else:
                    content = random.choice(FOLLOWUP_TEMPLATES["requester_info"])
            if dry:
                continue
            try:
                fid = g.create("ITILFollowup", {
                    "itemtype": "Ticket",
                    "items_id": tid,
                    "content": content,
                    "users_id": who["id"],
                    "date": _fmt(last_ts),
                    "date_creation": _fmt(last_ts),
                })
                track(state, "ITILFollowup", fid)
            except Exception as e:
                log.debug("Followup create failed: %s", e)

        created += 1
        if created % 50 == 0:
            log.info("Progress: %d / %d tickets", created, target_total)
            save_state(state)  # periodic checkpoint

    log.info("Done. Tickets created: %d", created)


# ============================================================================
# Wipe
# ============================================================================

# Delete order: dependents first
WIPE_ORDER = [
    "ITILFollowup", "Ticket",
    "Group_User", "User",
    "ITILCategory", "Group", "Entity",
]


def wipe(g: Glpi, state: dict) -> None:
    for itemtype in WIPE_ORDER:
        ids = state.get(itemtype, [])
        if not ids:
            continue
        log.info("Deleting %d %s(s)...", len(ids), itemtype)
        for i, item_id in enumerate(ids, 1):
            g.delete(itemtype, item_id, purge=True)
            if i % 100 == 0:
                log.info("  %d/%d", i, len(ids))
        state[itemtype] = []
    save_state(state)


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--volume", choices=list(VOLUME_PRESETS), default="large")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wipe-created", action="store_true")
    ap.add_argument("--skip-reference", action="store_true",
                    help="Skip creating entities/categories/groups/users; expect them to exist. "
                         "Only creates tickets + followups.")
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

    state = load_state()

    with Glpi(base_url=base_url, app_token=app_token, user_token=user_token,
              verify_ssl=verify_ssl) as g:

        if args.wipe_created:
            wipe(g, state)
            log.info("Wipe complete.")
            return 0

        vol = VOLUME_PRESETS[args.volume]
        log.info("Volume '%s' -> users=%d, tickets=%d, history=%dd",
                 args.volume, vol["users"], vol["tickets"], vol["history_days"])

        if args.skip_reference:
            entities = {n: g.find_by_name("Entity", n) or 0 for n in ENTITIES}
            groups = {n: g.find_by_name("Group", n) or 0 for n in DEPARTMENTS}
            categories = {}
            for parent, children in CATEGORIES.items():
                categories[parent] = g.find_by_name("ITILCategory", parent) or 0
                for c in children:
                    categories[c] = g.find_by_name("ITILCategory", c) or 0
            # end users: fetch the ones we already tracked
            end_users = []
            techs = [{"id": g.find_by_name("User", t[0]) or 0, "login": t[0],
                      "group": t[3], "is_karim": t[4]} for t in TECHNICIANS]
            log.warning("--skip-reference: rebuilding end_users list from state is not supported; "
                        "cannot assign tickets to users. Aborting.")
            return 2

        entities = ensure_entities(g, state, args.dry_run)
        save_state(state)
        groups = ensure_groups(g, state, args.dry_run)
        save_state(state)
        categories = ensure_categories(g, state, args.dry_run)
        save_state(state)
        techs, end_users = ensure_users(g, state, args.dry_run, vol["users"], groups)
        save_state(state)

        create_tickets(
            g, state, args.dry_run,
            entities=entities, categories=categories, groups=groups,
            techs=techs, end_users=end_users,
            target_total=vol["tickets"],
            followups_per_ticket=vol["followups_per_ticket"],
            history_days=vol["history_days"],
        )
        save_state(state)

    log.info("Populate finished. State file: %s", STATE_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
