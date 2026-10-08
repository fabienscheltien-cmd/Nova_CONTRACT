"""Révision de prix : suggestion uniquement, à partir d'un indice saisi à la main."""
from __future__ import annotations

import re

from .outils import formater_date, formater_montant


def extraire_nombre(texte: str | None) -> float | None:
    """Lit un nombre seulement si le texte EST un nombre (ex. '123,45'). Rien n'est déduit d'un nom d'indice."""
    if not texte:
        return None
    s = re.sub(r"[\s  ]", "", texte).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def montant_revise(montant: float, indice_reference: float, indice_nouveau: float,
                   part_fixe_pct: float = 0.0) -> float:
    """P = P0 × (part fixe + part variable × I / I0). Sans part fixe : P0 × I / I0."""
    if indice_reference <= 0 or indice_nouveau <= 0:
        raise ValueError("Les indices doivent être strictement positifs.")
    if not 0 <= part_fixe_pct <= 100:
        raise ValueError("La part fixe doit être comprise entre 0 et 100 %.")
    a = part_fixe_pct / 100
    return round(montant * (a + (1 - a) * indice_nouveau / indice_reference), 2)


def variation_pct(ancien: float, nouveau: float) -> float:
    return (nouveau / ancien - 1) * 100 if ancien else 0.0


def _virgule(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def modele_courrier(*, client: str, site: str, activite: str, date_revision, indice: str | None,
                    indice_reference: float, indice_nouveau: float, ancien_montant: float,
                    nouveau_montant: float, periodicite: str | None, devise: str | None,
                    formule: str | None, part_fixe_pct: float = 0.0) -> str:
    variation = variation_pct(ancien_montant, nouveau_montant)
    nom_indice = indice or "indice contractuel"
    lignes = [
        f"Objet : Révision annuelle du prix – {activite} – {site}",
        "",
        "Madame, Monsieur,",
        "",
        f"Conformément à la clause d'indexation de notre contrat ({activite}, site {site}), "
        f"nous vous informons de la révision de nos prix à compter du {formater_date(date_revision)}.",
        "",
    ]
    if formule:
        lignes += [f"Formule contractuelle : {formule}", ""]
    lignes += [
        f"- {nom_indice} de référence : {_virgule(indice_reference)}",
        f"- {nom_indice} nouveau : {_virgule(indice_nouveau)}",
    ]
    if part_fixe_pct:
        lignes.append(f"- Part fixe retenue : {_virgule(part_fixe_pct)} %")
    lignes += [
        f"- Montant HT {periodicite or ''} actuel : {formater_montant(ancien_montant, devise)}".replace("  ", " "),
        f"- Nouveau montant HT : {formater_montant(nouveau_montant, devise)} "
        f"({'+' if variation >= 0 else ''}{_virgule(variation)} %)",
        "",
        "Nous restons à votre disposition pour tout complément d'information.",
        "",
        "Cordialement,",
        "",
        "[Nom, fonction et société]",
        f"[Client : {client}]",
    ]
    return "\n".join(lignes)
