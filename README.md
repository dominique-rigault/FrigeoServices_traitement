# Frigéo Services : traitement de données

Cas de portfolio de traitement de données pour une PME fictive de maintenance frigorifique, Frigéo Services (Eure et Seine-Maritime). Les entreprises, personnes, clients, identifiants et montants sont entièrement fictifs.

L'objectif est de démontrer une méthode de traitement standardisée, traçable et réutilisable en mission, depuis des exports bruts hétérogènes jusqu'à des tableaux de bord de pilotage.

## Contexte

Les logiciels de l'entreprise ne sont pas interfacés. L'ERP de planification (CSV), la facturation et les achats (Excel), la comptabilité (FEC), le tableur RH et le CRM (CSV) produisent chacun leurs exports, avec les défauts habituels d'une PME : ressaisies, exports successifs, encodages différents, erreurs de saisie.

La mission consiste à charger ces exports tels quels, contrôler leur qualité, rapprocher les sources, puis calculer les indicateurs d'activité et la marge opérationnelle par intervention.

## Démarche

| Étape | Contenu | Outil | Notebook | Avancement |
| --- | --- | --- | --- | --- |
| 1 | Inventaire et chargement des fichiers bruts sans modification, avec lignage | Python, Jupyter | 01 | Fait sur le cas Frigéo, à rendre générique |
| 2 | Profilage de chaque fichier | Python, Jupyter | 02 | Fait sur le cas Frigéo, à rendre générique |
| 2b | Configuration des sources, chargement piloté, masquage, tests | Python, Jupyter | aucun | Terminé |
02c | Terminé, sauf une cellule propre au cas (comparaison avec le chapitre 4) |
| 2d | Revue du dictionnaire par le métier (classeur de revue, import et fusion des statuts) | Python, Excel | 02c | Terminé |
| 3 | Contrôles de format et de complétude, détection des doublons | Python, Jupyter | 03 | Terminé |
| 4 | Contrôles des règles de gestion et rapprochements entre sources | Python, Jupyter | 04 | Terminé |
| 5 | Table des anomalies | Python, Jupyter | 05 | À venir |
| 6 | Règles de nettoyage explicites et jeu de données nettoyé | Python, Jupyter | 06 | À venir |
| 7 | Modèle en étoile, indicateurs et marge opérationnelle | SQL Server, Azure SQL Database | aucun | À venir |
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

## Limites et adaptation à un autre client

Les notebooks 03 et 04 ne contiennent aucun nom de table, de colonne ni de valeur propre à Frigéo Services, et le notebook 02c une seule cellule, la comparaison avec le chapitre 4, à retirer chez un autre client. Les notebooks 01 et 02 en contiennent encore (formats des fichiers texte déclarés dans le notebook, colonnes examinées une à une, valeurs affichées), et sont à rendre génériques avant un cas réel. Hors de ces notebooks, tout ce qui est propre au client tient dans les quatre fichiers de `config/` (`sources.yaml`, `sensibilite.yaml`, `controles.yaml`, `gestion.yaml`) et dans le dictionnaire revu par le métier. Le code porte cependant l'empreinte des données rencontrées sur quelques points :

- **Types de règles de gestion.** Le catalogue de l'étape 4 (28 types génériques) ne couvre que les règles de ce cas. Un autre client demandera des types nouveaux, ajoutés au catalogue sans reprendre les autres.
- **Natures reconnues.** Trois formes de date, l'heure HH:MM, les décimaux à virgule ou à point. Des heures HH:MM:SS, des milliers séparés par une espace ou des dates MM/JJ/AAAA demanderaient d'étendre `profilage.py` et `typage.py`.
- **Périodes.** Une période annuelle puis des mois (`perimetre.py`). Un client qui ne livre que des mois ou des trimestres demanderait d'adapter ce modèle, que suivent aussi les totaux par période.
- **Seuils du dictionnaire.** Les seuils de génération (200 valeurs, 12 valeurs principales, 95 %, 2 % de vides) sont des constantes du code, fixées a priori; les déplacer dans la configuration serait simple.
- **Formats de fichiers.** Texte délimité et Excel seulement. Les encodages et les séparateurs sont déclarés à la main : l'étape qui les découvrirait n'est pas faite.
- **Stock théorique.** Les entrées sont lues dans une seule table, et les sorties dans une seule table. Un client qui exporte ses retours ou ses ventes au comptoir dans un fichier à part demanderait d'étendre le type, ou de déclarer une seconde règle.
- **Lieux de stockage.** Un seul lieu. Un stock par référence et par lieu est possible si chaque table porte un code de lieu, mais pas les transferts entre lieux.
- **Stock rendu négatif par un avoir.** Il n'est signalé qu'à la sortie suivante. Le stock n'est contrôlé qu'à partir de la date du stock initial, qu'il vaut mieux lire dans le fichier du client que déclarer dans la configuration.

## Structure du dépôt

```
config/      configuration propre au client (sources, sensibilité, contrôles, doublons et règles de gestion)
data/        données locales, ignorées par Git
docs/        documentation
notebooks/   un notebook par étape (01 à 06)
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
  config/           dictionnaire généré (contient des valeurs observées)
  revue/            classeur de revue du dictionnaire (étape 2d)
```

## Conventions de travail

- Une branche par étape, fusionnée par pull request vers `main`.
- Messages de commit à l'impératif, en français.
- Notebooks versionnés sans leurs sorties.

## Auteur

Dominique Rigault, consultant en données.