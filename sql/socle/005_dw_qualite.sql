/*
  Socle, script 005 : tables génériques du tableau qualité dans dw.

  Le tableau de bord qualité lit les anomalies dans le modèle en étoile,
  comme les autres chiffres. Ces tables sont génériques (identiques chez
  tous les clients) : elles reprennent, pour l'exécution, le registre des
  anomalies et le bilan des contrôles que le traitement a écrits dans
  qualite, sans rien recalculer.

  - dw.dim_controle : un membre par contrôle du bilan (qualite.bilan_controle,
    les deux états réunis), même sans anomalie, pour qu'un taux à zéro
    existe. Attributs du bilan : étape, table, champ, règle, gravité,
    indicateurs affectés.
  - dw.fait_anomalie : une ligne par anomalie du registre après nettoyage
    (l'état « nettoyé » de qualite.anomalie, le registre principal), les
    trois issues comprises (anomalie, à arbitrer, information), avec les
    colonnes utiles à la descente et à l'export : clé, champ, valeur,
    constat, gravité, décision du métier. Les valeurs sont celles de
    qualite : une valeur d'une colonne sensible y est déjà « masqué ».
    Une anomalie sans ligne source (un total par période) reste, sans
    id_chargement. Le registre brut reste dans qualite.

  Comme les dimensions du pack : clé technique numérotée dans l'ordre
  binaire, membres -1 « (non renseigné) » et -2 « (introuvable) », libellé
  du contrôle en classement binaire, tables vidées puis remplies à chaque
  reconstruction, étapes inscrites dans dw.journal_reconstruction.

  Le pack appelle les trois procédures depuis dw.reconstruire :
  dw.vider_tableau_qualite avec les autres vidages, puis
  dw.construire_dim_controle et dw.construire_fait_anomalie. Un pack qui ne
  les appelle pas laisse ces tables vides, ce que la vérification sort en
  non conforme (limite au README).
*/

/*
  Un contrôle du traitement : un membre par libellé distinct du bilan des
  contrôles de l'exécution (les deux états réunis, les attributs de l'état
  nettoyé faisant foi quand le contrôle est dans les deux).
*/
CREATE TABLE dw.dim_controle (
    id_controle   int             NOT NULL,
    controle      nvarchar(400)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    etape         nvarchar(50)    NULL,
    table_source  nvarchar(128)   NULL,
    champ         nvarchar(4000)  NULL,
    regle         nvarchar(400)   NULL,
    gravite       nvarchar(50)    NULL,
    indicateurs   nvarchar(4000)  NULL,
    CONSTRAINT pk_dim_controle PRIMARY KEY (id_controle),
    CONSTRAINT uq_dim_controle_controle UNIQUE (controle)
);
GO

/*
  Une anomalie du registre après nettoyage, avec son lignage; id_chargement
  reste vide pour une anomalie sans ligne source (un total par période).
  id_anomalie est l'identifiant stable du registre, unique dans un état.
*/
CREATE TABLE dw.fait_anomalie (
    id_fait_anomalie  int             NOT NULL,
    id_anomalie       nvarchar(32)    NOT NULL,
    id_controle       int             NOT NULL,
    etape             nvarchar(50)    NOT NULL,
    table_source      nvarchar(128)   NULL,
    periode_export    nvarchar(20)    NULL,
    cle               nvarchar(1000)  NULL,
    champ             nvarchar(4000)  NULL,
    valeur            nvarchar(4000)  NULL,
    constat           nvarchar(4000)  NULL,
    issue             nvarchar(50)    NULL,
    statut_regle      nvarchar(50)    NULL,
    detail            nvarchar(4000)  NULL,
    proposition       nvarchar(4000)  NULL,
    gravite           nvarchar(50)    NULL,
    decision_metier   nvarchar(50)    NULL,
    id_chargement     int             NULL,
    fichier_source    nvarchar(260)   NULL,
    feuille_source    nvarchar(128)   NULL,
    num_ligne_source  int             NULL,
    CONSTRAINT pk_fait_anomalie PRIMARY KEY (id_fait_anomalie),
    CONSTRAINT uq_fait_anomalie_id UNIQUE (id_anomalie),
    CONSTRAINT fk_fait_anomalie_controle
        FOREIGN KEY (id_controle) REFERENCES dw.dim_controle (id_controle)
);
GO

/* Vide les tables du tableau qualité, avant les dimensions qu'elles référencent. */
CREATE PROCEDURE dw.vider_tableau_qualite
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM dw.fait_anomalie;
END;
GO

CREATE PROCEDURE dw.construire_dim_controle
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_controle;
    INSERT INTO dw.dim_controle (id_controle, controle) VALUES
        (-1, N'(non renseigné)'),
        (-2, N'(introuvable)');

    WITH bilans AS (
        SELECT etape, controle, table_source, champ, regle, gravite, indicateurs,
               ROW_NUMBER() OVER (
                   PARTITION BY controle COLLATE Latin1_General_100_BIN2
                   ORDER BY CASE etat WHEN N'nettoyé' THEN 0 ELSE 1 END
               ) AS rang
        FROM qualite.bilan_controle
        WHERE id_execution = @id_execution
    )
    INSERT INTO dw.dim_controle (id_controle, controle, etape, table_source, champ,
                                 regle, gravite, indicateurs)
    SELECT ROW_NUMBER() OVER (ORDER BY controle COLLATE Latin1_General_100_BIN2),
           controle, etape, table_source, champ, regle, gravite, indicateurs
    FROM bilans
    WHERE rang = 1;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_controle', @lignes, @debut;
END;
GO

CREATE PROCEDURE dw.construire_fait_anomalie
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.fait_anomalie;
    INSERT INTO dw.fait_anomalie (
        id_fait_anomalie, id_anomalie, id_controle, etape, table_source, periode_export,
        cle, champ, valeur, constat, issue, statut_regle, detail, proposition, gravite,
        decision_metier, id_chargement, fichier_source, feuille_source, num_ligne_source
    )
    SELECT ROW_NUMBER() OVER (ORDER BY a.id_anomalie COLLATE Latin1_General_100_BIN2),
           a.id_anomalie,
           CASE WHEN a.controle = N'' THEN -1 ELSE COALESCE(c.id_controle, -2) END,
           a.etape,
           a.table_source,
           a.periode_export,
           a.cle,
           a.champ,
           a.valeur,
           a.constat,
           a.issue,
           a.statut_regle,
           a.detail,
           a.proposition,
           a.gravite,
           a.decision_metier,
           a.id_chargement,
           a.fichier_source,
           a.feuille_source,
           a.num_ligne_source
    FROM qualite.anomalie AS a
    LEFT JOIN dw.dim_controle AS c
        ON c.controle = a.controle COLLATE Latin1_General_100_BIN2
       AND c.id_controle >= 1
    WHERE a.id_execution = @id_execution
      AND a.etat = N'nettoyé';

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'fait_anomalie', @lignes, @debut;
END;
GO
