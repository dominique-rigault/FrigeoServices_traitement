/*
  Socle, script 001 : schémas de la base et suivi des scripts appliqués.

  Cinq schémas, chacun alimenté par un seul acteur :
  - chargement : tables telles que livrées, en texte, avec lignage (Python)
  - propre : tables nettoyées et typées, avec lignage (Python)
  - qualite : anomalies, nettoyage, décisions, bilans et journaux (Python)
  - dw : modèle décisionnel, reconstruit à chaque chargement (procédure SQL)
  - pbi : vues exposées à Power BI, seul schéma qu'il lit

  Script appliqué une seule fois, dans une transaction, par l'applicateur
  de scripts : il ne teste donc pas l'existence des objets.
*/

CREATE SCHEMA chargement;
GO
CREATE SCHEMA propre;
GO
CREATE SCHEMA qualite;
GO
CREATE SCHEMA dw;
GO
CREATE SCHEMA pbi;
GO

/*
  Une ligne par script appliqué. nom_script est le chemin relatif au dossier
  sql (ex. socle/001_schemas.sql), ce qui distingue les scripts du socle et
  ceux des packs. L'empreinte permet de refuser un script modifié après son
  application. version_traitement (étiquette et commit Git) reste facultative,
  Git n'étant pas forcément présent là où le traitement s'exécute.
*/
CREATE TABLE qualite.script_applique (
    id_script           int IDENTITY(1, 1) NOT NULL,
    nom_script          nvarchar(260)      NOT NULL,
    empreinte_sha256    char(64)           NOT NULL,
    version_traitement  nvarchar(100)      NULL,
    date_application    datetime2(0)       NOT NULL
        CONSTRAINT df_script_applique_date DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_script_applique PRIMARY KEY (id_script),
    CONSTRAINT uq_script_applique_nom UNIQUE (nom_script)
);
GO