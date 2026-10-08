"""Configuration locale (config.toml) et emplacements des données."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

RACINE_PROJET = Path(os.environ.get("CONTRATHEQUE_HOME") or Path(__file__).resolve().parent.parent)
CONFIG = RACINE_PROJET / "config.toml"
DATA = RACINE_PROJET / "data"
DB = DATA / "contratheque.db"
SAUVEGARDES = DATA / "sauvegardes"
NOM_DOSSIER_CALENDRIER = "_Calendrier"


def charger(chemin: Path = CONFIG) -> dict:
    try:
        with open(chemin, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}


def sauver(cfg: dict, chemin: Path = CONFIG) -> None:
    lignes = []
    for cle, valeur in cfg.items():
        if isinstance(valeur, bool):
            lignes.append(f"{cle} = {'true' if valeur else 'false'}")
        else:  # json.dumps produit une chaîne TOML valide (antislash et accents échappés)
            lignes.append(f"{cle} = {json.dumps(str(valeur), ensure_ascii=False)}")
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def dossier_onedrive_probable() -> str:
    return os.environ.get("OneDriveCommercial") or os.environ.get("OneDrive") or ""


def parcourir_dossier(initial: str = "") -> str:
    """Boîte de dialogue « Choisir un dossier » (processus séparé, pour ne pas bloquer Streamlit)."""
    code = (
        "import sys, tkinter as tk\nfrom tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "print(filedialog.askdirectory(initialdir=sys.argv[1] or None) or '')"
    )
    try:
        res = subprocess.run(
            [sys.executable, "-c", code, initial], capture_output=True, timeout=600,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return res.stdout.decode("utf-8").strip()
    except (OSError, subprocess.SubprocessError):
        return ""
