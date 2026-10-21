# Mode opératoire d'un cycle de traitement

Document à l'usage du consultant. Il décrit, dans l'ordre chronologique, ce que font le consultant, le métier du client et l'assistant LLM pour traiter les exports d'un client avec cet outil, jusqu'à l'étape 6 comprise. Il sera complété avec les étapes 7 et suivantes.

## Rôles et règles communes

| Code | Rôle | Ce qu'il fait |
| --- | --- | --- |
| C | Consultant | Dépose les fichiers de configuration, exécute les notebooks, commite, anime la revue avec le métier. |
| M | Métier du client | Fournit les exports, valide ou corrige les propositions (classeur de revue, formulaires de règles), tranche les éléments du classeur d'arbitrage. |
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
| 1.2 | Rédiger `config/sources.yaml` : périodes (`annuelle`, `premier_mois`), puis par flux le motif de nom avec `{p}` (ou le nom du référentiel), l'emplacement, le format, l'encodage, le séparateur, la ligne d'en-tête et les tables (feuille pour Excel); `{p}` n'est pas une expression régulière mais un emplacement remplacé par chaque période du périmètre (`2025`, `2026-01`, etc.), et `motif_annuel` donne au besoin un autre nom à l'export annuel | A, puis C | inventaire 0.3, noms des fichiers | opérationnel |
| 1.3 | Rédiger `config/sensibilite.yaml` : colonnes sensibles par table, proposées d'après les noms de colonnes | A, validé par C et M | en-têtes des fichiers | opérationnel |
| 1.4 | Modifier `perimetre.py` seulement si le client ne suit pas le modèle « une période annuelle puis des mois » (mois seuls, trimestres) | A | code et tests | à créer si nécessaire |

Les périodes ne s'ajoutent pas dans `perimetre.py` : elles se déduisent de `periodes.premier_mois` (dans `config/sources.yaml`) et de `PERIODE_FIN`. Aucun gabarit vierge n'existe pour les deux fichiers YAML : ceux de Frigéo servent d'exemple.

### Phase 2, inventaire et chargement (notebook 01)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 2.1 | Mettre `PERIODE_FIN` au dernier mois déposé | C | notebook 01, première cellule de code | opérationnel |
| 2.2 | Exécuter le notebook en entier; un fichier manquant ou présent à deux endroits arrête la cellule `# PERIMETRE` avec la liste des problèmes; lire les décomptes de `# SONDAGE` (échecs de décodage, feuilles non déclarées), `# EN-TETES` (en-têtes qui changent d'un export à l'autre) et `# COMPARAISON` (lignes perdues), avec le guide de lecture en fin de notebook | C | notebook 01 | opérationnel |
| 2.3 | En cas d'échec de décodage, d'en-têtes différents entre deux exports d'un même flux ou de lignes perdues : corriger `config/sources.yaml` (encodage, séparateur, ligne d'en-tête), ou demander un réexport, puis relancer le notebook | C, A, M | notebook 01 | opérationnel |
| 2.4 | Exporter les décomptes des cellules à l'encodage suspect (table, colonne, constat, mécanisme, nombre de cellules, cellules réparables), sans les valeurs | C | cellule `# EXPORT` | opérationnel |
| 2.5 | Rédiger la partie « cellules à l'encodage suspect » du rapport | A | export 2.4 | opérationnel |

Repères pour la phase 2 :

- le notebook n'affiche aucune valeur des données, seulement des noms de fichiers, de feuilles, de tables et de colonnes et des décomptes; le texte de la cellule `# EXPORT` peut être transmis à l'assistant;
- les formats sont lus dans `config/sources.yaml` (module `src/frigeo/inventaire.py`); une feuille d'un classeur absente de ce fichier est signalée mais pas chargée;
- le mécanisme d'une cellule à l'encodage suspect est déduit du format déclaré de la source, sans regarder les valeurs; la réparation relève du nettoyage (phase 8).

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

