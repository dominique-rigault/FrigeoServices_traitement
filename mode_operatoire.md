# Mode opératoire d'un cycle de traitement

Document à l'usage du consultant. Il décrit, dans l'ordre chronologique, ce que font le consultant, le métier du client et l'assistant LLM pour traiter les exports d'un client avec cet outil, jusqu'à l'étape 6 comprise. Il sera complété avec les étapes 7 et suivantes. Les notebooks sont numérotés dans l'ordre d'exécution (01 à 07), qui ne suit pas la numérotation des étapes du README.

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
| 3.1 | Mettre `PERIODE_FIN` à jour et exécuter le notebook en entier; lire la synthèse par table, les colonnes dont la nature change d'un export à l'autre et les points à regarder, et examiner au besoin une colonne dans `# DETAIL D'UNE COLONNE` (guide de lecture en fin de notebook) | C | notebook 02 | opérationnel |
| 3.2 | Exporter le profil agrégé (synthèse par table; par colonne la nature, les parts de la nature et des vides, le nombre de valeurs distinctes et de formes, les formes principales; les points à regarder), sans bornes ni valeurs, formes des colonnes sensibles masquées | C | cellule `# EXPORT` | opérationnel |
| 3.3 | Rédiger la partie « synthèse du profilage » du rapport | A | export 3.2 | opérationnel |
| 3.4 | Si le profil montre une forme de date, d'heure ou de nombre non reconnue (point « forme numérique non reconnue » : HH:MM:SS, MM/JJ/AAAA, milliers séparés par une espace) : étendre les natures de `profilage.py` et de `typage.py`, avec leurs tests | A, puis C (tests et commit) | `src`, `tests` | à créer si nécessaire |

L'étape 3.4 précède le notebook 03 : la nature proposée au dictionnaire, puis la lecture typée de l'étape 4, reposent sur ces natures.

Repères pour la phase 3 :

- le notebook ne nomme aucune table ni colonne; la synthèse et les points à regarder viennent de `src/frigeo/profilage.py`;
- les bornes des colonnes sensibles sont masquées dans le notebook; le texte de `# EXPORT` ne porte ni borne ni valeur, et les formes des colonnes sensibles y sont masquées : il peut être transmis à l'assistant;
- `# DETAIL D'UNE COLONNE` affiche une valeur d'exemple par forme (sauf colonne sensible) : sa sortie reste sur le poste;
- le point « forme numérique non reconnue » ne retient que les formes que ni le profil ni le nettoyage ne savent lire; il signale aussi des codes formatés (téléphone, référence de pièce), qui relèvent de la règle `format` du dictionnaire et non de l'étape 3.4;
- le point « forme élargie lue par le nettoyage » (JJ.MM.AAAA, JJ/MM/AA, milliers séparés par une espace) ne demande pas d'étendre les natures : ces valeurs sont converties par la règle `nature` du nettoyage (phase 8).

