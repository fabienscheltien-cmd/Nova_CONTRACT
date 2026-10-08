import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from contratheque import conformite, service
from contratheque.lecture import LectureError, lire_texte
from contratheque.prefill import analyser_texte, trouver_dates

EXEMPLE = (Path(__file__).parent / "data" / "contrat_exemple.txt").read_text(encoding="utf-8")


def docx_minimal(paragraphes: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    corps = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>" for p in paragraphes)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{ns}"><w:body>{corps}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def pdf_minimal(texte: str) -> bytes:
    """PDF d'une page avec du texte (police standard Helvetica, encodage WinAnsi)."""
    flux = "BT /F1 11 Tf 40 780 Td 14 TL " + " ".join(
        f"({ligne.replace('(', '[').replace(')', ']')}) Tj T*" for ligne in texte.split("\n")) + " ET"
    flux_b = flux.encode("cp1252")
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(flux_b)).encode() + b" >>\nstream\n" + flux_b + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    sortie = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objets, start=1):
        offsets.append(len(sortie))
        sortie += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        sortie += f"{off:010d} 00000 n \n".encode()
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(sortie)


# --------------------------------------------------------------------------- lecture

def test_lecture_txt_utf8_et_cp1252():
    t = "Contrat de prestation d'accueil conclu entre la société Alpha et la société Béta pour une durée de 3 ans. " * 2
    assert "Béta" in lire_texte("c.txt", t.encode("utf-8"))
    assert "Béta" in lire_texte("c.txt", t.encode("cp1252"))


def test_lecture_docx():
    texte = lire_texte("c.docx", docx_minimal(["CONTRAT D'ACCUEIL", "Le prix est fixé à 1 000 euros HT par mois pour le site de Lyon, hors options."]))
    assert "CONTRAT D'ACCUEIL" in texte and "1 000 euros" in texte


def test_lecture_pdf():
    texte = lire_texte("c.pdf", pdf_minimal("Contrat d'accueil\nLe prix est fixe a 1 000 euros HT par mois.\n"
                                            "Le contrat prend effet le 1er janvier 2026 pour une duree de 2 ans."))
    assert "1 000 euros HT par mois" in texte and "1er janvier 2026" in texte


def test_lecture_erreurs_lisibles():
    with pytest.raises(LectureError, match="scan"):
        lire_texte("scan.pdf", pdf_minimal(""))
    with pytest.raises(LectureError, match="illisible"):
        lire_texte("x.docx", b"pas un zip")
    with pytest.raises(LectureError, match="illisible"):
        lire_texte("x.pdf", b"pas un pdf")
    with pytest.raises(LectureError, match=r"\.docx"):
        lire_texte("ancien.doc", b"x")
    with pytest.raises(LectureError, match="non géré"):
        lire_texte("image.png", b"x")


# --------------------------------------------------------------------------- pré-remplissage

def test_dates_francaises():
    assert trouver_dates("à compter du 1er janvier 2026 et jusqu'au 31 décembre 2028") == [date(2026, 1, 1), date(2028, 12, 31)]
    assert trouver_dates("le 05/03/2027") == [date(2027, 3, 5)]
    assert trouver_dates("le 31 février 2027") == []


def test_prefill_contrat_exemple():
    r = analyser_texte(EXEMPLE, "contrat.txt")
    assert not r.erreurs
    d = r.donnees
    assert d.client == "Groupe Acme"  # forme juridique retirée
    assert d.site == "Lyon Part-Dieu" and d.activite == "Accueil" and d.type_document == "contrat"
    assert d.montant_ht == 4250.0 and d.periodicite == "mensuel"
    assert d.date_effet == date(2026, 1, 1) and d.date_echeance == date(2028, 12, 31) and d.duree_mois == 36
    assert d.reconduction_tacite is True and d.duree_reconduction_mois == 12
    assert d.preavis_denonciation_jours == 90
    assert d.indexation.indice == "Syntec" and d.indexation.formule == "P1 = P0 x (S1/S0)"
    assert "dernier indice publié" in d.indexation.indice_reference  # texte du contrat, aucune valeur d'indice inventée
    # citations à l'appui
    assert "4 250,00 euros HT par mois" in d.preuves["montant_ht"]
    assert "31 décembre 2028" in d.preuves["date_echeance"]
    assert "trois (3) mois" in d.preuves["preavis_denonciation_jours"]
    # tout ce qui est converti ou calculé est signalé
    points = " ".join(d.points_a_verifier)
    assert "converti en 90 jours" in points and "CALCULÉE" in points


def test_prefill_ne_tranche_pas_l_activite_ambigue():
    texte = ("Contrat de services. Le prestataire fournit une prestation de conciergerie et un service d'accueil, "
             "avec traiteur et café pour les événements. Le prix est de 900 euros HT par mois. " * 2)
    r = analyser_texte(texte)
    assert r.donnees.activite is None
    assert any("Activité non tranchée" in p for p in r.donnees.points_a_verifier)


