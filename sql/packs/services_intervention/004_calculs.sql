/*
  Pack services_intervention, script 004 : calculs (étape 7.4).

  Les calculs portent sur les faits déjà construits (script 003) et sont
  appelés par dw.reconstruire après eux, dans la même transaction. Ils
  restent vérifiables ligne par ligne : le traitement Python les refait de
  son côté à partir de propre et des rattachements
  (frigeo.packs.services_intervention), et compare son résultat à dw.

  Paramètres de calcul : les valeurs propres au client que les calculs
  utilisent (catégorie et article d'un chantier, type de pièce d'une
  facture, date du stock initial, taux de charges selon le type de contrat)
  sont déclarées ici, dans dw.parametre_calcul et dw.parametre_taux_charges,
  et non dans les procédures. Elles sont vérifiées avant toute
  construction par dw.verifier_parametres, contre les valeurs admises des
  listes fermées du dictionnaire (qualite.valeur_liste) : une valeur
  renommée par le métier fait échouer l'exécution, au lieu de vider
  silencieusement un calcul. Pour un autre client, ce sont les premières
  lignes du pack à revoir.

  Chantiers : un chantier sur plusieurs jours (installation) n'a pas
  d'identifiant dans les fichiers. Il se reconnaît à sa facture : une seule
  facture, émise après le dernier jour, porte une ligne de l'article de
  chantier pour chaque jour (le forfait sur le premier, 0 sur les suivants).
  dw.calculer_chantiers regroupe ainsi les interventions de la catégorie de
  chantier reliées à des lignes de l'article de chantier d'une même facture,
  et donne à chacune l'intervention du premier jour (id_chantier), son rang
  (jour_chantier) et le nombre de jours (nb_jours_chantier). Une autre
  intervention est son propre chantier, d'un jour. Le chantier décrit
  l'activité : les interventions non retenues en font partie.
*/

/* Une valeur propre au client utilisée par les calculs. table_source et
   colonne_source (noms du dictionnaire) désignent la liste fermée dont la
   valeur doit être une valeur admise; famille date : une date AAAA-MM-JJ,
   sans liste. */
CREATE TABLE dw.parametre_calcul (
    cle             nvarchar(100)   NOT NULL,
    valeur          nvarchar(4000)  NOT NULL,
    famille         nvarchar(20)    NOT NULL,
    table_source    nvarchar(128)   NULL,
    colonne_source  nvarchar(128)   NULL,
    description     nvarchar(4000)  NOT NULL,
    CONSTRAINT pk_parametre_calcul PRIMARY KEY (cle),
    CONSTRAINT ck_parametre_calcul_famille
        CHECK ((famille = N'texte' AND table_source IS NOT NULL AND colonne_source IS NOT NULL)
               OR (famille = N'date' AND table_source IS NULL AND colonne_source IS NULL))
);
GO

INSERT INTO dw.parametre_calcul
    (cle, valeur, famille, table_source, colonne_source, description) VALUES
    (N'categorie_chantier', N'Installation', N'texte', N'interventions', N'categorie',
     N'Catégorie des interventions qui peuvent former un chantier sur plusieurs jours'),
    (N'article_chantier', N'INST-F', N'texte', N'factures_lignes', N'code_article',
     N'Article facturé pour chaque jour d''un chantier (forfait le premier jour, 0 ensuite)'),
    (N'type_piece_facture', N'Facture', N'texte', N'factures_entetes', N'type_piece',
     N'Type de pièce d''une facture (par opposition à un avoir)'),
    (N'date_stock_initial', N'2025-01-01', N'date', NULL, NULL,
     N'Date du stock et du CUMP initiaux du catalogue (aussi date_initial de la règle R19)');
GO

/* Colonne de propre.parametres_couts qui donne le taux de charges d'un type
   de contrat (valeur de intervenants.type_contrat). */
CREATE TABLE dw.parametre_taux_charges (
    type_contrat  nvarchar(450)  NOT NULL,
    colonne_taux  nvarchar(128)  NOT NULL,
    CONSTRAINT pk_parametre_taux_charges PRIMARY KEY (type_contrat),
    CONSTRAINT ck_parametre_taux_charges_colonne
        CHECK (colonne_taux IN (N'taux_charges_cdi_cdd', N'taux_charges_apprenti'))
);
GO

INSERT INTO dw.parametre_taux_charges (type_contrat, colonne_taux) VALUES
    (N'CDI', N'taux_charges_cdi_cdd'),
    (N'CDD', N'taux_charges_cdi_cdd'),
    (N'Apprentissage', N'taux_charges_apprenti');
GO

