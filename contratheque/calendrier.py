"""Calendrier Microsoft : une interface commune, trois implémentations.

1. IcsCalendrier   : fichiers .ics (par défaut, fonctionne partout).
2. OutlookCom      : Outlook classique via COM (pywin32), repli sur .ics si absent.
3. GraphCalendrier : Microsoft Graph (MSAL, device code) — NON implémenté, interface seulement.
"""
from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .alertes import Alerte

# Rappel (VALARM) : la veille à 9 h pour un événement « journée entière » (qui démarre à 0 h).
RAPPEL_MINUTES_AVANT = 15 * 60
CATEGORIE = "Contrathèque"


@dataclass
class ResultatSync:
    message: str
    fichiers: list[Path] = field(default_factory=list)
    entry_ids: dict[str, str] = field(default_factory=dict)  # uid -> identifiant côté calendrier


class Calendrier(ABC):
    nom: str

    @abstractmethod
    def disponible(self) -> bool:
        """Ce calendrier est-il utilisable sur cette machine ?"""

    @abstractmethod
    def synchroniser(self, alertes: Sequence[Alerte], entry_ids: Mapping[str, str],
                     aujourdhui: date) -> ResultatSync:
        """Crée ou met à jour les alertes à venir (sans doublon, grâce à l'UID / l'EntryID)."""

    def retirer(self, entry_ids: Iterable[str]) -> None:
        """Supprime côté calendrier les événements qui n'existent plus (par défaut : rien)."""


# --------------------------------------------------------------------------- .ics

def _echapper(texte: str) -> str:
    return (texte.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\n").replace("\n", "\\n"))


def _plier(ligne: str) -> str:
    """Pliage RFC 5545 : 75 octets maximum par ligne, sans couper un caractère UTF-8."""
    lignes: list[str] = []
    courante, taille = "", 0
    for ch in ligne:
        n = len(ch.encode("utf-8"))
        limite = 75 if not lignes else 74  # les lignes de suite commencent par une espace
        if taille + n > limite:
            lignes.append(courante)
            courante, taille = "", 0
        courante += ch
        taille += n
    lignes.append(courante)
    return "\r\n ".join(lignes)


def generer_ics(alertes: Iterable[Alerte], maintenant: datetime | None = None,
                nom_calendrier: str = "Contrathèque") -> str:
    """Contenu d'un fichier .ics ; un seul VEVENT par UID."""
    maintenant = (maintenant or datetime.now(timezone.utc)).astimezone(timezone.utc)
    horodatage = maintenant.strftime("%Y%m%dT%H%M%SZ")
    sequence = int(maintenant.timestamp() // 60)  # croît à chaque régénération -> Outlook met à jour
    lignes = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Contratheque//FR//",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_echapper(nom_calendrier)}",
    ]
    vus: set[str] = set()
    for a in sorted(alertes, key=lambda x: (x.date, x.uid)):
        if a.uid in vus:
            continue
        vus.add(a.uid)
        lignes += [
            "BEGIN:VEVENT",
            f"UID:{a.uid}",
            f"DTSTAMP:{horodatage}",
            f"LAST-MODIFIED:{horodatage}",
            f"SEQUENCE:{sequence}",
            f"DTSTART;VALUE=DATE:{a.date:%Y%m%d}",
            f"DTEND;VALUE=DATE:{a.date + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_echapper(a.titre)}",
            f"DESCRIPTION:{_echapper(a.description)}",
            f"CATEGORIES:{CATEGORIE}",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM", "ACTION:DISPLAY",
            f"DESCRIPTION:{_echapper(a.titre)}",
            f"TRIGGER:-PT{RAPPEL_MINUTES_AVANT // 60}H",
            "END:VALARM",
            "END:VEVENT",
        ]
    lignes.append("END:VCALENDAR")
    return "\r\n".join(_plier(l) for l in lignes) + "\r\n"


class IcsCalendrier(Calendrier):
    nom = "Fichiers .ics"
    NOM_GLOBAL = "toutes_alertes.ics"

    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)

    def disponible(self) -> bool:
        return True

    def chemin_contrat(self, groupe: str) -> Path:
        return self.dossier / f"{groupe}.ics"

    def synchroniser(self, alertes, entry_ids, aujourdhui, maintenant: datetime | None = None):
        a_venir = [a for a in alertes if a.date >= aujourdhui]
        self.dossier.mkdir(parents=True, exist_ok=True)
        par_contrat: dict[str, list[Alerte]] = defaultdict(list)
        for a in a_venir:
            par_contrat[a.groupe].append(a)

        ecrits: list[Path] = []
        for groupe, liste in par_contrat.items():
            chemin = self.chemin_contrat(groupe)
            chemin.write_bytes(generer_ics(liste, maintenant, f"Contrathèque – {groupe}").encode("utf-8"))
            ecrits.append(chemin)
        global_ = self.dossier / self.NOM_GLOBAL
        global_.write_bytes(generer_ics(a_venir, maintenant).encode("utf-8"))
        ecrits.append(global_)

        for ancien in self.dossier.glob("*.ics"):  # contrats sans alerte à venir : on retire le .ics
            if ancien not in ecrits:
                ancien.unlink()
        return ResultatSync(f"{len(a_venir)} alerte(s) à venir écrite(s) dans {self.dossier}", ecrits)


