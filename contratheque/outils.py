"""Petites fonctions utilitaires partagées (texte, dates, montants)."""
from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime


def sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def ajouter_mois(d: date, n: int) -> date:
    """Ajoute n mois (n peut être négatif) ; le jour est ramené à la fin du mois si besoin.

    31 mars - 1 mois = 28 (ou 29) février ; 29 février + 12 mois = 28 février.
    """
    total = d.year * 12 + (d.month - 1) + n
    annee, mois = divmod(total, 12)
    mois += 1
    return date(annee, mois, min(d.day, calendar.monthrange(annee, mois)[1]))


def lire_date(valeur) -> date | None:
    """Convertit 'AAAA-MM-JJ' (ou une date) en date ; None si vide ou illisible."""
    if valeur in (None, ""):
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    try:
        return date.fromisoformat(str(valeur).strip()[:10])
    except ValueError:
        return None


def cle_contrat(client: str, site: str, activite: str) -> str:
    """Identifiant logique d'un contrat : client + site + activité (insensible aux accents/casse)."""
    parties = []
    for p in (client, site, activite):
        p = sans_accents(p or "").lower()
        parties.append(re.sub(r"[^a-z0-9]+", " ", p).strip())
    return "|".join(parties)


def formater_date(d: date | str | None) -> str:
    d = lire_date(d)
    return d.strftime("%d/%m/%Y") if d else "—"


def formater_montant(valeur: float | None, devise: str | None = "EUR") -> str:
    if valeur is None:
        return "—"
    texte = f"{valeur:,.2f}".replace(",", " ").replace(".", ",")
    devise = devise or "EUR"
    return f"{texte} {'€' if devise == 'EUR' else devise}"
