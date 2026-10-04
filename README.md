# Frigéo Services : traitement de données

Cas de portfolio de traitement de données pour une PME fictive de maintenance frigorifique, Frigéo Services (Eure et Seine-Maritime). Les entreprises, personnes, clients, identifiants et montants sont entièrement fictifs.

L'objectif est de démontrer une méthode de traitement standardisée, traçable et réutilisable en mission, depuis des exports bruts hétérogènes jusqu'à des tableaux de bord de pilotage.

## Contexte

Les logiciels de l'entreprise ne sont pas interfacés. L'ERP de planification (CSV), la facturation et les achats (Excel), la comptabilité (FEC), le tableur RH et le CRM (CSV) produisent chacun leurs exports, avec les défauts habituels d'une PME : ressaisies, exports successifs, encodages différents, erreurs de saisie.

La mission consiste à charger ces exports tels quels, contrôler leur qualité, rapprocher les sources, puis calculer les indicateurs d'activité et la marge opérationnelle par intervention.

## Démarche

| Étape | Contenu | Outil | Avancement |
| --- | --- | --- | --- |
| 1 | Inventaire et chargement des fichiers bruts sans modification, avec lignage | Python, Jupyter | En cours |
| 2 | Profilage de chaque fichier | Python, Jupyter | À venir |
| 3 | Contrôles de format et de complétude, détection des doublons | Python, Jupyter | À venir |
| 4 | Contrôles des règles de gestion et rapprochements entre sources | Python, Jupyter | À venir |
| 5 | Table des anomalies | Python, Jupyter | À venir |
| 6 | Règles de nettoyage explicites et jeu de données nettoyé | Python, Jupyter | À venir |
| 7 | Modèle en étoile, indicateurs et marge opérationnelle | SQL Server, Azure SQL Database | À venir |
| 8 | Tableaux de bord direction et qualité | Power BI | À venir |
| 9 | Documentation de la méthode, des choix et des limites | Markdown | À venir |
| 10 | Déploiement sur Azure et passation | Azure, Power Automate | À venir |

## Principes

- **Aucune correction manuelle.** Tout nettoyage passe par une règle explicite, versionnée et traçable.
- **Lignage.** Chaque enregistrement chargé conserve son fichier source, son numéro de ligne physique (en-tête = ligne 1) et sa date de chargement.
- **Anomalies tracées.** Chaque écart est consigné avec le fichier, la ligne, la clé métier, le champ, la valeur constatée, la règle violée, la gravité et les indicateurs affectés.
- **Données et secrets hors dépôt.** Les fichiers de données et les identifiants ne sont jamais versionnés (`.gitignore`, variables d'environnement).

## Structure du dépôt

```
notebooks/   un notebook par étape (01 à 06)
src/         fonctions Python réutilisables (lecture, lignage, contrôles)
sql/         scripts T-SQL (étape 7)
docs/        documentation
data/        données locales, ignorées par Git
```

## Installation

Prérequis : Python 3.11 ou plus récent, et Git.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows avec Git Bash
# source .venv/bin/activate     # Linux ou macOS
python -m pip install -r requirements.txt
python -m nbstripout --install
```

La dernière commande retire automatiquement les sorties des notebooks à chaque commit.

## Données

Les fichiers de données ne sont pas versionnés. Ils sont attendus en local selon l'arborescence suivante :

```
data/
  raw/2025/         exports annuels 2025
  raw/2026/         exports mensuels 2026
  referentiels/     intervenants, clients, fournisseurs, catalogue, paramètres
```

## Conventions de travail

- Une branche par étape, fusionnée par pull request vers `main`.
- Messages de commit à l'impératif, en français.
- Notebooks versionnés sans leurs sorties.

## Auteur

Dominique Rigault, consultant en données.