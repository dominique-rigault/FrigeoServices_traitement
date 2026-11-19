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
  nettoyage, le taux par contrôle dans les deux états, son historique par
  exécution et le journal des chargements, lus dans dw et qualite,
  identiques chez tous les clients.

  [Ordre de gravité] (1 bloquante, 2 majeure, 3 mineure, 9 autre) sert au
  tri de la gravité dans le rapport (Trier par colonne), qui sinon suivrait
  l'ordre alphabétique.
*/

CREATE VIEW pbi.[Contrôles] AS
SELECT id_controle AS [Clé contrôle],
       controle AS [Contrôle],
       etape AS [Étape],
       table_source AS [Table],
       champ AS [Champ],
       regle AS [Règle],
       gravite AS [Gravité],
       CASE gravite WHEN N'bloquante' THEN 1 WHEN N'majeure' THEN 2
                    WHEN N'mineure' THEN 3 ELSE 9 END AS [Ordre de gravité],
       indicateurs AS [Indicateurs affectés]
FROM dw.dim_controle;
GO

/*
  Anomalies : [Anomalie ouverte] vaut 1 pour une anomalie d'issue anomalie
  ou à arbitrer sans décision du métier, la règle qui exclut une ligne des
  indicateurs quand l'anomalie est bloquante (dw.controles_bloquants); une
  information n'est jamais ouverte.
*/

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
       CASE gravite WHEN N'bloquante' THEN 1 WHEN N'majeure' THEN 2
                    WHEN N'mineure' THEN 3 ELSE 9 END AS [Ordre de gravité],
       decision_metier AS [Décision du métier],
       CAST(CASE WHEN issue IN (N'anomalie', N'à arbitrer')
                  AND (decision_metier IS NULL OR LTRIM(RTRIM(decision_metier)) = N'')
                 THEN 1 ELSE 0 END AS bit) AS [Anomalie ouverte],
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
  Historique des contrôles : le bilan des contrôles de chaque exécution
  réussie (une par période de fin, rejouer une période remplaçant son
  exécution), dans les deux états, lu dans qualite.bilan_controle, pour
  suivre mois après mois la qualité des fichiers livrés. Le contrôle et sa
  gravité sont ceux de l'exécution; [Clé contrôle] relie la ligne au
  contrôle de la dernière reconstruction, -2 quand il n'y figure plus. Les
  non évaluables sont comptés à part, comme dans le bilan.
*/
CREATE VIEW pbi.[Historique des contrôles] AS
SELECT b.id_bilan_controle AS [Clé historique],
       e.periode_fin AS [Période de fin],
       e.fin AS [Fin de l'exécution (UTC)],
       b.etat AS [État],
       CASE WHEN b.controle = N'' THEN -1 ELSE COALESCE(c.id_controle, -2) END
           AS [Clé contrôle],
       b.controle AS [Contrôle],
       b.gravite AS [Gravité],
       b.controlees AS [Lignes contrôlées],
       b.anomalies AS [Anomalies],
       b.a_arbitrer AS [À arbitrer],
       b.informations AS [Informations],
       n.lignes AS [Non évaluables],
       b.taux AS [Taux d'anomalies]
FROM qualite.bilan_controle AS b
JOIN qualite.execution AS e
    ON e.id_execution = b.id_execution AND e.statut = N'réussie'
LEFT JOIN dw.dim_controle AS c
    ON c.controle = b.controle COLLATE Latin1_General_100_BIN2
   AND c.id_controle >= 1
OUTER APPLY (
    SELECT COUNT(*) AS lignes
    FROM qualite.non_evaluable AS v
    WHERE v.id_execution = b.id_execution
      AND v.etat = b.etat
      AND v.controle COLLATE Latin1_General_100_BIN2
          = b.controle COLLATE Latin1_General_100_BIN2
) AS n;
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
    (N'Historique des contrôles', N'qualite.bilan_controle (où id_execution IN (SELECT id_execution FROM qualite.execution WHERE statut = N''réussie''))'),
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
    (N'Contrôles', N'Ordre de gravité'),
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
    (N'Anomalies', N'Ordre de gravité'),
    (N'Anomalies', N'Décision du métier'),
    (N'Anomalies', N'Anomalie ouverte'),
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
    (N'Historique des contrôles', N'Clé historique'),
    (N'Historique des contrôles', N'Période de fin'),
    (N'Historique des contrôles', N'Fin de l''exécution (UTC)'),
    (N'Historique des contrôles', N'État'),
    (N'Historique des contrôles', N'Clé contrôle'),
    (N'Historique des contrôles', N'Contrôle'),
    (N'Historique des contrôles', N'Gravité'),
    (N'Historique des contrôles', N'Lignes contrôlées'),
    (N'Historique des contrôles', N'Anomalies'),
    (N'Historique des contrôles', N'À arbitrer'),
    (N'Historique des contrôles', N'Informations'),
    (N'Historique des contrôles', N'Non évaluables'),
    (N'Historique des contrôles', N'Taux d''anomalies'),
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
