from datetime import date

from contratheque.alertes import calculer_alertes, date_limite_denonciation, fusionner_alertes, uid_alerte
from contratheque.outils import ajouter_mois, cle_contrat


def sit(**kw):
    base = {"cle": cle_contrat("Acme", "Paris", "Accueil"), "client": "Acme", "site": "Paris",
            "activite": "Accueil", "montant_ht": 1000.0, "periodicite": "mensuel", "devise": "EUR",
            "date_echeance": None, "date_revision": None, "date_limite_denonciation": None,
            "preavis_denonciation_jours": None, "groupe_origine": None}
    return {**base, **kw}


def par_type(alertes):
    return {a.type: a.date for a in alertes}


def test_ajouter_mois_fins_de_mois():
    assert ajouter_mois(date(2027, 3, 31), -1) == date(2027, 2, 28)
    assert ajouter_mois(date(2028, 3, 31), -1) == date(2028, 2, 29)  # bissextile
    assert ajouter_mois(date(2028, 2, 29), 12) == date(2029, 2, 28)
    assert ajouter_mois(date(2028, 8, 31), -6) == date(2028, 2, 29)
    assert ajouter_mois(date(2026, 8, 31), -6) == date(2026, 2, 28)
    assert ajouter_mois(date(2026, 1, 31), -2) == date(2025, 11, 30)  # passage d'année
    assert ajouter_mois(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_alertes_echeance_revision_denonciation():
    a = par_type(calculer_alertes(sit(date_echeance="2027-03-31", date_revision="2027-03-31",
                                      date_limite_denonciation="2026-12-31")))
    assert a == {
        "fin_6m": date(2026, 9, 30), "fin_3m": date(2026, 12, 31),
        "revision_3m": date(2026, 12, 31), "revision_1m": date(2027, 2, 28),
        "denonciation_1m": date(2026, 11, 30), "denonciation_jour": date(2026, 12, 31),
    }


def test_titre_nom_du_contrat_et_theme():
    titres = {a.type: a.titre for a in calculer_alertes(sit(date_echeance="2027-03-31", date_revision="2027-03-31"))}
    assert titres["revision_3m"] == "Acme – Paris – Accueil – Revalorisation (dans 3 mois)"
    assert titres["fin_6m"] == "Acme – Paris – Accueil – Fin de contrat (dans 6 mois)"
    assert titres["fin_3m"].endswith("Fin de contrat (dans 3 mois)")


def test_alertes_annee_bissextile():
    a = par_type(calculer_alertes(sit(date_echeance="2028-08-31", date_revision="2028-04-30")))
    assert a["fin_6m"] == date(2028, 2, 29)
    assert a["fin_3m"] == date(2028, 5, 31)
    assert a["revision_3m"] == date(2028, 1, 30) and a["revision_1m"] == date(2028, 3, 30)


def test_date_limite_calculee_si_absente():
    s = sit(date_echeance="2027-03-31", preavis_denonciation_jours=90)
    assert date_limite_denonciation(s) == (date(2026, 12, 31), True)
    a = par_type(calculer_alertes(s))
    assert a["denonciation_jour"] == date(2026, 12, 31) and a["denonciation_1m"] == date(2026, 11, 30)


def test_date_limite_declaree_prioritaire():
    s = sit(date_echeance="2027-03-31", preavis_denonciation_jours=90, date_limite_denonciation="2026-12-15")
    assert date_limite_denonciation(s) == (date(2026, 12, 15), False)


def test_pas_de_dates_pas_d_alertes():
    assert calculer_alertes(sit()) == []
    assert calculer_alertes(sit(date_echeance="2027-03-31", preavis_denonciation_jours=None))[0].type == "fin_6m"


def test_uid_stable_quand_la_date_change():
    a1 = calculer_alertes(sit(date_echeance="2027-03-31"))[0]
    a2 = calculer_alertes(sit(date_echeance="2028-03-31"))[0]
    assert a1.uid == a2.uid and a1.date != a2.date
    assert uid_alerte("x", "fin_6m") != uid_alerte("y", "fin_6m")


def test_regroupement_agenda_multi_site():
    sites = [("Paris", "Accueil"), ("Lyon", "Accueil"), ("Lille", "Conciergerie")]
    alertes = []
    for site, act in sites:
        alertes += calculer_alertes(sit(cle=cle_contrat("Acme", site, act), site=site, activite=act,
                                        date_echeance="2027-03-31", groupe_origine="abc123def456"))
    assert len(alertes) == 6  # fin_6m et fin_3m pour chacun des 3 enregistrements
    agenda = fusionner_alertes(alertes)
    assert len(agenda) == 2
    fin6 = next(a for a in agenda if a.type == "fin_6m")
    assert fin6.titre == "Acme (3 sites) – Fin de contrat (dans 6 mois)"
    for site, _ in sites:
        assert site in fin6.description
    assert fin6.uid == min(a.uid for a in alertes if a.type == "fin_6m")  # stable


def test_pas_de_regroupement_si_dates_differentes_ou_sans_origine():
    a = calculer_alertes(sit(cle="a|b|c", site="Paris", date_echeance="2027-03-31", groupe_origine="o1"))
    b = calculer_alertes(sit(cle="d|e|f", site="Lyon", date_echeance="2027-04-30", groupe_origine="o1"))
    assert len(fusionner_alertes(a + b)) == 4
    c = calculer_alertes(sit(cle="g|h|i", date_echeance="2027-03-31"))
    d = calculer_alertes(sit(cle="j|k|l", date_echeance="2027-03-31"))
    assert len(fusionner_alertes(c + d)) == 4
