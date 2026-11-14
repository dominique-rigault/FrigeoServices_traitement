/*
  Pack services_intervention, script 002 : dimensions du modèle en étoile.

  Chaque dimension est vidée puis remplie par sa procédure
  dw.construire_dim_<nom>, appelée par dw.reconstruire et inscrite dans
  dw.journal_reconstruction (nombre de membres, hors membres spéciaux).

  Clé technique : un entier numéroté dans l'ordre binaire du code, de sorte que
  les mêmes données donnent les mêmes clés d'une reconstruction à l'autre.
  Deux membres spéciaux dans chaque dimension : -1 « non renseigné » (clé vide
  dans la ligne de fait) et -2 « introuvable » (clé absente de la dimension).

  Code métier : en classement binaire (Latin1_General_100_BIN2), comme la
  comparaison « telle quelle » du traitement Python : le classement de la base
  ignorant la casse, « C001 » et « c001 » feraient sinon un seul membre. Le
  regroupement par code se fait dans ce classement.

  Dimension issue d'un référentiel : une ligne par code; si un code occupe
  plusieurs lignes (clé en double gardée par le métier, signalée dans
  qualite), la première dans l'ordre du lignage est retenue et lignes_source
  donne leur nombre. Le lignage de la ligne retenue est conservé. Une
  dimension déduite d'une table de faits (article, compte) n'a pas de lignage.

  Codes en doublon (clients, fournisseurs, déclarés dans dw.regroupement_codes) :
  un code que le métier a rattaché à un code principal n'a pas de membre;
  codes_en_doublon donne, pour le membre du code principal, le nombre de codes
  qui lui sont rattachés. Les faits qui citent un code en doublon sont comptés
  sur le membre du code principal (script 003).

  Données personnelles : dw garde ce qui nomme un membre (raison sociale, nom
  et prénom); adresse, téléphone, courriel, SIRET et motif de sortie n'y
  entrent pas. Ce qui est exposé à Power BI se décide dans les vues pbi.
*/

/* Colonnes de propre lues par les dimensions. */
INSERT INTO dw.contrat_entree (table_propre, colonne, famille) VALUES
    (N'catalogue_pieces', N'ref_piece', N'texte'),
    (N'catalogue_pieces', N'libelle', N'texte'),
    (N'catalogue_pieces', N'famille', N'texte'),
    (N'catalogue_pieces', N'unite', N'texte'),
    (N'catalogue_pieces', N'fournisseur_principal', N'texte'),
    (N'clients', N'code_client', N'texte'),
    (N'clients', N'raison_sociale', N'texte'),
    (N'clients', N'type_commerce', N'texte'),
    (N'clients', N'cp', N'texte'),
    (N'clients', N'ville', N'texte'),
    (N'clients', N'contrat_maintenance', N'texte'),
    (N'clients', N'date_creation', N'date'),
    (N'clients', N'date_fin_relation', N'date'),
    (N'clients', N'statut', N'texte'),
    (N'factures_lignes', N'code_article', N'texte'),
    (N'fec', N'compte_num', N'texte'),
    (N'fec', N'compte_lib', N'texte'),
    (N'fournisseurs', N'code_fournisseur', N'texte'),
    (N'fournisseurs', N'raison_sociale', N'texte'),
    (N'fournisseurs', N'categorie', N'texte'),
    (N'fournisseurs', N'cp', N'texte'),
    (N'fournisseurs', N'ville', N'texte'),
    (N'fournisseurs', N'delai_paiement', N'texte'),
    (N'fournisseurs', N'statut', N'texte'),
    (N'intervenants', N'matricule', N'texte'),
    (N'intervenants', N'nom', N'texte'),
    (N'intervenants', N'prenom', N'texte'),
    (N'intervenants', N'poste', N'texte'),
    (N'intervenants', N'type_contrat', N'texte'),
    (N'intervenants', N'secteur', N'texte'),
    (N'intervenants', N'date_entree', N'date'),
    (N'intervenants', N'date_sortie', N'date');
GO

