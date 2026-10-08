# Contrathèque

Application locale (Windows) pour suivre vos contrats et avenants : échéances, révisions de prix,
dates limites de dénonciation, chiffre d'affaires récurrent. Aucune API, aucune clé : l'analyse du
contrat se fait dans votre Projet claude.ai, vous collez ici le résultat JSON.

## Lancer
Double-cliquez sur **`lancer.bat`** (Python 3.11 ou plus récent requis). Au premier lancement,
l'application installe ce qu'il faut, ouvre votre navigateur et vous demande le **dossier racine
OneDrive** de vos contrats (mémorisé dans `config.toml`).

## Utiliser
1. Onglet **Ajouter un contrat**, au choix :
   - **glissez-déposez le contrat** (PDF, Word `.docx` ou `.txt`) : le texte est lu sur votre ordinateur et
     les champs sont pré-remplis (client, site, activité, montant, dates, durée, reconduction, préavis,
     indexation) avec la phrase du contrat qui justifie chaque valeur ; **ou**
   - collez la réponse de l'analyse claude.ai (le texte autour du JSON est ignoré ; plusieurs blocs collés
     d'un coup forment un lot traité un par un), avec ou sans fichier, puis **Analyser le JSON collé**.
   Le pré-remplissage automatique fonctionne par règles de lecture, pas par IA : il peut se tromper ou
   passer à côté d'une clause. Tout ce qui est converti ou calculé est signalé dans « points à vérifier ».
   Un PDF scanné (sans texte) est refusé avec un message clair.
2. Relisez : les **points à vérifier** et les **dates absentes ou douteuses** sont surlignés, la citation
   du contrat est affichée à côté de chaque champ. Cliquez **Valider et enregistrer**.
3. Contrat **multi-site** : l'écran de scission propose une ligne par site + activité (montant, dates et
   alertes propres à chaque ligne). Le bouton reste bloqué tant que les lignes ne sont pas valides.
   Le fichier est copié dans chaque dossier et toutes les lignes restent liées au document d'origine.
4. Dès le fichier lu, deux panneaux s'affichent :
   - **Alertes agenda** : bouton « Ajouter ces alertes à mon agenda (.ics) » (sans enregistrer). Événements
     nommés « Nom du contrat – Thème (délai) » : Fin de contrat (6 et 3 mois avant), Revalorisation (3 et
     1 mois avant), Dénonciation (1 mois avant et jour J), avec rappel la veille à 9 h.
   - **Contrôle de conformité** (droit français) : clause par clause, risques et recommandations, avec liens
     Légifrance. Règles écrites à l'avance, articles relus sur Légifrance le 2026-10-08. **L'application ne
     cherche pas de jurisprudence** : pour cela, une demande prête à coller est fournie pour votre Projet
     claude.ai (connecteur Légifrance). Ce n'est pas un avis juridique.
5. Onglet **Suivi** : tableau, CA annuel récurrent, 12 mois, échéances à 3/6/12 mois, historique.
   Bandeau **À traiter** en haut (30 jours ou dépassé ; bouton « Traité » pour l'acquitter).
6. Onglet **Révision de prix** : saisissez l'indice publié, l'application calcule un montant suggéré
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
- Alertes : fin de contrat −6 et −3 mois ; révision −3 et −1 mois ; dénonciation −1 mois et jour J
  (date limite = échéance − préavis si elle n'est pas écrite).

## Tests
`pip install -r requirements-dev.txt` puis `python -m pytest`.