def test_prefill_echeance_calculee_signalee():
    texte = ("Le présent contrat de services d'accueil prend effet le 1er mars 2026 pour une durée de douze (12) mois. "
             "Les hôtesses d'accueil assurent l'accueil des visiteurs. Redevance : 1 000 euros HT par mois.")
    d = analyser_texte(texte).donnees
    assert d.date_echeance == date(2027, 2, 28) and d.duree_mois == 12
    assert any("Échéance CALCULÉE" in p for p in d.points_a_verifier)


def test_prefill_avenant_et_multi_site():
    texte = ("AVENANT N° 2 au contrat n° ACME-2024-17\nLes parties conviennent de modifier le prix.\n"
             "Site : Paris La Défense\nSite : Lyon Part-Dieu\nSite : Lille Euralille\n"
             "Le nouveau prix est de 5 000 euros HT par mois pour l'ensemble des sites.")
    r = analyser_texte(texte)
    d = r.donnees
    assert d.type_document == "avenant" and d.numero_avenant == 2 and d.contrat_parent == "ACME-2024-17"
    assert d.multi_site is True and [s.site for s in d.sites_detectes] == ["Paris La Défense", "Lyon Part-Dieu", "Lille Euralille"]
    assert d.montant_ht is None  # jamais de répartition inventée
    assert any("scindé" in p for p in d.points_a_verifier)


def test_prefill_indexation_sans_indice_reconnu():
    texte = "Les prix seront indexés chaque année selon un indice convenu entre les parties. " * 3 + "Le prix est de 100 euros HT par mois."
    d = analyser_texte(texte).donnees
    assert d.indexation.indice is None
    assert any("indice non reconnu" in p for p in d.points_a_verifier)


# --------------------------------------------------------------------------- conformité

def test_conformite_exemple():
    d = analyser_texte(EXEMPLE).donnees
    par_clause = {c.clause: c for c in conformite.analyser_conformite(EXEMPLE, d)}
    assert par_clause["Clause pénale"].niveau == "risque"  # 15 000 € ≥ 25 % de 51 000 € annuels
    assert par_clause["Reconduction tacite"].niveau == "verifier"
    assert par_clause["Délai de paiement"].niveau == "ok"  # 45 jours
    assert "Pénalités de retard" in par_clause and "Indexation" in par_clause
    assert all(url.startswith("https://www.legifrance.gouv.fr/") for c in par_clause.values() for _, url in c.references)
    assert [c.niveau for c in conformite.analyser_conformite(EXEMPLE, d)] == sorted(
        [c.niveau for c in conformite.analyser_conformite(EXEMPLE, d)], key=["risque", "verifier", "ok"].index)


def test_conformite_cas_a_risque():
    texte = ("Les factures sont payables à 90 jours date de facture. Le prix est de 1 000 euros HT par mois. "
             "Le contrat est reconduit tacitement chaque année. La révision suit l'indice IPC des prix à la consommation. "
             "Le client peut résilier à tout moment sans motif. La responsabilité du prestataire est limitée à 500 euros.")
    d = analyser_texte(texte).donnees
    par = {c.clause: c for c in conformite.analyser_conformite(texte, d)}
    assert par["Délai de paiement"].niveau == "risque" and "45 jours" in par["Délai de paiement"].probleme
    assert par["Reconduction tacite"].niveau == "risque"  # aucun préavis
    assert par["Indexation"].niveau == "risque"
    assert "Résiliation / droits unilatéraux" in par and "Limitation de responsabilité" in par


def test_demande_claude_et_rapport():
    assert "Légifrance" in conformite.demande_claude("Acme – Lyon") and "Acme – Lyon" in conformite.demande_claude("Acme – Lyon")
    d = analyser_texte(EXEMPLE).donnees
    md = conformite.rapport_markdown("Acme", conformite.analyser_conformite(EXEMPLE, d))
    assert md.startswith("# Contrôle de conformité – Acme") and "Aucune jurisprudence" in md


# --------------------------------------------------------------------------- export agenda immédiat

def test_export_agenda_immediat_sans_enregistrer():
    d = analyser_texte(EXEMPLE).donnees
    ics, alertes = service.ics_depuis_contrat(d, date(2026, 10, 8))
    titres = [a.titre for a in alertes]
    assert "Groupe Acme – Lyon Part-Dieu – Accueil – Fin de contrat (dans 6 mois)" in titres
    assert "Groupe Acme – Lyon Part-Dieu – Accueil – Revalorisation (dans 1 mois)" in titres
    assert all(a.date >= date(2026, 10, 8) for a in alertes)  # la révision à 3 mois est déjà passée
    texte = ics.decode("utf-8")
    assert texte.count("BEGIN:VEVENT") == len(alertes) == texte.count("BEGIN:VALARM")
