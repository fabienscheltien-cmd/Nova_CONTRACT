"""Contrôles d'aide à la relecture : dates absentes, ambiguës ou incohérentes."""
from __future__ import annotations

from datetime import timedelta

from .outils import lire_date, sans_accents

CHAMPS_DATES = {
    "date_effet": "Date d'effet",
    "date_echeance": "Date d'échéance",
    "date_limite_denonciation": "Date limite de dénonciation",
    "date_revision": "Date de révision",
}
MOTS_CLES = {
    "date_effet": ("effet", "prise d'effet", "entree en vigueur", "demarrage", "signature"),
    "date_echeance": ("echeance", "fin du contrat", "terme", "expiration", "duree"),
    "date_limite_denonciation": ("denonciation", "preavis", "resiliation"),
    "date_revision": ("revision", "indexation", "indice", "revalorisation"),
}


# Clés de « preuves » du schéma : activite, date_echeance, preavis_denonciation_jours, indexation, montant_ht.
ALIAS_PREUVES = {
    "date_limite_denonciation": ("preavis_denonciation_jours",),
    "date_revision": ("indexation",),
    "indice": ("indexation",), "formule": ("indexation",), "indice_reference": ("indexation",),
}
SANS_PREUVE_ATTENDUE = {"date_effet"}  # le schéma ne prévoit pas de citation pour la date d'effet


def chercher_preuve(preuves: dict, champ: str) -> str | None:
    """Citation associée à un champ (clé du champ, ou clé voisine du schéma : préavis, indexation)."""
    if not preuves:
        return None
    normalisees = {sans_accents(str(k)).lower(): v for k, v in preuves.items()}
    for cle in (champ, f"indexation.{champ}", f"indexation_{champ}", *ALIAS_PREUVES.get(champ, ())):
        v = normalisees.get(cle)
        if v:
            return v
    return None


def diagnostiquer_dates(valeurs: dict, points: list[str], preuves: dict) -> dict[str, list[str]]:
    """Pour chaque date à surveiller, la liste des raisons de la surligner.

    `valeurs` : date_effet, date_echeance, date_limite_denonciation, date_revision (texte AAAA-MM-JJ),
    plus preavis_denonciation_jours et indexation_presente (bool) pour les règles contextuelles.
    """
    pb: dict[str, list[str]] = {c: [] for c in CHAMPS_DATES}
    points_norm = [sans_accents(p or "").lower() for p in points]
    dates = {c: lire_date(valeurs.get(c)) for c in CHAMPS_DATES}
    preavis = valeurs.get("preavis_denonciation_jours")

    for champ in CHAMPS_DATES:
        brut = valeurs.get(champ)
        if brut not in (None, "") and dates[champ] is None:
            pb[champ].append("format illisible (attendu AAAA-MM-JJ)")
        elif dates[champ] is None:
            if champ == "date_revision" and not valeurs.get("indexation_presente"):
                continue
            if champ == "date_limite_denonciation" and dates["date_echeance"] and preavis:
                continue  # sera calculée à partir de l'échéance et du préavis
            pb[champ].append("date absente")
        else:
            if any(m in p for p in points_norm for m in MOTS_CLES[champ]):
                pb[champ].append("évoquée dans les points à vérifier")
            if preuves and champ not in SANS_PREUVE_ATTENDUE and not chercher_preuve(preuves, champ):
                pb[champ].append("aucune citation à l'appui")

    eff, ech, lim = dates["date_effet"], dates["date_echeance"], dates["date_limite_denonciation"]
    if eff and ech and ech < eff:
        pb["date_echeance"].append("antérieure à la date d'effet")
    if lim and ech and lim > ech:
        pb["date_limite_denonciation"].append("postérieure à l'échéance")
    if lim and ech and preavis:
        attendue = ech - timedelta(days=int(preavis))
        if abs((lim - attendue).days) > 1:
            pb["date_limite_denonciation"].append(
                f"différente de échéance − préavis ({attendue.strftime('%d/%m/%Y')})"
            )
    return {c: m for c, m in pb.items() if m}
