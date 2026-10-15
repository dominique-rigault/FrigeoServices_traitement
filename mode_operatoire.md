# Mode opératoire d'un cycle de traitement

Document à l'usage du consultant. Il décrit, dans l'ordre chronologique, ce que font le consultant, le métier du client et l'assistant LLM pour traiter les exports d'un client avec cet outil, jusqu'à l'étape 4 comprise. Il sera complété avec les étapes 5 et suivantes.

## Rôles et règles communes

| Code | Rôle | Ce qu'il fait |
| --- | --- | --- |
| C | Consultant | Dépose les fichiers de configuration, exécute les notebooks, commite, anime la revue avec le métier. |
| M | Métier du client | Fournit les exports, valide ou corrige les propositions (classeur de revue, formulaires de règles). |
| A | Assistant LLM | Rédige les fichiers de configuration, le code générique et ses tests, les parties du rapport. |

Règles valables à chaque étape :

- l'assistant ne reçoit jamais de valeurs des données du client, seulement des décomptes, des noms de tables et de colonnes et des formes (`AA-9999`); ce que le consultant lui transmet passe par une cellule d'export qui le garantit;
- l'accès de l'assistant au poste est limité aux dossiers `src` et `tests`; les fichiers de `config/` et les cellules de notebook sont donnés dans la conversation et déposés par le consultant;
- aucune donnée n'est corrigée à la main : un fichier mal formé est réexporté par le client, ou décrit autrement dans `config/sources.yaml`;
- le métier valide ou corrige des valeurs proposées, il ne les ressaisit pas.

État de chaque étape dans la colonne « État » :

- **opérationnel** : utilisable tel quel chez un autre client;
- **à adapter** : fait sur le cas Frigéo, mais le notebook contient encore des noms, des encodages ou des valeurs propres à ce cas;
- **à créer** : prévu par la séquence, n'existe pas encore.

## Cycle initial (nouveau client)

### Phase 0, préalables

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 0.1 | Encadrer l'usage d'un assistant (accord de confidentialité, RGPD, conditions du fournisseur) | C, M | contrat | hors outil |
| 0.2 | Recopier le dépôt dans un dossier propre au client, dépôt privé, installation (README, rubrique « Installation ») | C | Git, `.venv` | opérationnel |
| 0.3 | Inventorier les exports avec le métier : flux, logiciel d'origine, période couverte par chaque fichier, encodage et séparateur s'ils sont connus, feuilles Excel, ligne d'en-tête | C, M | entretien | hors outil |

### Phase 1, dépôt des fichiers et configuration des sources

Cette phase précède le notebook 01 : `decouvrir` lit `config/sources.yaml` dès la deuxième cellule de chaque notebook, et le chargement en tire encodages, séparateurs et feuilles.

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 1.1 | Déposer les exports selon la convention de nommage : exports périodiques n'importe où sous `data/raw/`, la période dans le nom (`interventions_2025.csv`, `interventions_2026-01.csv`); référentiels dans `data/referentiels/` (à côté de `data/raw/`, pas dedans) | M, C | Explorateur | opérationnel |
| 1.2 | Rédiger `config/sources.yaml` : périodes (`annuelle`, `premier_mois`), puis par flux le motif de nom avec `{p}` (ou le nom du référentiel), l'emplacement, le format, l'encodage, le séparateur, la ligne d'en-tête et les tables (feuille pour Excel) | A, puis C | inventaire 0.3, noms des fichiers | opérationnel |
| 1.3 | Rédiger `config/sensibilite.yaml` : colonnes sensibles par table, proposées d'après les noms de colonnes | A, validé par C et M | en-têtes des fichiers | opérationnel |
| 1.4 | Modifier `perimetre.py` seulement si le client ne suit pas le modèle « une période annuelle puis des mois » (mois seuls, trimestres) | A | code et tests | à créer si nécessaire |

Les périodes ne s'ajoutent pas dans `perimetre.py` : elles se déduisent de `periodes.premier_mois` (dans `config/sources.yaml`) et de `PERIODE_FIN`. Aucun gabarit vierge n'existe pour les deux fichiers YAML : ceux de Frigéo servent d'exemple.

