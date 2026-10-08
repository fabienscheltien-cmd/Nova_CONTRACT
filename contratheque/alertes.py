"""Calcul des alertes d'un contrat (dates + identifiants stables) et regroupement pour l'agenda."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta

from . import rangement
from .outils import ajouter_mois, formater_date, formater_montant, lire_date


# Thèmes et délais des rappels : « Nom du contrat – Thème (délai) ».
THEME_FIN = "Fin de contrat"
THEME_REVISION = "Revalorisation"
THEME_DENONCIATION = "Dénonciation"
DELAIS_FIN = (("fin_6m", 6, "dans 6 mois"), ("fin_3m", 3, "dans 3 mois"))
DELAIS_REVISION = (("revision_3m", 3, "dans 3 mois"), ("revision_1m", 1, "dans 1 mois"))


@dataclass(frozen=True)
class Alerte:
    uid: str
    cle: str
    groupe: str  # "Client_Site_Activite", sert à nommer le .ics du contrat
    type: str
    date: date
    titre: str
    description: str
    origine: str | None = None  # document d'origine commun (contrat multi-site)
    intitule: str = ""
    client: str = ""
    site_activite: str = ""
    resume: str = ""


def uid_alerte(cle: str, type_alerte: str) -> str:
    """Identifiant stable : même contrat + même type d'alerte = même UID, quelle que soit la date."""
    return f"{hashlib.sha1(cle.encode('utf-8')).hexdigest()[:20]}-{type_alerte}@contratheque.local"


def date_limite_denonciation(sit: dict) -> tuple[date | None, bool]:
    """(date, calculée ?) : la date du contrat, sinon échéance − préavis si les deux sont connus."""
    declaree = lire_date(sit.get("date_limite_denonciation"))
    if declaree:
        return declaree, False
    echeance = lire_date(sit.get("date_echeance"))
    preavis = sit.get("preavis_denonciation_jours")
    if echeance and preavis:
        return echeance - timedelta(days=int(preavis)), True
    return None, False


def libelle_contrat(sit: dict) -> str:
    return " – ".join(x for x in (sit.get("client"), sit.get("site"), sit.get("activite")) if x)


def calculer_alertes(sit: dict) -> list[Alerte]:
    """Alertes d'une « situation » de contrat (contrat + avenants fusionnés)."""
    cle = sit["cle"]
    groupe = rangement.nom_base(sit["client"], sit["site"], sit["activite"])
    lib = libelle_contrat(sit)
    site_activite = f"{sit['site']} – {sit['activite']}"
    echeance = lire_date(sit.get("date_echeance"))
    revision = lire_date(sit.get("date_revision"))
    limite, calculee = date_limite_denonciation(sit)

    contexte = [f"Contrat : {lib}"]
    resume = []
    if sit.get("montant_ht") is not None:
        montant = (f"{formater_montant(sit['montant_ht'], sit.get('devise'))}"
                   f" ({sit.get('periodicite') or 'périodicité non précisée'})")
        contexte.append(f"Montant HT : {montant}")
        resume.append(montant)
    if echeance:
        contexte.append(f"Échéance : {formater_date(echeance)}")
        resume.append(f"échéance {formater_date(echeance)}")
    if limite:
        contexte.append(
            f"Date limite de dénonciation : {formater_date(limite)}" + (" (calculée)" if calculee else "")
        )
    if revision:
        contexte.append(f"Prochaine révision : {formater_date(revision)}")
    base = "\n".join(contexte)

    def alerte(type_alerte: str, quand: date, theme: str, delai: str) -> Alerte:
        intitule = f"{theme} ({delai})"
        return Alerte(uid_alerte(cle, type_alerte), cle, groupe, type_alerte, quand,
                      f"{lib} – {intitule}", base, sit.get("groupe_origine"), intitule,
                      sit["client"], site_activite, ", ".join(resume))

    resultat: list[Alerte] = []
    for type_alerte, mois, delai in DELAIS_FIN:
        if echeance:
            resultat.append(alerte(type_alerte, ajouter_mois(echeance, -mois), THEME_FIN, delai))
    for type_alerte, mois, delai in DELAIS_REVISION:
        if revision:
            resultat.append(alerte(type_alerte, ajouter_mois(revision, -mois), THEME_REVISION, delai))
    if limite:
        resultat.append(alerte("denonciation_1m", ajouter_mois(limite, -1), THEME_DENONCIATION, "dans 1 mois"))
        resultat.append(alerte("denonciation_jour", limite, THEME_DENONCIATION, "dernier jour"))
    return resultat


def fusionner_alertes(alertes: list[Alerte]) -> list[Alerte]:
    """Vue « agenda » : un seul événement par (document d'origine, type, date).

    Les alertes restent créées par enregistrement en base ; seule l'agenda regroupe, pour éviter
    10 rappels identiques le même jour. L'UID de l'événement regroupé est le plus petit UID de ses
    membres : il reste stable tant que ce membre fait partie du même groupe.
    """
    sortie: list[Alerte] = []
    groupes: dict[tuple, list[Alerte]] = defaultdict(list)
    for a in alertes:
        if a.origine:
            groupes[(a.origine, a.type, a.date)].append(a)
        else:
            sortie.append(a)
    for (origine, _type, _date), membres in groupes.items():
        if len(membres) == 1:
            sortie.append(membres[0])
            continue
        membres.sort(key=lambda m: m.uid)
        premier = membres[0]
        lignes = [f"- {m.site_activite}" + (f" : {m.resume}" if m.resume else "") for m in membres]
        description = (f"{premier.intitule} – {premier.client}\n"
                       f"Contrat commun à {len(membres)} sites (un seul document d'origine).\n\n"
                       "Sites concernés :\n" + "\n".join(lignes))
        sortie.append(replace(
            premier,
            titre=f"{premier.client} ({len(membres)} sites) – {premier.intitule}",
            description=description,
            groupe=f"{rangement.normaliser(premier.client)}_MultiSites_{origine[:6]}",
        ))
    return sorted(sortie, key=lambda a: (a.date, a.uid))
