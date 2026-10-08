from datetime import date, datetime, timezone

from contratheque.alertes import Alerte, calculer_alertes
from contratheque.calendrier import GraphCalendrier, IcsCalendrier, OutlookCom, generer_ics
from contratheque.outils import cle_contrat

MAINTENANT = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def alerte(uid="u1", d=date(2027, 1, 31), titre="Titre, avec; virgule", groupe="Acme_Paris_Accueil"):
    return Alerte(uid, "cle", groupe, "fin_6m", d, titre, "Ligne 1\nLigne 2")


def uids(ics):
    return [l[4:] for l in ics.split("\r\n") if l.startswith("UID:")]


def test_structure_et_rappel():
    ics = generer_ics([alerte(), alerte("u2")], MAINTENANT)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 2 and ics.count("BEGIN:VALARM") == 2
    assert "DTSTART;VALUE=DATE:20270131" in ics and "DTEND;VALUE=DATE:20270201" in ics
    assert "TRIGGER:-PT15H" in ics
    assert "SUMMARY:Titre\\, avec\\; virgule" in ics and "Ligne 1\\nLigne 2" in ics


def test_lignes_pliees_75_octets():
    ics = generer_ics([alerte(titre="é" * 120)], MAINTENANT)
    for ligne in ics.split("\r\n"):
        assert len(ligne.encode("utf-8")) <= 75
    # le texte dé-plié est intact
    assert ("é" * 120) in ics.replace("\r\n ", "")


def test_pas_de_doublon_meme_uid():
    ics = generer_ics([alerte(), alerte(d=date(2027, 5, 1))], MAINTENANT)
    assert uids(ics) == ["u1"]


def test_regeneration_met_a_jour_sans_dupliquer():
    avant = generer_ics([alerte("u1", date(2027, 1, 31)), alerte("u2")], MAINTENANT)
    apres = generer_ics([alerte("u1", date(2027, 3, 1)), alerte("u2")], MAINTENANT)
    assert sorted(uids(avant)) == sorted(uids(apres)) == ["u1", "u2"]
    assert "DTSTART;VALUE=DATE:20270301" in apres


def test_calendrier_ics_fichiers(tmp_path):
    cal = IcsCalendrier(tmp_path / "_Calendrier")
    a = [alerte("u1", groupe="A_B_C"), alerte("u2", groupe="D_E_F"), alerte("u3", d=date(2020, 1, 1), groupe="G_H_I")]
    r = cal.synchroniser(a, {}, date(2026, 10, 8), MAINTENANT)
    noms = sorted(p.name for p in (tmp_path / "_Calendrier").glob("*.ics"))
    assert noms == ["A_B_C.ics", "D_E_F.ics", "toutes_alertes.ics"]  # G_H_I : alerte passée, pas de fichier
    glob_ = (tmp_path / "_Calendrier" / "toutes_alertes.ics").read_bytes().decode("utf-8")
    assert uids(glob_) == ["u1", "u2"] and len(r.fichiers) == 3
    # deuxième passe : rien ne se duplique, un contrat disparu voit son .ics supprimé
    cal.synchroniser(a[:1], {}, date(2026, 10, 8), MAINTENANT)
    assert sorted(p.name for p in (tmp_path / "_Calendrier").glob("*.ics")) == ["A_B_C.ics", "toutes_alertes.ics"]
    assert uids((tmp_path / "_Calendrier" / "toutes_alertes.ics").read_bytes().decode("utf-8")) == ["u1"]


def test_ics_depuis_alertes_reelles():
    s = {"cle": cle_contrat("Acme", "Paris", "Accueil"), "client": "Acme", "site": "Paris", "activite": "Accueil",
         "montant_ht": 1000.0, "periodicite": "mensuel", "devise": "EUR", "date_echeance": "2027-03-31",
         "date_revision": "2027-03-31", "date_limite_denonciation": None, "preavis_denonciation_jours": 90}
    ics = generer_ics(calculer_alertes(s) + calculer_alertes(s), MAINTENANT)
    assert len(uids(ics)) == len(set(uids(ics))) == 6


def test_outlook_absent_sans_erreur_et_graph_non_implemente():
    assert OutlookCom().disponible() is False  # hors Windows : repli sur .ics, sans exception
    assert GraphCalendrier().disponible() is False
