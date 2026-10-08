# Contrathèque

Application locale (Windows) pour suivre vos contrats et avenants : échéances, révisions de prix,
dates limites de dénonciation, chiffre d'affaires récurrent. Aucune API, aucune clé : l'analyse du
contrat se fait dans votre Projet claude.ai, vous collez ici le résultat JSON.

## Lancer
Double-cliquez sur **`lancer.bat`** (Python 3.11 ou plus récent requis). Au premier lancement,
l'application installe ce qu'il faut, ouvre votre navigateur et vous demande le **dossier racine
OneDrive** de vos contrats (mémorisé dans `config.toml`).

## Utiliser
1. Onglet **Ajouter un contrat** : collez la réponse de l'analyse (le texte autour du JSON est ignoré ;
   plusieurs blocs collés d'un coup forment un lot traité un par un), déposez le fichier si vous voulez,
   cliquez **Analyser**.
2. Relisez : les **points à vérifier** et les **dates absentes ou douteuses** sont surlignés, la citation
   du contrat est affichée à côté de chaque champ. Cliquez **Valider et enregistrer**.
3. Contrat **multi-site** : l'écran de scission propose une ligne par site + activité (montant, dates et
   alertes propres à chaque ligne). Le bouton reste bloqué tant que les lignes ne sont pas valides.
   Le fichier est copié dans chaque dossier et toutes les lignes restent liées au document d'origine.
4. Onglet **Suivi** : tableau, CA annuel récurrent, 12 mois, échéances à 3/6/12 mois, historique.
   Bandeau **À traiter** en haut (30 jours ou dépassé ; bouton « Traité » pour l'acquitter).
5. Onglet **Révision de prix** : saisissez l'indice publié, l'application calcule un montant suggéré
   et un modèle de courrier. Aucune valeur d'indice n'est inventée.

## Où vont les choses
- Fichiers : `<racine>/<Client>/<Client>_<Site>_<Activite>/Client_Site_Activite_Contrat.pdf`
  (`..._Avenant1.pdf`, etc.). Jamais d'écrasement : `_v2`, `_v3`…
- Rappels : `<racine>/_Calendrier/` (un `.ics` par contrat + `toutes_alertes.ics`), ouvert après chaque
  validation. Option Outlook classique dans la barre latérale (repli automatique sur `.ics`).
- Base : `data/contratheque.db`, sauvegardes datées dans `data/sauvegardes/` (5 conservées).

## Règles de calcul
- Montant sur la durée = montant mensuel × 12 × nombre d'années (annuel ×1, trimestriel ×4).
- Un avenant remplace les champs qu'il renseigne ; l'historique des versions est conservé.
- Alertes : fin de contrat −6 mois ; révision −2 et −1 mois ; dénonciation −1 mois et jour J
  (date limite = échéance − préavis si elle n'est pas écrite).

## Tests
`pip install -r requirements-dev.txt` puis `python -m pytest`.
