# Frigéo Services : traitement de données

Cas de portfolio de traitement de données pour une PME fictive de maintenance frigorifique, Frigéo Services (Eure et Seine-Maritime). Les entreprises, personnes, clients, identifiants et montants sont entièrement fictifs.

L'objectif est de démontrer une méthode de traitement standardisée, traçable et réutilisable en mission, depuis des exports bruts hétérogènes jusqu'à des tableaux de bord de pilotage.

## Contexte

Les logiciels de l'entreprise ne sont pas interfacés. L'ERP de planification (CSV), la facturation et les achats (Excel), la comptabilité (FEC), le tableur RH et le CRM (CSV) produisent chacun leurs exports, avec les défauts habituels d'une PME : ressaisies, exports successifs, encodages différents, erreurs de saisie.

La mission consiste à charger ces exports tels quels, contrôler leur qualité, rapprocher les sources, puis calculer les indicateurs d'activité et la marge opérationnelle par intervention.

## Démarche

| Étape | Contenu | Outil | Notebook | Avancement |
| --- | --- | --- | --- | --- |
| 1 | Inventaire et chargement des fichiers bruts sans modification, avec lignage | Python, Jupyter | 01 | Terminé |
| 2 | Profilage de chaque fichier | Python, Jupyter | 02 | Terminé |
| 2b | Configuration des sources, chargement piloté, masquage, tests | Python, Jupyter | aucun | Terminé |
| 2c | Dictionnaire des données généré à partir des données observées, à faire valider par le métier | Python, Jupyter | 03 | Terminé |
| 2d | Revue du dictionnaire par le métier (classeur de revue, import et fusion des statuts) | Python, Excel | 03 | Terminé |
| 3 | Contrôles de format et de complétude, détection des doublons, formulaire des règles de contrôle pour le métier | Python, Excel, Jupyter | 04 | Terminé |
| 4 | Contrôles des règles de gestion et rapprochements entre sources, formulaire des règles de gestion pour le métier | Python, Excel, Jupyter | 05 | Terminé |
| 5 | Table des anomalies, gravité et indicateurs affectés, export CSV | Python, Jupyter | 06 | Terminé |
| 6 | Règles de nettoyage explicites, décisions du métier ligne par ligne, journal des corrections | Python, Excel, Jupyter | 07 | Terminé |
| 7 | Base SQL Server (socle, écriture et vérification des données chargées et nettoyées et des sorties de la qualité), puis modèle en étoile, indicateurs et marge opérationnelle | SQL Server, Python, Azure SQL Database | 07 | En cours (socle, écriture, dimensions, rattachement aux référentiels et faits terminés) |
| 8 | Tableaux de bord direction et qualité | Power BI | aucun | À venir |
| 9 | Documentation de la méthode, des choix et des limites | Markdown | aucun | À venir |
| 10 | Déploiement sur Azure et passation | Azure, Power Automate | aucun | À venir |

Le mode opératoire d'un cycle de traitement (qui fait quoi et dans quel ordre, entre le consultant, le métier du client et l'assistant LLM) est décrit dans [mode_operatoire.md](mode_operatoire.md).

## Principes

