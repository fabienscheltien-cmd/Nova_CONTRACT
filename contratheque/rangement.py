"""Rangement des fichiers dans l'arborescence OneDrive, sans jamais écraser."""
from __future__ import annotations

import re
from pathlib import Path

from .outils import sans_accents

RESERVES_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}


def normaliser(texte: str | None, longueur_max: int = 40) -> str:
    """'Société Générale' -> 'Societe-Generale' (ni accents, ni espaces, ni caractères interdits)."""
    s = sans_accents(texte or "")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:longueur_max].strip("-")
    if not s:
        return "Inconnu"
    if s.upper() in RESERVES_WINDOWS:
        s += "-"
    return s


def nom_base(client: str, site: str, activite: str) -> str:
    return "_".join(normaliser(x) for x in (client, site, activite))


def dossier_contrat(racine: Path, client: str, site: str, activite: str) -> Path:
    """<racine>/<Client>/<Client>_<Site>_<Activite>/"""
    return Path(racine) / normaliser(client) / nom_base(client, site, activite)


def nom_fichier(client: str, site: str, activite: str, type_document: str,
                numero_avenant: int | None, extension: str) -> str:
    """Client_Site_Activite_Contrat.ext ou Client_Site_Activite_Avenant1.ext"""
    if type_document == "avenant":
        suffixe = f"Avenant{numero_avenant or 1}"
    else:
        suffixe = "Contrat"
    extension = extension.lower()
    if extension and not extension.startswith("."):
        extension = "." + extension
    return f"{nom_base(client, site, activite)}_{suffixe}{extension}"


def ranger_fichier(racine: Path, client: str, site: str, activite: str, type_document: str,
                   numero_avenant: int | None, nom_origine: str, contenu: bytes) -> Path:
    """Écrit le fichier sous le bon dossier (créé au besoin) ; ajoute _v2, _v3... si le nom existe."""
    dossier = dossier_contrat(racine, client, site, activite)
    dossier.mkdir(parents=True, exist_ok=True)
    nom = nom_fichier(client, site, activite, type_document, numero_avenant, Path(nom_origine).suffix)
    base = Path(nom)
    version = 1
    while True:
        cible = dossier / (nom if version == 1 else f"{base.stem}_v{version}{base.suffix}")
        try:
            with open(cible, "xb") as f:  # 'x' : échoue si le fichier existe déjà
                f.write(contenu)
            return cible
        except FileExistsError:
            version += 1