### Phase 4, dictionnaire et revue (notebook 03)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 4.1 | Ajuster si nécessaire les seuils de génération (200 valeurs, 12 valeurs principales, 95 %, 2 % de vides), par exemple pour un client aux petits référentiels | A | constantes de `dictionnaire.py` | opérationnel (dans le code, pas dans un fichier YAML) |
| 4.2 | Mettre `PERIODE_FIN` à jour et exécuter les cellules jusqu'à `# ECRITURE APRES FUSION` (premier dictionnaire : `# FUSION` affiche « rien à fusionner ») | C | notebook 03 | opérationnel |
| 4.3 | Exporter le classeur de revue | C | cellule `# EXPORT` | opérationnel |
| 4.4 | Revoir le classeur (feuilles `règles`, `valeurs`, `formes`, mode d'emploi dans la première feuille); une revue partielle suffit pour avancer | M avec C | Excel | opérationnel |
| 4.5 | Appliquer la revue : enregistrer et fermer le classeur, `# IMPORT`, `# APPLICATION`, `# ECRITURE` (qui archive le classeur appliqué dans `data/formulaires/appliques/`), puis `# EXPORT` pour la revue suivante | C | notebook 03 | opérationnel |

Repères pour la phase 4 :

- les quatre classeurs remplis par le métier (revue du dictionnaire, règles de contrôle, règles de gestion, arbitrage) sont rangés ensemble dans `data/formulaires/`, hors du dépôt; un classeur appliqué est archivé dans `data/formulaires/appliques/`, sous un nom qui porte l'heure de l'archivage, et un classeur ouvert dans Excel arrête l'écriture sans rien modifier;

- `# IMPORT` puis `# APPLICATION` sur un classeur non modifié est sans effet (aucune écriture);
- `# FUSION` et `# ECRITURE APRES FUSION` ne servent qu'à une régénération (un mois de plus, ou une nouvelle version du code de génération); chaque exécution de `# ECRITURE APRES FUSION` sur un dictionnaire revu ajoute une copie de sauvegarde, même si rien n'a changé;
- la revue n'est pas un préalable aux étapes 3 et 4 : une règle non revue est contrôlée et ses écarts portent le statut `observé`;
- la relecture du classeur se fait sans en coller d'extraits dans la conversation.

### Phase 5, règles de contrôle (notebook 04)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 5.1 | Mettre `PERIODE_FIN` à jour, exécuter `# CHARGEMENT` puis `# EXPORT FORMULAIRE`, qui écrit `data/formulaires/controles_AAAA-MM.xlsx` : les règles en vigueur dans `config/controles.yaml` (statut documenté) et les propositions tirées des données (statut observé) pour les décimales, les bornes et la clé de Luhn de chaque colonne numérique ou de chiffres, les groupes de colonnes qui ne doivent pas se répéter (clé, unique, présumé unique) et, par table, la recherche des lignes identiques hors clé | C | notebook 04 | opérationnel |
| 5.2 | Revoir le formulaire (mode d'emploi dans la première feuille) : un statut par ligne (valide adopte la proposition, documenté prend les valeurs saisies, invalide écarte la règle et la proposition), un commentaire si besoin, un groupe de plusieurs colonnes ajouté en bas de la feuille `doublons`; une revue partielle suffit pour avancer | M avec C | Excel | opérationnel |
| 5.3 | Enregistrer et fermer le formulaire, exécuter `# IMPORT FORMULAIRE` (rapport des règles changées et avertissements; un formulaire mal rempli arrête la cellule avec la liste des lignes à corriger), puis `# ECRITURE FORMULAIRE`, qui copie l'ancien fichier dans `data/config/sauvegardes/`, archive le formulaire dans `data/formulaires/appliques/` et réécrit `config/controles.yaml` | C | notebook 04 | opérationnel |
| 5.4 | Commiter `config/controles.yaml` | C | Git | opérationnel |
| 5.5 | Si le métier demande un motif (expression régulière), l'écrire à la main dans `config/controles.yaml`, quand aucun formulaire n'attend son import | A, puis C (dépôt dans `config/`) | `config/controles.yaml` | opérationnel |
| 5.6 | Exécuter le notebook en entier, et vérifier les lignes « N règles complémentaires lues » et « N tables avec des doublons déclarés » (emplacement attendu) | C | notebook 04 | opérationnel |

Repères pour la phase 5 :

- le formulaire porte des valeurs observées (minimum et maximum, masqués pour une colonne sensible) : il reste dans `data/formulaires/` et ne se colle pas dans la conversation;
- un formulaire pas encore rempli ne change rien, si bien que le notebook peut toujours être exécuté en entier; après une écriture, l'exécution suivante exporte un nouveau formulaire;
- le formulaire porte le nom de la période (`controles_2026-04.xlsx`) : un formulaire d'un mois précédent laissé sans revue reste dans `data/formulaires/` et `# EXPORT FORMULAIRE` le signale (« autres formulaires en attente », qui liste aussi un classeur de revue ou d'arbitrage non importé); le supprimer à la main, celui du mois en reprend les lignes;
- un formulaire exporté avant une modification de `config/controles.yaml` (un motif ajouté à la main, par exemple) est refusé à l'import : le supprimer, puis le réexporter;
- `config/controles.yaml` est réécrit en entier, dans l'ordre du dictionnaire : un commentaire écrit à la main y est perdu, celui du métier se saisit dans le formulaire;
- une forme fixe (code postal, SIRET, téléphone) ne va pas dans ce formulaire : elle relève de la règle `format` du dictionnaire, décidée à la revue (phase 4).

### Phase 6, règles de gestion (notebook 05)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 6.1 | Mettre `PERIODE_FIN` à jour, exécuter `# CHARGEMENT` puis `# EXPORT FORMULAIRE`, qui écrit `data/formulaires/gestion_AAAA-MM.xlsx` : les règles en vigueur dans `config/gestion.yaml` (statut documenté) et les propositions tirées des données (statut observé) pour trois familles de règles qui tiennent sur une ligne (valeur connue d'une colonne de référence, colonne renseignée selon la valeur d'une autre, date dans la période de son export), les jours fériés légaux de la France pour chaque année des données, les autres règles écrites en clair et les règles demandées | C | notebook 05 | opérationnel |
| 6.2 | Revoir le formulaire avec le métier (mode d'emploi dans la première feuille) : un statut par ligne (valide adopte la proposition, documenté prend les valeurs saisies, invalide retire la règle ou écarte la proposition), un commentaire si besoin; une règle utile mais trop rare pour être proposée, ou une clé de plusieurs colonnes, s'ajoute en bas de sa feuille; un jour propre à l'entreprise (pont, fermeture) s'ajoute en bas de la feuille `jours_fériés`; pour les autres règles, changer le libellé ou l'issue (une pratique normale en information) ou retirer la règle; les règles voulues en plus se décrivent en clair dans la feuille `nouvelles_règles` (tables, tolérance ou délai, issue); une revue partielle suffit pour avancer | M avec C | Excel | opérationnel |
| 6.3 | Enregistrer et fermer le formulaire, exécuter `# IMPORT FORMULAIRE` (rapport des changements et avertissements; un formulaire mal rempli arrête la cellule avec la liste des lignes à corriger), puis `# ECRITURE FORMULAIRE`, qui copie l'ancien fichier dans `data/config/sauvegardes/`, archive le formulaire dans `data/formulaires/appliques/` et réécrit `config/gestion.yaml` | C | notebook 05 | opérationnel |
| 6.4 | Commiter `config/gestion.yaml` | C | Git | opérationnel |
| 6.5 | Traduire chaque règle demandée (clé `demandes` de `config/gestion.yaml`) en une règle d'un type du catalogue (`# TYPES DE REGLES`); pour une règle qui n'entre dans aucun type, proposer un nouveau type générique, faire valider le critère, puis le coder avec ses tests | A, validé par C | `src/frigeo/gestion.py`, `tests` | opérationnel (catalogue limité aux 29 types de Frigéo) |
| 6.6 | Si un seuil est une hypothèse, l'éprouver par une cellule d'essai qui n'affiche que des décomptes, puis la supprimer | A, exécutée par C | notebook 05 | opérationnel |
| 6.7 | Écrire la règle traduite dans `config/gestion.yaml`, retirer sa demande de la clé `demandes`, vérifier le fichier par `problemes_regles_gestion`, puis le commiter; le faire quand aucun formulaire n'attend son import | A, puis C (dépôt dans `config/`) | `config/gestion.yaml` | opérationnel |
| 6.8 | Exécuter le notebook en entier; lire le nombre de règles lues et les avertissements (année absente des jours fériés, lignes de référentiel inutilisables) | C | notebook 05 | opérationnel |

Repères pour la phase 6 :

- le formulaire porte des valeurs du client (valeurs des listes, codes, dates) : il reste dans `data/formulaires/` et ne se colle pas dans la conversation; seuls les textes de la feuille `nouvelles_règles` sont transmis à l'assistant pour l'action 6.5, ils peuvent citer des codes du client;
- une colonne sensible ne sert jamais de colonne selon à une proposition : ses valeurs entreraient dans `config/gestion.yaml`, versionné;
- une proposition demande qu'au moins 95 % des lignes suivent la règle, en comptant une ligne contraire de plus : elle ne repose jamais sur moins de 19 lignes;
- un formulaire pas encore rempli ne change rien, si bien que le notebook peut toujours être exécuté en entier; après une écriture, l'exécution suivante exporte un nouveau formulaire;
- un formulaire exporté avant une modification de `config/gestion.yaml` (une règle écrite à l'action 6.7, par exemple) est refusé à l'import : le supprimer, puis le réexporter; d'où l'ordre, appliquer d'abord le formulaire, puis écrire les règles traduites;
- `config/gestion.yaml` est réécrit en entier : une ligne de commentaire écrite à la main y est perdue, le commentaire d'une règle s'écrit sous sa clé `commentaire` ou dans le formulaire; une règle retirée reste sous la clé `retirees` et se rétablit par documenté;
- les jours fériés sont déclarés une fois pour le fichier (clé `jours_feries`) et repris par chaque règle d'horaires qui n'en déclare pas.

Le code d'un type nouveau va dans `src/`, jamais dans le notebook ni dans une fonction propre au client. `config/controles.yaml` doit exister avant le notebook 05 : sa clé `doublons` donne la clé affichée et les doublons écartés des rapprochements, et ses clés et colonnes uniques servent de cibles aux références proposées par le formulaire.

### Phase 7, table des anomalies (notebook 06)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 7.1 | Arrêter avec le métier les indicateurs que suivra le client et, pour chaque colonne, les indicateurs qu'elle alimente; désigner les contrôles dont une anomalie est bloquante | M avec C | formulaire | à créer |
| 7.2 | Rédiger `config/anomalies.yaml` (clés `indicateurs`, `colonnes`, `exceptions`) et le vérifier par `charger_qualification` puis `problemes_qualification` | A, puis C (dépôt dans `config/`) | formulaire 7.1, liste des colonnes | opérationnel |
| 7.3 | Exécuter le notebook en entier (il relance les contrôles des notebooks 04 et 05, environ 45 secondes) et vérifier : 0 ligne dont la valeur ou la clé sensible n'est pas masquée, nombres d'indicateurs, de colonnes déclarées et d'exceptions lus (emplacement attendu), avertissements, contrôles non qualifiés, colonnes non déclarées | C | notebook 06 | opérationnel |
| 7.4 | Déclarer les colonnes non déclarées et qualifier les contrôles non qualifiés dans `config/anomalies.yaml`, puis relancer la cellule `# GRAVITE ET INDICATEURS` et les suivantes | A, puis C | liste de la cellule `# GRAVITE ET INDICATEURS` | opérationnel |
| 7.5 | Lire le bilan avec le métier (anomalies par étape et par gravité, contrôles aux plus forts taux) et nuancer par des exceptions une gravité par défaut trop grossière | M avec C | bilan, `config/anomalies.yaml` | opérationnel |
| 7.6 | Écrire la table et le bilan en CSV dans `data/anomalies/` (cellule `# ECRITURE`); un CSV ouvert dans Excel bloque l'écriture sans rien modifier : le fermer et relancer la cellule | C | notebook 06 | opérationnel |
| 7.7 | Ouvrir les CSV dans Excel par Données, À partir d'un fichier texte/CSV, détection du type de données réglée sur « Ne pas détecter les types de données » | C, M | Excel | opérationnel |

Repères pour la phase 7 :

- la liste des colonnes à déclarer (`colonnes_non_declarees`) ne contient que des noms de tables et de colonnes : elle peut être transmise à l'assistant;
- les indicateurs affectés sont une déclaration du consultant, validée par le métier, et non un calcul; la gravité par défaut est « majeure » dès qu'une colonne alimente un indicateur, « mineure » sinon, et « bloquante » seulement par exception;
- les CSV portent des valeurs du client (valeurs constatées, clés) : ils restent hors dépôt et ne se collent pas dans la conversation; seuls les décomptes du bilan se transmettent;
- ouvert par double-clic, Excel retire les zéros en tête, écrit un SIRET en notation scientifique, lit `2026-03` comme une date et une valeur commençant par `=` comme une formule, d'où l'étape 7.7;
- l'écriture refuse une table où une valeur sensible serait visible, ou qui n'est pas passée par `qualifier`; les deux fichiers sont réécrits à chaque exécution, sans copie de sauvegarde.

### Phase 8, nettoyage et décisions du métier (notebook 07)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 8.1 | Mettre `PERIODE_FIN` à jour et exécuter le notebook en entier (environ trois minutes : nettoyage, puis contrôles avant et après nettoyage); vérifier le nombre de décisions du métier lues (emplacement attendu), les corrections sur une colonne sensible toutes masquées, 0 ligne dont la valeur ou la clé sensible n'est pas masquée | C | notebook 07 | opérationnel |
| 8.2 | Lire le bilan du nettoyage (cellules corrigées, lignes retirées, raisons de non-correction) et la comparaison avant et après; regarder un par un les contrôles aux anomalies apparues (une valeur devenue lisible rend une règle évaluable) | C, A (décomptes seulement) | cellules `# NETTOYAGE` et `# COMPARAISON` | opérationnel |
| 8.3 | Exporter le classeur d'arbitrage dans `data/formulaires/` (cellule `# EXPORT ARBITRAGE`) | C | notebook 07 | opérationnel |
| 8.4 | Trancher les lignes du classeur dans la colonne `decision` (corriger avec la valeur retenue, garder ou retirer, selon la sorte), mode d'emploi dans la première feuille; une ligne sans décision sera proposée de nouveau | M avec C | Excel | opérationnel |
| 8.5 | Enregistrer et fermer le classeur, puis `# IMPORT ARBITRAGE` (tous les problèmes listés en une fois, décisions enregistrées dans `data/config/decisions.yaml` avec une copie datée, classeur archivé dans `data/formulaires/appliques/`) | C | notebook 07 | opérationnel |
| 8.6 | Relancer le notebook en entier : `# NETTOYAGE` applique les décisions, et le classeur suivant ne propose que les éléments restants | C | notebook 07 | opérationnel |
| 8.7 | Écrire le journal et le bilan du nettoyage dans `data/nettoyage/`, et la table des anomalies après nettoyage avec la décision du métier, et son bilan, dans `data/anomalies/` (cellule `# ECRITURE`); un CSV ouvert dans Excel bloque l'écriture sans rien modifier | C | notebook 07 | opérationnel |

Repères pour la phase 8 :

- les règles automatiques ne corrigent que ce qui se lit sans ambiguïté; tout le reste passe par une décision du métier, gardée d'un mois à l'autre tant que la donnée ne change pas;
- une décision dont la donnée a changé (source corrigée, ou réexportée avec des lignes décalées) devient caduque : le nettoyage ne l'applique pas, son bilan le dit, et l'élément revient au classeur suivant;
- une anomalie de règle de gestion (issue « anomalie ») n'entre pas dans le classeur : sa correction se fait dans le logiciel source;
- le classeur porte des valeurs du client, colonnes sensibles comprises : il reste dans `data/formulaires/` et ne se colle pas dans la conversation; le journal du nettoyage masque les colonnes sensibles;
- une année écrite sur deux chiffres est complétée en 20AA si la date ne dépasse pas la date de coupure; ces conversions sont visibles au journal (« siècle 20 ajouté ») et sont à faire vérifier par le métier quand une règle de gestion les signale;
- le jeu nettoyé n'est pas écrit : il se recalcule à chaque exécution à partir des fichiers bruts, des règles et des décisions.

## Cycle mensuel (un mois de plus)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| M.1 | Déposer les exports du mois (période dans le nom, par exemple dans `data/raw/2026/2026-04/`), et les référentiels s'ils ont changé | M, C | Explorateur | opérationnel |
| M.2 | Mettre `PERIODE_FIN` à jour dans chaque notebook exécuté | C | notebooks 01, 03, 04, 05, 06, 07 | opérationnel |
| M.3 | Exécuter le notebook 01 (fichiers attendus, en-têtes, lignes chargées) | C | notebook 01 | opérationnel |
| M.4 | Exécuter le notebook 02 seulement si un format nouveau est soupçonné (points « nature différente selon l'export » et « forme numérique non reconnue ») | C | notebook 02 | opérationnel |
| M.5 | Régénérer le dictionnaire : cellules jusqu'à `# ECRITURE APRES FUSION`, lire le rapport de `# FUSION` (événements « à regarder ») | C | notebook 03 | opérationnel |
| M.6 | Revue si de nouvelles valeurs ou formes sont à arbitrer (phase 4, étapes 4.3 à 4.5) | M avec C | Excel, notebook 03 | opérationnel |
| M.7 | Exécuter les notebooks 04 puis 05 en entier; si `# EXPORT FORMULAIRE` signale des lignes à « observé » nouvelles (une colonne, un groupe ou une proposition de plus), faire revoir le formulaire du mois (phase 5, actions 5.2 à 5.4, ou phase 6, actions 6.2 à 6.4) | C, M | notebooks 04, 05, Excel | opérationnel |
| M.8 | Exécuter le notebook 06 en entier : il relance les contrôles et réécrit les deux CSV de la période dans `data/anomalies/` | C | notebook 06 | opérationnel |
| M.9 | Revoir `config/anomalies.yaml` quand une colonne ou un indicateur change (le notebook 06 liste les colonnes non déclarées et les contrôles non qualifiés) | A, puis C | `config/anomalies.yaml` | opérationnel |
| M.10 | Exécuter le notebook 07 en entier, puis l'arbitrage si des éléments sont à trancher (phase 8, étapes 8.3 à 8.7) | C, M | notebook 07, Excel | opérationnel |

Une fois par an : valider dans le formulaire des règles de gestion les jours fériés de la nouvelle année, proposés dès que ses premiers exports sont chargés (le notebook 05 avertit quand une année manque) et vérifier que les paramètres annuels du client couvrent la nouvelle année.

## Points ouverts

- **Changement d'année.** Le modèle de périodes garde une période annuelle unique suivie de mois. Le passage à un export annuel de l'année suivante n'est pas prévu.
- **Formulaires.** Les formulaires des règles de contrôle (phase 5) et des règles de gestion (phase 6) sont faits. Deux familles de règles de gestion pourraient tenir sur une ligne du formulaire au lieu de la feuille des autres règles : les plages d'une valeur selon une autre colonne et les correspondances entre une valeur et la catégorie de la ligne liée.
- **Rapport.** Le rapport au client (plan, destinataire, format) n'est pas encore défini; les parties 2.5 et 3.3 en sont les premières briques.
- **Découverte des encodages et séparateurs.** Ils sont déclarés à la main dans `config/sources.yaml`; l'étape qui les proposerait n'est pas faite.
- **Dates dont le siècle a été ajouté.** Elles ne sont pas soumises à la confirmation du métier; les faire confirmer dans le classeur d'arbitrage serait une amélioration possible.