- **Aucune correction manuelle.** Tout nettoyage passe par une règle explicite, versionnée et traçable.
- **Lignage.** Chaque enregistrement chargé conserve son fichier source, son numéro de ligne physique (en-tête = ligne 1) et sa date de chargement.
- **Anomalies tracées.** Chaque écart est consigné avec le fichier, la ligne, la clé métier, le champ, la valeur constatée, la règle violée, la gravité et les indicateurs affectés.
- **Données et secrets hors dépôt.** Les fichiers de données et les identifiants ne sont jamais versionnés (`.gitignore`, variables d'environnement).
- **Configuration propre au client séparée du code générique.** src/ ne contient aucun nom de fichier ni de colonne d'un client, et config/ porte tout ce qui change d'un client à l'autre.

## Lire les résultats

Les fichiers écrits dans `data/anomalies/` se lisent avec les conventions suivantes.

- **Registre de référence.** C'est la table des anomalies après nettoyage (`anomalies_nettoyees_AAAA-MM.csv`), à présenter au métier : les défauts corrigés sans ambiguïté et leurs conséquences sur les autres lignes en ont disparu. La table des données brutes (`anomalies_AAAA-MM.csv`) sert à mesurer ce que le nettoyage résout.
- **Issues.** Seules les lignes « anomalie » sont comptées. Une ligne « à arbitrer » attend la décision du métier (classeur d'arbitrage). Une ligne « information » n'est pas une anomalie : pratique normale décrite par le client (annulation sur place facturée, délai non échu), ou suite d'un écart déjà signalé.
- **Un écart, une ligne.** Un rapprochement entre deux tables est porté par la ligne de la table de la règle, pas forcément par celle qui porte l'erreur. Un stock qui devient négatif est porté par la sortie qui le fait passer sous zéro, les sorties suivantes restant en information tant qu'il est négatif. Un chevauchement d'interventions est porté par celle qui commence le plus tard, comparée à l'intervention précédente qui finit le plus tard.
- **Cascades.** Un défaut sur une ligne peut produire des écarts sur les lignes qui s'y rattachent : une durée aberrante fait chevaucher les interventions suivantes du même intervenant, une date de création de client fausse fait échouer le contrôle de toutes ses interventions, une catégorie mal écrite celui des lignes de sa facture. La valeur affichée et la colonne `champ` disent quelle autre table ou quelle autre ligne est en cause.
- **Lignes non évaluables.** Une ligne qu'une règle de gestion ne peut pas juger (valeur vide ou illisible, ligne liée absente ou inutilisable) n'est pas dans la table des anomalies. Elle figure, avec son lignage et sans aucune valeur, dans `non_evaluables_AAAA-MM.csv` (et `non_evaluables_nettoyees_AAAA-MM.csv` après nettoyage), qui distingue « contrôlé sans écart » de « non contrôlable ». Une ligne de référentiel inutilisable (sortie antérieure à l'entrée d'un intervenant, par exemple) rend non évaluables les lignes qui s'y rapportent, et porte elle-même l'écart d'une règle d'ordre entre ses deux dates. La cause n'y est pas encore donnée ligne par ligne. Une date facultative vide (date de lettrage d'une écriture non lettrée, par exemple) laisse la ligne hors champ, pas non évaluable.
- **Doublons.** Toutes les lignes d'un groupe sont listées, la première occurrence comprise, à la suite. Pour un doublon exact, la ligne en surnombre est celle que le nettoyage retire. Pour une table d'en-têtes de documents qui déclare sa table des lignes (`table_des_lignes`), deux en-têtes identiques hors clé ne sont à arbitrer que si leurs lignes le sont aussi, dans n'importe quel ordre et en même nombre. Pour un référentiel déclaré `regrouper_codes` (clients, fournisseurs, clé d'une seule colonne), une valeur en double hors de la clé (même SIRET) est soumise au métier comme deux codes possibles d'une même entité : le classeur d'arbitrage propose de rattacher chaque code au code de la première ligne du groupe dans l'ordre des fichiers et des lignes, que le métier confirme ou corrige. Une ligne sans code, ou dont la clé est sensible, reste une ligne en doublon ordinaire.
- **Masquage.** La valeur d'une colonne sensible, et la clé d'une ligne dont une colonne de clé est sensible, s'écrivent « masqué ». Au journal du nettoyage, une valeur masquée est accompagnée de son empreinte avant et après correction (colonnes `empreinte_avant` et `empreinte_apres`), calculée avec une clé secrète conservée dans `data/config/cle_empreintes.txt` (`nettoyage.empreinte_valeur`) : qui a la clé et les données vérifie une correction sans que la valeur figure dans le fichier.

## Limites et adaptation à un autre client