/* Valeur d'un paramètre de calcul, NULL s'il n'est pas déclaré. */
CREATE FUNCTION dw.parametre (
    @cle nvarchar(100)
)
RETURNS nvarchar(4000)
AS
BEGIN
    RETURN (SELECT valeur FROM dw.parametre_calcul WHERE cle = @cle);
END;
GO

/* Vérifie les paramètres de calcul pour une exécution : valeur d'une liste
   absente des valeurs admises de qualite.valeur_liste, date invalide, type
   de contrat admis sans taux de charges, taux déclaré pour un type de contrat
   qui n'est pas admis. Lève une erreur qui liste tous les écarts, par
   paramètre, sans valeur; sinon inscrit l'étape dans le journal. */
CREATE PROCEDURE dw.verifier_parametres
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();

    DECLARE @ecarts TABLE (ordre int IDENTITY(1, 1), texte nvarchar(2000) NOT NULL);

    WITH admis AS (
        SELECT table_source, colonne_source, valeur
        FROM qualite.valeur_liste
        WHERE id_execution = @id_execution
    ),
    constats AS (
        SELECT 1 AS rang, p.cle AS objet,
               CONCAT(N'paramètre ', p.cle, N' : valeur absente des valeurs admises de ',
                      p.table_source, N'.', p.colonne_source) AS texte
        FROM dw.parametre_calcul AS p
        WHERE p.famille = N'texte'
          AND NOT EXISTS (SELECT 1 FROM admis AS a
                          WHERE a.table_source = p.table_source
                            AND a.colonne_source = p.colonne_source
                            AND a.valeur = p.valeur COLLATE Latin1_General_100_BIN2)
        UNION ALL
        SELECT 1, p.cle, CONCAT(N'paramètre ', p.cle, N' : date AAAA-MM-JJ invalide')
        FROM dw.parametre_calcul AS p
        WHERE p.famille = N'date'
          AND (p.valeur NOT LIKE N'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
               OR TRY_CONVERT(date, p.valeur, 23) IS NULL)
        UNION ALL
        SELECT 2, a.valeur,
               N'type de contrat admis de intervenants.type_contrat sans taux de charges '
               + N'(dw.parametre_taux_charges)'
        FROM admis AS a
        WHERE a.table_source = N'intervenants' AND a.colonne_source = N'type_contrat'
          AND NOT EXISTS (SELECT 1 FROM dw.parametre_taux_charges AS t
                          WHERE t.type_contrat = a.valeur COLLATE Latin1_General_100_BIN2)
        UNION ALL
        SELECT 3, t.type_contrat,
               N'taux de charges déclaré pour un type de contrat absent des valeurs admises '
               + N'de intervenants.type_contrat'
        FROM dw.parametre_taux_charges AS t
        WHERE NOT EXISTS (SELECT 1 FROM admis AS a
                          WHERE a.table_source = N'intervenants'
                            AND a.colonne_source = N'type_contrat'
                            AND a.valeur = t.type_contrat COLLATE Latin1_General_100_BIN2)
    )
    INSERT INTO @ecarts (texte)
    SELECT texte FROM constats ORDER BY rang, objet;

    DECLARE @nombre int = (SELECT COUNT(*) FROM @ecarts);
    IF @nombre > 0
    BEGIN
        DECLARE @detail nvarchar(max) = (
            SELECT STRING_AGG(CAST(texte AS nvarchar(max)), N'; ') WITHIN GROUP (ORDER BY ordre)
            FROM @ecarts
        );
        DECLARE @message nvarchar(2048) = CONCAT(
            N'Paramètres de calcul du pack non conformes (', @nombre, N' écart(s)) : ',
            CASE WHEN LEN(@detail) > 1900 THEN CONCAT(LEFT(@detail, 1900), N'...')
                 ELSE @detail END
        );
        THROW 50020, @message, 1;
    END;

    DECLARE @lignes int =
        (SELECT COUNT(*) FROM dw.parametre_calcul)
        + (SELECT COUNT(*) FROM dw.parametre_taux_charges);
    EXEC dw.inscrire_etape @id_execution, N'paramètres de calcul', @lignes, @debut;
END;
GO

