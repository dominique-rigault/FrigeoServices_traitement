# Mode opératoire d'un cycle de traitement

Document à l'usage du consultant. Il décrit, dans l'ordre chronologique, ce que font le consultant, le métier du client et l'assistant LLM pour traiter les exports d'un client avec cet outil, jusqu'à l'étape 6 comprise, puis la mise en place de la base de données (étape 7, en cours). Il sera complété au fil de l'étape 7 et des suivantes. Les notebooks sont numérotés dans l'ordre d'exécution (01 à 07), qui ne suit pas la numérotation des étapes du README.

## Rôles et règles communes

| Code | Rôle | Ce qu'il fait |
| --- | --- | --- |
| C | Consultant | Dépose les fichiers de configuration, exécute les notebooks, commite, anime la revue avec le métier. |
| M | Métier du client | Fournit les exports, valide ou corrige les propositions (classeur de revue, formulaires de règles), tranche les éléments du classeur d'arbitrage. |
| A | Assistant LLM | Rédige les fichiers de configuration, le code générique et ses tests, les parties du rapport. |

Règles valables à chaque étape :

- l'assistant ne reçoit jamais de valeurs des données du client, seulement des décomptes, des noms de tables et de colonnes et des formes (`AA-9999`); ce que le consultant lui transmet passe par une cellule d'export qui le garantit;
- l'accès de l'assistant au poste est limité aux dossiers `src` et `tests`; les fichiers de `config/` et de `sql/` et les cellules de notebook sont donnés dans la conversation et déposés par le consultant;
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
- un remplacement ne sert qu'à une variante d'écriture d'une seule valeur valide (casse, accents, abréviation); une valeur qui peut correspondre à plusieurs valeurs valides (« Divers », « Autre », « SAV ») reste invalide sans remplacement, et le métier la tranche ligne par ligne dans le classeur d'arbitrage (phase 8);
- la relecture du classeur se fait sans en coller d'extraits dans la conversation.

### Phase 5, règles de contrôle (notebook 04)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 5.1 | Mettre `PERIODE_FIN` à jour, exécuter `# CHARGEMENT` puis `# EXPORT FORMULAIRE`, qui écrit `data/formulaires/controles_AAAA-MM.xlsx` : les règles en vigueur dans `config/controles.yaml` (statut documenté) et les propositions tirées des données (statut observé) pour les décimales, les bornes et la clé de Luhn de chaque colonne numérique ou de chiffres, les groupes de colonnes qui ne doivent pas se répéter (clé, unique, présumé unique) et, par table, la recherche des lignes identiques hors clé | C | notebook 04 | opérationnel |
| 5.2 | Revoir le formulaire (mode d'emploi dans la première feuille) : un statut par ligne (valide adopte la proposition, documenté prend les valeurs saisies, invalide écarte la règle et la proposition), un commentaire si besoin, un groupe de plusieurs colonnes ajouté en bas de la feuille `doublons`; une revue partielle suffit pour avancer | M avec C | Excel | opérationnel |
| 5.3 | Enregistrer et fermer le formulaire, exécuter `# IMPORT FORMULAIRE` (rapport des règles changées et avertissements; un formulaire mal rempli arrête la cellule avec la liste des lignes à corriger), puis `# ECRITURE FORMULAIRE`, qui copie l'ancien fichier dans `data/config/sauvegardes/`, archive le formulaire dans `data/formulaires/appliques/` et réécrit `config/controles.yaml` | C | notebook 04 | opérationnel |
| 5.4 | Commiter `config/controles.yaml` | C | Git | opérationnel |
| 5.5 | Si le métier demande un motif (expression régulière), si une colonne de durée porte des valeurs écrites avec leurs unités (1h10, 95 min), ou si une table d'en-têtes de documents a sa table de lignes, écrire à la main le motif, la règle `duree` (unité de la colonne, minutes ou heures) ou la clé `table_des_lignes` de l'en-tête dans `config/controles.yaml`, quand aucun formulaire n'attend son import | A, puis C (dépôt dans `config/`) | `config/controles.yaml` | opérationnel |
| 5.6 | Exécuter le notebook en entier, et vérifier les lignes « N règles complémentaires lues » et « N tables avec des doublons déclarés » (emplacement attendu) | C | notebook 04 | opérationnel |

Repères pour la phase 5 :

- le formulaire porte des valeurs observées (minimum et maximum, masqués pour une colonne sensible) : il reste dans `data/formulaires/` et ne se colle pas dans la conversation;
- un formulaire pas encore rempli ne change rien, si bien que le notebook peut toujours être exécuté en entier; après une écriture, l'exécution suivante exporte un nouveau formulaire;
- le formulaire porte le nom de la période (`controles_2026-04.xlsx`) : un formulaire d'un mois précédent laissé sans revue reste dans `data/formulaires/` et `# EXPORT FORMULAIRE` le signale (« autres formulaires en attente », qui liste aussi un classeur de revue ou d'arbitrage non importé); le supprimer à la main, celui du mois en reprend les lignes;
- un formulaire exporté avant une modification de `config/controles.yaml` (un motif ajouté à la main, par exemple) est refusé à l'import : le supprimer, puis le réexporter;
- `config/controles.yaml` est réécrit en entier, dans l'ordre du dictionnaire : un commentaire écrit à la main y est perdu, celui du métier se saisit dans le formulaire;
- l'unité d'une colonne de durée (règle `duree`) ne donne aucun contrôle à cette phase : elle sert au nettoyage (phase 8), et le formulaire la montre dans la feuille `durées` sans la modifier;
- pour une table d'en-têtes de documents (factures, pièces d'achat), la clé `table_des_lignes` nomme sa table des lignes, déclarée avec une clé qui contient celle de l'en-tête et au moins une autre colonne; deux en-têtes identiques hors clé ne sont alors à arbitrer que si leurs lignes le sont aussi, et le formulaire la montre dans la feuille `tables` sans la modifier;
- une forme fixe (code postal, SIRET, téléphone) ne va pas dans ce formulaire : elle relève de la règle `format` du dictionnaire, décidée à la revue (phase 4).

