"""Extraction du premier bloc JSON d'un texte collé, puis validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .schema import VERSION_SCHEMA, ContratJSON, valider

CLES_ATTENDUES = ("version_schema", "client", "date_echeance", "montant_ht")


@dataclass
class ResultatAnalyse:
    donnees: ContratJSON | None = None
    brut: dict | None = None
    json_texte: str | None = None
    erreurs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.donnees is not None and not self.erreurs


def extraire_tous_json(texte: str) -> tuple[list[dict], str | None]:
    """Tous les blocs JSON d'analyse du texte, dans l'ordre (texte autour et ```json tolérés).

    Renvoie (blocs, message d'erreur) ; le message n'est renseigné que si aucun bloc n'a été trouvé.
    """
    decodeur = json.JSONDecoder()
    blocs: list[dict] = []
    premiere_erreur: json.JSONDecodeError | None = None
    accolade_vue = False
    pos = texte.find("{")
    while pos != -1:
        accolade_vue = True
        try:
            objet, fin = decodeur.raw_decode(texte, pos)
        except json.JSONDecodeError as exc:
            premiere_erreur = premiere_erreur or exc
            pos = texte.find("{", pos + 1)
            continue
        # On ignore les petits objets imbriqués d'un JSON cassé ou les accolades parasites.
        if isinstance(objet, dict) and any(c in objet for c in CLES_ATTENDUES):
            blocs.append(objet)
            pos = texte.find("{", fin)
        else:
            pos = texte.find("{", pos + 1)
    if blocs:
        return blocs, None
    if premiere_erreur is not None:
        return [], (
            "Le JSON est mal formé (ligne "
            f"{premiere_erreur.lineno}, colonne {premiere_erreur.colno} : {premiere_erreur.msg}). "
            "Vérifiez qu'il est complet (accolade fermante, guillemets, virgules)."
        )
    if accolade_vue:
        return [], "Un bloc { ... } a été trouvé, mais il ne ressemble pas à une analyse de contrat."
    return [], "Aucun bloc JSON trouvé dans le texte collé."


def extraire_json(texte: str) -> tuple[dict | None, str | None]:
    """Premier bloc JSON du texte : (dict, None) ou (None, message d'erreur)."""
    blocs, erreur = extraire_tous_json(texte)
    return (blocs[0], None) if blocs else (None, erreur)


def _analyser_bloc(brut: dict) -> ResultatAnalyse:
    version = brut.get("version_schema")
    if version is None:
        return ResultatAnalyse(
            brut=brut,
            erreurs=[
                "Le champ « version_schema » est absent : ce JSON ne vient pas du bon modèle "
                f"d'analyse (version attendue : {VERSION_SCHEMA})."
            ],
        )
    if isinstance(version, bool) or version != VERSION_SCHEMA:
        return ResultatAnalyse(
            brut=brut,
            erreurs=[
                f"Version de schéma non reconnue (« {version} »). Cette application gère uniquement "
                f"la version {VERSION_SCHEMA} : relancez l'analyse avec le bon Projet, ou mettez "
                "l'application à jour."
            ],
        )
    donnees, erreurs = valider(brut)
    return ResultatAnalyse(
        donnees=donnees,
        brut=brut,
        json_texte=json.dumps(brut, ensure_ascii=False, indent=2),
        erreurs=erreurs,
    )


def analyser_lot(texte: str) -> list[ResultatAnalyse]:
    """Analyse tous les blocs JSON collés (un seul bloc = un lot de 1)."""
    if not texte or not texte.strip():
        return [ResultatAnalyse(erreurs=["Rien n'a été collé : collez le résultat de l'analyse."])]
    blocs, erreur = extraire_tous_json(texte)
    if not blocs:
        return [ResultatAnalyse(erreurs=[erreur])]
    return [_analyser_bloc(b) for b in blocs]


def analyser(texte: str) -> ResultatAnalyse:
    """Analyse du premier bloc JSON seulement."""
    return analyser_lot(texte)[0]