/*
  Calendrier, du 1er janvier de la première année des fichiers chargés
  (qualite.journal_chargement.periode_export) au 31 décembre de l'année qui
  suit periode_fin, pour les échéances. Clé AAAAMMJJ. Jour de la semaine
  calculé à partir du lundi 1er janvier 1900, sans dépendre des réglages de
  langue du serveur (1 lundi, 7 dimanche). Jours fériés de qualite.jour_ferie :
  pour une année dont les jours fériés ne sont pas déclarés, ferie et ouvre
  restent vides plutôt que faux. periode_chargee vaut 1 jusqu'au dernier jour
  du mois de periode_fin, 0 au-delà : les tableaux de bord filtrent dessus, pour
  que les mois sans données et la comparaison à l'année précédente s'arrêtent à
  la période chargée.
*/
CREATE TABLE dw.dim_date (
    id_date          int            NOT NULL,
    date_jour        date           NULL,
    libelle          nvarchar(20)   NOT NULL,
    annee            smallint       NULL,
    trimestre        tinyint        NULL,
    mois             tinyint        NULL,
    libelle_mois     nvarchar(10)   NULL,
    annee_mois       nvarchar(7)    NULL,
    jour_semaine     tinyint        NULL,
    libelle_jour     nvarchar(10)   NULL,
    feries_declares  bit            NULL,
    ferie            bit            NULL,
    ouvre            bit            NULL,
    periode_chargee  bit            NULL,
    CONSTRAINT pk_dim_date PRIMARY KEY (id_date),
    INDEX ux_dim_date_jour UNIQUE (date_jour) WHERE date_jour IS NOT NULL
);
GO

CREATE PROCEDURE dw.construire_dim_date
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DECLARE @annee_fin int = (
        SELECT CAST(LEFT(periode_fin, 4) AS int) + 1
        FROM qualite.execution WHERE id_execution = @id_execution
    );
    DECLARE @annee_debut int = COALESCE((
        SELECT MIN(TRY_CAST(LEFT(periode_export, 4) AS int))
        FROM qualite.journal_chargement
        WHERE id_execution = @id_execution AND periode_export IS NOT NULL
    ), @annee_fin - 1);
    DECLARE @premier date = DATEFROMPARTS(@annee_debut, 1, 1);
    DECLARE @dernier date = DATEFROMPARTS(@annee_fin, 12, 31);
    DECLARE @fin_chargee date = (
        SELECT EOMONTH(DATEFROMPARTS(CAST(LEFT(periode_fin, 4) AS int),
                                     CAST(RIGHT(periode_fin, 2) AS int), 1))
        FROM qualite.execution WHERE id_execution = @id_execution
    );

    DELETE FROM dw.dim_date;
    INSERT INTO dw.dim_date (id_date, libelle) VALUES
        (-1, N'(non renseignée)'),
        (-2, N'(hors calendrier)');

    WITH nombres AS (
        SELECT TOP (DATEDIFF(day, @premier, @dernier) + 1)
               ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS k
        FROM sys.all_columns AS a CROSS JOIN sys.all_columns AS b
    ),
    jours AS (
        SELECT d.jour, YEAR(d.jour) AS annee, MONTH(d.jour) AS mois,
               DATEDIFF(day, DATEFROMPARTS(1900, 1, 1), d.jour) % 7 + 1 AS jour_semaine
        FROM nombres
        CROSS APPLY (SELECT DATEADD(day, CAST(nombres.k AS int), @premier) AS jour) AS d
    ),
    feries AS (
        SELECT j.*,
               CASE WHEN EXISTS (SELECT 1 FROM qualite.jour_ferie AS f
                                 WHERE f.id_execution = @id_execution AND f.annee = j.annee)
                    THEN 1 ELSE 0 END AS declares,
               CASE WHEN EXISTS (SELECT 1 FROM qualite.jour_ferie AS f
                                 WHERE f.id_execution = @id_execution AND f.jour = j.jour)
                    THEN 1 ELSE 0 END AS est_ferie
        FROM jours AS j
    )
    INSERT INTO dw.dim_date (id_date, date_jour, libelle, annee, trimestre, mois, libelle_mois,
                             annee_mois, jour_semaine, libelle_jour, feries_declares, ferie, ouvre,
                             periode_chargee)
    SELECT annee * 10000 + mois * 100 + DAY(jour),
           jour,
           CONVERT(nvarchar(10), jour, 103),
           annee,
           (mois + 2) / 3,
           mois,
           CHOOSE(mois, N'janvier', N'février', N'mars', N'avril', N'mai', N'juin', N'juillet',
                  N'août', N'septembre', N'octobre', N'novembre', N'décembre'),
           CONCAT(annee, N'-', RIGHT(CONCAT(N'0', mois), 2)),
           jour_semaine,
           CHOOSE(jour_semaine, N'lundi', N'mardi', N'mercredi', N'jeudi', N'vendredi',
                  N'samedi', N'dimanche'),
           declares,
           CASE WHEN declares = 1 THEN est_ferie END,
           CASE WHEN declares = 1 THEN
               CASE WHEN jour_semaine <= 5 AND est_ferie = 0 THEN 1 ELSE 0 END END,
           CASE WHEN jour <= @fin_chargee THEN 1 ELSE 0 END
    FROM feries;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_date', @lignes, @debut;