### Phase 7, table des anomalies (notebook 05)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 7.1 | Arrêter avec le métier les indicateurs que suivra le client et, pour chaque colonne, les indicateurs qu'elle alimente; désigner les contrôles dont une anomalie est bloquante | M avec C | formulaire | à créer |
| 7.2 | Rédiger `config/anomalies.yaml` (clés `indicateurs`, `colonnes`, `exceptions`) et le vérifier par `charger_qualification` puis `problemes_qualification` | A, puis C (dépôt dans `config/`) | formulaire 7.1, liste des colonnes | opérationnel |
| 7.3 | Exécuter le notebook en entier (il relance les contrôles des notebooks 03 et 04, environ 45 secondes) et vérifier : 0 ligne dont la valeur ou la clé sensible n'est pas masquée, nombres d'indicateurs, de colonnes déclarées et d'exceptions lus (emplacement attendu), avertissements, contrôles non qualifiés, colonnes non déclarées | C | notebook 05 | opérationnel |
| 7.4 | Déclarer les colonnes non déclarées et qualifier les contrôles non qualifiés dans `config/anomalies.yaml`, puis relancer la cellule `# GRAVITE ET INDICATEURS` et les suivantes | A, puis C | liste de la cellule `# GRAVITE ET INDICATEURS` | opérationnel |
| 7.5 | Lire le bilan avec le métier (anomalies par étape et par gravité, contrôles aux plus forts taux) et nuancer par des exceptions une gravité par défaut trop grossière | M avec C | bilan, `config/anomalies.yaml` | opérationnel |
| 7.6 | Écrire la table et le bilan en CSV dans `data/anomalies/` (cellule `# ECRITURE`); un CSV ouvert dans Excel bloque l'écriture sans rien modifier : le fermer et relancer la cellule | C | notebook 05 | opérationnel |
| 7.7 | Ouvrir les CSV dans Excel par Données, À partir d'un fichier texte/CSV, détection du type de données réglée sur « Ne pas détecter les types de données » | C, M | Excel | opérationnel |

Repères pour la phase 7 :

- la liste des colonnes à déclarer (`colonnes_non_declarees`) ne contient que des noms de tables et de colonnes : elle peut être transmise à l'assistant;
- les indicateurs affectés sont une déclaration du consultant, validée par le métier, et non un calcul; la gravité par défaut est « majeure » dès qu'une colonne alimente un indicateur, « mineure » sinon, et « bloquante » seulement par exception;
- les CSV portent des valeurs du client (valeurs constatées, clés) : ils restent hors dépôt et ne se collent pas dans la conversation; seuls les décomptes du bilan se transmettent;
- ouvert par double-clic, Excel retire les zéros en tête, écrit un SIRET en notation scientifique, lit `2026-03` comme une date et une valeur commençant par `=` comme une formule, d'où l'étape 7.7;
- l'écriture refuse une table où une valeur sensible serait visible, ou qui n'est pas passée par `qualifier`; les deux fichiers sont réécrits à chaque exécution, sans copie de sauvegarde.

### Phase 8, nettoyage et décisions du métier (notebook 06)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 8.1 | Mettre `PERIODE_FIN` à jour et exécuter le notebook en entier (environ trois minutes : nettoyage, puis contrôles avant et après nettoyage); vérifier le nombre de décisions du métier lues (emplacement attendu), les corrections sur une colonne sensible toutes masquées, 0 ligne dont la valeur ou la clé sensible n'est pas masquée | C | notebook 06 | opérationnel |
| 8.2 | Lire le bilan du nettoyage (cellules corrigées, lignes retirées, raisons de non-correction) et la comparaison avant et après; regarder un par un les contrôles aux anomalies apparues (une valeur devenue lisible rend une règle évaluable) | C, A (décomptes seulement) | cellules `# NETTOYAGE` et `# COMPARAISON` | opérationnel |
| 8.3 | Exporter le classeur d'arbitrage dans `data/decisions/` (cellule `# EXPORT ARBITRAGE`) | C | notebook 06 | opérationnel |
| 8.4 | Trancher les lignes du classeur dans la colonne `decision` (corriger avec la valeur retenue, garder ou retirer, selon la sorte), mode d'emploi dans la première feuille; une ligne sans décision sera proposée de nouveau | M avec C | Excel | opérationnel |
| 8.5 | Enregistrer et fermer le classeur, puis `# IMPORT ARBITRAGE` (tous les problèmes listés en une fois, décisions enregistrées dans `data/config/decisions.yaml` avec une copie datée); supprimer le classeur importé de `data/decisions/` | C | notebook 06 | opérationnel |
| 8.6 | Relancer le notebook en entier : `# NETTOYAGE` applique les décisions, et le classeur suivant ne propose que les éléments restants | C | notebook 06 | opérationnel |
| 8.7 | Écrire le journal et le bilan du nettoyage dans `data/nettoyage/`, et la table des anomalies après nettoyage avec la décision du métier, et son bilan, dans `data/anomalies/` (cellule `# ECRITURE`); un CSV ouvert dans Excel bloque l'écriture sans rien modifier | C | notebook 06 | opérationnel |

