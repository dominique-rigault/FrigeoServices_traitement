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
  famille (texte, date, heure, entier, décimal), et les rattachements de
  qualite.regle_rattachement qu'il utilise pour relier un fait à ses
  dimensions. Il est vérifié avant toute construction, tous les écarts étant
  listés en un seul message, sans valeur du client. Chaque dimension et
  chaque fait y ajoute les colonnes et les rattachements qu'il lit : une
  règle de rapprochement retirée de config/gestion.yaml fait alors échouer
  l'exécution, au lieu d'envoyer toutes les lignes vers le membre
  « introuvable ».

  Contrat des mesures et des dates : pour la vérification de l'écriture
  (frigeo.ecriture_base.controles_mesures), le pack déclare de quelles
  colonnes de propre chaque mesure d'un fait est tirée (dw.contrat_mesure) et
  quelles dates d'un fait sont lues sur sa ligne de propre (dw.contrat_date).
  La vérification compare les sommes des mesures à celles que Python a
  écrites dans propre, et contrôle ligne à ligne le jour du calendrier de
  chaque date déclarée. Toute colonne numérique d'une table de faits (hors
  int, réservé aux clés et au lignage) doit avoir sa mesure déclarée.

  Codes en doublon : un code que le métier a rattaché à un code principal
  (qualite.correspondance_cle, décisions « rattacher » retenues par le
  nettoyage) n'a pas de membre dans sa dimension, et les faits qui le citent
  sont comptés sur le membre du code principal. Le pack déclare dans
  dw.regroupement_codes les tables dont il regroupe les codes; une
  correspondance sur une autre table fait échouer la vérification du contrat,
  au lieu d'être ignorée.

  Ordre de reconstruction : les tables de faits ont des clés étrangères vers
  les dimensions (aucune ligne orpheline). dw.vider_faits les vide d'abord,
  puis chaque dimension est vidée et remplie par sa procédure, puis chaque
  fait.
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

/* Un rattachement lu par le pack : table, clé et référentiel, avec les noms
   du dictionnaire et les colonnes d'une clé reliées par « , », comme dans
   qualite.regle_rattachement. table_fait, colonne_fait et forme disent, pour
   la vérification de l'écriture (frigeo.ecriture_base.controles_faits), quelle
   colonne d'un fait doit refléter ce rattachement ligne à ligne : forme membre
   (autant de -1 et de -2 que de clés vides et introuvables), lien (autant de
   « non renseignée » et d'« introuvable »), numero (autant de valeurs
   renseignées que de lignes rattachées). Un rattachement porté par un
   en-tête, qui se compte par document et non par ligne du fait, n'en a pas. */
CREATE TABLE dw.contrat_rattachement (
    id_contrat       int IDENTITY(1, 1) NOT NULL,
    table_source     nvarchar(128)   NOT NULL,
    cle              nvarchar(1000)  NOT NULL,
    table_reference  nvarchar(128)   NOT NULL,
    table_fait       nvarchar(128)   NULL,
    colonne_fait     nvarchar(128)   NULL,
    forme            nvarchar(10)    NULL,
    CONSTRAINT pk_contrat_rattachement PRIMARY KEY (id_contrat),
    CONSTRAINT ck_contrat_rattachement_forme
        CHECK ((table_fait IS NULL AND colonne_fait IS NULL AND forme IS NULL)
               OR (table_fait IS NOT NULL AND colonne_fait IS NOT NULL
                   AND forme IN (N'membre', N'lien', N'numero')))
);
GO

/* Un fait de dw et la table du dictionnaire dont il a une ligne par ligne de
   propre : la vérification de l'écriture compare leurs nombres de lignes. */
CREATE TABLE dw.source_fait (
    table_fait    nvarchar(128)  NOT NULL,
    table_source  nvarchar(128)  NOT NULL,
    CONSTRAINT pk_source_fait PRIMARY KEY (table_fait)
);
GO

/* Une mesure d'un fait de dw et la colonne de propre dont elle est tirée,
   avec son signe (noms en base, comme dans dw.contrat_entree). Une mesure
   calculée a une ligne par colonne source : le solde d'une écriture, débit
   moins crédit, a la ligne du débit (signe 1) et celle du crédit (signe -1).
   La vérification de l'écriture compare la somme de la mesure à la somme,
   affectée du signe, de ses colonnes sources dans propre (un vide ne comptant
   pas), et, pour une mesure à une seule source, leurs nombres de valeurs
   renseignées. */
CREATE TABLE dw.contrat_mesure (
    table_fait      nvarchar(128)  NOT NULL,
    colonne_fait    nvarchar(128)  NOT NULL,
    table_propre    nvarchar(128)  NOT NULL,
    colonne_propre  nvarchar(128)  NOT NULL,
    signe           smallint       NOT NULL,
    CONSTRAINT pk_contrat_mesure
        PRIMARY KEY (table_fait, colonne_fait, table_propre, colonne_propre),
    CONSTRAINT ck_contrat_mesure_signe CHECK (signe IN (1, -1))
);
GO

/* Une date d'un fait de dw (sa clé vers dw.dim_date) lue sur la ligne de
   propre dont le fait a une ligne, de même lignage (noms en base). La
   vérification de l'écriture contrôle ligne à ligne que la clé désigne le
   jour de propre, -1 pour une date vide, une date hors calendrier étant un
   écart. Une date reprise d'un en-tête (date de facture d'une ligne de
   facture) n'y figure pas : ses -1 et -2 mêlent un en-tête absent et une date
   vide. */
CREATE TABLE dw.contrat_date (
    table_fait      nvarchar(128)  NOT NULL,
    colonne_fait    nvarchar(128)  NOT NULL,
    table_propre    nvarchar(128)  NOT NULL,
    colonne_propre  nvarchar(128)  NOT NULL,
    CONSTRAINT pk_contrat_date PRIMARY KEY (table_fait, colonne_fait)
);
GO