END;
GO

/*
  Catégories d'intervention : valeurs admises de la liste fermée de
  interventions.categorie, lues dans qualite.valeur_liste pour l'exécution
  (valides, documentées ou proposées non revues). La clé est le rang de la
  valeur dans le dictionnaire. Une catégorie invalide restée dans propre
  pointera vers -2. Sans liste fermée, la construction s'arrête.
*/
CREATE TABLE dw.dim_categorie (
    id_categorie   int            NOT NULL,
    categorie      nvarchar(450)  COLLATE Latin1_General_100_BIN2 NOT NULL,
    statut_valeur  nvarchar(20)   NULL,
    CONSTRAINT pk_dim_categorie PRIMARY KEY (id_categorie),
    CONSTRAINT uq_dim_categorie_code UNIQUE (categorie)
);
GO

CREATE PROCEDURE dw.construire_dim_categorie
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_categorie;
    INSERT INTO dw.dim_categorie (id_categorie, categorie, statut_valeur) VALUES
        (-1, N'(non renseignée)', NULL),
        (-2, N'(hors liste)', NULL);

    INSERT INTO dw.dim_categorie (id_categorie, categorie, statut_valeur)
    SELECT rang, valeur, statut
    FROM qualite.valeur_liste
    WHERE id_execution = @id_execution
      AND table_source = N'interventions'
      AND colonne_source = N'categorie';

    DECLARE @lignes int = @@ROWCOUNT;
    IF @lignes = 0
        THROW 50020, N'dim_categorie : aucune valeur admise pour interventions.categorie dans qualite.valeur_liste (la colonne n''a plus de liste fermée au dictionnaire ?).', 1;
    EXEC dw.inscrire_etape @id_execution, N'dim_categorie', @lignes, @debut;
END;
GO

/* Libellé de référence de chaque article facturé : valeur propre au client,
   tirée de sa grille tarifaire, aucun fichier ne décrivant les articles (le
   libellé d'une ligne de facture varie : désignation de la pièce, date de la
   visite). Vérifiée avant toute construction par dw.verifier_parametres
   (script 004) contre les valeurs admises de factures_lignes.code_article :
   un code admis sans libellé, ou un libellé pour un code inconnu, fait échouer
   l'exécution. Pour un autre client, c'est sa grille qui remplace celle-ci. */
CREATE TABLE dw.libelle_article (
    code_article  nvarchar(450)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    libelle       nvarchar(4000)  NOT NULL,
    CONSTRAINT pk_libelle_article PRIMARY KEY (code_article)
);
GO

INSERT INTO dw.libelle_article (code_article, libelle) VALUES
    (N'MO-STD', N'Main d''oeuvre heure normale'),
    (N'MO-URG', N'Main d''oeuvre urgence (soir, samedi, férié)'),
    (N'DEPL', N'Forfait déplacement'),
    (N'CTRL-F', N'Forfait contrôle d''étanchéité'),
    (N'PREV-F', N'Visite préventive sous contrat (déplacement inclus)'),
    (N'INST-F', N'Forfait installation et mise en service'),
    (N'PIECE', N'Pièces détachées (libellé variable)'),
    (N'FLUIDE', N'Fluide frigorigène');
