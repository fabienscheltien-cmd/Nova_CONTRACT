"""Lecture locale du texte d'un contrat (PDF, Word .docx, .txt) : rien ne quitte l'ordinateur."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
EXTENSIONS = ("pdf", "docx", "txt")
SEUIL_TEXTE = 80  # en dessous, on considère le document comme un scan sans texte


class LectureError(Exception):
    """Erreur de lecture, avec un message lisible par l'utilisateur."""


def _txt(contenu: bytes) -> str:
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            return contenu.decode(encodage)
        except UnicodeDecodeError:
            continue
    return contenu.decode("latin-1", errors="replace")


def _docx(contenu: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            racine = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise LectureError("Ce fichier Word est illisible ou n'est pas un .docx valide.") from None
    lignes = []
    for para in racine.iter(f"{W}p"):
        morceaux = []
        for el in para.iter():
            if el.tag == f"{W}t" and el.text:
                morceaux.append(el.text)
            elif el.tag == f"{W}tab":
                morceaux.append("\t")
            elif el.tag in (f"{W}br", f"{W}cr"):
                morceaux.append("\n")
        lignes.append("".join(morceaux))
    return "\n".join(lignes)


def _pdf(contenu: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError:
        raise LectureError("La lecture des PDF n'est pas installée (relancez lancer.bat).") from None
    try:
        lecteur = PdfReader(io.BytesIO(contenu))
        if lecteur.is_encrypted:
            lecteur.decrypt("")
        return "\n".join((page.extract_text() or "") for page in lecteur.pages)
    except (PyPdfError, ValueError, KeyError, OSError):
        raise LectureError("Ce PDF est illisible, protégé ou endommagé.") from None


def lire_texte(nom: str, contenu: bytes) -> str:
    """Texte du document, ou LectureError (scan sans texte, format non géré...)."""
    ext = Path(nom).suffix.lower().lstrip(".")
    if ext == "doc":
        raise LectureError("Le format Word ancien (.doc) n'est pas lu : enregistrez le fichier en .docx ou en PDF.")
    if ext not in EXTENSIONS:
        raise LectureError(f"Format .{ext} non géré : déposez un PDF, un .docx ou un .txt.")
    texte = {"pdf": _pdf, "docx": _docx, "txt": _txt}[ext](contenu)
    texte = texte.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    texte = re.sub(r"[ \t]+", " ", texte)
    texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
    if len(texte) < SEUIL_TEXTE:
        raise LectureError("Aucun texte lisible dans ce fichier : c'est probablement un scan. "
                           "Faites-le passer en reconnaissance de texte (OCR), ou collez le JSON d'analyse.")
    return texte