/* Une table du dictionnaire dont le pack regroupe les codes en doublon sous
   leur code principal, avec la dimension et la colonne du code de celle-ci
   (pour la vérification de l'écriture, frigeo.ecriture_base). */
CREATE TABLE dw.regroupement_codes (
    table_source     nvarchar(128)  NOT NULL,
    table_dimension  nvarchar(128)  NOT NULL,
    colonne_code     nvarchar(128)  NOT NULL,
    CONSTRAINT pk_regroupement_codes PRIMARY KEY (table_source)
);
GO

/* Codes en doublon d'une table pour une exécution, avec leur code principal
   (qualite.correspondance_cle), en classement binaire. Un code principal
   n'est jamais lui-même un code en doublon : une seule jointure suffit. */
CREATE FUNCTION dw.correspondances (
    @id_execution int,
    @table_source nvarchar(128)
)
RETURNS TABLE
AS
RETURN (
    SELECT code_doublon, code_principal
    FROM qualite.correspondance_cle
    WHERE id_execution = @id_execution
      AND table_source = @table_source
);
GO

/* Numéro (id_regle) du rattachement d'une exécution pour une table, une clé
   et un référentiel; NULL s'il n'existe pas. Deux rattachements de même
   table, clé et référentiel ne diffèrent que par la comparaison : le premier
   dans l'ordre de config/gestion.yaml est rendu. */
CREATE FUNCTION dw.regle_rattachement (
    @id_execution int,
    @table_source nvarchar(128),
    @cle nvarchar(1000),
    @table_reference nvarchar(128)
)
RETURNS int
AS
BEGIN
    RETURN (
        SELECT MIN(id_regle)
        FROM qualite.regle_rattachement
        WHERE id_execution = @id_execution
          AND table_source = @table_source
          AND cle = @cle
          AND table_reference = @table_reference
    );
END;
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

/* Vérifie le contrat d'entrée contre les colonnes réelles de propre (table
   absente, colonne absente, famille différente), contre les rattachements
   de l'exécution (rattachement absent) et contre ses codes en doublon
   (correspondance sur une table que le pack ne regroupe pas). Lève une erreur qui liste tous les
   écarts (tronquée au-delà de la longueur admise par THROW). */
CREATE PROCEDURE dw.verifier_contrat
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @ecarts TABLE (ordre int IDENTITY(1, 1), texte nvarchar(2000) NOT NULL);

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
        SELECT DISTINCT 1 AS rang, k.table_propre, NULL AS colonne,
               CONCAT(N'propre.', k.table_propre, N' : table absente') AS texte
        FROM dw.contrat_entree AS k
        WHERE NOT EXISTS (SELECT 1 FROM reelles AS r WHERE r.table_propre = k.table_propre)
        UNION ALL
        SELECT 1, k.table_propre, k.colonne,
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
        UNION ALL
        SELECT DISTINCT 2, k.table_source, k.cle,
               CONCAT(N'rattachement ', k.table_source, N'.', k.cle, N' vers ',
                      k.table_reference, N' : absent de qualite.regle_rattachement')
        FROM dw.contrat_rattachement AS k
        WHERE dw.regle_rattachement(@id_execution, k.table_source, k.cle,
                                    k.table_reference) IS NULL
        UNION ALL
        SELECT DISTINCT 3, c.table_source, NULL,
               CONCAT(N'codes en doublon de ', c.table_source,
                      N' : non regroupés par le pack (dw.regroupement_codes)')
        FROM qualite.correspondance_cle AS c
        WHERE c.id_execution = @id_execution
          AND NOT EXISTS (SELECT 1 FROM dw.regroupement_codes AS r
                          WHERE r.table_source = c.table_source)
    )
    INSERT INTO @ecarts (texte)
    SELECT texte FROM constats ORDER BY rang, table_propre, colonne;

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

/* Vide les tables de faits de dw (nom commençant par fait_, préfixe réservé
   aux faits : une table du cadre ne doit pas le porter), avant la
   reconstruction des dimensions qu'elles référencent. Une table de faits
   référencée par une autre (une consommation vers son intervention) est
   vidée après celle-ci. Générique : un fait ajouté par le pack est vidé sans
   modifier cette procédure. */
CREATE PROCEDURE dw.vider_faits
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @restantes TABLE (object_id int PRIMARY KEY, nom nvarchar(300) NOT NULL);
    INSERT INTO @restantes (object_id, nom)
    SELECT t.object_id, CONCAT(QUOTENAME(s.name), N'.', QUOTENAME(t.name))
    FROM sys.tables AS t
    JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    WHERE s.name = N'dw' AND t.name LIKE N'fait[_]%';

    DECLARE @objet int, @nom nvarchar(300), @instruction nvarchar(400);
    WHILE EXISTS (SELECT 1 FROM @restantes)
    BEGIN
        SET @objet = NULL;
        SELECT TOP (1) @objet = r.object_id, @nom = r.nom
        FROM @restantes AS r
        WHERE NOT EXISTS (
            SELECT 1
            FROM sys.foreign_keys AS f
            JOIN @restantes AS a ON a.object_id = f.parent_object_id
            WHERE f.referenced_object_id = r.object_id
              AND f.parent_object_id <> r.object_id
        )
        ORDER BY r.nom;
        IF @objet IS NULL
            THROW 50011, N'dw.vider_faits : références circulaires entre tables de faits.', 1;
        SET @instruction = CONCAT(N'DELETE FROM ', @nom, N';');
        EXEC sys.sp_executesql @instruction;
        DELETE FROM @restantes WHERE object_id = @objet;
    END;
END;
GO
