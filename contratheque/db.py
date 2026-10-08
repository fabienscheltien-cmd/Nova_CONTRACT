"""Base SQLite : contrats versionnés, alertes (UID -> EntryID Outlook), jalons traités."""
from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .alertes import Alerte
from .outils import cle_contrat
from .schema import ContratJSON

COLONNES = (
    "client", "site", "activite", "type_document", "numero_avenant", "contrat_parent", "montant_ht",
    "periodicite", "devise", "date_effet", "date_echeance", "duree_mois", "reconduction_tacite",
    "duree_reconduction_mois", "preavis_denonciation_jours", "date_limite_denonciation",
    "indice", "formule", "date_revision", "indice_reference",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS contrat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cle TEXT NOT NULL,
    client TEXT NOT NULL, site TEXT NOT NULL, activite TEXT NOT NULL,
    type_document TEXT NOT NULL,
    numero_avenant INTEGER,
    version INTEGER NOT NULL,
    courant INTEGER NOT NULL DEFAULT 1,
    contrat_parent TEXT,
    montant_ht REAL, periodicite TEXT, devise TEXT,
    date_effet TEXT, date_echeance TEXT, duree_mois INTEGER,
    reconduction_tacite INTEGER, duree_reconduction_mois INTEGER,
    preavis_denonciation_jours INTEGER, date_limite_denonciation TEXT,
    indice TEXT, formule TEXT, date_revision TEXT, indice_reference TEXT,
    preuves TEXT, points_a_verifier TEXT, json_brut TEXT,
    chemin_fichier TEXT,
    groupe_origine TEXT,
    fichier_origine TEXT,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contrat_cle ON contrat(cle);
CREATE TABLE IF NOT EXISTS alerte (
    uid TEXT PRIMARY KEY,
    cle TEXT NOT NULL,
    type TEXT NOT NULL,
    date_alerte TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evenement (
    uid TEXT PRIMARY KEY,
    outlook_entry_id TEXT
);
CREATE TABLE IF NOT EXISTS jalon_traite (
    cle TEXT NOT NULL, type TEXT NOT NULL, date_jalon TEXT NOT NULL,
    PRIMARY KEY (cle, type, date_jalon)
);
"""


def connecter(chemin: Path) -> sqlite3.Connection:
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(chemin))
    conn.row_factory = sqlite3.Row
    return conn


def initialiser(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def sauvegarder_base(chemin_db: Path, dossier: Path, garder: int = 5,
                     maintenant: datetime | None = None) -> Path | None:
    """Copie datée de la base ; on ne conserve que les `garder` plus récentes."""
    chemin_db = Path(chemin_db)
    if not chemin_db.exists():
        return None
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    maintenant = maintenant or datetime.now()
    cible = dossier / f"contratheque_{maintenant:%Y%m%d_%H%M%S}.db"
    source = sqlite3.connect(str(chemin_db))
    dest = sqlite3.connect(str(cible))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    for ancienne in sorted(dossier.glob("contratheque_*.db"), reverse=True)[garder:]:
        ancienne.unlink()
    return cible


# --------------------------------------------------------------------------- contrats

def _ligne(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d["reconduction_tacite"] is not None:
        d["reconduction_tacite"] = bool(d["reconduction_tacite"])
    d["preuves"] = json.loads(d["preuves"]) if d.get("preuves") else {}
    d["points_a_verifier"] = json.loads(d["points_a_verifier"]) if d.get("points_a_verifier") else []
    return d


def prochain_numero_avenant(conn: sqlite3.Connection, cle: str) -> int:
    r = conn.execute(
        "SELECT MAX(numero_avenant) FROM contrat WHERE cle=? AND type_document='avenant'", (cle,)
    ).fetchone()
    return (r[0] or 0) + 1


def inserer_version(conn: sqlite3.Connection, c: ContratJSON, chemin_fichier: str | None,
                    json_brut: str | None, maintenant: datetime | None = None,
                    groupe_origine: str | None = None, fichier_origine: str | None = None,
                    autocommit: bool = True) -> dict:
    """Ajoute une version ; la précédente du même document reste en base (courant=0).

    `groupe_origine` relie les lignes issues d'un même document multi-site.
    `autocommit=False` laisse l'appelant valider (ou annuler) un lot d'insertions.
    """
    plat = c.a_plat()
    cle = cle_contrat(plat["client"], plat["site"], plat["activite"])
    type_doc = plat["type_document"]
    numero = plat["numero_avenant"] if type_doc == "avenant" else None
    if type_doc == "avenant" and numero is None:
        numero = prochain_numero_avenant(conn, cle)
    plat["numero_avenant"] = numero
    maintenant = maintenant or datetime.now()
    with (conn if autocommit else nullcontext()):
        r = conn.execute(
            "SELECT MAX(version) FROM contrat WHERE cle=? AND type_document=? "
            "AND COALESCE(numero_avenant,0)=COALESCE(?,0)", (cle, type_doc, numero)).fetchone()
        version = (r[0] or 0) + 1
        conn.execute(
            "UPDATE contrat SET courant=0 WHERE cle=? AND type_document=? "
            "AND COALESCE(numero_avenant,0)=COALESCE(?,0)", (cle, type_doc, numero))
        valeurs = [plat[col] for col in COLONNES]
        cur = conn.execute(
            f"INSERT INTO contrat (cle, version, courant, {', '.join(COLONNES)}, preuves, "
            "points_a_verifier, json_brut, chemin_fichier, groupe_origine, fichier_origine, cree_le) "
            f"VALUES (?, ?, 1, {', '.join('?' for _ in COLONNES)}, ?, ?, ?, ?, ?, ?, ?)",
            [cle, version, *valeurs,
             json.dumps(c.preuves, ensure_ascii=False), json.dumps(c.points_a_verifier, ensure_ascii=False),
             json_brut, chemin_fichier, groupe_origine, fichier_origine,
             maintenant.isoformat(timespec="seconds")])
    return {"id": cur.lastrowid, "cle": cle, "version": version, "numero_avenant": numero}


def lignes_courantes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM contrat WHERE courant=1 ORDER BY cle, "
        "CASE type_document WHEN 'contrat' THEN 0 ELSE 1 END, COALESCE(numero_avenant,0), id").fetchall()
    return [_ligne(r) for r in rows]


def historique(conn: sqlite3.Connection, cle: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM contrat WHERE cle=? ORDER BY CASE type_document WHEN 'contrat' THEN 0 ELSE 1 END, "
        "COALESCE(numero_avenant,0), version", (cle,)).fetchall()
    return [_ligne(r) for r in rows]


# --------------------------------------------------------------------------- alertes

@dataclass
class BilanAlertes:
    nouvelles: int = 0
    modifiees: int = 0
    retirees: int = 0


def appliquer_alertes(conn: sqlite3.Connection, alertes: list[Alerte]) -> BilanAlertes:
    """Aligne la table sur les alertes calculées (une par enregistrement) : upsert par UID."""
    bilan = BilanAlertes()
    connues = {r["uid"]: r for r in conn.execute("SELECT * FROM alerte")}
    with conn:
        for a in alertes:
            iso = a.date.isoformat()
            ancienne = connues.get(a.uid)
            if ancienne is None:
                bilan.nouvelles += 1
                conn.execute("INSERT INTO alerte (uid, cle, type, date_alerte) VALUES (?,?,?,?)",
                             (a.uid, a.cle, a.type, iso))
            elif ancienne["date_alerte"] != iso:
                bilan.modifiees += 1
                conn.execute("UPDATE alerte SET date_alerte=? WHERE uid=?", (iso, a.uid))
        courantes = {a.uid for a in alertes}
        for uid in connues:
            if uid not in courantes:
                bilan.retirees += 1
                conn.execute("DELETE FROM alerte WHERE uid=?", (uid,))
    return bilan


def aligner_evenements(conn: sqlite3.Connection, uids: set[str]) -> list[str]:
    """Événements d'agenda (regroupés) : ajoute les nouveaux, retire les disparus.

    Renvoie les EntryID Outlook des événements disparus, à supprimer côté Outlook.
    """
    connus = {r["uid"]: r["outlook_entry_id"] for r in conn.execute("SELECT * FROM evenement")}
    disparus = []
    with conn:
        for uid in uids - connus.keys():
            conn.execute("INSERT INTO evenement (uid) VALUES (?)", (uid,))
        for uid, eid in connus.items():
            if uid not in uids:
                if eid:
                    disparus.append(eid)
                conn.execute("DELETE FROM evenement WHERE uid=?", (uid,))
    return disparus


def entry_ids(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["uid"]: r["outlook_entry_id"]
            for r in conn.execute("SELECT uid, outlook_entry_id FROM evenement "
                                  "WHERE outlook_entry_id IS NOT NULL")}


def memoriser_entry_ids(conn: sqlite3.Connection, ids: dict[str, str]) -> None:
    with conn:
        for uid, eid in ids.items():
            conn.execute("UPDATE evenement SET outlook_entry_id=? WHERE uid=?", (eid, uid))


def nombre_alertes(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM alerte").fetchone()[0]


# --------------------------------------------------------------------------- jalons traités

def marquer_traite(conn: sqlite3.Connection, cle: str, type_jalon: str, date_jalon: str) -> None:
    with conn:
        conn.execute("INSERT OR IGNORE INTO jalon_traite VALUES (?,?,?)", (cle, type_jalon, date_jalon))


def jalons_traites(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    return {(r["cle"], r["type"], r["date_jalon"]) for r in conn.execute("SELECT * FROM jalon_traite")}
