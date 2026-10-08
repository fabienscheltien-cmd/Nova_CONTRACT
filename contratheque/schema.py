"""Schéma JSON attendu (version_schema = 1) et messages d'erreur en français."""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from .outils import sans_accents

VERSION_SCHEMA = 1
ACTIVITES = ("Accueil", "Conciergerie", "Hospitalité")
TYPES_DOCUMENT = ("contrat", "avenant")
PERIODICITES = ("mensuel", "trimestriel", "annuel", "ponctuel")


def _enum(valeurs):
    table = {sans_accents(v).lower(): v for v in valeurs}

    def normaliser(v):
        if isinstance(v, str):
            v = v.strip()
            return table.get(sans_accents(v).lower(), v) if v else None
        return v

    return normaliser


def _date(v):
    if v is None:
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            raise ValueError("format_date")
        try:
            return date.fromisoformat(s)
        except ValueError:
            raise ValueError("date_impossible") from None
    raise ValueError("format_date")


def _nombre(v):
    if isinstance(v, str):
        s = re.sub(r"[\s  €]", "", v).replace(",", ".")
        return s or None
    return v


def _texte(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        v = " | ".join(str(x) for x in v)
    if isinstance(v, str):
        return v.strip() or None
    return v


def _booleen(v):
    if isinstance(v, str):
        s = sans_accents(v).strip().lower()
        if s in ("oui", "o"):
            return True
        if s in ("non", "n"):
            return False
        if s in ("", "null", "none"):
            return None
    return v


def _vide_si_none(defaut):
    def f(v):
        return defaut() if v is None else v

    return f


Texte = Annotated[str | None, BeforeValidator(_texte)]
Date = Annotated[date | None, BeforeValidator(_date)]
Decimal_ = Annotated[float | None, BeforeValidator(_nombre)]
Entier = Annotated[int | None, BeforeValidator(_nombre)]
Booleen = Annotated[bool | None, BeforeValidator(_booleen)]
Activite = Annotated[
    Literal["Accueil", "Conciergerie", "Hospitalité"] | None, BeforeValidator(_enum(ACTIVITES))
]
TypeDocument = Annotated[Literal["contrat", "avenant"] | None, BeforeValidator(_enum(TYPES_DOCUMENT))]
Periodicite = Annotated[
    Literal["mensuel", "trimestriel", "annuel", "ponctuel"] | None,
    BeforeValidator(_enum(PERIODICITES)),
]


class Indexation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    indice: Texte = None
    formule: Texte = None
    date_revision: Date = None
    indice_reference: Texte = None


def _site_depuis_texte(v):
    return {"site": v} if isinstance(v, str) else v


class SiteDetecte(BaseModel):
    """Un site (et son activité) repéré dans un contrat multi-site. Seul `site` est utile en général."""

    model_config = ConfigDict(extra="ignore")

    site: Texte = None
    activite: Activite = None
    montant_ht: Decimal_ = None
    periodicite: Periodicite = None
    date_effet: Date = None
    date_echeance: Date = None
    date_limite_denonciation: Date = None
    date_revision: Date = None
    preuve: Texte = None


class ContratJSON(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version_schema: int = VERSION_SCHEMA
    client: Texte = None
    site: Texte = None
    activite: Activite = None
    multi_site: Booleen = None
    sites_detectes: Annotated[
        list[Annotated[SiteDetecte, BeforeValidator(_site_depuis_texte)]],
        BeforeValidator(_vide_si_none(list)),
    ] = Field(default_factory=list)
    type_document: TypeDocument = None
    numero_avenant: Entier = None
    contrat_parent: Texte = None
    montant_ht: Decimal_ = None
    periodicite: Periodicite = None
    devise: Texte = None
    date_effet: Date = None
    date_echeance: Date = None
    duree_mois: Entier = None
    reconduction_tacite: Booleen = None
    duree_reconduction_mois: Entier = None
    preavis_denonciation_jours: Entier = None
    date_limite_denonciation: Date = None
    indexation: Annotated[Indexation, BeforeValidator(_vide_si_none(dict))] = Field(
        default_factory=Indexation
    )
    preuves: Annotated[dict[str, Texte], BeforeValidator(_vide_si_none(dict))] = Field(
        default_factory=dict
    )
    points_a_verifier: Annotated[list[Texte], BeforeValidator(_vide_si_none(list))] = Field(
        default_factory=list
    )

    def a_plat(self) -> dict:
        """Dictionnaire à plat (dates en AAAA-MM-JJ) prêt pour la base."""
        d = self.model_dump(mode="json", exclude={"indexation", "preuves", "points_a_verifier", "multi_site", "sites_detectes"})
        d.update(self.indexation.model_dump(mode="json"))
        return d


# --------------------------------------------------------------------------- erreurs en français

LIBELLES = {
    "version_schema": "Version du schéma",
    "client": "Client",
    "site": "Site",
    "activite": "Activité",
    "multi_site": "Contrat multi-site",
    "sites_detectes": "Sites détectés",
    "type_document": "Type de document",
    "numero_avenant": "Numéro d'avenant",
    "contrat_parent": "Contrat parent",
    "montant_ht": "Montant HT",
    "periodicite": "Périodicité",
    "devise": "Devise",
    "date_effet": "Date d'effet",
    "date_echeance": "Date d'échéance",
    "duree_mois": "Durée (mois)",
    "reconduction_tacite": "Reconduction tacite",
    "duree_reconduction_mois": "Durée de reconduction (mois)",
    "preavis_denonciation_jours": "Préavis de dénonciation (jours)",
    "date_limite_denonciation": "Date limite de dénonciation",
    "indexation": "Indexation",
    "indexation.indice": "Indice (indexation)",
    "indexation.formule": "Formule (indexation)",
    "indexation.date_revision": "Date de révision (indexation)",
    "indexation.indice_reference": "Indice de référence (indexation)",
    "preuves": "Preuves",
    "points_a_verifier": "Points à vérifier",
}
ATTENDUS = {
    "activite": ACTIVITES,
    "type_document": TYPES_DOCUMENT,
    "periodicite": PERIODICITES,
}
MESSAGES_CODES = {
    "format_date": "doit être une date au format AAAA-MM-JJ (exemple : 2026-03-31)",
    "date_impossible": "n'est pas une date qui existe dans le calendrier",
}
MESSAGES_TYPES = {
    "bool_parsing": "doit être vrai ou faux (true/false, oui/non)",
    "bool_type": "doit être vrai ou faux (true/false, oui/non)",
    "int_parsing": "doit être un nombre entier",
    "int_from_float": "doit être un nombre entier (sans décimales)",
    "int_type": "doit être un nombre entier",
    "float_parsing": "doit être un nombre (exemple : 1250.50)",
    "float_type": "doit être un nombre (exemple : 1250.50)",
    "string_type": "doit être un texte",
    "list_type": "doit être une liste [ ... ]",
    "dict_type": "doit être un bloc { ... }",
}


def _traduire(err: dict) -> str:
    loc = ".".join(str(p) for p in err["loc"] if not isinstance(p, int))
    if loc.startswith("preuves."):
        champ = f"Preuve « {loc.split('.', 1)[1]} »"
    else:
        champ = LIBELLES.get(loc, loc or "JSON")
    t = err["type"]
    if t == "value_error":
        code = str(err.get("ctx", {}).get("error", ""))
        msg = MESSAGES_CODES.get(code, code or "valeur invalide")
    elif t == "literal_error":
        msg = f"valeur « {err.get('input')} » non reconnue"
        attendu = ATTENDUS.get(loc)
        if attendu:
            msg += f" (valeurs possibles : {', '.join(attendu)})"
    elif t.startswith("model") or t == "dict_type":
        msg = "doit être un bloc { ... }"
    else:
        msg = MESSAGES_TYPES.get(t, err.get("msg", "valeur invalide"))
    return f"« {champ} » : {msg}."


def valider(brut: dict) -> tuple[ContratJSON | None, list[str]]:
    """Valide un dictionnaire ; renvoie (contrat, erreurs lisibles en français)."""
    try:
        return ContratJSON.model_validate(brut), []
    except ValidationError as exc:
        return None, [_traduire(e) for e in exc.errors()]