/*
  Chantiers sur plusieurs jours. Une ligne de propre.factures_lignes de
  l'article de chantier relie son en-tête (rattachement
  factures_lignes.num_facture, en-tête de type facture) à son intervention
  (rattachement factures_lignes.id_intervention, intervention de la
  catégorie de chantier). Les interventions reliées à un même en-tête forment
  un chantier si elles sont au moins deux; une intervention reliée à
  plusieurs en-têtes suit le premier dans l'ordre du lignage de l'en-tête.
  Les jours d'un chantier sont rangés par date de début, heure de début, puis
  lignage de l'intervention (vides d'abord, lignage en classement binaire).
  fait_intervention en sort avec, pour chaque intervention d'un chantier,
  l'intervention du premier jour, son rang et le nombre de jours; les autres
  gardent les valeurs de leur construction (elles-mêmes, 1, 1).
*/
CREATE PROCEDURE dw.calculer_chantiers
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @categorie nvarchar(4000) = dw.parametre(N'categorie_chantier');
    DECLARE @article nvarchar(4000) = dw.parametre(N'article_chantier');
    DECLARE @type_facture nvarchar(4000) = dw.parametre(N'type_piece_facture');
    IF @categorie IS NULL OR @article IS NULL OR @type_facture IS NULL
        THROW 50021, N'dw.calculer_chantiers : paramètre categorie_chantier, article_chantier ou type_piece_facture absent de dw.parametre_calcul.', 1;
    DECLARE @r_entete int =
        dw.regle_rattachement(@id_execution, N'factures_lignes', N'num_facture',
                              N'factures_entetes');
    DECLARE @r_intervention int =
        dw.regle_rattachement(@id_execution, N'factures_lignes', N'id_intervention',
                              N'interventions');

    WITH liens AS (
        SELECT DISTINCT
               h.id_chargement AS entete_chargement,
               h.fichier_source AS entete_fichier,
               h.feuille_source AS entete_feuille,
               h.num_ligne_source AS entete_ligne,
               fi.id_fait_intervention,
               i.date_debut, i.heure_debut,
               i.fichier_source, i.feuille_source, i.num_ligne_source
        FROM propre.factures_lignes AS p
        JOIN qualite.rattachement AS re
            ON re.id_execution = @id_execution AND re.id_regle = @r_entete
           AND re.id_chargement = p.id_chargement AND re.num_ligne_source = p.num_ligne_source
        JOIN propre.factures_entetes AS h
            ON h.id_chargement = re.id_chargement_reference
           AND h.num_ligne_source = re.num_ligne_reference
        JOIN qualite.rattachement AS rv
            ON rv.id_execution = @id_execution AND rv.id_regle = @r_intervention
           AND rv.id_chargement = p.id_chargement AND rv.num_ligne_source = p.num_ligne_source
        JOIN propre.interventions AS i
            ON i.id_chargement = rv.id_chargement_reference
           AND i.num_ligne_source = rv.num_ligne_reference
        JOIN dw.fait_intervention AS fi
            ON fi.id_chargement = i.id_chargement AND fi.num_ligne_source = i.num_ligne_source
        WHERE p.code_article = @article COLLATE Latin1_General_100_BIN2
          AND h.type_piece = @type_facture COLLATE Latin1_General_100_BIN2
          AND i.categorie = @categorie COLLATE Latin1_General_100_BIN2
    ),
    affectes AS (
        SELECT l.*,
               ROW_NUMBER() OVER (
                   PARTITION BY l.id_fait_intervention
                   ORDER BY l.entete_fichier COLLATE Latin1_General_100_BIN2,
                            l.entete_feuille COLLATE Latin1_General_100_BIN2,
                            l.entete_ligne) AS rang_entete
        FROM liens AS l
    ),
    jours AS (
        SELECT a.id_fait_intervention,
               COUNT(*) OVER (PARTITION BY a.entete_chargement, a.entete_ligne) AS nb_jours,
               ROW_NUMBER() OVER (
                   PARTITION BY a.entete_chargement, a.entete_ligne
                   ORDER BY a.date_debut, a.heure_debut,
                            a.fichier_source COLLATE Latin1_General_100_BIN2,
                            a.feuille_source COLLATE Latin1_General_100_BIN2,
                            a.num_ligne_source) AS jour,
               FIRST_VALUE(a.id_fait_intervention) OVER (
                   PARTITION BY a.entete_chargement, a.entete_ligne
                   ORDER BY a.date_debut, a.heure_debut,
                            a.fichier_source COLLATE Latin1_General_100_BIN2,
                            a.feuille_source COLLATE Latin1_General_100_BIN2,
                            a.num_ligne_source
                   ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS premier
        FROM affectes AS a
        WHERE a.rang_entete = 1
    )
    UPDATE f
    SET id_chantier = j.premier,
        jour_chantier = j.jour,
        nb_jours_chantier = j.nb_jours
    FROM dw.fait_intervention AS f
    JOIN jours AS j ON j.id_fait_intervention = f.id_fait_intervention
    WHERE j.nb_jours >= 2;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'chantiers', @lignes, @debut;
END;
GO