def ouvrir_fichier(chemin: Path) -> bool:
    """Ouvre un fichier avec l'application Windows associée (Outlook pour un .ics)."""
    if sys.platform != "win32":
        return False
    try:
        os.startfile(str(chemin))  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- Outlook classique

class OutlookCom(Calendrier):
    """Outlook classique (pas le « nouvel Outlook », qui n'expose pas COM)."""

    nom = "Outlook classique"

    def __init__(self):
        self._app = None

    def _application(self):
        if self._app is None:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore

            pythoncom.CoInitialize()  # Streamlit exécute le script dans un thread secondaire
            self._app = win32com.client.Dispatch("Outlook.Application")
        return self._app

    def disponible(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            self._application().GetNamespace("MAPI")
            return True
        except Exception:
            self._app = None
            return False

    def synchroniser(self, alertes, entry_ids, aujourdhui):
        app = self._application()
        espace = app.GetNamespace("MAPI")
        ids: dict[str, str] = {}
        crees = maj = 0
        for a in alertes:
            if a.date < aujourdhui:
                continue
            item = None
            eid = entry_ids.get(a.uid)
            if eid:
                try:
                    item = espace.GetItemFromID(eid)
                except Exception:
                    item = None  # supprimé dans Outlook : on le recrée
            if item is None:
                item = app.CreateItem(1)  # olAppointmentItem
                crees += 1
            else:
                maj += 1
            debut = datetime(a.date.year, a.date.month, a.date.day)
            item.AllDayEvent = True
            item.Start = debut
            item.End = debut + timedelta(days=1)
            item.Subject = a.titre
            item.Body = a.description
            item.BusyStatus = 0  # libre : ne bloque pas l'agenda
            item.Categories = CATEGORIE
            item.ReminderSet = True
            item.ReminderMinutesBeforeStart = RAPPEL_MINUTES_AVANT
            item.Save()
            ids[a.uid] = item.EntryID
        return ResultatSync(f"Outlook : {crees} créée(s), {maj} mise(s) à jour.", [], ids)

    def retirer(self, entry_ids):
        espace = self._application().GetNamespace("MAPI")
        for eid in entry_ids:
            if not eid:
                continue
            try:
                espace.GetItemFromID(eid).Delete()
            except Exception:
                pass


# --------------------------------------------------------------------------- Microsoft Graph (à faire)

class GraphCalendrier(Calendrier):
    """Interface prête, NON implémentée.

    Pour plus tard : MSAL `PublicClientApplication.initiate_device_flow` (device code), jeton mis en
    cache, puis POST/PATCH https://graph.microsoft.com/v1.0/me/events avec `isAllDay`, `isReminderOn`,
    `reminderMinutesBeforeStart` ; l'identifiant d'événement Graph est renvoyé dans `entry_ids`.
    """

    nom = "Microsoft Graph"

    def disponible(self) -> bool:
        return False

    def synchroniser(self, alertes, entry_ids, aujourdhui):
        raise NotImplementedError("Microsoft Graph n'est pas encore implémenté.")
