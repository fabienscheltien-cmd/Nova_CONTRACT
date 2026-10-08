import json

from contratheque.extraction import analyser, analyser_lot, extraire_json, extraire_tous_json

BASE = {"version_schema": 1, "client": "Acme", "site": "Paris", "activite": "Accueil",
        "type_document": "contrat", "montant_ht": 1200.5, "periodicite": "mensuel",
        "date_echeance": "2027-03-31"}


def test_json_dans_texte_bruite_avec_cloture():
    texte = ("Voici {le résultat} de l'analyse :\n```json\n" + json.dumps(BASE, ensure_ascii=False)
             + "\n```\nÀ vérifier : la date {ambiguë}. Cordialement")
    brut, erreur = extraire_json(texte)
    assert erreur is None and brut["client"] == "Acme"


def test_accolades_dans_les_chaines():
    d = {**BASE, "client": "A} {B", "points_a_verifier": ["clause {3.2} floue"]}
    brut, _ = extraire_json("avant " + json.dumps(d) + " après")
    assert brut["client"] == "A} {B"


def test_premier_bloc_seulement():
    deux = json.dumps(BASE) + " puis " + json.dumps({**BASE, "client": "Autre"})
    assert analyser(deux).donnees.client == "Acme"


def test_aucun_json():
    r = analyser("Pas de JSON ici")
    assert r.donnees is None and "Aucun bloc JSON" in r.erreurs[0]


def test_json_casse_ne_renvoie_pas_un_sous_objet():
    casse = '{"version_schema": 1, "client": "A", "indexation": {"indice": "x"}'  # accolade finale manquante
    r = analyser(casse)
    assert r.donnees is None and "mal formé" in r.erreurs[0]


def test_version_inconnue_refusee_proprement():
    r = analyser(json.dumps({**BASE, "version_schema": 2}))
    assert r.donnees is None and "Version de schéma non reconnue" in r.erreurs[0]


def test_version_absente():
    d = dict(BASE)
    del d["version_schema"]
    r = analyser(json.dumps(d))
    assert r.donnees is None and "version_schema" in r.erreurs[0]


def test_erreurs_lisibles_en_francais():
    r = analyser(json.dumps({**BASE, "date_echeance": "31/03/2027", "periodicite": "hebdo",
                             "activite": "Sécurité", "reconduction_tacite": "peut-être"}))
    texte = " ".join(r.erreurs)
    assert r.donnees is None
    assert "AAAA-MM-JJ" in texte and "valeurs possibles" in texte and "vrai ou faux" in texte


def test_date_inexistante():
    r = analyser(json.dumps({**BASE, "date_echeance": "2027-02-30"}))
    assert "n'est pas une date" in r.erreurs[0]


def test_tolerances():
    d = {**BASE, "activite": "hospitalite", "montant_ht": "1 200,50 €", "reconduction_tacite": "Oui",
         "champ_inconnu": 1, "indexation": None, "preuves": None, "points_a_verifier": None}
    r = analyser(json.dumps(d))
    assert not r.erreurs
    assert r.donnees.activite == "Hospitalité" and r.donnees.montant_ht == 1200.5
    assert r.donnees.reconduction_tacite is True and r.donnees.points_a_verifier == []


def test_multi_site_et_sites_detectes():
    d = {**BASE, "site": None, "activite": None, "multi_site": True,
         "sites_detectes": ["Paris", {"site": "Lyon", "activite": "Conciergerie", "montant_ht": 900,
                                      "periodicite": "mensuel", "preuve": "Lyon : 900 €"}]}
    r = analyser(json.dumps(d))
    assert not r.erreurs and r.donnees.multi_site
    assert [s.site for s in r.donnees.sites_detectes] == ["Paris", "Lyon"]
    assert r.donnees.sites_detectes[1].preuve == "Lyon : 900 €"


def test_lot_de_plusieurs_blocs():
    texte = ("Contrat 1 :\n```json\n" + json.dumps(BASE) + "\n```\nContrat 2 :\n```json\n"
             + json.dumps({**BASE, "client": "Beta"}) + "\n```")
    blocs, erreur = extraire_tous_json(texte)
    assert erreur is None and [b["client"] for b in blocs] == ["Acme", "Beta"]
    assert [r.donnees.client for r in analyser_lot(texte)] == ["Acme", "Beta"]


def test_lot_signale_le_bloc_invalide():
    texte = json.dumps(BASE) + json.dumps({**BASE, "version_schema": 9})
    lot = analyser_lot(texte)
    assert lot[0].ok and not lot[1].ok