Les notebooks 01 à 07 ne contiennent aucun nom de table, de colonne ni de valeur propre à Frigéo Services. Hors de ces notebooks, tout ce qui est propre au client tient dans les cinq fichiers de `config/` (`sources.yaml`, `sensibilite.yaml`, `controles.yaml`, `gestion.yaml`, `anomalies.yaml`), dans le dictionnaire revu par le métier et dans ses décisions ligne par ligne (`data/config/decisions.yaml`). Le code porte cependant l'empreinte des données rencontrées sur quelques points :

- **Types de règles de gestion.** Le catalogue de l'étape 4 (31 types génériques) ne couvre que les règles de ce cas. Un autre client demandera des types nouveaux, ajoutés au catalogue sans reprendre les autres.
- **Échéances.** Le type `dates_ordonnees` borne un délai en jours. Une échéance à « N jours fin de mois » ne se contrôle donc que par l'enveloppe de ses délais possibles (de 30 à 75 jours pour 30 ou 45 jours fin de mois), sans le calcul exact selon les conditions de paiement de chaque fournisseur, qui demanderait un type entre deux tables.
- **Plausibilité des dates.** Une date des référentiels n'est contrôlée que par des bornes larges : un minimum fixe, et la date de coupure plus une marge. Une faute de saisie qui reste entre ces bornes (2021 pour 2012, par exemple) passe inaperçue.
- **Natures reconnues.** Trois formes de date, l'heure HH:MM, les décimaux à virgule ou à point. Des heures HH:MM:SS, des milliers séparés par une espace ou des dates MM/JJ/AAAA demanderaient d'étendre `profilage.py` et `typage.py`. Une date MM/JJ/AAAA isolée dans une colonne de dates JJ/MM/AAAA n'est repérée que si elle est impossible lue jour puis mois (25 comme mois, par exemple) : le classeur d'arbitrage propose alors la date lue mois puis jour, à confirmer par le métier. Lisible dans les deux sens (03/04/2025), elle passe pour une date juste.
- **Périodes.** Une période annuelle puis des mois (`perimetre.py`). Un client qui ne livre que des mois ou des trimestres demanderait d'adapter ce modèle, que suivent aussi les totaux par période.
- **Seuils du dictionnaire.** Les seuils de génération (200 valeurs, 12 valeurs principales, 95 %, 2 % de vides) sont des constantes du code, fixées a priori; les déplacer dans la configuration serait simple.
- **Formats de fichiers.** Texte délimité et Excel seulement. Les encodages et les séparateurs sont déclarés à la main : l'étape qui les découvrirait n'est pas faite.
- **Stock théorique.** Les entrées sont lues dans une seule table, et les sorties dans une seule table. Un client qui exporte ses retours ou ses ventes au comptoir dans un fichier à part demanderait d'étendre le type, ou de déclarer une seconde règle.
- **Lieux de stockage.** Un seul lieu. Un stock par référence et par lieu est possible si chaque table porte un code de lieu, mais pas les transferts entre lieux.
- **Stock rendu négatif par un avoir.** Il n'est signalé qu'à la sortie suivante. Le stock n'est contrôlé qu'à partir de la date du stock initial, qu'il vaut mieux lire dans le fichier du client que déclarer dans la configuration.
- **Encodages suspects.** La règle `encodage` essaie les trois encodages d'Europe occidentale (Windows-1252, ISO-8859-15, Latin-1). Des fichiers venus d'un autre jeu de caractères (Europe centrale, cyrillique) demanderaient d'étendre `ENCODAGES_SUSPECTS`. Un `à` mal décodé n'est plus reconnaissable si un logiciel a remplacé l'espace insécable qui le suit par une espace ordinaire, et un double encodage n'est signalé qu'une fois.
- **Espaces.** La règle `espaces` signale puis corrige, dans toutes les colonnes de texte, les espaces en début ou en fin de texte, les espaces répétées et les espaces autres que l'espace ordinaire (insécable, fine, tabulation). Les sauts de ligne ne sont ni signalés ni corrigés : rien ne distingue un saut voulu dans un texte libre d'un saut parasite. Une espace insécable voulue (avant un deux-points dans un libellé) devient une espace ordinaire. Avant nettoyage, une valeur d'une liste fermée qui ne diffère d'une valeur connue que par une espace est signalée deux fois (hors liste et espaces).
- **Variantes d'une clé.** Une clé qui ne se retrouve dans son référentiel qu'après normalisation (casse, accents, espaces, et ordre des mots si la règle le tolère) est signalée à arbitrer, règle « forme du référentiel ». Elle est corrigée au nettoyage par la forme du référentiel quand celle-ci est unique et déjà celle de 95 % au moins des lignes de la même clé, compté au seuil robuste : une variante isolée demande ainsi 38 lignes déjà bien écrites. Sinon elle reste à arbitrer, avec la forme du référentiel préremplie dans le classeur quand elle est unique, y compris sur une colonne sensible. Une inversion de l'ordre des mots, tolérée par la règle, n'est jamais signalée. Seuls les rapprochements d'une clé avec un référentiel cherchent ces variantes (existence dans la table de référence, date dans une période de la table de référence). Les concordances entre deux référentiels et les intervalles sans chevauchement ne les cherchent pas, et une clé de plusieurs colonnes est signalée sans proposition ni correction.
- **Doublons de documents.** Deux en-têtes identiques hors clé ne sont signalés que si leurs lignes sont identiques, colonne par colonne hors de la clé des lignes. Un document ressaisi avec ses lignes regroupées autrement (une ligne de quantité 2 au lieu de deux lignes de quantité 1), ou rattaché à une autre intervention, n'est donc pas signalé.
- **Formulaire des règles de contrôle.** Il réécrit `config/controles.yaml` en entier, dans l'ordre du dictionnaire : un commentaire écrit à la main dans ce fichier est perdu, et seuls les motifs (expressions régulières), l'unité des colonnes de durée et la table des lignes d'une table d'en-têtes s'y écrivent encore à la main, le formulaire les montrant sans les modifier. Il porte les minimums et maximums observés (masqués pour une colonne sensible) et reste donc dans `data/formulaires/`. Un formulaire exporté avant une modification du fichier est refusé à l'import.
- **Formulaire des règles de gestion.** Il réécrit `config/gestion.yaml` en entier : une ligne de commentaire écrite à la main y est perdue, le commentaire d'une règle s'écrit sous sa clé `commentaire`. Seules trois familles de règles (valeur connue d'une colonne de référence, colonne renseignée selon la valeur d'une autre, date dans la période de son export) et les jours fériés y sont proposés et modifiables; les autres règles s'y retirent ou s'y commentent seulement, et une règle nouvelle hors de ces familles est demandée en texte libre, puis écrite par le consultant. Les paramètres communs par type (clé `parametres_communs`) y sont montrés avec la mention « (commun) » dans la feuille des autres règles, sans y être modifiables; les feuilles des trois familles ne les montrent pas. Les jours fériés proposés sont ceux de la France métropolitaine, sans l'Alsace-Moselle. Le formulaire porte des valeurs du client (valeurs des listes, codes) et reste dans `data/formulaires/`. Un formulaire exporté avant une modification du fichier est refusé à l'import.
- **Gravité et indicateurs affectés.** Ils sont déclarés par le consultant dans `config/anomalies.yaml`, à faire valider par le métier, et non calculés. La gravité par défaut est grossière (« majeure » dès qu'une colonne alimente un indicateur) et se nuance par des exceptions, sans code. Le fichier est à revoir quand un indicateur ou une colonne change.
- **Export CSV.** Séparateur point-virgule et virgule décimale, pour Excel en paramètres français. Ouvert par double-clic, Excel retire les zéros en tête, écrit un SIRET en notation scientifique, lit `2026-03` comme une date et une valeur commençant par `=` comme une formule. Il faut donc ouvrir le fichier par Données, À partir d'un fichier texte/CSV, sans détection des types. Les identifiants d'anomalie changent si un fichier est réexporté avec des lignes décalées.
- **Nettoyage automatique.** Les règles ne corrigent que ce qui se lit sans ambiguïté : encodages, espaces superflues, clés écrites autrement que dans leur référentiel, remplacements décidés au dictionnaire, formes élargies de date et de nombre, doublons exacts. Une durée écrite avec ses unités (95 min, 2 h, 1h10) n'est convertie que dans une colonne déclarée durée (règle `duree` de `config/controles.yaml`, minutes ou heures), et seulement si la conversion est exacte dans cette unité. Ailleurs, elle reste signalée. La conversion est visible au journal du nettoyage (« durée en minutes »). Dans le classeur d'arbitrage, une valeur retenue écrite avec ses unités est refusée à l'import : le métier la saisit dans l'unité de la colonne. Une année écrite sur deux chiffres est complétée en 20AA si la date ne dépasse pas la date de coupure : une date ancienne mal saisie peut ainsi devenir fausse, et la conversion n'est visible qu'au journal du nettoyage (« siècle 20 ajouté »).
- **Décisions du métier.** Le classeur d'arbitrage porte des valeurs du client, colonnes sensibles comprises, et reste dans `data/formulaires/`. Une décision est rattachée à l'identifiant de l'anomalie et à une empreinte de la donnée : un fichier réexporté avec des lignes décalées rend les décisions caduques, et les éléments reviennent au classeur suivant. On ne peut pas corriger une cellule vers une valeur vide, et une anomalie de règle de gestion (hors écart à arbitrer) ne se tranche pas dans le classeur : sa correction se fait dans le logiciel source. La décision « rattacher » (sorte « code ») laisse la ligne dans les données nettoyées avec son code : le regroupement sous le code principal se fait dans la base. Un code principal lui-même rattaché, ou un même code rattaché à deux codes principaux, est refusé à l'import du classeur. Une décision « corriger » ou « retirer » devenue caduque ne s'applique plus. Le notebook 07 les compte, et les retire du fichier des décisions à la demande (paramètre `RETIRER_CADUQUES`), avec une copie datée et une trace du retrait.
- **Empreintes.** La clé des empreintes du journal est créée au premier nettoyage, se garde avec les données du client et ne se transmet qu'à une personne qui a déjà accès aux données (un évaluateur). La perdre ou la remplacer rend les empreintes des journaux suivants incomparables aux anciennes, sans autre conséquence, le journal se régénérant à chaque exécution. L'empreinte des décisions du métier (`data/config/decisions.yaml`), qui sert seulement à voir si la donnée a changé, reste un hachage sans clé : ce fichier ne doit pas quitter le poste du client, car une valeur peu variée s'y retrouverait en essayant les valeurs possibles; passer au hachage à clé rendrait caduques les décisions déjà enregistrées.
- **Jeu nettoyé.** Il n'est pas écrit sur disque : il se recalcule à chaque exécution à partir des fichiers bruts, des règles et des décisions, la source brute restant la seule référence. La représentation de la source est conservée (une date en texte reste un texte); les types sont attribués à l'écriture en base (schéma `propre`, étape 7).
- **Base de données.** Les tables des schémas `chargement` (valeurs telles que livrées) et `propre` (valeurs nettoyées et typées) sont générées à partir du dictionnaire revu, supprimées et recréées à chaque exécution : elles reflètent la dernière exécution, l'historique n'étant gardé que dans le schéma `qualite`, une exécution par période de fin. Une colonne « entier (texte) » qui est un code (formes fermées, liste fermée, clé de Luhn ou motif) reste en texte, pour garder ses zéros de tête; les nombres sont en `decimal(28, 8)` et une date en `date`, sans heure. Un texte de plus de 4 000 caractères, une date native avec une heure ou un nombre de plus de 8 décimales arrêtent l'écriture sans rien modifier, et une valeur restée illisible après nettoyage est écrite vide dans `propre`. Jusqu'au premier déploiement d'une base dont le contenu est à conserver, les scripts SQL du socle peuvent être réécrits, la base se reconstruisant par `python -m frigeo.base --recreer`; ensuite, toute évolution passe par un nouveau script. Les jours fériés de `config/gestion.yaml` et les valeurs admises des listes fermées du dictionnaire sont repris dans `qualite` à chaque exécution, pour les dimensions du modèle en étoile, sans les colonnes sensibles. Une année absente de `jours_feries` n'y a aucun jour férié : ses jours fériés ne sont connus de la base qu'une fois déclarés. Le schéma `dw` est reconstruit par une procédure unique, `dw.reconstruire`, déclarée par le pack métier : plusieurs packs sur une même base (un pack comptable commun à tous les clients à côté du pack métier, ou une entreprise qui exerce deux métiers) demanderaient un ordre de construction entre packs et une règle sur qui possède une dimension partagée. Les articles facturés (main d'œuvre, déplacement, forfaits) n'ont pas de référentiel : leur dimension se déduit des lignes de facture, sans compte de produit, et un client qui fournit son catalogue d'articles permettrait de la compléter. Le rattachement d'une ligne à la ligne de son référentiel (pour relier un fait au bon membre de dimension) reprend les règles de `config/gestion.yaml` qui rapprochent une clé d'un référentiel, avec leur comparaison, mais sans leur filtre; plusieurs lignes du référentiel de même clé sont départagées par la date de la ligne quand une seule de leurs périodes la contient, sinon par l'ordre du lignage, comme les dimensions. Une clé qu'aucune de ces règles ne rapproche ne peut se rattacher que par égalité exacte de son code. Les faits du modèle en étoile ont une ligne par ligne de `propre`, sans filtre, avec son lignage; un document à en-tête et lignes (facture, pièce d'achat) n'a qu'un fait, au grain de la ligne, ses totaux d'en-tête n'étant pas repris. Les écritures du FEC n'ont ni client ni fournisseur : leur compte auxiliaire n'a pas la forme des codes des référentiels. Seule l'authentification Windows est prévue.

## Structure du dépôt

```
config/      configuration propre au client (sources, sensibilité, contrôles, doublons, règles de gestion, gravité et indicateurs)
data/        données locales, ignorées par Git
docs/        documentation
notebooks/   un notebook par étape, numérotés dans l'ordre d'exécution (01 à 07)
sql/         scripts T-SQL (étape 7)
src/         fonctions Python réutilisables (lecture, lignage, contrôles)
tests/       tests automatisés sur données fictives
```

## Installation

Prérequis : Python 3.11 ou plus récent, et Git.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows avec Git Bash
# source .venv/bin/activate     # Linux ou macOS
python -m pip install -r requirements.txt
python -m pip install -e .
python -m nbstripout --install
python -m pytest tests -q
```

La commande `nbstripout --install` retire automatiquement les sorties des notebooks à chaque commit. La dernière lance les tests.

## Données

Les fichiers de données ne sont pas versionnés. Ils sont attendus en local selon l'arborescence suivante :

```
data/
  raw/2025/         exports annuels 2025
  raw/2026/         exports mensuels 2026
  referentiels/     intervenants, clients, fournisseurs, catalogue, paramètres
  config/           dictionnaire généré (contient des valeurs observées), décisions du métier et clé des empreintes
  formulaires/      classeurs remplis par le métier (revue du dictionnaire, règles de contrôle, règles de gestion, arbitrage des anomalies), et appliques/ pour les classeurs appliqués
  anomalies/        table des anomalies, bilan par contrôle et lignes non évaluables en CSV (étape 5, et après nettoyage à l'étape 6)
  nettoyage/        journal et bilan du nettoyage en CSV (étape 6)
```

## Conventions de travail

- Une branche par étape, fusionnée par pull request vers `main`.
- Messages de commit à l'impératif, en français.
- Notebooks versionnés sans leurs sorties.

## Auteur

Dominique Rigault, consultant en données.