### Phase 2, inventaire et chargement (notebook 01)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 2.1 | Mettre `PERIODE_FIN` au dernier mois déposé | C | notebook 01, cellule 1 | opérationnel |
| 2.2 | Exécuter le notebook en entier; un fichier manquant ou présent à deux endroits arrête la cellule 2 avec la liste des problèmes | C | notebook 01 | à adapter |
| 2.3 | En cas d'échec de décodage, d'en-têtes différents entre deux exports d'un même flux ou de lignes perdues : corriger `config/sources.yaml` (encodage, séparateur, ligne d'en-tête), ou demander un réexport, puis relancer le notebook | C, A, M | notebook 01 | opérationnel |
| 2.4 | Exporter les décomptes des cellules à l'encodage suspect (table, colonne, nombre de cellules, mécanisme), sans les valeurs | C | cellule d'export | à créer |
| 2.5 | Rédiger la partie « cellules à l'encodage suspect » du rapport | A | export 2.4 | opérationnel |

Pourquoi « à adapter » : la cellule de sondage des fichiers texte déclare les flux, encodages et séparateurs de Frigéo dans une fonction `format_declare` au lieu de les lire dans `config/sources.yaml`; les cellules d'encodage suspect visent trois colonnes de Frigéo et affichent les valeurs (des noms de clients); la synthèse en Markdown porte les chiffres de Frigéo.

### Phase 3, profilage (notebook 02)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 3.1 | Mettre `PERIODE_FIN` à jour et exécuter le notebook | C | notebook 02 | à adapter |
| 3.2 | Exporter le profil agrégé (natures, taux de vides, nombre de valeurs distinctes, formes principales), exemples masqués et colonnes sensibles masquées | C | cellule `# EXPORT` | à créer |
| 3.3 | Rédiger la partie « synthèse du profilage » du rapport | A | export 3.2 | opérationnel |
| 3.4 | Si le profil montre une forme de date, d'heure ou de nombre non reconnue (HH:MM:SS, MM/JJ/AAAA, milliers séparés par une espace) : étendre les natures de `profilage.py` et de `typage.py`, avec leurs tests | A, puis C (tests et commit) | `src`, `tests` | à créer si nécessaire |

L'étape 3.4 précède le notebook 02c : la nature proposée au dictionnaire, puis la lecture typée de l'étape 4, reposent sur ces natures.

Pourquoi « à adapter » : les cellules 3 à 15 nomment des tables et des colonnes de Frigéo, il n'existe pas de cellule d'export, et la synthèse en Markdown est celle de Frigéo.

