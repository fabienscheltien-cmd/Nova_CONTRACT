import json
from datetime import date

import pytest

from contratheque import db, multisite, service
from contratheque.controles import diagnostiquer_dates
from contratheque.extraction import analyser
from datetime import datetime, timedelta

AUJ = date(2026, 10, 8)

CONTRAT = {"version_schema": 1, "client": "Acme", "site": "Paris", "activite": "Accueil",
           "type_document": "contrat", "montant_ht": 1000, "periodicite": "mensuel",
           "date_effet": "2026-01-01", "date_echeance": "2027-12-31", "duree_mois": 24,
           "preavis_denonciation_jours": 90,
           "indexation": {"indice": "Syntec", "date_revision": "2027-01-01"}}


@pytest.fixture
def conn(tmp_path):
    c = db.connecter(tmp_path / "data" / "c.db")
    db.initialiser(c)
    return c


def contrat(**kw):
    r = analyser(json.dumps({**CONTRAT, **kw}))
    assert not r.erreurs, r.erreurs
    return r


def test_enregistrement_complet_et_revalidation_sans_doublon(conn, tmp_path):
    racine = tmp_path / "OneDrive"
    racine.mkdir()
    r = contrat()
    res = service.enregistrer_contrat(conn, racine, r.donnees, ("scan.pdf", b"%PDF"), r.json_texte,
                                      aujourdhui=AUJ, ouvrir=None)
    assert res.version == 1
    assert res.chemin_fichier == racine / "Acme" / "Acme_Paris_Accueil" / "Acme_Paris_Accueil_Contrat.pdf"
    assert res.chemin_fichier.read_bytes() == b"%PDF"
    assert db.nombre_alertes(conn) == 5  # fin, 2 révisions, 2 dénonciations (calculée)
    assert (racine / "_Calendrier" / "Acme_Paris_Accueil.ics").exists()

    # nouvelle validation : version 2, fichier non écrasé, alertes mises à jour sans doublon
    r2 = contrat(date_echeance="2028-12-31")
    res2 = service.enregistrer_contrat(conn, racine, r2.donnees, ("scan.pdf", b"%PDF2"), r2.json_texte,
                                       aujourdhui=AUJ, ouvrir=None)
    assert res2.version == 2 and res2.chemin_fichier.name.endswith("_v2.pdf")
    assert res.chemin_fichier.read_bytes() == b"%PDF"
    assert db.nombre_alertes(conn) == 5
    assert res2.sync.bilan.nouvelles == 0 and res2.sync.bilan.modifiees >= 1
    ics = (racine / "_Calendrier" / "toutes_alertes.ics").read_bytes().decode("utf-8")
    assert ics.count("BEGIN:VEVENT") == 5
    courants = db.lignes_courantes(conn)
    assert len(courants) == 1 and courants[0]["version"] == 2
    assert len(db.historique(conn, courants[0]["cle"])) == 2


def test_sans_fichier(conn, tmp_path):
    r = contrat()
    res = service.enregistrer_contrat(conn, tmp_path, r.donnees, None, r.json_texte, aujourdhui=AUJ, ouvrir=None)
    assert res.chemin_fichier is None
    assert db.lignes_courantes(conn)[0]["chemin_fichier"] is None


def test_avenant_numerote_et_rattache(conn, tmp_path):
    r = contrat()
    service.enregistrer_contrat(conn, tmp_path, r.donnees, None, None, aujourdhui=AUJ, ouvrir=None)
    av = contrat(type_document="avenant", montant_ht=1100, date_echeance=None, date_effet="2027-01-01",
                 contrat_parent="Contrat Acme")
    res = service.enregistrer_contrat(conn, tmp_path, av.donnees, ("av.docx", b"x"), None, aujourdhui=AUJ, ouvrir=None)
    assert res.numero_avenant == 1 and res.chemin_fichier.name == "Acme_Paris_Accueil_Avenant1.docx"
    from contratheque import suivi
    s = suivi.situations(conn)
    assert len(s) == 1 and s[0]["montant_ht"] == 1100 and s[0]["date_echeance"] == "2027-12-31"
    assert len(db.historique(conn, s[0]["cle"])) == 2


