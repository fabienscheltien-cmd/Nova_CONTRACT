"""Contrats multi-sites : scission en une ligne par site + activité."""
from __future__ import annotations

from .outils import cle_contrat, lire_date
from .schema import ContratJSON, valider

CHAMPS_LIGNE = ("site", "activite", "montant_ht", "periodicite", "date_effet", "date_echeance",
                "date_limite_denonciation", "date_revision")
# "preuve" (citation du bordereau) accompagne la ligne mais n'est pas un champ du contrat.


def lignes_initiales(c: ContratJSON) -> list[dict]:
    """Une ligne par site détecté ; les valeurs absentes reprennent celles du contrat global."""
    lignes = []
    for s in c.sites_detectes:
        lignes.append({
            "site": s.site,
            "activite": s.activite or c.activite,
            # Pas de montant global repris par défaut : la répartition n'est jamais déduite.
            "montant_ht": s.montant_ht,
            "periodicite": s.periodicite or c.periodicite,
            "date_effet": (s.date_effet or c.date_effet),
            "date_echeance": (s.date_echeance or c.date_echeance),
            "date_limite_denonciation": s.date_limite_denonciation,
            "date_revision": (s.date_revision or c.indexation.date_revision),
            "preuve": s.preuve,
        })
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in l.items()} for l in lignes]


def _vide(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip())


def scinder(commun: dict, lignes: list[dict]) -> tuple[list[ContratJSON], list[str]]:
    """Valide les lignes et fabrique un contrat par ligne.

    `commun` : dictionnaire au format JSON (client, périodicité, préavis, indexation, preuves...).
    Chaque ligne apporte son site, son activité, son montant et ses dates ; ce qu'elle ne renseigne
    pas est repris du commun. La date limite de dénonciation du commun n'est reprise que si
    l'échéance de la ligne est la même (sinon elle est recalculée à partir du préavis).
    """
    erreurs: list[str] = []
    contrats: list[ContratJSON] = []
    vus: dict[str, int] = {}
    lignes = [l for l in lignes if not all(_vide(l.get(c)) for c in CHAMPS_LIGNE)]
    if len(lignes) < 2:
        erreurs.append("Le contrat concerne plusieurs sites : il faut au moins 2 lignes (site + activité).")
    for i, ligne in enumerate(lignes, start=1):
        # Le montant global n'est jamais réparti : chaque ligne apporte le sien (ou reste vide).
        brut = {**commun, "multi_site": False, "sites_detectes": [], "montant_ht": None}
        for champ in CHAMPS_LIGNE:
            if not _vide(ligne.get(champ)):
                brut[champ] = ligne[champ]
        ech_ligne = lire_date(ligne.get("date_echeance")) if not _vide(ligne.get("date_echeance")) else None
        if _vide(ligne.get("date_limite_denonciation")) and ech_ligne \
                and ech_ligne != lire_date(commun.get("date_echeance")):
            brut["date_limite_denonciation"] = None
        if not _vide(ligne.get("preuve")):
            brut["preuves"] = {**(commun.get("preuves") or {}), "ligne": ligne["preuve"]}
        if not _vide(ligne.get("date_revision")):
            brut["indexation"] = {**(commun.get("indexation") or {}), "date_revision": ligne["date_revision"]}
        c, errs = valider(brut)
        pref = f"Ligne {i} : "
        if errs:
            erreurs += [pref + e for e in errs]
            continue
        manquants = [n for n, v in (("site", c.site), ("activité", c.activite)) if not v]
        if manquants:
            erreurs.append(pref + "renseignez " + " et ".join(manquants) + ".")
            continue
        cle = cle_contrat(c.client or "", c.site, c.activite)
        if cle in vus:
            erreurs.append(f"{pref}le couple site + activité est déjà utilisé à la ligne {vus[cle]}.")
            continue
        vus[cle] = i
        contrats.append(c)
    if not (commun.get("client") or "").strip():
        erreurs.append("Le client est obligatoire.")
    if not commun.get("type_document"):
        erreurs.append("Le type de document est obligatoire.")
    return contrats, erreurs
