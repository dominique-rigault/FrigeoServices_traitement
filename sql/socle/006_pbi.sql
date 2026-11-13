/*
  Socle, script 006 : cadre des vues pbi.

  Power BI n'importe que les vues du schéma pbi, telles quelles : leurs noms
  et leurs colonnes forment l'interface convenue avec le rapport. Tant
  qu'ils ne changent pas, le rapport fonctionne. Chaque vue et chacune de
  ses colonnes sont donc déclarées ici par le script qui la crée, et la
  vérification compare cette déclaration à la base dans les deux sens : une
  colonne disparue ou renommée sort en non conforme avant que le rapport ne
  casse.

  Les vues métier appartiennent au pack (sql/packs/<pack>/005_vues.sql),
  les vues génériques du tableau qualité au socle. Aucune vue n'est
  SCHEMABINDING : les tables de dw ne sont pas supprimées à la
  reconstruction, seulement vidées et remplies.
*/

/* Une vue pbi et l'objet dont elle compte les lignes (schéma.objet). Une
   annotation « (où …) » déclare une condition appliquée au décompte de la
   source; toute autre annotation est un simple commentaire. */
CREATE TABLE dw.source_vue (
    vue     nvarchar(128)  NOT NULL,
    source  nvarchar(260)  NOT NULL,
    CONSTRAINT pk_source_vue PRIMARY KEY (vue)
);
GO

/* Les colonnes convenues d'une vue pbi : le contrat avec le rapport. */
CREATE TABLE dw.contrat_vue (
    vue      nvarchar(128)  NOT NULL,
    colonne  nvarchar(128)  NOT NULL,
    CONSTRAINT pk_contrat_vue PRIMARY KEY (vue, colonne),
    CONSTRAINT fk_contrat_vue_source
        FOREIGN KEY (vue) REFERENCES dw.source_vue (vue)
);
GO

/*
  Vues génériques du tableau qualité : les anomalies du registre après
  nettoyage, le taux par contrôle dans les deux états et le journal des
  chargements, lus dans dw et qualite, identiques chez tous les clients.
*/

CREATE VIEW pbi.[Contrôles] AS
SELECT id_controle AS [Clé contrôle],
       controle AS [Contrôle],
       etape AS [Étape],
       table_source AS [Table],
       champ AS [Champ],
       regle AS [Règle],
       gravite AS [Gravité],
       indicateurs AS [Indicateurs affectés]
FROM dw.dim_controle;
GO

CREATE VIEW pbi.[Anomalies] AS
SELECT id_fait_anomalie AS [Clé anomalie],
       id_anomalie AS [Identifiant d'anomalie],
       id_controle AS [Clé contrôle],
       table_source AS [Table],
       periode_export AS [Période d'export],
       cle AS [Clé de la ligne],
       champ AS [Champ],
       valeur AS [Valeur],
       constat AS [Constat],
       issue AS [Issue],
       detail AS [Détail],
       proposition AS [Proposition],
       gravite AS [Gravité],
       decision_metier AS [Décision du métier],
       fichier_source AS [Fichier source],
       feuille_source AS [Feuille source],
       num_ligne_source AS [Ligne source]
FROM dw.fait_anomalie;
GO

CREATE VIEW pbi.[Bilan des contrôles] AS
SELECT id_fait_bilan_controle AS [Clé bilan],
       etat AS [État],
       id_controle AS [Clé contrôle],
       controlees AS [Lignes contrôlées],
       anomalies AS [Anomalies],
       a_arbitrer AS [À arbitrer],
       informations AS [Informations],
       non_evaluables AS [Non évaluables],
       taux AS [Taux d'anomalies],
       lignes_distinctes AS [Lignes distinctes]
FROM dw.fait_bilan_controle;
GO

/*
  Chargements : le journal des fichiers chargés, toutes exécutions gardées
  (une par période de fin), avec la version du traitement : l'audit de ce
  que le rapport contient.
*/
CREATE VIEW pbi.[Chargements] AS
SELECT j.id_chargement AS [Clé chargement],
       e.periode_fin AS [Période de fin],
       j.fichier_source AS [Fichier source],
       j.feuille_source AS [Feuille source],
       j.periode_export AS [Période d'export],
       j.nb_lignes AS [Lignes],
       j.empreinte_sha256 AS [Empreinte SHA-256],
       j.date_chargement AS [Date de chargement (UTC)],
       e.version_traitement AS [Version du traitement],
       e.statut AS [Statut de l'exécution]
FROM qualite.journal_chargement AS j
JOIN qualite.execution AS e ON e.id_execution = j.id_execution;
GO

/* Déclaration des vues génériques : le contrat avec le rapport. */
INSERT INTO dw.source_vue (vue, source) VALUES
    (N'Contrôles', N'dw.dim_controle'),
    (N'Anomalies', N'dw.fait_anomalie'),
    (N'Bilan des contrôles', N'dw.fait_bilan_controle'),
    (N'Chargements', N'qualite.journal_chargement');
GO

INSERT INTO dw.contrat_vue (vue, colonne) VALUES
    (N'Contrôles', N'Clé contrôle'),
    (N'Contrôles', N'Contrôle'),
    (N'Contrôles', N'Étape'),
    (N'Contrôles', N'Table'),
    (N'Contrôles', N'Champ'),
    (N'Contrôles', N'Règle'),
    (N'Contrôles', N'Gravité'),
    (N'Contrôles', N'Indicateurs affectés'),
    (N'Anomalies', N'Clé anomalie'),
    (N'Anomalies', N'Identifiant d''anomalie'),
    (N'Anomalies', N'Clé contrôle'),
    (N'Anomalies', N'Table'),
    (N'Anomalies', N'Période d''export'),
    (N'Anomalies', N'Clé de la ligne'),
    (N'Anomalies', N'Champ'),
    (N'Anomalies', N'Valeur'),
    (N'Anomalies', N'Constat'),
    (N'Anomalies', N'Issue'),
    (N'Anomalies', N'Détail'),
    (N'Anomalies', N'Proposition'),
    (N'Anomalies', N'Gravité'),
    (N'Anomalies', N'Décision du métier'),
    (N'Anomalies', N'Fichier source'),
    (N'Anomalies', N'Feuille source'),
    (N'Anomalies', N'Ligne source'),
    (N'Bilan des contrôles', N'Clé bilan'),
    (N'Bilan des contrôles', N'État'),
    (N'Bilan des contrôles', N'Clé contrôle'),
    (N'Bilan des contrôles', N'Lignes contrôlées'),
    (N'Bilan des contrôles', N'Anomalies'),
    (N'Bilan des contrôles', N'À arbitrer'),
    (N'Bilan des contrôles', N'Informations'),
    (N'Bilan des contrôles', N'Non évaluables'),
    (N'Bilan des contrôles', N'Taux d''anomalies'),
    (N'Bilan des contrôles', N'Lignes distinctes'),
    (N'Chargements', N'Clé chargement'),
    (N'Chargements', N'Période de fin'),
    (N'Chargements', N'Fichier source'),
    (N'Chargements', N'Feuille source'),
    (N'Chargements', N'Période d''export'),
    (N'Chargements', N'Lignes'),
    (N'Chargements', N'Empreinte SHA-256'),
    (N'Chargements', N'Date de chargement (UTC)'),
    (N'Chargements', N'Version du traitement'),
    (N'Chargements', N'Statut de l''exécution');
GO