GO

/* Articles facturés (main d'œuvre, déplacement, forfaits) : codes distincts de factures_lignes.code_article, avec le libellé de référence de dw.libelle_article (NULL pour un code hors des valeurs admises, déjà signalé dans qualite). Le compte de produit d'un article n'apparaît nulle part ligne à ligne. */
CREATE TABLE dw.dim_article (
    id_article          int             NOT NULL,
    code_article        nvarchar(450)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    libelle             nvarchar(4000)  NULL,
    CONSTRAINT pk_dim_article PRIMARY KEY (id_article),
    CONSTRAINT uq_dim_article_code UNIQUE (code_article)
);
GO

CREATE PROCEDURE dw.construire_dim_article
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_article;
    INSERT INTO dw.dim_article (id_article, code_article, libelle)
    VALUES (-1, N'(non renseigné)', NULL),
           (-2, N'(introuvable)', NULL);

    WITH codes AS (
        SELECT DISTINCT p.code_article COLLATE Latin1_General_100_BIN2 AS code
        FROM propre.factures_lignes AS p
        WHERE p.code_article IS NOT NULL
    )
    INSERT INTO dw.dim_article (id_article, code_article, libelle)
    SELECT ROW_NUMBER() OVER (ORDER BY c.code), c.code, l.libelle
    FROM codes AS c
    LEFT JOIN dw.libelle_article AS l ON l.code_article = c.code;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_article', @lignes, @debut;
END;
GO

/* Pièces du catalogue. Le stock et le CUMP initiaux de la ligne retenue sont lus par le calcul du CUMP (script 004); le prix de vente n'est pas repris.
   Un fournisseur principal dont le code est en doublon est remplacé par son code principal. */
CREATE TABLE dw.dim_piece (
    id_piece            int             NOT NULL,
    ref_piece           nvarchar(450)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    libelle             nvarchar(4000)  NULL,
    famille             nvarchar(4000)  NULL,
    unite               nvarchar(4000)  NULL,
    code_fournisseur_principal nvarchar(4000)  NULL,
    lignes_source       int             NOT NULL,
    id_chargement       int             NULL,
    fichier_source      nvarchar(260)   NULL,
    feuille_source      nvarchar(128)   NULL,
    num_ligne_source    int             NULL,
    CONSTRAINT pk_dim_piece PRIMARY KEY (id_piece),
    CONSTRAINT uq_dim_piece_code UNIQUE (ref_piece)
);
GO

CREATE PROCEDURE dw.construire_dim_piece
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_piece;
    INSERT INTO dw.dim_piece (id_piece, ref_piece, libelle, famille, unite, code_fournisseur_principal, lignes_source, id_chargement, fichier_source, feuille_source, num_ligne_source)
    VALUES (-1, N'(non renseigné)', NULL, NULL, NULL, NULL, 0, NULL, NULL, NULL, NULL),
           (-2, N'(introuvable)', NULL, NULL, NULL, NULL, 0, NULL, NULL, NULL, NULL);

    WITH l AS (
        SELECT p.*,
               ROW_NUMBER() OVER (
                   PARTITION BY p.ref_piece COLLATE Latin1_General_100_BIN2
                   ORDER BY p.fichier_source, p.feuille_source, p.num_ligne_source) AS rang,
               COUNT(*) OVER (PARTITION BY p.ref_piece COLLATE Latin1_General_100_BIN2) AS lignes
        FROM propre.catalogue_pieces AS p
        WHERE p.ref_piece IS NOT NULL
    )
    INSERT INTO dw.dim_piece (id_piece, ref_piece, libelle, famille, unite, code_fournisseur_principal, lignes_source, id_chargement, fichier_source, feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY l.ref_piece COLLATE Latin1_General_100_BIN2),
           l.ref_piece,
           l.libelle,
           l.famille,
           l.unite,
           COALESCE(c.code_principal COLLATE DATABASE_DEFAULT, l.fournisseur_principal),
           l.lignes,
           l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM l
    LEFT JOIN dw.correspondances(@id_execution, N'fournisseurs') AS c
        ON c.code_doublon = l.fournisseur_principal COLLATE Latin1_General_100_BIN2
    WHERE l.rang = 1;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_piece', @lignes, @debut;