### Phase 6, règles de gestion (notebook 05)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 6.1 | Mettre `PERIODE_FIN` à jour, exécuter `# CHARGEMENT` puis `# EXPORT FORMULAIRE`, qui écrit `data/formulaires/gestion_AAAA-MM.xlsx` : les règles en vigueur dans `config/gestion.yaml` (statut documenté) et les propositions tirées des données (statut observé) pour trois familles de règles qui tiennent sur une ligne (valeur connue d'une colonne de référence, colonne renseignée selon la valeur d'une autre, date dans la période de son export, avec `vide_hors_champ` pour une date facultative dont l'absence est normale), les jours fériés légaux de la France pour chaque année des données, les autres règles écrites en clair et les règles demandées | C | notebook 05 | opérationnel |
| 6.2 | Revoir le formulaire avec le métier (mode d'emploi dans la première feuille) : un statut par ligne (valide adopte la proposition, documenté prend les valeurs saisies, invalide retire la règle ou écarte la proposition), un commentaire si besoin; une règle utile mais trop rare pour être proposée, ou une clé de plusieurs colonnes, s'ajoute en bas de sa feuille; un jour propre à l'entreprise (pont, fermeture) s'ajoute en bas de la feuille `jours_fériés`; pour les autres règles, changer le libellé ou l'issue (une pratique normale en information) ou retirer la règle; les règles voulues en plus se décrivent en clair dans la feuille `nouvelles_règles` (tables, tolérance ou délai, issue); une revue partielle suffit pour avancer | M avec C | Excel | opérationnel |
| 6.3 | Enregistrer et fermer le formulaire, exécuter `# IMPORT FORMULAIRE` (rapport des changements et avertissements; un formulaire mal rempli arrête la cellule avec la liste des lignes à corriger), puis `# ECRITURE FORMULAIRE`, qui copie l'ancien fichier dans `data/config/sauvegardes/`, archive le formulaire dans `data/formulaires/appliques/` et réécrit `config/gestion.yaml` | C | notebook 05 | opérationnel |
| 6.4 | Commiter `config/gestion.yaml` | C | Git | opérationnel |
| 6.5 | Traduire chaque règle demandée (clé `demandes` de `config/gestion.yaml`) en une règle d'un type du catalogue (`# TYPES DE REGLES`); pour une règle qui n'entre dans aucun type, proposer un nouveau type générique, faire valider le critère, puis le coder avec ses tests | A, validé par C | `src/frigeo/gestion.py`, `tests` | opérationnel (catalogue limité aux 31 types de Frigéo) |
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
- les jours fériés sont déclarés une fois pour le fichier (clé `jours_feries`) et repris par chaque règle d'horaires qui n'en déclare pas;
- des paramètres peuvent être déclarés une fois par type (clé `parametres_communs`, avec une clé `commentaire` qui dit ce qu'ils représentent) et sont repris par chaque règle du type qui ne les déclare pas; ils se modifient dans `config/gestion.yaml`, le formulaire les montrant avec la mention « (commun) ».

Le code d'un type nouveau va dans `src/`, jamais dans le notebook ni dans une fonction propre au client. `config/controles.yaml` doit exister avant le notebook 05 : sa clé `doublons` donne la clé affichée et les doublons écartés des rapprochements, et ses clés et colonnes uniques servent de cibles aux références proposées par le formulaire. La clé `regrouper_codes: true` d'un référentiel (clients, fournisseurs) s'écrit à la main par le consultant : elle fait proposer au métier, dans le classeur d'arbitrage, le rattachement de deux codes d'une même entité (phase 8), et le formulaire des règles de contrôle la montre en lecture seule.

### Phase 7, table des anomalies (notebook 06)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 7.1 | Arrêter avec le métier les indicateurs que suivra le client et, pour chaque colonne, les indicateurs qu'elle alimente; désigner les contrôles dont une anomalie est bloquante | M avec C | formulaire | à créer |
| 7.2 | Rédiger `config/anomalies.yaml` (clés `indicateurs`, `colonnes`, `exceptions`) et le vérifier par `charger_qualification` puis `problemes_qualification` | A, puis C (dépôt dans `config/`) | formulaire 7.1, liste des colonnes | opérationnel |
| 7.3 | Exécuter le notebook en entier (il relance les contrôles des notebooks 04 et 05, environ 45 secondes) et vérifier : 0 ligne dont la valeur ou la clé sensible n'est pas masquée, nombres d'indicateurs, de colonnes déclarées et d'exceptions lus (emplacement attendu), avertissements, contrôles non qualifiés, colonnes non déclarées | C | notebook 06 | opérationnel |
| 7.4 | Déclarer les colonnes non déclarées et qualifier les contrôles non qualifiés dans `config/anomalies.yaml`, puis relancer la cellule `# GRAVITE ET INDICATEURS` et les suivantes | A, puis C | liste de la cellule `# GRAVITE ET INDICATEURS` | opérationnel |
| 7.5 | Lire le bilan avec le métier (anomalies par étape et par gravité, contrôles aux plus forts taux) et nuancer par des exceptions une gravité par défaut trop grossière | M avec C | bilan, `config/anomalies.yaml` | opérationnel |
| 7.6 | Écrire la table, le bilan et les lignes non évaluables des règles de gestion en CSV dans `data/anomalies/` (cellule `# ECRITURE`); un CSV ouvert dans Excel bloque l'écriture sans rien modifier : le fermer et relancer la cellule | C | notebook 06 | opérationnel |
| 7.7 | Ouvrir les CSV dans Excel par Données, À partir d'un fichier texte/CSV, détection du type de données réglée sur « Ne pas détecter les types de données » | C, M | Excel | opérationnel |

Repères pour la phase 7 :

- la liste des colonnes à déclarer (`colonnes_non_declarees`) ne contient que des noms de tables et de colonnes : elle peut être transmise à l'assistant;
- les indicateurs affectés sont une déclaration du consultant, validée par le métier, et non un calcul; la gravité par défaut est « majeure » dès qu'une colonne alimente un indicateur, « mineure » sinon, et « bloquante » seulement par exception;
- une anomalie bloquante (issue anomalie ou à arbitrer) que le métier n'a pas résolue par une décision du classeur d'arbitrage exclut sa ligne des indicateurs : la ligne reste en base, marquée non retenue (phase 9); déclarer bloquant un contrôle, c'est donc décider que ses lignes ne comptent pas tant qu'elles ne sont pas tranchées (chez Frigéo, les champs indispensables aux calculs, les interventions de même numéro et un salaire hors bornes); pour une ligne de référentiel, l'effet s'étend à tout ce qui s'y réfère : une rémunération exclue laisse sans coût salarial ni marge toutes les interventions de la personne sur sa période;
- les CSV portent des valeurs du client (valeurs constatées, clés) : ils restent hors dépôt et ne se collent pas dans la conversation; seuls les décomptes du bilan se transmettent;
- ouvert par double-clic, Excel retire les zéros en tête, écrit un SIRET en notation scientifique, lit `2026-03` comme une date et une valeur commençant par `=` comme une formule, d'où l'étape 7.7;
- l'écriture refuse une table où une valeur sensible serait visible, ou qui n'est pas passée par `qualifier`; les trois fichiers sont réécrits à chaque exécution, sans copie de sauvegarde.

### Phase 8, nettoyage et décisions du métier (notebook 07)

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 8.1 | Mettre `PERIODE_FIN` à jour et exécuter le notebook en entier (environ trois minutes : nettoyage, puis contrôles avant et après nettoyage, écriture en base et sa vérification, voir la phase 9); vérifier le nombre de décisions du métier lues (emplacement attendu), la clé des empreintes créée au premier passage puis lue (`data/config/cle_empreintes.txt`), les corrections sur une colonne sensible toutes masquées et avec leurs deux empreintes, 0 ligne aux empreintes incohérentes, 0 ligne dont la valeur ou la clé sensible n'est pas masquée | C | notebook 07 | opérationnel |
| 8.2 | Lire le bilan du nettoyage (cellules corrigées, lignes retirées, raisons de non-correction) et la comparaison avant et après; regarder un par un les contrôles aux anomalies apparues (une valeur devenue lisible rend une règle évaluable) | C, A (décomptes seulement) | cellules `# NETTOYAGE` et `# COMPARAISON` | opérationnel |
| 8.3 | Exporter le classeur d'arbitrage dans `data/formulaires/` (cellule `# EXPORT ARBITRAGE`) | C | notebook 07 | opérationnel |
| 8.4 | Trancher les lignes du classeur dans la colonne `decision` (corriger avec la valeur retenue, garder ou retirer, selon la sorte; pour une ligne de sorte code, rattacher au code principal écrit en valeur retenue, garder la ligne du code principal ou une autre entité, ou retirer), mode d'emploi dans la première feuille; une ligne sans décision sera proposée de nouveau (une exécution complète du notebook importe le classeur enregistré, terminé ou non : ne la lancer qu'une fois l'arbitrage fini); la valeur retenue est préremplie quand l'outil propose une correction (date hors période, forme du référentiel d'une clé mal écrite, date au jour et au mois inversés, y compris sur une colonne sensible), à vérifier avant de choisir corriger | M avec C | Excel | opérationnel |
| 8.5 | Enregistrer et fermer le classeur, puis relancer le notebook en entier : `# IMPORT ARBITRAGE`, placée juste après `# CHARGEMENT` et avant `# NETTOYAGE`, importe le classeur (tous les problèmes listés en une fois, décisions enregistrées dans `data/config/decisions.yaml` avec une copie datée, classeur archivé dans `data/formulaires/appliques/`) | C | notebook 07 | opérationnel |
| 8.6 | Lire les résultats de cette même exécution : `# NETTOYAGE` a appliqué les décisions (et compte les codes en doublon regroupés), `# DECISIONS CADUQUES` compte celles qui ne s'appliquent plus, la base les reflète, et le classeur suivant ne propose que les éléments restants | C | notebook 07 | opérationnel |
| 8.7 | Écrire le journal et le bilan du nettoyage dans `data/nettoyage/`, et la table des anomalies après nettoyage avec la décision du métier, son bilan et les lignes non évaluables, dans `data/anomalies/` (cellule `# ECRITURE`); un CSV ouvert dans Excel bloque l'écriture sans rien modifier | C | notebook 07 | opérationnel |

Repères pour la phase 8 :

- les règles automatiques ne corrigent que ce qui se lit sans ambiguïté; tout le reste passe par une décision du métier, gardée d'un mois à l'autre tant que la donnée ne change pas;
- une décision dont la donnée a changé (source corrigée, ou réexportée avec des lignes décalées) devient caduque : le nettoyage ne l'applique pas, son bilan le dit, et l'élément revient au classeur suivant; une décision « corriger », « retirer » ou « rattacher » caduque reste dans `data/config/decisions.yaml` jusqu'à son retrait. Pour la retirer, mettre `RETIRER_CADUQUES` à True dans `# DECISIONS CADUQUES`, exécuter cette cellule, remettre False (à ne jamais commiter) et relancer `# NETTOYAGE`. Le fichier est copié avant, et le retrait est tracé;
- une clé qui ne se retrouve dans son référentiel qu'après normalisation est corrigée par la règle `referentiel` quand la forme du référentiel est unique et déjà celle de 95 % au moins des lignes de la même clé; sinon elle reste à arbitrer, avec la forme préremplie dans le classeur;
- une anomalie de règle de gestion (issue « anomalie ») n'entre pas dans le classeur : sa correction se fait dans le logiciel source;
- le classeur porte des valeurs du client, colonnes sensibles comprises : il reste dans `data/formulaires/` et ne se colle pas dans la conversation; le journal du nettoyage masque les colonnes sensibles et donne à leur place l'empreinte des valeurs avant et après, calculée avec la clé secrète `data/config/cle_empreintes.txt`; cette clé se garde avec les données du client, hors du dépôt, et ne se transmet qu'à une personne qui a déjà accès aux données (un évaluateur, pour vérifier les corrections masquées);
- une année écrite sur deux chiffres est complétée en 20AA si la date ne dépasse pas la date de coupure; ces conversions sont visibles au journal (« siècle 20 ajouté ») et sont à faire vérifier par le métier quand une règle de gestion les signale;
- dans une colonne déclarée durée, une durée écrite avec ses unités est convertie dans l'unité de la colonne si la conversion est exacte (« durée en minutes » au journal); sinon elle reste à corriger, avec la raison « valeur avec une unité » ou « durée non exacte dans l'unité » au bilan du nettoyage, et sa valeur retenue dans le classeur d'arbitrage s'écrit dans l'unité de la colonne, sans unité;
- le jeu nettoyé n'est pas écrit : il se recalcule à chaque exécution à partir des fichiers bruts, des règles et des décisions.
- la table à présenter au métier est celle après nettoyage (`anomalies_nettoyees_AAAA-MM.csv`), lue avec les conventions de la section « Lire les résultats » du README; le fichier des lignes non évaluables (`non_evaluables_nettoyees_AAAA-MM.csv`) dit ce qui n'a pas pu être contrôlé, et le tableau « avant, après » de la cellule `# COMPARAISON` ce que le nettoyage a rendu contrôlable.

### Phase 9, base de données (étape 7, en cours)

Cette phase met en place la base SQL Server qui recevra les données chargées et nettoyées. La structure de la base est construite (sous-étape 7.1), et le notebook 07 y écrit les données chargées et nettoyées et les sorties de la qualité, puis vérifie ce qu'il a écrit (sous-étape 7.2). Le modèle en étoile est construit et vérifié de bout en bout (sous-étape 7.3) : dimensions, rattachement des lignes à leurs référentiels, faits, codes en doublon regroupés, mesures et dates comparées à `propre`. Les lignes exclues des indicateurs sont marquées dans `propre` et dans les faits, les chantiers sur plusieurs jours sont reconnus, et le CUMP mensuel, le coût des pièces, les coûts salarial et de déplacement, le CA et la marge de chaque intervention sont calculés (sous-étape 7.4). Le tableau qualité est dans le modèle : anomalies du registre après nettoyage et taux par contrôle dans les deux états, non évaluables comptés à part (`dw.dim_controle`, `dw.fait_anomalie`, `dw.fait_bilan_controle`, tables génériques du socle, sous-étape 7.5); les vues pour Power BI suivront.

| N° | Action | Qui | Outil | État |
| --- | --- | --- | --- | --- |
| 9.1 | Installer SQL Server 2025 Developer (instance par défaut, authentification Windows, classement French_100_CI_AS), le pilote ODBC Driver 18 for SQL Server et SSMS | C | installateurs Microsoft | opérationnel sur le poste du consultant (hébergement chez le client : étape 10) |
| 9.2 | Copier `.env.exemple` en `.env` à la racine du dépôt et y renseigner `BASE_SERVEUR`, `BASE_NOM`, `BASE_PILOTE`, `BASE_CONFIANCE_CERTIFICAT` et, au besoin, `BASE_CLASSEMENT` (French_100_CI_AS par défaut) | C | éditeur | opérationnel |
| 9.3 | Lister dans `config/base.yaml` les packs métier appliqués après le socle (Frigéo : `services_intervention`) | A, puis C | `config/base.yaml` | opérationnel |
| 9.4 | Créer la base par `python -m frigeo.base --recreer`, depuis la racine du dépôt : la commande supprime la base si elle existe, la recrée, puis applique les scripts de `sql/socle/` par ordre de nom et ceux de chaque pack | C | terminal | opérationnel |
| 9.5 | Vérifier dans SSMS que `qualite.script_applique` liste chaque script appliqué, avec son empreinte et la version du code | C | SSMS | opérationnel |
| 9.6 | Après l'ajout d'un script, l'appliquer par `python -m frigeo.base` (une base à jour affiche « aucun script à appliquer ») | C | terminal | opérationnel |
| 9.7 | Après le notebook 07, exécuter sa cellule `# BASE` : elle écrit en base les tables chargées (schéma `chargement`, valeurs telles que livrées) et nettoyées (schéma `propre`, valeurs typées), les fichiers chargés (`qualite.journal_chargement`, avec leur empreinte) et la correspondance des colonnes (`qualite.correspondance_colonne`), puis, dans la même transaction, les anomalies avant nettoyage (état « brut », celles du fichier `anomalies_AAAA-MM.csv`) et après nettoyage (état « nettoyé »), leurs bilans et lignes non évaluables, le journal et le bilan du nettoyage, les décisions du métier appliquées, et les tables de référence issues de la configuration (`qualite.jour_ferie`, jours fériés de `config/gestion.yaml`; `qualite.valeur_liste`, valeurs admises des listes fermées du dictionnaire), le rattachement des lignes nettoyées à leurs référentiels (`qualite.regle_rattachement` et `qualite.rattachement`, dont la cellule affiche le bilan par rattachement), les codes en doublon regroupés sous un code principal par les décisions « rattacher » du métier (`qualite.correspondance_cle`), et enfin, si un pack la déclare, la reconstruction de `dw` par la procédure `dw.reconstruire` (tables génériques du tableau qualité comprises); elle affiche aussi le nombre de lignes non retenues par table (anomalie bloquante non résolue); un refus ou une erreur n'écrit rien (voir les repères) | C | notebook 07 | opérationnel |
| 9.8 | Exécuter ensuite la cellule `# VERIFICATION BASE` : elle relit la base et la compare à ce que Python a préparé (lignes et cellules renseignées de chaque table, sommes exactes, dates extrêmes, cellules illisibles rattachées à une anomalie, lignes non retenues de chaque table de `propre` égales, ligne à ligne, à celles qui portent une anomalie bloquante non résolue dans `qualite.anomalie`, lignes de `qualite` par état, jours fériés, valeurs des listes fermées et rattachements compris, lignes rattachées par rattachement, journal de la reconstruction de `dw` et contrat d'entrée du pack, pour chaque fait une ligne par ligne de `propre` et, colonne par colonne, des membres -1 et -2 (ou des liens non renseignés et introuvables, ou des numéros renseignés) égaux aux clés vides et introuvables (ou aux lignes rattachées) du bilan des rattachements, pour les clients et les fournisseurs aucun membre pour un code en doublon et les codes en doublon comptés sur les membres principaux, pour chaque mesure d'un fait une somme exacte égale à celle de ses colonnes de `propre` (`dw.contrat_mesure`; le solde d'une écriture, débit moins crédit) et autant de valeurs renseignées, aucune colonne numérique d'un fait sans mesure déclarée, pour chaque date lue sur la ligne même d'un fait (`dw.contrat_date`) le jour du calendrier égal à celui de `propre` ligne à ligne, autant de -1 que de dates vides et aucun -2, pour chaque fait une retenue égale ligne à ligne à celle de sa ligne de `propre` et de son en-tête (`dw.contrat_retenue`), pour les calculs du pack (famille « calculs ») le chantier de chaque intervention, le CUMP de chaque pièce et de chaque mois, le coût de chaque consommation et le CA, les coûts, la marge et le motif de chaque intervention recalculés en Python et égaux à ceux de `dw` (le coût salarial total affiché « masqué »), le total des lignes de facture retenues de `propre` égal au CA des interventions plus les lignes retenues rattachées à aucune intervention ou d'une intervention sans CA, la date du stock initial du pack égale à celle de la règle de stock de `config/gestion.yaml`, exécution unique de la période, et pour le tableau qualité un membre de `dw.dim_controle` par contrôle des deux bilans, une ligne de `dw.fait_anomalie` par anomalie du registre après nettoyage (décomptes par issue, aucun contrôle introuvable, totaux par période sans ligne source) et, dans `dw.fait_bilan_controle`, les compteurs et les non évaluables de chaque état égaux aux sorties du traitement); 0 contrôle non conforme attendu, un écart se lit dans le tableau affiché | C | notebook 07 | opérationnel |
| 9.9 | Pour relancer seule la reconstruction de `dw`, sans rejouer le notebook 07 : `python -m frigeo.base --reconstruire`; elle porte sur la dernière exécution réussie, dans sa propre transaction (en cas d'erreur, `dw` reste tel qu'il était), et affiche le journal des étapes. Une procédure modifiée dans un script déjà appliqué demande d'abord `--recreer`, puis une exécution de la cellule `# BASE` | C | terminal | opérationnel |

Repères pour la phase 9 :

- un script appliqué puis modifié ou supprimé arrête la commande avant toute application, avec la liste des scripts en cause (une modification involontaire s'annule par `git restore` du script); deux régimes, séparés par un jalon :
  - jusqu'au premier déploiement d'une base dont le contenu est à conserver (étape 10, ou première base d'un client), les scripts du socle et des packs peuvent être réécrits pour rester lisibles et exacts, la base se reconstruisant par `--recreer` (la base de développement se régénère entièrement à partir des fichiers);
  - ce déploiement est marqué par un tag Git; ensuite, un script appliqué ne se modifie plus, et toute évolution de la base passe par un nouveau script numéroté (`ALTER TABLE`, reprise des données);
- chaque script est appliqué dans sa propre transaction : en cas d'échec, la commande s'arrête en nommant le script et le lot fautifs, les scripts précédents restent appliqués, et il suffit de corriger le script fautif, pas encore inscrit, puis de relancer;
- dans un script, les lots sont séparés par une ligne qui ne contient que `GO`;
- `--recreer` efface toute la base, données comprises, et coupe les connexions ouvertes, SSMS compris; il est refusé hors d'un serveur local (localhost, ., (local), 127.0.0.1);
- la version du code inscrite à chaque application est celle de `git describe`, suivie de « -dirty » si un fichier suivi est modifié ou si un fichier nouveau n'est pas encore commité : commiter avant une application à tracer;
- `.env` n'est pas versionné; `.env.exemple` donne la liste des variables;
- les tables des schémas `chargement` et `propre` ne sont créées par aucun script numéroté : la cellule `# BASE` les génère à partir du dictionnaire revu, les supprime et les recrée à chaque exécution; elles reflètent donc toujours la dernière exécution, et une vue construite sur elles ne doit pas être créée `WITH SCHEMABINDING`;
- `python -m frigeo.structure_base --essai` vérifie le SQL généré (création des tables dans une transaction annulée), sans rien laisser en base;
- rejouer la même `PERIODE_FIN` remplace l'exécution précédente de cette période, une nouvelle période s'ajoute à l'historique de `qualite`;
- une écriture arrêtée par un garde-fou (texte de plus de 4 000 caractères, date avec une heure, nombre de plus de 8 décimales ou trop grand) ou par une erreur du serveur ne modifie rien : l'exécution précédente et ses tables restent en place, et la nouvelle est inscrite « échouée » dans `qualite.execution`, avec le message (sans valeur du client);
- une valeur restée illisible après nettoyage est écrite vide dans `propre`, sa valeur livrée restant dans `chargement`;
- les paramètres de calcul du pack (`dw.parametre_calcul` : catégorie et article d'un chantier, type de pièce d'une facture, date du stock initial; `dw.parametre_taux_charges` : colonne du taux de charges de chaque type de contrat) sont écrits dans le script `004_calculs.sql` du pack, pas dans les procédures; `dw.verifier_parametres` les contrôle avant toute construction contre les valeurs admises des listes fermées (`qualite.valeur_liste`), et un type de contrat admis sans taux de charges fait aussi échouer l'exécution : après un renommage de valeur par le métier, on corrige le script et on recrée la base (`--recreer`); pour un autre client, ce sont les premières lignes du pack à revoir, avec la date du stock initial de la règle de stock de `config/gestion.yaml`, à garder égale;
- le CUMP est calculé chaque mois, du mois de la date du stock initial (premier jour d'un mois) à celui de `PERIODE_FIN`, pour chaque pièce du catalogue (`dw.cump_mensuel`), à partir des achats au mois de leur facture et des consommations retenus; une consommation est valorisée au CUMP de la fin du mois précédent, ou reçoit un motif (`motif_calcul`) qui dit pourquoi elle ne l'est pas; les mesures calculées par le pack sont déclarées dans `dw.mesure_calculee`, et non dans `dw.contrat_mesure`, puisque le module de vérification du pack les refait;
- la marge de chaque intervention est le CA de ses lignes de facture retenues moins ses coûts salarial, de déplacement et des pièces; le coût salarial prend la dernière rémunération du matricule dont la date d'effet ne dépasse pas la date de l'intervention, le type de contrat de la période d'emploi rattachée et les paramètres de coûts de l'année; si l'une de ces lignes de référence est exclue des indicateurs, elle n'est pas remplacée par une autre et le coût reste vide (motifs « rémunération non retenue », « paramètres de coûts de l'année non retenus », « intervenant non retenu »), jusqu'à ce que le métier tranche l'anomalie ou corrige sa source; une composante impossible reste vide, ainsi que la marge, avec la première raison dans `motif_calcul`; une ligne de facture ou une consommation liée exclue des indicateurs laisse de même vides le CA ou le coût des pièces, et la marge; le coût horaire chargé n'est gardé nulle part;
- un chantier sur plusieurs jours n'a pas d'identifiant dans les fichiers : il se reconnaît à sa facture, qui porte une ligne de l'article de chantier pour chaque jour; un chantier pas encore facturé reste en jours isolés jusqu'à l'exécution qui suit sa facture;
- les calculs du pack sont refaits en Python par le module du pack (`src/frigeo/packs/services_intervention.py`), appelé par `# VERIFICATION BASE` : une règle de calcul modifiée dans le pack doit l'être aussi dans ce module;
- chaque table de `propre` a une colonne `retenue` : 0 pour une ligne qui porte, dans la table des anomalies après nettoyage, une anomalie bloquante (issue anomalie ou à arbitrer) sans décision du métier, 1 sinon; une décision quelle qu'elle soit (garder, rattacher) résout l'anomalie, et une anomalie sans ligne (total d'une période) n'écarte rien; chaque fait reprend la retenue de sa ligne de `propre`, et une ligne de facture ou d'achat n'est retenue que si son en-tête l'est aussi (`dw.contrat_retenue`); une consommation ou une ligne de facture liée à une intervention non retenue reste retenue, le CA et le stock ne dépendant pas de l'intervention; pour faire compter une ligne exclue, le métier la tranche dans le classeur d'arbitrage (phase 8), ou le consultant revoit la gravité du contrôle dans `config/anomalies.yaml` (phase 7);
- dans `qualite`, les valeurs sont celles des fichiers CSV de `data/anomalies` et `data/nettoyage` : une valeur d'une colonne sensible y reste « masqué » (et non vide), et les mêmes refus s'appliquent avant toute écriture (valeur sensible non masquée, table non qualifiée), ainsi qu'un texte plus long que sa colonne en base;
- les jours fériés et les valeurs admises des listes fermées sont repris à chaque exécution de `config/gestion.yaml` et du dictionnaire revu, pour les dimensions du modèle en étoile : une année absente de `jours_feries` n'a aucune ligne dans `qualite.jour_ferie`, une année déclarée avec une liste vide y a une ligne sans jour; `qualite.valeur_liste` ne reprend ni les valeurs invalides ou à arbitrer, ni les colonnes sensibles, et une liste pas encore revue y figure avec ses valeurs au statut « observé »;
- le schéma `dw` est reconstruit entièrement par la procédure `dw.reconstruire` du pack, appelée dans la transaction de l'écriture juste avant que l'exécution passe à « réussie » : `propre` et `dw` reflètent toujours la même exécution, et `dw.journal_reconstruction` ne garde que la dernière reconstruction (l'historique reste dans `qualite`); la procédure refuse de s'exécuter hors d'une transaction, ce qui interdit un `dw` à moitié construit après un appel isolé depuis SSMS;
- le contrat d'entrée du pack (`dw.contrat_entree`) liste les colonnes de `propre` que le pack lit, avec leur famille (texte, date, heure, entier, décimal) : il est vérifié avant toute construction, et un écart (table ou colonne absente, famille différente, après une évolution du dictionnaire par exemple) fait échouer l'exécution avec la liste de tous les écarts, sans valeur du client; on corrige alors le dictionnaire ou le pack; il liste aussi les rattachements que le pack utilise (`dw.contrat_rattachement` : table, clé, référentiel), vérifiés contre `qualite.regle_rattachement` de l'exécution, si bien qu'une règle de rapprochement retirée de `config/gestion.yaml` fait échouer l'exécution au lieu d'envoyer toutes les lignes vers le membre « introuvable »;
- le pack déclare les mesures de chaque fait et les colonnes de `propre` dont elles sont tirées (`dw.contrat_mesure`, avec un signe pour une mesure calculée), et les dates lues sur la ligne même d'un fait (`dw.contrat_date`) : une colonne numérique ajoutée à un fait sans sa déclaration sort en non conforme à la vérification; les dates venues d'un en-tête (date et échéance d'une ligne de facture ou d'achat) ne sont pas contrôlées ligne à ligne, leurs -1 et -2 mêlant un en-tête absent et une date vide;
- les tables de faits de `dw` ont des clés étrangères vers les dimensions : `dw.reconstruire` vide d'abord tous les faits (`dw.vider_faits`, qui vide une table de faits référencée par une autre après celle-ci), puis reconstruit les dimensions, puis les faits;
- chaque dimension de `dw` a deux membres spéciaux, -1 « non renseigné » et -2 « introuvable », et ses autres clés sont numérotées dans l'ordre du code, en classement binaire (la casse compte, comme dans la comparaison « telle quelle » du traitement) : les mêmes données redonnent les mêmes clés; un code qui occupe plusieurs lignes d'un référentiel garde la première dans l'ordre du lignage (`lignes_source` en donne le nombre), sauf un intervenant, qui garde sa période d'emploi la plus récente;
- le rattachement dit, pour chaque ligne de `propre` qui cite un référentiel, quelle ligne du référentiel elle cite : il reprend les règles de `config/gestion.yaml` de type `existence_dans_reference` ou `date_dans_periode_reference`, avec leur comparaison (telle quelle, après normalisation, mots dans le désordre) mais sans leur filtre, deux règles de même clé et de même référentiel ne faisant qu'un rattachement; une clé vide ou absente du référentiel n'a pas de ligne, et plusieurs lignes du référentiel de même clé sont départagées par la date de la ligne quand une seule de leurs périodes la contient, sinon par l'ordre du lignage; les lignes sont désignées par leur lignage (`id_chargement`, `num_ligne_source`), sans valeur du client; une règle de rapprochement ajoutée ou retirée dans `config/gestion.yaml` change donc aussi les rattachements, à l'exécution suivante;
- chaque table de faits de `dw` (`fait_intervention`, `fait_consommation`, `fait_ligne_facture`, `fait_achat`, `fait_ecriture`) a une ligne par ligne de `propre`, sans filtre (les lignes annulées, non facturables ou en anomalie restent et se distinguent par leurs colonnes), avec son lignage; une clé vide pointe vers le membre -1 de la dimension, une clé qui ne se rattache à aucune ligne du référentiel vers -2, si bien que les nombres de -1 et de -2 d'un fait se comparent aux clés vides et introuvables du bilan des rattachements; une consommation ou une ligne de facture porte la clé de son intervention dans `fait_intervention`, ou NULL avec la raison dans `lien_intervention` (non renseignée, introuvable); une ligne de facture ou d'achat reçoit les dates, le client ou le fournisseur et le type de pièce de son en-tête (`lien_entete`), les totaux des en-têtes n'étant pas repris (la somme des lignes les donne); une écriture du FEC porte le numéro de la facture ou de la pièce d'achat que désigne sa référence de pièce, tous journaux confondus (chez Frigéo, seules les écritures des journaux de ventes et d'achats en désignent un, les encaissements ne portant pas le numéro de la facture), mais ni client ni fournisseur, et le libellé du compte auxiliaire n'entre pas dans `dw`;
- le calendrier (`dw.dim_date`) va du 1er janvier de la première année chargée au 31 décembre de l'année qui suit `PERIODE_FIN` : pour une année absente de `jours_feries`, les indicateurs férié et ouvré restent vides; il suffit de déclarer l'année dans `config/gestion.yaml` et de rejouer la période;
- les tables de `propre` étant recréées à chaque exécution, seules les procédures du pack les lisent : une vue de `dw` ou de `pbi` ne porte que sur `dw`;
- pour une décision du métier sur une colonne sensible, `qualite.decision.valeur_retenue` reste vide et seule son empreinte est écrite (`empreinte_valeur_retenue`, avec la clé de `data/config/cle_empreintes.txt`);
- un notebook modifié hors de l'éditeur (par l'assistant, ou par `git pull`) se ferme sans l'enregistrer puis se rouvre avant de l'exécuter : sinon l'éditeur exécute l'ancienne version qu'il garde en mémoire, et peut la réenregistrer;
- les tests se lancent tous sans base par `python -m pytest tests -q`, comme à l'installation (README, rubrique « Installation »).

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
| M.8 | Exécuter le notebook 06 en entier : il relance les contrôles et réécrit les trois CSV de la période dans `data/anomalies/` (table des anomalies, bilan, lignes non évaluables) | C | notebook 06 | opérationnel |
| M.9 | Revoir `config/anomalies.yaml` quand une colonne ou un indicateur change (le notebook 06 liste les colonnes non déclarées et les contrôles non qualifiés) | A, puis C | `config/anomalies.yaml` | opérationnel |
| M.10 | Exécuter le notebook 07 en entier, puis l'arbitrage si des éléments sont à trancher (phase 8, étapes 8.3 à 8.7); l'exécution complète écrit aussi la période en base et la vérifie (phase 9, actions 9.7 et 9.8) | C, M | notebook 07, Excel | opérationnel |

Une fois par an : valider dans le formulaire des règles de gestion les jours fériés de la nouvelle année, proposés dès que ses premiers exports sont chargés (le notebook 05 avertit quand une année manque) et vérifier que les paramètres annuels du client couvrent la nouvelle année.

## Points ouverts

- **Changement d'année.** Le modèle de périodes garde une période annuelle unique suivie de mois. Le passage à un export annuel de l'année suivante n'est pas prévu.
- **Formulaires.** Les formulaires des règles de contrôle (phase 5) et des règles de gestion (phase 6) sont faits. Deux familles de règles de gestion pourraient tenir sur une ligne du formulaire au lieu de la feuille des autres règles : les plages d'une valeur selon une autre colonne et les correspondances entre une valeur et la catégorie de la ligne liée.
- **Rapport.** Le rapport au client (plan, destinataire, format) n'est pas encore défini; les parties 2.5 et 3.3 en sont les premières briques.
- **Découverte des encodages et séparateurs.** Ils sont déclarés à la main dans `config/sources.yaml`; l'étape qui les proposerait n'est pas faite.
- **Dates dont le siècle a été ajouté.** Elles ne sont pas soumises à la confirmation du métier; les faire confirmer dans le classeur d'arbitrage serait une amélioration possible.
- **Base de données.** L'authentification Windows est la seule prévue; la connexion à Azure SQL Database (étape 10) reste à faire. Un script ajouté avec un numéro inférieur à celui d'un script déjà appliqué serait appliqué après lui sans alerte, alors qu'une reconstruction l'appliquerait avant : toujours numéroter à la suite. Le jalon du premier déploiement (tag Git à partir duquel les scripts sont figés) reste à poser.
