from contratheque.rangement import dossier_contrat, nom_fichier, normaliser, ranger_fichier


def test_normaliser():
    assert normaliser("Société Générale") == "Societe-Generale"
    assert normaliser("  Hôtel du Parc / Lyon  ") == "Hotel-du-Parc-Lyon"
    assert normaliser("") == "Inconnu" and normaliser(None) == "Inconnu"
    assert normaliser("CON").upper() != "CON"  # nom réservé Windows
    assert "/" not in normaliser("a/b\\c:d*e?")


def test_nom_fichier():
    assert nom_fichier("Société Générale", "Tour Défense", "Hospitalité", "contrat", None, ".PDF") \
        == "Societe-Generale_Tour-Defense_Hospitalite_Contrat.pdf"
    assert nom_fichier("Acme", "Paris", "Accueil", "avenant", 2, "docx") == "Acme_Paris_Accueil_Avenant2.docx"


def test_dossier(tmp_path):
    assert dossier_contrat(tmp_path, "Acme", "Paris 8", "Accueil") == tmp_path / "Acme" / "Acme_Paris-8_Accueil"


def test_ne_jamais_ecraser(tmp_path):
    args = (tmp_path, "Acme", "Paris", "Accueil", "contrat", None, "scan.pdf")
    p1 = ranger_fichier(*args, b"un")
    p2 = ranger_fichier(*args, b"deux")
    p3 = ranger_fichier(*args, b"trois")
    assert p1.name == "Acme_Paris_Accueil_Contrat.pdf"
    assert p2.name == "Acme_Paris_Accueil_Contrat_v2.pdf"
    assert p3.name == "Acme_Paris_Accueil_Contrat_v3.pdf"
    assert (p1.read_bytes(), p2.read_bytes(), p3.read_bytes()) == (b"un", b"deux", b"trois")
    assert p1.parent == tmp_path / "Acme" / "Acme_Paris_Accueil"