END;
GO

/* Comptes du FEC : numéros distincts de fec.compte_num, avec la classe (premier chiffre). Un compte d'achat absent du FEC pointera vers -2. */
CREATE TABLE dw.dim_compte (
    id_compte           int             NOT NULL,
    compte_num          nvarchar(450)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    compte_lib          nvarchar(4000)  NULL,
    classe              nchar(1)        NULL,
    CONSTRAINT pk_dim_compte PRIMARY KEY (id_compte),
    CONSTRAINT uq_dim_compte_code UNIQUE (compte_num)
);
GO

CREATE PROCEDURE dw.construire_dim_compte
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_compte;
    INSERT INTO dw.dim_compte (id_compte, compte_num, compte_lib, classe)
    VALUES (-1, N'(non renseigné)', NULL, NULL),
           (-2, N'(introuvable)', NULL, NULL);

    /* Libellé le plus fréquent de chaque code (un libellé vide ne compte pas, à
       égalité le premier dans l'ordre binaire). */
    WITH frequences AS (
        SELECT p.compte_num COLLATE Latin1_General_100_BIN2 AS code,
               p.compte_lib COLLATE Latin1_General_100_BIN2 AS libelle,
               COUNT(*) AS lignes
        FROM propre.fec AS p
        WHERE p.compte_num IS NOT NULL
        GROUP BY p.compte_num COLLATE Latin1_General_100_BIN2, p.compte_lib COLLATE Latin1_General_100_BIN2
    ),
    rangs AS (
        SELECT code, libelle,
               ROW_NUMBER() OVER (
                   PARTITION BY code
                   ORDER BY CASE WHEN libelle IS NULL THEN 1 ELSE 0 END,
                            lignes DESC, libelle) AS rang
        FROM frequences
    )
    INSERT INTO dw.dim_compte (id_compte, compte_num, compte_lib, classe)
    SELECT ROW_NUMBER() OVER (ORDER BY code), code, libelle, LEFT(code, 1)
    FROM rangs
    WHERE rang = 1;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_compte', @lignes, @debut;
END;
GO

/*
  Intervenants. Un matricule peut occuper plusieurs lignes, une par période
  d'emploi (règle R21) : la dimension retient la période la plus récente (date
  d'entrée la plus grande, puis l'ordre du lignage), dont elle garde les
  attributs, les dates et le lignage, et ajoute la date de première entrée.
  lignes_source donne le nombre de périodes.
*/
CREATE TABLE dw.dim_intervenant (
    id_intervenant        int             NOT NULL,
    matricule             nvarchar(450)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    nom                   nvarchar(4000)  NULL,
    prenom                nvarchar(4000)  NULL,
    poste                 nvarchar(4000)  NULL,
    type_contrat          nvarchar(4000)  NULL,
    secteur               nvarchar(4000)  NULL,
    date_premiere_entree  date            NULL,
    date_entree           date            NULL,
    date_sortie           date            NULL,
    lignes_source       int             NOT NULL,
    id_chargement       int             NULL,
    fichier_source      nvarchar(260)   NULL,
    feuille_source      nvarchar(128)   NULL,
    num_ligne_source    int             NULL,
    CONSTRAINT pk_dim_intervenant PRIMARY KEY (id_intervenant),
    CONSTRAINT uq_dim_intervenant_code UNIQUE (matricule)
);
GO

