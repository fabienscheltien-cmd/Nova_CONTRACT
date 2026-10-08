from datetime import date

import pytest

from contratheque import revision, suivi
from contratheque.outils import cle_contrat

AUJ = date(2026, 10, 8)


def sit(**kw):
    base = {"cle": cle_contrat("Acme", "Paris", "Accueil"), "client": "Acme", "site": "Paris",
            "activite": "Accueil", "montant_ht": 1000.0, "periodicite": "mensuel", "devise": "EUR",
            "date_effet": "2026-01-01", "date_echeance": None, "duree_mois": None, "reconduction_tacite": None,
            "date_revision": None, "date_limite_denonciation": None, "preavis_denonciation_jours": None}
    return {**base, **kw}


def test_valeur_sur_duree_mensuel_3_ans():
    s = sit(duree_mois=36)
    assert suivi.ca_annuel(s) == 12000
    assert suivi.valeur_sur_duree(s) == 36000  # 1000 × 12 mois × 3 ans


def test_valeur_annuel_trimestriel_ponctuel():
    assert suivi.valeur_sur_duree(sit(periodicite="annuel", montant_ht=5000, duree_mois=24)) == 10000
    assert suivi.valeur_sur_duree(sit(periodicite="trimestriel", montant_ht=3000, duree_mois=12)) == 12000
    assert suivi.valeur_sur_duree(sit(periodicite="ponctuel", montant_ht=800)) == 800
    assert suivi.ca_annuel(sit(periodicite="ponctuel")) == 0


def test_duree_deduite_des_dates():
    s = sit(date_effet="2026-01-01", date_echeance="2028-12-31")
    assert suivi.duree_effective_mois(s) == 36
    assert suivi.valeur_sur_duree(s) == 36000


def test_ca_total_et_par_client():
    sits = [sit(), sit(cle="b", client="Beta", montant_ht=500, periodicite="annuel"),
            sit(cle="c", client="Acme", montant_ht=100, date_echeance="2026-01-31"),  # échu
            sit(cle="d", client="Acme", montant_ht=100, date_echeance="2026-01-31", reconduction_tacite=True)]
    assert suivi.ca_total(sits, AUJ) == 12000 + 500 + 1200
    assert suivi.ca_par_client(sits, AUJ) == {"Acme": 13200, "Beta": 500}


def test_ca_mensuel_12_mois():
    mensuel = suivi.ca_mensuel([sit(date_echeance="2027-01-31")], AUJ)
    assert len(mensuel) == 12 and mensuel[0][0] == date(2026, 10, 1)
    assert [round(v) for _, v in mensuel[:4]] == [1000, 1000, 1000, 1000]  # oct à janvier
    assert mensuel[4][1] == 0


def test_avenant_fusionne_sans_ecraser_l_historique():
    contrat = {**sit(), "type_document": "contrat", "numero_avenant": None, "id": 1}
    avenant = {**sit(montant_ht=1100.0, date_echeance="2028-06-30", date_effet="2027-01-01", periodicite=None,
                     devise=None),
               "type_document": "avenant", "numero_avenant": 1, "id": 2}
    contrat["date_echeance"] = "2027-12-31"
    contrat["date_limite_denonciation"] = "2027-09-30"
    s = suivi.fusionner([contrat, avenant])
    assert s["montant_ht"] == 1100 and s["periodicite"] == "mensuel" and s["date_effet"] == "2026-01-01"
    assert s["date_echeance"] == "2028-06-30" and s["date_limite_denonciation"] is None  # à recalculer
    assert s["nb_avenants"] == 1


def test_jalons_a_traiter_et_timeline():
    s = sit(date_echeance="2026-10-20", date_revision="2026-09-01", preavis_denonciation_jours=60)
    a_faire = suivi.a_traiter([s], set(), AUJ)
    assert {j.type for j in a_faire} == {"echeance", "revision", "denonciation"}  # révision dépassée, dénonciation dépassée
    traites = {j.identifiant for j in a_faire if j.type == "revision"}
    assert {j.type for j in suivi.a_traiter([s], traites, AUJ)} == {"echeance", "denonciation"}
    assert [j.type for j in suivi.timeline([s], AUJ, 3)] == ["echeance"]


def test_revision_montant():
    assert revision.montant_revise(1000, 100, 103) == 1030.0
    assert revision.montant_revise(1000, 100, 110, part_fixe_pct=20) == 1080.0
    with pytest.raises(ValueError):
        revision.montant_revise(1000, 0, 103)
    assert revision.extraire_nombre("123,45") == 123.45
    assert revision.extraire_nombre("Syntec août 2025") is None  # rien n'est inventé


def test_courrier():
    texte = revision.modele_courrier(
        client="Acme", site="Paris", activite="Accueil", date_revision="2027-01-01", indice="Syntec",
        indice_reference=100.0, indice_nouveau=103.0, ancien_montant=1000.0, nouveau_montant=1030.0,
        periodicite="mensuel", devise="EUR", formule=None)
    assert "Syntec nouveau : 103,00" in texte and "+3,00 %" in texte and "01/01/2027" in texte