### Phase 4, dictionnaire et revue (notebook 02c)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 4.1 | Ajuster si nécessaire les seuils de génération (200 valeurs, 12 valeurs principales, 95 %, 2 % de vides), par exemple pour un client aux petits référentiels | A | constantes de `dictionnaire.py` | opérationnel (dans le code, pas dans un fichier YAML) |
| 4.2 | Mettre `PERIODE_FIN` à jour et exécuter les cellules jusqu'à `# ECRITURE APRES FUSION` (premier dictionnaire : `# FUSION` affiche « rien à fusionner ») | C | notebook 02c | opérationnel |
| 4.3 | Ne pas exécuter `# COMPARAISON AVEC LE CHAPITRE 4` | C | notebook 02c | à retirer pour un cas réel |
| 4.4 | Exporter le classeur de revue | C | cellule `# EXPORT` | opérationnel |
| 4.5 | Revoir le classeur (feuilles `regles`, `valeurs`, `formes`, mode d'emploi dans la première feuille); une revue partielle suffit pour avancer | M avec C | Excel | opérationnel |
| 4.6 | Appliquer la revue : enregistrer et fermer le classeur, `# IMPORT`, `# APPLICATION`, `# ECRITURE`, supprimer le classeur périmé de `data/revue/`, puis `# EXPORT` pour la revue suivante | C | notebook 02c | opérationnel |

Repères pour la phase 4 :

- `# IMPORT` puis `# APPLICATION` sur un classeur non modifié est sans effet (aucune écriture);
- `# FUSION` et `# ECRITURE APRES FUSION` ne servent qu'à une régénération (un mois de plus, ou une nouvelle version du code de génération); chaque exécution de `# ECRITURE APRES FUSION` sur un dictionnaire revu ajoute une copie de sauvegarde, même si rien n'a changé;
- la revue n'est pas un préalable aux étapes 3 et 4 : une règle non revue est contrôlée et ses écarts portent le statut `observé`;
- la relecture du classeur se fait sans en coller d'extraits dans la conversation.

### Phase 5, règles de contrôle (notebook 03)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 5.1 | Remplir le formulaire des règles de contrôle : décimales, bornes, motif, clé de Luhn par colonne; pour les doublons, la clé de chaque table, les colonnes uniques, les colonnes présumées uniques, les tables où chercher les lignes identiques hors clé | M avec C | formulaire | à créer |
| 5.2 | Rédiger `config/controles.yaml` (clés `regles` et `doublons`) et le vérifier par son chargement | A, puis C (dépôt dans `config/`) | formulaire 5.1 | opérationnel |
| 5.3 | Exécuter le notebook en entier, et vérifier les lignes « N règles complémentaires lues » et « N tables avec des doublons déclarés » (emplacement attendu) | C | notebook 03 | opérationnel |

Une forme fixe (code postal, SIRET, téléphone) ne va pas dans ce formulaire : elle relève de la règle `format` du dictionnaire, décidée à la revue (phase 4).

### Phase 6, règles de gestion (notebook 04)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 6.1 | Remplir le formulaire des règles de gestion (entretiens) : règle en clair, tables concernées, tolérances, délais, horaires, jours fériés, pratiques normales à présenter en information | M avec C | formulaire | à créer |
| 6.2 | Rattacher chaque règle à un type du catalogue (`# TYPES DE REGLES`); pour une règle qui n'entre dans aucun type, proposer un nouveau type générique, faire valider le critère, puis le coder avec ses tests | A, validé par C | `src/frigeo/gestion.py`, `tests` | opérationnel (catalogue limité aux 28 types de Frigéo) |
| 6.3 | Si un seuil est une hypothèse, l'éprouver par une cellule d'essai qui n'affiche que des décomptes, puis la supprimer | A, exécutée par C | notebook 04 | opérationnel |
| 6.4 | Rédiger `config/gestion.yaml` et le vérifier par `problemes_regles_gestion` | A, puis C (dépôt dans `config/`) | formulaire 6.1 | opérationnel |
| 6.5 | Exécuter le notebook en entier; lire le nombre de règles lues et les avertissements (année absente des jours fériés, lignes de référentiel inutilisables) | C | notebook 04 | opérationnel |

Le code d'un type nouveau va dans `src/`, jamais dans le notebook ni dans une fonction propre au client. `config/controles.yaml` doit exister avant le notebook 04 : sa clé `doublons` donne la clé affichée et les doublons écartés des rapprochements.

## Cycle mensuel (un mois de plus)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| M.1 | Déposer les exports du mois (période dans le nom, par exemple dans `data/raw/2026/2026-04/`), et les référentiels s'ils ont changé | M, C | Explorateur | opérationnel |
| M.2 | Mettre `PERIODE_FIN` à jour dans chaque notebook exécuté | C | notebooks 01, 02c, 03, 04 | opérationnel |
| M.3 | Exécuter le notebook 01 (fichiers attendus, en-têtes, lignes chargées) | C | notebook 01 | à adapter |
| M.4 | Exécuter le notebook 02 seulement si un format nouveau est soupçonné | C | notebook 02 | à adapter |
| M.5 | Régénérer le dictionnaire : cellules jusqu'à `# ECRITURE APRES FUSION`, lire le rapport de `# FUSION` (événements « à regarder ») | C | notebook 02c | opérationnel |
| M.6 | Revue si de nouvelles valeurs ou formes sont à arbitrer (phase 4, étapes 4.4 à 4.6) | M avec C | Excel, notebook 02c | opérationnel |
| M.7 | Exécuter les notebooks 03 puis 04 en entier | C | notebooks 03, 04 | opérationnel |

Une fois par an : compléter les jours fériés de l'année suivante dans `config/gestion.yaml` (le notebook 04 avertit quand une année manque) et vérifier que les paramètres annuels du client couvrent la nouvelle année.

## Points ouverts

- **Changement d'année.** Le modèle de périodes garde une période annuelle unique suivie de mois. Le passage à un export annuel de l'année suivante n'est pas prévu.
- **Formulaires.** Les formulaires des règles de contrôle et des règles de gestion restent à concevoir (forme, et passage du formulaire au YAML).
- **Rapport.** Le rapport au client (plan, destinataire, format) n'est pas encore défini; les parties 2.5 et 3.3 en sont les premières briques.
- **Découverte des encodages et séparateurs.** Ils sont déclarés à la main dans `config/sources.yaml`; l'étape qui les proposerait n'est pas faite.