CREATE PROCEDURE dw.construire_dim_intervenant
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_intervenant;
    INSERT INTO dw.dim_intervenant (id_intervenant, matricule, nom, prenom, poste, type_contrat,
                                    secteur, date_premiere_entree, date_entree, date_sortie,
                                    lignes_source, id_chargement, fichier_source,
                                    feuille_source, num_ligne_source)
    VALUES (-1, N'(non renseigné)', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0,
            NULL, NULL, NULL, NULL),
           (-2, N'(introuvable)', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0,
            NULL, NULL, NULL, NULL);

    WITH l AS (
        SELECT p.*,
               ROW_NUMBER() OVER (
                   PARTITION BY p.matricule COLLATE Latin1_General_100_BIN2
                   ORDER BY CASE WHEN p.date_entree IS NULL THEN 1 ELSE 0 END,
                            p.date_entree DESC,
                            p.fichier_source, p.feuille_source, p.num_ligne_source) AS rang,
               COUNT(*) OVER (PARTITION BY p.matricule COLLATE Latin1_General_100_BIN2) AS lignes,
               MIN(p.date_entree) OVER (PARTITION BY p.matricule COLLATE Latin1_General_100_BIN2) AS premiere
        FROM propre.intervenants AS p
        WHERE p.matricule IS NOT NULL
    )
    INSERT INTO dw.dim_intervenant (id_intervenant, matricule, nom, prenom, poste, type_contrat,
                                    secteur, date_premiere_entree, date_entree, date_sortie,
                                    lignes_source, id_chargement, fichier_source,
                                    feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY l.matricule COLLATE Latin1_General_100_BIN2),
           l.matricule, l.nom, l.prenom, l.poste, l.type_contrat, l.secteur,
           l.premiere, l.date_entree, l.date_sortie,
           l.lignes, l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM l
    WHERE l.rang = 1;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_intervenant', @lignes, @debut;
END;
GO

/* Tables dont le pack regroupe les codes en doublon. */
INSERT INTO dw.regroupement_codes (table_source, table_dimension, colonne_code) VALUES
    (N'clients', N'dim_client', N'code_client'),
    (N'fournisseurs', N'dim_fournisseur', N'code_fournisseur');
GO

/* Clients : un membre par code, sauf les codes en doublon rattachés à un code principal. */
CREATE TABLE dw.dim_client (
    id_client           int             NOT NULL,
    code_client         nvarchar(450)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    raison_sociale      nvarchar(4000)  NULL,
    type_commerce       nvarchar(4000)  NULL,
    cp                  nvarchar(4000)  NULL,
    ville               nvarchar(4000)  NULL,
    contrat_maintenance nvarchar(4000)  NULL,
    date_creation       date            NULL,
    date_fin_relation   date            NULL,
    statut              nvarchar(4000)  NULL,
    lignes_source       int             NOT NULL,
    codes_en_doublon    int             NOT NULL,
    id_chargement       int             NULL,
    fichier_source      nvarchar(260)   NULL,
    feuille_source      nvarchar(128)   NULL,
    num_ligne_source    int             NULL,
    CONSTRAINT pk_dim_client PRIMARY KEY (id_client),
    CONSTRAINT uq_dim_client_code UNIQUE (code_client)
);
GO

CREATE PROCEDURE dw.construire_dim_client
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_client;
    INSERT INTO dw.dim_client (id_client, code_client, raison_sociale, type_commerce, cp, ville, contrat_maintenance, date_creation, date_fin_relation, statut, lignes_source, codes_en_doublon, id_chargement, fichier_source, feuille_source, num_ligne_source)
    VALUES (-1, N'(non renseigné)', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, NULL, NULL, NULL, NULL),
           (-2, N'(introuvable)', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, NULL, NULL, NULL, NULL);

    WITH l AS (
        SELECT p.*,
               ROW_NUMBER() OVER (
                   PARTITION BY p.code_client COLLATE Latin1_General_100_BIN2
                   ORDER BY p.fichier_source, p.feuille_source, p.num_ligne_source) AS rang,
               COUNT(*) OVER (PARTITION BY p.code_client COLLATE Latin1_General_100_BIN2) AS lignes
        FROM propre.clients AS p
        WHERE p.code_client IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM dw.correspondances(@id_execution, N'clients') AS c
                          WHERE c.code_doublon = p.code_client COLLATE Latin1_General_100_BIN2)
    ),
    r AS (
        SELECT code_principal, COUNT(*) AS codes
        FROM dw.correspondances(@id_execution, N'clients')
        GROUP BY code_principal
    )
    INSERT INTO dw.dim_client (id_client, code_client, raison_sociale, type_commerce, cp, ville, contrat_maintenance, date_creation, date_fin_relation, statut, lignes_source, codes_en_doublon, id_chargement, fichier_source, feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY l.code_client COLLATE Latin1_General_100_BIN2),
           l.code_client,
           l.raison_sociale,
           l.type_commerce,
           l.cp,
           l.ville,
           l.contrat_maintenance,
           l.date_creation,
           l.date_fin_relation,
           l.statut,
           l.lignes,
           COALESCE(r.codes, 0),
           l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM l
    LEFT JOIN r ON r.code_principal = l.code_client COLLATE Latin1_General_100_BIN2
    WHERE l.rang = 1;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_client', @lignes, @debut;