def test_refus_si_identite_incomplete(conn, tmp_path):
    r = contrat(activite=None)
    with pytest.raises(ValueError):
        service.enregistrer_contrat(conn, tmp_path, r.donnees, None, None, aujourdhui=AUJ, ouvrir=None)


# --------------------------------------------------------------------------- multi-site

MULTI = {**CONTRAT, "site": None, "activite": None, "montant_ht": None, "multi_site": True,
         "sites_detectes": [
             {"site": "Paris", "activite": "Accueil", "montant_ht": 1000, "periodicite": "mensuel", "preuve": "P : 1000"},
             {"site": "Lyon", "activite": "Accueil", "montant_ht": 800, "periodicite": "mensuel"},
             {"site": "Lyon", "activite": "Conciergerie", "montant_ht": None}]}


def commun_depuis(d):
    return {k: v for k, v in d.items() if k not in ("sites_detectes", "multi_site")}


def test_scission_valide_et_bloque():
    r = analyser(json.dumps(MULTI))
    lignes = multisite.lignes_initiales(r.donnees)
    assert len(lignes) == 3 and lignes[2]["montant_ht"] is None  # jamais de répartition inventée
    contrats, erreurs = multisite.scinder(commun_depuis(MULTI), lignes)
    assert not erreurs and len(contrats) == 3
    assert contrats[2].montant_ht is None and contrats[0].preuves["ligne"] == "P : 1000"
    # une seule ligne : bloqué
    _, erreurs = multisite.scinder(commun_depuis(MULTI), lignes[:1])
    assert any("au moins 2 lignes" in e for e in erreurs)
    # doublon site + activité
    _, erreurs = multisite.scinder(commun_depuis(MULTI), [lignes[0], dict(lignes[0])])
    assert any("déjà utilisé" in e for e in erreurs)
    # activité manquante
    _, erreurs = multisite.scinder(commun_depuis(MULTI), [lignes[0], {**lignes[1], "activite": None}])
    assert any("activité" in e for e in erreurs)
    # date invalide dans une ligne
    _, erreurs = multisite.scinder(commun_depuis(MULTI), [lignes[0], {**lignes[1], "date_echeance": "31/12/2027"}])
    assert any(e.startswith("Ligne 2") and "AAAA-MM-JJ" in e for e in erreurs)


def test_date_limite_non_heritee_si_echeance_differente():
    lignes = multisite.lignes_initiales(analyser(json.dumps(MULTI)).donnees)
    commun = {**commun_depuis(MULTI), "date_limite_denonciation": "2027-10-02"}
    lignes[1]["date_echeance"] = "2028-06-30"
    contrats, _ = multisite.scinder(commun, lignes)
    assert contrats[0].date_limite_denonciation.isoformat() == "2027-10-02"
    assert contrats[1].date_limite_denonciation is None  # sera calculée : échéance − préavis


