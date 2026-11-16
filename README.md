# Assistant PC

Petite appli Windows qui envoie fichiers et consignes au serveur Chat IA maison et affiche la réponse en direct.

## Installer

1. Récupérer `AssistantPC.exe` (onglet **Releases** du dépôt, ou artefact de la dernière compilation).
2. Le placer où l'on veut, par exemple `%LOCALAPPDATA%\AssistantPC\`, et le lancer. Rien d'autre à installer.
   Windows SmartScreen peut avertir la première fois (exe non signé) : « Informations complémentaires » → « Exécuter quand même ».
3. Se connecter. Seul le **jeton** renvoyé par le serveur est gardé, dans le Gestionnaire d'identification
   de Windows (entrée `AssistantPC/jeton`). Le mot de passe n'est jamais enregistré.

## Utiliser

- Icône près de l'horloge : clic pour afficher ou masquer, clic droit pour le menu. Fermer la fenêtre la masque seulement.
- Glisser des fichiers dans la fenêtre (ou **+** → Pièce jointe, ou les coller depuis l'Explorateur) : PDF, Word, Excel, images, texte.
  25 Mo et 10 fichiers au maximum par message. Ils partent au serveur dès le dépôt.
- **+** → **Capture d'écran** : rectangle libre (glisser), fenêtre (cliquer dessus) ou écran entier (miniatures des écrans : cliquer sur celui à capturer, clic droit pour une nouvelle capture de son état actuel).
  Échap ou clic droit pour annuler. La capture devient une pièce jointe PNG, affichée en vignette (clic pour agrandir). Une image copiée se colle aussi avec Ctrl+V.
- Écrire la consigne, **Entrée** pour envoyer, **Maj+Entrée** pour aller à la ligne, **Stop** pour arrêter la réponse.
- **Micro** (sous le trombone) : dictée, micro au choix dans les paramètres. Le texte s'affiche en direct (provisoire, puis figé à chaque pause) ; un visualiseur de spectre (graves à gauche, aigus à droite) s'affiche en haut de la zone de texte. Dans les paramètres, une barre verte montre si le micro choisi capte le son.
  Cliquez de nouveau pour arrêter. Windows doit autoriser les applications de bureau à utiliser le micro.
- **🔎 Recherches** dans une réponse : déplie les recherches web faites et leurs résultats.
- **📋 Copier** sous une réponse : mise en forme conservée dans Word et Outlook, Markdown dans un éditeur de texte.
- Blocs de code : bouton « Copier le code » en haut à droite ; au-delà de 10 lignes, seules les 5 premières
  sont affichées, avec « Afficher tout ».
- **➕** (Ctrl+N) : nouvelle conversation.

## Serveur et sécurité

- Adresse par défaut : `https://192.168.1.41:8443`, à travers le VPN.
- Le certificat maison est **épinglé** par son empreinte SHA-256 (modifiable dans les paramètres quand il sera
  renouvelé). Si l'empreinte ne correspond pas, la connexion est refusée, sans possibilité de passer outre.
- `http://…:8080` reste possible, à saisir à la main, avec un avertissement : tout circule alors en clair.
- Chaque requête porte l'en-tête `X-Client: pc`.
- Aucune autre connexion (hormis la vérification des mises à jour sur GitHub) : pas de télémétrie, pas de proxy système, et aucune
  ressource externe chargée dans les réponses.
- Réglages : `%APPDATA%\AssistantPC\config.json` (sans mot de passe ni jeton).

## Mises à jour

Au démarrage (désactivable dans les paramètres) et via « Vérifier les mises à jour », l'appli consulte la
dernière Release GitHub de `lolzerra/Assistant_Win`. C'est la seule connexion en dehors du serveur maison.
Si une version plus récente existe, elle propose de la télécharger. L'exe est vérifié (taille et SHA-256),
remplacé sur place, puis relancé. Il doit donc se trouver dans un dossier où l'on peut écrire.

## Compiler

Sur un PC Windows avec Python 3.12 (64 bits) :

```bat
build.bat
```

Résultat : `dist\AssistantPC.exe`. Le workflow `.github/workflows/exe.yml` fait la même chose sur GitHub
à chaque envoi sur `main`. Une étiquette `vX.Y.Z` publie en plus l'exe dans une Release.

Pour lancer depuis les sources : `pip install -r requirements.txt` puis `python run.py`.
