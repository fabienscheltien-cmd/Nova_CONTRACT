"""Suivi : situation actuelle des contrats, CA récurrent, jalons et timeline."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from . import db
from .alertes import date_limite_denonciation, libelle_contrat
from .outils import ajouter_mois, lire_date

PERIODES_PAR_AN = {"mensuel": 12, "trimestriel": 4, "annuel": 1}
# Champs qu'un avenant remplace quand il les renseigne (la date d'effet du contrat, elle, est conservée).
CHAMPS_AVENANT = (
    "montant_ht", "periodicite", "devise", "date_echeance", "duree_mois", "reconduction_tacite",
    "duree_reconduction_mois", "preavis_denonciation_jours", "date_limite_denonciation",
    "indice", "formule", "date_revision", "indice_reference",
)
LIBELLES_JALONS = {
    "echeance": "Échéance du contrat",
    "revision": "Révision / revalorisation",
    "denonciation": "Date limite de dénonciation",
}


def fusionner(lignes: list[dict]) -> dict:
    """Situation actuelle = contrat courant + avenants courants (champs non vides, dans l'ordre)."""
    base = next((l for l in lignes if l["type_document"] == "contrat"), lignes[0])
    sit = dict(base)
    avenants = [l for l in lignes if l is not base and l["type_document"] == "avenant"]
    sit["nb_avenants"] = len(avenants)
    sit["a_contrat"] = base["type_document"] == "contrat"
    for av in avenants:
        if av.get("date_echeance") and not av.get("date_limite_denonciation"):
            sit["date_limite_denonciation"] = None  # sera recalculée avec la nouvelle échéance
        for champ in CHAMPS_AVENANT:
            if av.get(champ) is not None:
                sit[champ] = av[champ]
    sit["devise"] = sit.get("devise") or "EUR"
    return sit


def situations(conn) -> list[dict]:
    groupes: dict[str, list[dict]] = defaultdict(list)
    for l in db.lignes_courantes(conn):
        groupes[l["cle"]].append(l)
    return [fusionner(l) for l in groupes.values()]


# --------------------------------------------------------------------------- montants

def ca_annuel(sit: dict) -> float:
    """Chiffre d'affaires annuel récurrent HT (mensuel ×12, trimestriel ×4, annuel ×1 ; ponctuel exclu)."""
    if sit.get("montant_ht") is None:
        return 0.0
    return sit["montant_ht"] * PERIODES_PAR_AN.get(sit.get("periodicite"), 0)


def duree_effective_mois(sit: dict) -> int | None:
    if sit.get("duree_mois"):
        return int(sit["duree_mois"])
    debut, fin = lire_date(sit.get("date_effet")), lire_date(sit.get("date_echeance"))
    if debut and fin and fin >= debut:
        return max(1, round(((fin - debut).days + 1) / 30.4375))
    return None


def valeur_sur_duree(sit: dict) -> float | None:
    """Montant total sur la durée : mensuel × 12 × nombre d'années (ponctuel : le montant lui-même)."""
    if sit.get("montant_ht") is None:
        return None
    if sit.get("periodicite") == "ponctuel":
        return sit["montant_ht"]
    duree = duree_effective_mois(sit)
    if duree is None or sit.get("periodicite") not in PERIODES_PAR_AN:
        return None
    return ca_annuel(sit) * duree / 12


def est_actif(sit: dict, aujourdhui: date) -> bool:
    """En cours ou à venir : pas échu, ou échu mais reconduit tacitement. Le ponctuel est exclu."""
    if sit.get("periodicite") not in PERIODES_PAR_AN:
        return False
    fin = lire_date(sit.get("date_echeance"))
    return fin is None or fin >= aujourdhui or bool(sit.get("reconduction_tacite"))


def par_devise(sits: list[dict]) -> dict[str, list[dict]]:
    groupes: dict[str, list[dict]] = defaultdict(list)
    for s in sits:
        groupes[s.get("devise") or "EUR"].append(s)
    return dict(groupes)


def ca_total(sits: list[dict], aujourdhui: date) -> float:
    return sum(ca_annuel(s) for s in sits if est_actif(s, aujourdhui))


def ca_par_client(sits: list[dict], aujourdhui: date) -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    for s in sits:
        if est_actif(s, aujourdhui):
            total[s["client"]] += ca_annuel(s)
    return dict(sorted(total.items(), key=lambda kv: -kv[1]))


def ca_mensuel(sits: list[dict], aujourdhui: date, nb_mois: int = 12) -> list[tuple[date, float]]:
    """CA récurrent lissé (annuel / 12) pour chaque mois, à partir du mois en cours."""
    premier = aujourdhui.replace(day=1)
    resultat = []
    for i in range(nb_mois):
        debut = ajouter_mois(premier, i)
        fin = ajouter_mois(debut, 1) - timedelta(days=1)
        somme = 0.0
        for s in sits:
            if s.get("periodicite") not in PERIODES_PAR_AN:
                continue
            eff, ech = lire_date(s.get("date_effet")), lire_date(s.get("date_echeance"))
            if eff and eff > fin:
                continue
            if ech and ech < debut and not s.get("reconduction_tacite"):
                continue
            somme += ca_annuel(s) / 12
        resultat.append((debut, somme))
    return resultat


# --------------------------------------------------------------------------- jalons

@dataclass(frozen=True)
class Jalon:
    cle: str
    type: str
    date: date
    contrat: str
    calculee: bool = False

    @property
    def libelle(self) -> str:
        return LIBELLES_JALONS[self.type]

    @property
    def identifiant(self) -> tuple[str, str, str]:
        return (self.cle, self.type, self.date.isoformat())


def jalons(sit: dict) -> list[Jalon]:
    lib = libelle_contrat(sit)
    resultat = []
    echeance = lire_date(sit.get("date_echeance"))
    if echeance:
        resultat.append(Jalon(sit["cle"], "echeance", echeance, lib))
    revision = lire_date(sit.get("date_revision"))
    if revision:
        resultat.append(Jalon(sit["cle"], "revision", revision, lib))
    limite, calculee = date_limite_denonciation(sit)
    if limite:
        resultat.append(Jalon(sit["cle"], "denonciation", limite, lib, calculee))
    return resultat


def tous_les_jalons(sits: list[dict]) -> list[Jalon]:
    return sorted((j for s in sits for j in jalons(s)), key=lambda j: (j.date, j.contrat))


def a_traiter(sits: list[dict], traites: set, aujourdhui: date, jours: int = 30) -> list[Jalon]:
    """Jalons dépassés ou à moins de `jours` jours, non marqués « traités »."""
    limite = aujourdhui + timedelta(days=jours)
    return [j for j in tous_les_jalons(sits) if j.date <= limite and j.identifiant not in traites]


def timeline(sits: list[dict], aujourdhui: date, mois: int) -> list[Jalon]:
    fin = ajouter_mois(aujourdhui, mois)
    return [j for j in tous_les_jalons(sits) if aujourdhui <= j.date <= fin]