Repères pour la phase 8 :

- les règles automatiques ne corrigent que ce qui se lit sans ambiguïté; tout le reste passe par une décision du métier, gardée d'un mois à l'autre tant que la donnée ne change pas;
- une décision dont la donnée a changé (source corrigée, ou réexportée avec des lignes décalées) devient caduque : le nettoyage ne l'applique pas, son bilan le dit, et l'élément revient au classeur suivant;
- une anomalie de règle de gestion (issue « anomalie ») n'entre pas dans le classeur : sa correction se fait dans le logiciel source;
- le classeur porte des valeurs du client, colonnes sensibles comprises : il reste dans `data/decisions/` et ne se colle pas dans la conversation; le journal du nettoyage masque les colonnes sensibles;
- une année écrite sur deux chiffres est complétée en 20AA si la date ne dépasse pas la date de coupure; ces conversions sont visibles au journal (« siècle 20 ajouté ») et sont à faire vérifier par le métier quand une règle de gestion les signale;
- le jeu nettoyé n'est pas écrit : il se recalcule à chaque exécution à partir des fichiers bruts, des règles et des décisions.

## Cycle mensuel (un mois de plus)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| M.1 | Déposer les exports du mois (période dans le nom, par exemple dans `data/raw/2026/2026-04/`), et les référentiels s'ils ont changé | M, C | Explorateur | opérationnel |
| M.2 | Mettre `PERIODE_FIN` à jour dans chaque notebook exécuté | C | notebooks 01, 02c, 03, 04, 05, 06 | opérationnel |
| M.3 | Exécuter le notebook 01 (fichiers attendus, en-têtes, lignes chargées) | C | notebook 01 | opérationnel |
| M.4 | Exécuter le notebook 02 seulement si un format nouveau est soupçonné | C | notebook 02 | à adapter |
| M.5 | Régénérer le dictionnaire : cellules jusqu'à `# ECRITURE APRES FUSION`, lire le rapport de `# FUSION` (événements « à regarder ») | C | notebook 02c | opérationnel |
| M.6 | Revue si de nouvelles valeurs ou formes sont à arbitrer (phase 4, étapes 4.4 à 4.6) | M avec C | Excel, notebook 02c | opérationnel |
| M.7 | Exécuter les notebooks 03 puis 04 en entier | C | notebooks 03, 04 | opérationnel |
| M.8 | Exécuter le notebook 05 en entier : il relance les contrôles et réécrit les deux CSV de la période dans `data/anomalies/` | C | notebook 05 | opérationnel |
| M.9 | Revoir `config/anomalies.yaml` quand une colonne ou un indicateur change (le notebook 05 liste les colonnes non déclarées et les contrôles non qualifiés) | A, puis C | `config/anomalies.yaml` | opérationnel |
| M.10 | Exécuter le notebook 06 en entier, puis l'arbitrage si des éléments sont à trancher (phase 8, étapes 8.3 à 8.7) | C, M | notebook 06, Excel | opérationnel |

Une fois par an : compléter les jours fériés de l'année suivante dans `config/gestion.yaml` (le notebook 04 avertit quand une année manque) et vérifier que les paramètres annuels du client couvrent la nouvelle année.

## Points ouverts

- **Changement d'année.** Le modèle de périodes garde une période annuelle unique suivie de mois. Le passage à un export annuel de l'année suivante n'est pas prévu.
- **Formulaires.** Les formulaires des règles de contrôle et des règles de gestion restent à concevoir (forme, et passage du formulaire au YAML).
- **Rapport.** Le rapport au client (plan, destinataire, format) n'est pas encore défini; les parties 2.5 et 3.3 en sont les premières briques.
- **Découverte des encodages et séparateurs.** Ils sont déclarés à la main dans `config/sources.yaml`; l'étape qui les proposerait n'est pas faite.
- **Dates dont le siècle a été ajouté.** Elles ne sont pas soumises à la confirmation du métier; les faire confirmer dans le classeur d'arbitrage serait une amélioration possible.