END;
GO

/* Fournisseurs : un membre par code, sauf les codes en doublon rattachés à un code principal. */
CREATE TABLE dw.dim_fournisseur (
    id_fournisseur      int             NOT NULL,
    code_fournisseur    nvarchar(450)   COLLATE Latin1_General_100_BIN2 NOT NULL,
    raison_sociale      nvarchar(4000)  NULL,
    categorie           nvarchar(4000)  NULL,
    cp                  nvarchar(4000)  NULL,
    ville               nvarchar(4000)  NULL,
    delai_paiement      nvarchar(4000)  NULL,
    statut              nvarchar(4000)  NULL,
    lignes_source       int             NOT NULL,
    codes_en_doublon    int             NOT NULL,
    id_chargement       int             NULL,
    fichier_source      nvarchar(260)   NULL,
    feuille_source      nvarchar(128)   NULL,
    num_ligne_source    int             NULL,
    CONSTRAINT pk_dim_fournisseur PRIMARY KEY (id_fournisseur),
    CONSTRAINT uq_dim_fournisseur_code UNIQUE (code_fournisseur)
);
GO

CREATE PROCEDURE dw.construire_dim_fournisseur
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DELETE FROM dw.dim_fournisseur;
    INSERT INTO dw.dim_fournisseur (id_fournisseur, code_fournisseur, raison_sociale, categorie, cp, ville, delai_paiement, statut, lignes_source, codes_en_doublon, id_chargement, fichier_source, feuille_source, num_ligne_source)
    VALUES (-1, N'(non renseigné)', NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, NULL, NULL, NULL, NULL),
           (-2, N'(introuvable)', NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, NULL, NULL, NULL, NULL);

    WITH l AS (
        SELECT p.*,
               ROW_NUMBER() OVER (
                   PARTITION BY p.code_fournisseur COLLATE Latin1_General_100_BIN2
                   ORDER BY p.fichier_source, p.feuille_source, p.num_ligne_source) AS rang,
               COUNT(*) OVER (PARTITION BY p.code_fournisseur COLLATE Latin1_General_100_BIN2) AS lignes
        FROM propre.fournisseurs AS p
        WHERE p.code_fournisseur IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM dw.correspondances(@id_execution, N'fournisseurs') AS c
                          WHERE c.code_doublon = p.code_fournisseur COLLATE Latin1_General_100_BIN2)
    ),
    r AS (
        SELECT code_principal, COUNT(*) AS codes
        FROM dw.correspondances(@id_execution, N'fournisseurs')
        GROUP BY code_principal
    )
    INSERT INTO dw.dim_fournisseur (id_fournisseur, code_fournisseur, raison_sociale, categorie, cp, ville, delai_paiement, statut, lignes_source, codes_en_doublon, id_chargement, fichier_source, feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY l.code_fournisseur COLLATE Latin1_General_100_BIN2),
           l.code_fournisseur,
           l.raison_sociale,
           l.categorie,
           l.cp,
           l.ville,
           l.delai_paiement,
           l.statut,
           l.lignes,
           COALESCE(r.codes, 0),
           l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM l
    LEFT JOIN r ON r.code_principal = l.code_fournisseur COLLATE Latin1_General_100_BIN2
    WHERE l.rang = 1;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'dim_fournisseur', @lignes, @debut;
END;
GO
