"""Orchestration : enregistrement d'un contrat, alertes, calendriers, mise à jour globale."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from . import config, db, rangement, suivi
from .alertes import Alerte, calculer_alertes, fusionner_alertes
from .calendrier import IcsCalendrier, OutlookCom, generer_ics, ouvrir_fichier
from .outils import cle_contrat
from .schema import ContratJSON


@dataclass
class ResultatSync:
    bilan: db.BilanAlertes
    messages: list[str] = field(default_factory=list)
    fichiers_ics: list[Path] = field(default_factory=list)
    outlook_ok: bool = False


@dataclass
class ResultatEnregistrement:
    version: int
    numero_avenant: int | None
    chemin_fichier: Path | None
    sync: ResultatSync
    avertissements: list[str] = field(default_factory=list)


def dossier_calendrier(racine: Path) -> Path:
    return Path(racine) / config.NOM_DOSSIER_CALENDRIER


def toutes_les_alertes(conn) -> list[Alerte]:
    return [a for sit in suivi.situations(conn) for a in calculer_alertes(sit)]


def synchroniser_calendriers(conn, racine: Path, outlook_actif: bool, aujourdhui: date) -> ResultatSync:
    """Recalcule toutes les alertes, met la base à jour, régénère les .ics (+ Outlook si actif)."""
    alertes = toutes_les_alertes(conn)  # une par enregistrement
    bilan = db.appliquer_alertes(conn, alertes)
    agenda = fusionner_alertes(alertes)  # un seul événement par document d'origine, type et date
    disparus = db.aligner_evenements(conn, {a.uid for a in agenda})
    res = ResultatSync(bilan)

    if outlook_actif:
        outlook = OutlookCom()
        if outlook.disponible():
            try:
                outlook.retirer(disparus)
                r = outlook.synchroniser(agenda, db.entry_ids(conn), aujourdhui)
                db.memoriser_entry_ids(conn, r.entry_ids)
                res.messages.append(r.message)
                res.outlook_ok = True
            except Exception as exc:  # repli silencieux : les .ics sont de toute façon générés
                res.messages.append(f"Outlook n'a pas répondu ({exc}) : fichiers .ics utilisés.")
        else:
            res.messages.append("Outlook classique non détecté : fichiers .ics utilisés.")

    ics = IcsCalendrier(dossier_calendrier(racine)).synchroniser(agenda, {}, aujourdhui)
    res.fichiers_ics = ics.fichiers
    res.messages.append(ics.message)
    return res


def mettre_a_jour(conn, racine: Path, outlook_actif: bool = False, aujourdhui: date | None = None) -> str:
    aujourdhui = aujourdhui or date.today()
    sync = synchroniser_calendriers(conn, racine, outlook_actif, aujourdhui)
    sits = suivi.situations(conn)
    return (f"Mise à jour terminée : {len(sits)} contrat(s), {db.nombre_alertes(conn)} alerte(s). "
            + " ".join(sync.messages))


def _fichier_a_ouvrir(contrat: ContratJSON, racine: Path, sync: ResultatSync,
                      origine: str | None) -> Path | None:
    ics = IcsCalendrier(dossier_calendrier(racine))
    groupe = (f"{rangement.normaliser(contrat.client)}_MultiSites_{origine[:6]}" if origine
              else rangement.nom_base(contrat.client, contrat.site, contrat.activite))
    propre = ics.chemin_contrat(groupe)
    return propre if propre in sync.fichiers_ics else None


def enregistrer_contrat(
    conn, racine: Path, contrat: ContratJSON, fichier: tuple[str, bytes] | None,
    json_brut: str | None, outlook_actif: bool = False, aujourdhui: date | None = None,
    ouvrir: Callable[[Path], bool] | None = ouvrir_fichier,
) -> ResultatEnregistrement:
    """Contrat à un seul site : base, rangement du fichier, alertes, ouverture du .ics."""
    return enregistrer_lignes(conn, racine, [contrat], fichier, json_brut, outlook_actif,
                              aujourdhui, ouvrir, multi_site=False)[0]


def enregistrer_multisite(
    conn, racine: Path, contrats: list[ContratJSON], fichier: tuple[str, bytes] | None,
    json_brut: str | None, outlook_actif: bool = False, aujourdhui: date | None = None,
    ouvrir: Callable[[Path], bool] | None = ouvrir_fichier,
) -> list[ResultatEnregistrement]:
    """Contrat scindé : un enregistrement par site + activité, tous liés au même document d'origine."""
    if len(contrats) < 2:
        raise ValueError("Un contrat multi-site doit être scindé en au moins 2 lignes.")
    return enregistrer_lignes(conn, racine, contrats, fichier, json_brut, outlook_actif,
                              aujourdhui, ouvrir, multi_site=True)


