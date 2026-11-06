/*
  Pack services_intervention, script 001 : cadre de la reconstruction de dw.

  Le schéma dw est reconstruit entièrement à chaque exécution, à partir des
  tables de propre, par la procédure dw.reconstruire. Elle est appelée par le
  traitement Python dans la transaction de l'écriture, juste avant que
  l'exécution passe à « réussie » : propre et dw ne peuvent donc pas être
  désaccordés, et un échec annule toute l'exécution. Pour la mise au point,
  python -m frigeo.base --reconstruire la relance seule, dans sa propre
  transaction, sur la dernière exécution réussie.

  Les tables de propre étant supprimées et recréées à chaque exécution, aucune
  vue ne porte sur elles : seules des procédures les lisent (résolution
  différée des noms), et les vues ne portent que sur dw.

  La procédure dw.reconstruire est créée par le dernier script du pack
  (900_reconstruire.sql), après les procédures qu'elle appelle.

  Contrat d'entrée : les colonnes de propre que le pack lit, avec leur
  famille (texte, date, heure, entier, décimal). Il est vérifié avant toute
  construction, tous les écarts étant listés en un seul message, sans valeur
  du client. Chaque dimension et chaque fait y ajoute les colonnes qu'il lit.
*/

/* Une colonne de propre lue par le pack. table_propre et colonne sont les
   noms en base (ceux de qualite.correspondance_colonne.table_base et
   colonne_base). */
CREATE TABLE dw.contrat_entree (
    table_propre  nvarchar(128)  NOT NULL,
    colonne       nvarchar(128)  NOT NULL,
    famille       nvarchar(20)   NOT NULL,
    CONSTRAINT pk_contrat_entree PRIMARY KEY (table_propre, colonne),
    CONSTRAINT ck_contrat_entree_famille
        CHECK (famille IN (N'texte', N'date', N'heure', N'entier', N'décimal'))
);
GO

/* Une étape de la dernière reconstruction de dw (vidée à chaque
   reconstruction, comme dw lui-même) : lignes écrites, ou colonnes vérifiées
   pour le contrat d'entrée. Pas de clé étrangère vers qualite.execution, dont
   les lignes d'une période rejouée sont supprimées. */
CREATE TABLE dw.journal_reconstruction (
    id_execution  int            NOT NULL,
    ordre         int            NOT NULL,
    etape         nvarchar(128)  NOT NULL,
    lignes        int            NOT NULL,
    debut         datetime2(0)   NOT NULL,
    fin           datetime2(0)   NOT NULL,
    CONSTRAINT pk_journal_reconstruction PRIMARY KEY (ordre)
);
GO

/* Vérifie le contrat d'entrée contre les colonnes réelles de propre : table
   absente, colonne absente, famille différente. Lève une erreur qui liste
   tous les écarts (tronquée au-delà de la longueur admise par THROW). */
CREATE PROCEDURE dw.verifier_contrat
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @ecarts TABLE (ordre int IDENTITY(1, 1), texte nvarchar(400) NOT NULL);

    WITH reelles AS (
        SELECT t.name AS table_propre,
               c.name AS colonne,
               CASE
                   WHEN ty.name IN (N'nvarchar', N'nchar', N'varchar', N'char') THEN N'texte'
                   WHEN ty.name = N'date' THEN N'date'
                   WHEN ty.name = N'time' THEN N'heure'
                   WHEN ty.name IN (N'bigint', N'int', N'smallint', N'tinyint') THEN N'entier'
                   WHEN ty.name IN (N'decimal', N'numeric') THEN N'décimal'
                   ELSE ty.name
               END AS famille
        FROM sys.tables AS t
        JOIN sys.schemas AS s ON s.schema_id = t.schema_id
        JOIN sys.columns AS c ON c.object_id = t.object_id
        JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
        WHERE s.name = N'propre'
    ),
    constats AS (
        SELECT DISTINCT k.table_propre, NULL AS colonne,
               CONCAT(N'propre.', k.table_propre, N' : table absente') AS texte
        FROM dw.contrat_entree AS k
        WHERE NOT EXISTS (SELECT 1 FROM reelles AS r WHERE r.table_propre = k.table_propre)
        UNION ALL
        SELECT k.table_propre, k.colonne,
               CASE
                   WHEN r.colonne IS NULL
                       THEN CONCAT(N'propre.', k.table_propre, N'.', k.colonne,
                                   N' : colonne absente')
                   ELSE CONCAT(N'propre.', k.table_propre, N'.', k.colonne, N' : famille ',
                               r.famille, N' au lieu de ', k.famille)
               END
        FROM dw.contrat_entree AS k
        LEFT JOIN reelles AS r
            ON r.table_propre = k.table_propre AND r.colonne = k.colonne
        WHERE EXISTS (SELECT 1 FROM reelles AS t WHERE t.table_propre = k.table_propre)
          AND (r.colonne IS NULL OR r.famille <> k.famille)
    )
    INSERT INTO @ecarts (texte)
    SELECT texte FROM constats ORDER BY table_propre, colonne;

    DECLARE @nombre int = (SELECT COUNT(*) FROM @ecarts);
    IF @nombre = 0
        RETURN;

    DECLARE @detail nvarchar(max) = (
        SELECT STRING_AGG(CAST(texte AS nvarchar(max)), N'; ') WITHIN GROUP (ORDER BY ordre)
        FROM @ecarts
    );
    DECLARE @message nvarchar(2048) = CONCAT(
        N'Contrat d''entrée du pack non respecté (', @nombre, N' écart(s)) : ',
        CASE WHEN LEN(@detail) > 1900 THEN CONCAT(LEFT(@detail, 1900), N'...') ELSE @detail END
    );
    THROW 50010, @message, 1;
END;
GO

/* Inscrit une étape de la reconstruction dans dw.journal_reconstruction, à la
   suite des précédentes. */
CREATE PROCEDURE dw.inscrire_etape
    @id_execution int,
    @etape nvarchar(128),
    @lignes int,
    @debut datetime2(0)
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO dw.journal_reconstruction (id_execution, ordre, etape, lignes, debut, fin)
    SELECT @id_execution, COALESCE(MAX(ordre), 0) + 1, @etape, @lignes, @debut, SYSUTCDATETIME()
    FROM dw.journal_reconstruction;
END;
GO