def test_enregistrement_multisite(conn, tmp_path):
    racine = tmp_path / "OD"
    racine.mkdir()
    r = analyser(json.dumps(MULTI))
    contrats, erreurs = multisite.scinder(commun_depuis(MULTI), multisite.lignes_initiales(r.donnees))
    assert not erreurs
    res = service.enregistrer_multisite(conn, racine, contrats, ("contrat.pdf", b"PDF"), r.json_texte,
                                        aujourdhui=AUJ, ouvrir=None)
    assert len(res) == 3
    # le fichier est copié dans chaque dossier Client_Site_Activite
    for site, act in (("Paris", "Accueil"), ("Lyon", "Accueil"), ("Lyon", "Conciergerie")):
        p = racine / "Acme" / f"Acme_{site}_{act}" / f"Acme_{site}_{act}_Contrat.pdf"
        assert p.read_bytes() == b"PDF"
    lignes = db.lignes_courantes(conn)
    assert len(lignes) == 3
    assert len({l["groupe_origine"] for l in lignes}) == 1 and lignes[0]["groupe_origine"]
    assert {l["fichier_origine"] for l in lignes} == {"contrat.pdf"}
    assert {l["montant_ht"] for l in lignes} == {1000, 800, None}
    # alertes par enregistrement : 3 × 5, agenda regroupé : 5 événements
    assert db.nombre_alertes(conn) == 15
    ics = (racine / "_Calendrier" / "toutes_alertes.ics").read_bytes().decode("utf-8")
    assert ics.count("BEGIN:VEVENT") == 5
    assert "3 sites" in ics.replace("\r\n ", "")
    for site in ("Paris", "Lyon"):
        assert site in ics.replace("\r\n ", "")
    assert len(list((racine / "_Calendrier").glob("Acme_MultiSites_*.ics"))) == 1
    # revalider ne duplique rien
    service.mettre_a_jour(conn, racine, aujourdhui=AUJ)
    assert db.nombre_alertes(conn) == 15
    assert (racine / "_Calendrier" / "toutes_alertes.ics").read_bytes().decode("utf-8").count("BEGIN:VEVENT") == 5


def test_multisite_tout_ou_rien(conn, tmp_path):
    r = analyser(json.dumps(MULTI))
    contrats, _ = multisite.scinder(commun_depuis(MULTI), multisite.lignes_initiales(r.donnees))
    contrats[2] = contrats[2].model_copy(update={"activite": None})  # invalide : échoue à la 3e ligne
    with pytest.raises(ValueError):
        service.enregistrer_multisite(conn, tmp_path, contrats, ("c.pdf", b"x"), None, aujourdhui=AUJ, ouvrir=None)
    assert db.lignes_courantes(conn) == []
    assert list(tmp_path.rglob("*.pdf")) == []  # fichiers déjà copiés retirés


def test_multisite_refuse_une_seule_ligne(conn, tmp_path):
    r = contrat()
    with pytest.raises(ValueError):
        service.enregistrer_multisite(conn, tmp_path, [r.donnees], None, None, aujourdhui=AUJ, ouvrir=None)


# --------------------------------------------------------------------------- base et contrôles

def test_sauvegarde_5_conservees(tmp_path):
    chemin = tmp_path / "c.db"
    c = db.connecter(chemin)
    db.initialiser(c)
    c.close()
    debut = datetime(2026, 1, 1, 10, 0, 0)
    for k in range(8):
        db.sauvegarder_base(chemin, tmp_path / "sauv", garder=5, maintenant=debut + timedelta(seconds=k))
    restants = sorted(p.name for p in (tmp_path / "sauv").glob("*.db"))
    assert len(restants) == 5 and restants[-1].endswith("100007.db")
    assert db.sauvegarder_base(tmp_path / "absent.db", tmp_path / "sauv") is None


def test_diagnostic_dates():
    base = {"date_effet": "2026-01-01", "date_echeance": "2027-12-31", "date_limite_denonciation": None,
            "date_revision": None, "preavis_denonciation_jours": 90, "indexation_presente": True}
    d = diagnostiquer_dates(base, ["Date de révision ambiguë"], {"date_echeance": "art. 3", "indexation": "art. 7"})
    assert "date_revision" in d  # nulle
    assert "date_limite_denonciation" not in d  # calculable : échéance − préavis
    d = diagnostiquer_dates({**base, "date_echeance": "2025-12-31"}, [], {})
    assert any("antérieure" in m for m in d["date_echeance"])
    d = diagnostiquer_dates({**base, "date_echeance": "31/12/2027"}, [], {})
    assert any("illisible" in m for m in d["date_echeance"])
    d = diagnostiquer_dates({**base, "date_limite_denonciation": "2027-12-01"}, [], {})
    assert any("échéance − préavis" in m for m in d["date_limite_denonciation"])
    d = diagnostiquer_dates({**base, "date_limite_denonciation": "2027-10-02"},
                            ["Le préavis est contradictoire"], {"date_echeance": "x"})
    assert any("points à vérifier" in m for m in d["date_limite_denonciation"])