def enregistrer_lignes(conn, racine, contrats, fichier, json_brut, outlook_actif, aujourdhui, ouvrir,
                       multi_site: bool) -> list[ResultatEnregistrement]:
    """Tout ou rien : si une ligne échoue, la base est annulée et les fichiers copiés sont retirés."""
    aujourdhui = aujourdhui or date.today()
    origine = uuid.uuid4().hex if multi_site else None
    fichiers_crees: list[Path] = []
    infos = []
    try:
        for c in contrats:
            if not (c.client and c.site and c.activite and c.type_document):
                raise ValueError("Client, site, activité et type de document sont obligatoires.")
            cle = cle_contrat(c.client, c.site, c.activite)
            avertissements = []
            if c.type_document == "avenant":
                if c.numero_avenant is None:
                    c = c.model_copy(update={"numero_avenant": db.prochain_numero_avenant(conn, cle)})
                if not any(l["cle"] == cle and l["type_document"] == "contrat"
                           for l in db.lignes_courantes(conn)):
                    avertissements.append("Aucun contrat de base n'est enregistré pour ce client/site/"
                                          "activité : l'avenant est conservé seul.")
            chemin = None
            if fichier:  # le même document est copié dans le dossier de chaque site
                chemin = rangement.ranger_fichier(
                    racine, c.client, c.site, c.activite, c.type_document,
                    c.numero_avenant, fichier[0], fichier[1])
                fichiers_crees.append(chemin)
            info = db.inserer_version(
                conn, c, str(chemin) if chemin else None, json_brut,
                groupe_origine=origine, fichier_origine=fichier[0] if fichier else None,
                autocommit=False)
            infos.append((c, info, chemin, avertissements))
        conn.commit()
    except Exception:
        conn.rollback()
        for f in fichiers_crees:
            f.unlink(missing_ok=True)
        raise

    sync = synchroniser_calendriers(conn, racine, outlook_actif, aujourdhui)
    if ouvrir and not sync.outlook_ok:
        cible = _fichier_a_ouvrir(contrats[0], racine, sync, origine)
        if cible:
            ouvrir(cible)
    return [ResultatEnregistrement(i["version"], i["numero_avenant"], ch, sync, av)
            for _, i, ch, av in infos]


def alertes_depuis_contrat(contrat: ContratJSON, nom_contrat: str | None = None) -> list[Alerte]:
    """Alertes d'un contrat pas encore enregistré (aperçu et export agenda immédiat)."""
    plat = contrat.a_plat()
    plat["client"] = contrat.client or nom_contrat or "Contrat"
    plat["site"] = contrat.site or ""
    plat["activite"] = contrat.activite or ""
    plat["devise"] = plat.get("devise") or "EUR"
    plat["cle"] = cle_contrat(plat["client"], plat["site"], plat["activite"])
    plat["groupe_origine"] = None
    return calculer_alertes(plat)


def ics_depuis_contrat(contrat: ContratJSON, aujourdhui: date | None = None) -> tuple[bytes, list[Alerte]]:
    """Fichier .ics des alertes à venir d'un contrat, sans l'enregistrer (importable dans Outlook)."""
    aujourdhui = aujourdhui or date.today()
    alertes = [a for a in alertes_depuis_contrat(contrat) if a.date >= aujourdhui]
    return generer_ics(alertes).encode("utf-8"), alertes
