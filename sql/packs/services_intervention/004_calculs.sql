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

  CUMP (coût unitaire moyen pondéré) : dw.calculer_cump le calcule pour
  chaque pièce et chaque mois, de celui du stock initial du catalogue à celui
  de la période de fin de l'exécution, dans dw.cump_mensuel :

    CUMP de fin de mois = (stock de début × CUMP de début + valeur des achats)
                          / (stock de début + quantités achetées)

  Le stock de début d'un mois est celui de fin du mois précédent (achats
  moins consommations), le premier étant le stock initial du catalogue, et le
  CUMP de début celui de fin du mois précédent, le premier étant le CUMP
  initial. Un achat compte au mois de la date de sa facture, un avoir comme
  un achat négatif (quantité et montant négatifs); seules les lignes retenues
  comptent, d'une pièce connue, avec leur quantité (et leur montant pour un
  achat). Un stock de début négatif, ou sans CUMP connu, pèse zéro; un mois
  sans achat, ou dont le dénominateur n'est pas positif, garde le CUMP de
  début. Le CUMP est arrondi à 4 décimales chaque mois, et c'est la valeur
  arrondie qui sert au mois suivant.

  Coût des pièces : une consommation est valorisée au CUMP de début de son
  mois (celui de la fin du mois précédent, le CUMP initial pour le premier
  mois) : cout_ht = quantité × CUMP, arrondi au centime. Quand il ne peut pas
  l'être, cump_applique et cout_ht restent vides et motif_calcul dit
  pourquoi (quantité vide, pièce non renseignée ou introuvable, date vide ou
  hors des mois du calcul, CUMP inconnu); le coût est calculé aussi pour une
  consommation non retenue.

  Marge opérationnelle : dw.calculer_marges donne à chaque intervention,
  toutes issues confondues et retenue ou non :
  - le CA : somme des montants HT de ses lignes de facture et d'avoir
    retenues (le forfait d'un chantier est sur son premier jour);
  - le coût salarial : (durée sur site + trajet) / 60 × coût horaire chargé,
    au centime, le coût horaire chargé étant
      salaire mensuel × 12 × (1 + taux de charges)
      / (heures annuelles × taux d'activité), arrondi à 4 décimales,
    avec la rémunération en vigueur à la date (la dernière ligne de même
    matricule dont la date d'effet n'est pas postérieure), le type de
    contrat de la période d'emploi que désigne le rattachement de
    l'intervenant, et les paramètres de coûts de l'année;
  - le coût de déplacement : distance × coût kilométrique de l'année, au
    centime;
  - le coût des pièces : somme des coûts de ses consommations retenues;
  - la marge : CA moins les trois coûts.
  Une composante impossible à calculer reste vide, jamais à zéro, ainsi que
  la marge, et motif_calcul donne la première raison dans l'ordre : date
  vide, durée vide, intervenant non rattaché, intervenant non retenu,
  rémunération non retenue, rémunération inconnue à la date, paramètres de
  coûts de l'année non retenus, paramètres de coûts de l'année absents, taux
  de charges inconnu, heures annuelles ou taux d'activité vides ou nuls,
  distance ou coût kilométrique vide, coût d'une pièce inconnu.
  Une ligne de référence exclue des indicateurs (période d'emploi,
  rémunération en vigueur, paramètres de l'année) ne sert à aucun calcul et
  n'est pas remplacée par une autre : le coût qui en dépend reste vide, pour
  ne pas donner une marge fausse (un salaire hors bornes, par exemple).
  De même, si une ligne de facture ou une consommation liée à l'intervention
  est exclue des indicateurs, le CA ou le coût des pièces serait incomplet :
  il reste vide, ainsi que la marge (motifs ligne de facture non retenue,
  consommation non retenue, en fin de liste). Le coût horaire chargé, qui
  révèle le salaire, n'est gardé nulle part.

  Arrondis et types : les opérandes sont ramenés à 6 décimales au plus pour
  que les produits et le quotient gardent toutes leurs décimales utiles
  (règles de précision de T-SQL); le seul arrondi est donc celui qui est
  annoncé, que la vérification en Python refait à l'identique (au plus
  proche, la moitié s'éloignant de zéro).
*/

/* Colonnes de propre lues par les calculs. */
INSERT INTO dw.contrat_entree (table_propre, colonne, famille) VALUES
    (N'catalogue_pieces', N'stock_initial', N'décimal'),
    (N'catalogue_pieces', N'cump_initial', N'décimal'),
    (N'remunerations', N'matricule', N'texte'),
    (N'remunerations', N'date_effet', N'date'),
    (N'remunerations', N'salaire_brut_mensuel', N'décimal'),
    (N'remunerations', N'taux_activite', N'décimal'),
    (N'parametres_couts', N'annee', N'décimal'),
    (N'parametres_couts', N'cout_km', N'décimal'),
    (N'parametres_couts', N'taux_charges_cdi_cdd', N'décimal'),
    (N'parametres_couts', N'taux_charges_apprenti', N'décimal'),
    (N'parametres_couts', N'heures_annuelles', N'décimal');
GO

/* Mesures des faits calculées par ce script. */
INSERT INTO dw.mesure_calculee (table_fait, colonne_fait, description) VALUES
    (N'fait_consommation', N'cump_applique',
     N'CUMP de la pièce à la fin du mois précédant la consommation'),
    (N'fait_consommation', N'cout_ht', N'Quantité consommée × CUMP appliqué, au centime'),
    (N'fait_intervention', N'ca_ht', N'Montants HT des lignes de facture et d''avoir retenues'),
    (N'fait_intervention', N'cout_salarial',
     N'(Durée sur site + trajet) / 60 × coût horaire chargé, au centime'),
    (N'fait_intervention', N'cout_deplacement',
     N'Distance × coût kilométrique de l''année, au centime'),
    (N'fait_intervention', N'cout_pieces', N'Coûts des consommations retenues'),
    (N'fait_intervention', N'marge', N'CA moins les coûts salarial, de déplacement et des pièces');
GO

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

/* CUMP d'une pièce pour un mois du calcul (voir l'en-tête du script). */
CREATE TABLE dw.cump_mensuel (
    id_piece            int             NOT NULL,
    mois                date            NOT NULL,
    stock_debut         decimal(28, 8)  NOT NULL,
    cump_debut          decimal(19, 4)  NULL,
    quantite_achetee    decimal(28, 8)  NOT NULL,
    valeur_achats       decimal(28, 8)  NOT NULL,
    quantite_consommee  decimal(28, 8)  NOT NULL,
    stock_fin           decimal(28, 8)  NOT NULL,
    cump_fin            decimal(19, 4)  NULL,
    CONSTRAINT pk_cump_mensuel PRIMARY KEY (id_piece, mois),
    CONSTRAINT ck_cump_mensuel_mois CHECK (DAY(mois) = 1),
    CONSTRAINT fk_cump_mensuel_piece FOREIGN KEY (id_piece) REFERENCES dw.dim_piece (id_piece)
);
GO

/* Vide les tables de calcul qui référencent les dimensions, avant leur
   reconstruction (comme dw.vider_faits pour les faits). */
CREATE PROCEDURE dw.vider_calculs
AS
BEGIN
    SET NOCOUNT ON;
    DELETE FROM dw.cump_mensuel;
END;
GO

/* CUMP de fin de mois d'une pièce, à partir du stock et du CUMP de début et
   des achats du mois (quantité et valeur). Un stock de début négatif ou sans
   CUMP pèse zéro; sans achat, ou si le dénominateur n'est pas positif, le
   CUMP de début est gardé (NULL s'il est inconnu). Les opérandes sont ramenés
   à 6 décimales : le quotient garde alors 18 décimales avant l'arrondi à 4. */
CREATE FUNCTION dw.cump_fin_de_mois (
    @stock_debut decimal(28, 8),
    @cump_debut decimal(19, 4),
    @quantite decimal(28, 8),
    @valeur decimal(28, 8)
)
RETURNS decimal(19, 4)
AS
BEGIN
    DECLARE @stock decimal(16, 6) =
        CASE WHEN @stock_debut > 0 AND @cump_debut IS NOT NULL
             THEN CAST(@stock_debut AS decimal(16, 6)) ELSE 0 END;
    DECLARE @achetee decimal(18, 6) = CAST(@quantite AS decimal(18, 6));
    IF @achetee = 0 OR @stock + @achetee <= 0
        RETURN @cump_debut;
    DECLARE @numerateur decimal(24, 10) = CAST(
        @stock * COALESCE(@cump_debut, 0) + CAST(@valeur AS decimal(18, 6))
        AS decimal(24, 10));
    DECLARE @denominateur decimal(18, 6) = CAST(@stock + @achetee AS decimal(18, 6));
    RETURN CAST(ROUND(@numerateur / @denominateur, 4) AS decimal(19, 4));
END;
GO

/*
  CUMP mensuel de chaque pièce, puis coût des consommations (voir l'en-tête
  du script). Les mois vont de celui de la date du stock initial
  (dw.parametre_calcul, premier jour d'un mois) à celui de la période de fin
  de l'exécution, tous dans le calendrier. Les mouvements (achats et
  consommations retenus) sont totalisés par pièce et par mois, toutes les
  pièces ayant une ligne pour chaque mois, puis le CUMP est calculé mois
  après mois par une expression de table récursive, chaque mois partant de la
  fin du précédent.
*/
CREATE PROCEDURE dw.calculer_cump
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @date_initiale date = TRY_CONVERT(date, dw.parametre(N'date_stock_initial'), 23);
    DECLARE @periode char(7) =
        (SELECT periode_fin FROM qualite.execution WHERE id_execution = @id_execution);
    IF @date_initiale IS NULL OR DAY(@date_initiale) <> 1
        THROW 50022, N'dw.calculer_cump : date_stock_initial de dw.parametre_calcul absente ou autre que le premier jour d''un mois.', 1;
    DECLARE @premier_mois date = @date_initiale;
    DECLARE @dernier_mois date =
        DATEFROMPARTS(CAST(LEFT(@periode, 4) AS int), CAST(RIGHT(@periode, 2) AS int), 1);
    IF @dernier_mois < @premier_mois
       OR @premier_mois < (SELECT MIN(date_jour) FROM dw.dim_date)
       OR EOMONTH(@dernier_mois) > (SELECT MAX(date_jour) FROM dw.dim_date)
        THROW 50023, N'dw.calculer_cump : mois du calcul hors du calendrier, ou période de fin antérieure au stock initial.', 1;

    DELETE FROM dw.cump_mensuel;

    DECLARE @pieces TABLE (
        id_piece       int             PRIMARY KEY,
        stock_initial  decimal(28, 8)  NOT NULL,
        cump_initial   decimal(19, 4)  NULL
    );
    INSERT INTO @pieces (id_piece, stock_initial, cump_initial)
    SELECT dp.id_piece,
           COALESCE(c.stock_initial, 0),
           CAST(ROUND(c.cump_initial, 4) AS decimal(19, 4))
    FROM dw.dim_piece AS dp
    LEFT JOIN propre.catalogue_pieces AS c
        ON c.id_chargement = dp.id_chargement AND c.num_ligne_source = dp.num_ligne_source
    WHERE dp.id_piece > 0;

    DECLARE @mouvements TABLE (
        id_piece            int             NOT NULL,
        mois                date            NOT NULL,
        quantite_achetee    decimal(28, 8)  NOT NULL,
        valeur_achats       decimal(28, 8)  NOT NULL,
        quantite_consommee  decimal(28, 8)  NOT NULL,
        PRIMARY KEY (id_piece, mois)
    );
    WITH mois AS (
        SELECT @premier_mois AS mois
        UNION ALL
        SELECT DATEADD(month, 1, mois) FROM mois WHERE mois < @dernier_mois
    ),
    lignes AS (
        SELECT a.id_piece, DATEFROMPARTS(YEAR(d.date_jour), MONTH(d.date_jour), 1) AS mois,
               a.quantite AS quantite_achetee, a.montant_ht AS valeur_achats,
               CAST(0 AS decimal(28, 8)) AS quantite_consommee
        FROM dw.fait_achat AS a
        JOIN dw.dim_date AS d ON d.id_date = a.id_date
        WHERE a.retenue = 1 AND a.id_piece > 0
          AND a.quantite IS NOT NULL AND a.montant_ht IS NOT NULL
        UNION ALL
        SELECT c.id_piece, DATEFROMPARTS(YEAR(d.date_jour), MONTH(d.date_jour), 1),
               CAST(0 AS decimal(28, 8)), CAST(0 AS decimal(28, 8)), c.quantite
        FROM dw.fait_consommation AS c
        JOIN dw.dim_date AS d ON d.id_date = c.id_date
        WHERE c.retenue = 1 AND c.id_piece > 0 AND c.quantite IS NOT NULL
    ),
    totaux AS (
        SELECT id_piece, mois, SUM(quantite_achetee) AS quantite_achetee,
               SUM(valeur_achats) AS valeur_achats, SUM(quantite_consommee) AS quantite_consommee
        FROM lignes
        WHERE mois BETWEEN @premier_mois AND @dernier_mois
        GROUP BY id_piece, mois
    )
    INSERT INTO @mouvements (id_piece, mois, quantite_achetee, valeur_achats, quantite_consommee)
    SELECT p.id_piece, m.mois,
           COALESCE(t.quantite_achetee, 0), COALESCE(t.valeur_achats, 0),
           COALESCE(t.quantite_consommee, 0)
    FROM @pieces AS p
    CROSS JOIN mois AS m
    LEFT JOIN totaux AS t ON t.id_piece = p.id_piece AND t.mois = m.mois
    OPTION (MAXRECURSION 1200);

    WITH calcul AS (
        SELECT m.id_piece, m.mois,
               p.stock_initial AS stock_debut,
               p.cump_initial AS cump_debut,
               m.quantite_achetee, m.valeur_achats, m.quantite_consommee,
               CAST(p.stock_initial + m.quantite_achetee - m.quantite_consommee
                    AS decimal(28, 8)) AS stock_fin,
               dw.cump_fin_de_mois(p.stock_initial, p.cump_initial, m.quantite_achetee,
                                   m.valeur_achats) AS cump_fin
        FROM @mouvements AS m
        JOIN @pieces AS p ON p.id_piece = m.id_piece
        WHERE m.mois = @premier_mois
        UNION ALL
        SELECT m.id_piece, m.mois,
               c.stock_fin,
               c.cump_fin,
               m.quantite_achetee, m.valeur_achats, m.quantite_consommee,
               CAST(c.stock_fin + m.quantite_achetee - m.quantite_consommee AS decimal(28, 8)),
               dw.cump_fin_de_mois(c.stock_fin, c.cump_fin, m.quantite_achetee,
                                   m.valeur_achats)
        FROM calcul AS c
        JOIN @mouvements AS m
            ON m.id_piece = c.id_piece AND m.mois = DATEADD(month, 1, c.mois)
    )
    INSERT INTO dw.cump_mensuel (id_piece, mois, stock_debut, cump_debut, quantite_achetee,
                                 valeur_achats, quantite_consommee, stock_fin, cump_fin)
    SELECT id_piece, mois, stock_debut, cump_debut, quantite_achetee, valeur_achats,
           quantite_consommee, stock_fin, cump_fin
    FROM calcul
    OPTION (MAXRECURSION 1200);
    DECLARE @lignes_cump int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'cump_mensuel', @lignes_cump, @debut;

    SET @debut = SYSUTCDATETIME();
    UPDATE f
    SET motif_calcul = x.motif,
        cump_applique = CASE WHEN x.motif IS NULL THEN k.cump_debut END,
        cout_ht = CASE WHEN x.motif IS NULL
                       THEN CAST(ROUND(CAST(f.quantite AS decimal(18, 6)) * k.cump_debut, 2)
                                 AS decimal(19, 2)) END
    FROM dw.fait_consommation AS f
    LEFT JOIN dw.dim_date AS d ON d.id_date = f.id_date
    OUTER APPLY (SELECT DATEFROMPARTS(YEAR(d.date_jour), MONTH(d.date_jour), 1) AS mois) AS j
    LEFT JOIN dw.cump_mensuel AS k ON k.id_piece = f.id_piece AND k.mois = j.mois
    CROSS APPLY (
        SELECT CASE
                   WHEN f.quantite IS NULL THEN N'quantité vide'
                   WHEN f.id_piece = -1 THEN N'pièce non renseignée'
                   WHEN f.id_piece = -2 THEN N'pièce introuvable'
                   WHEN f.id_date = -1 THEN N'date vide'
                   WHEN j.mois IS NULL OR j.mois < @premier_mois OR j.mois > @dernier_mois
                       THEN N'date hors des mois du calcul'
                   WHEN k.cump_debut IS NULL THEN N'CUMP inconnu'
               END AS motif
    ) AS x;
    DECLARE @lignes int = (SELECT COUNT(*) FROM dw.fait_consommation WHERE cout_ht IS NOT NULL);
    EXEC dw.inscrire_etape @id_execution, N'coût des pièces', @lignes, @debut;
END;
GO

/*
  Marge opérationnelle de chaque intervention (voir l'en-tête du script).
  Les lignes de référence (rémunération, paramètres de coûts de l'année) se
  choisissent parmi toutes les lignes, retenues ou non; à égalité de date
  d'effet ou d'année, la première dans l'ordre du lignage. Si la ligne
  choisie, ou la période d'emploi rattachée, n'est pas retenue, le coût qui
  en dépend n'est pas calculé.
*/
CREATE PROCEDURE dw.calculer_marges
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @r_intervenant int =
        dw.regle_rattachement(@id_execution, N'interventions', N'intervenant', N'intervenants');

    WITH base AS (
        SELECT f.id_fait_intervention,
               p.date_debut, p.duree_min, p.duree_trajet_min, p.distance_km,
               ti.matricule, ti.type_contrat, ti.retenue AS intervenant_retenu
        FROM dw.fait_intervention AS f
        JOIN propre.interventions AS p
            ON p.id_chargement = f.id_chargement AND p.num_ligne_source = f.num_ligne_source
        LEFT JOIN qualite.rattachement AS ri
            ON ri.id_execution = @id_execution AND ri.id_regle = @r_intervenant
           AND ri.id_chargement = p.id_chargement AND ri.num_ligne_source = p.num_ligne_source
        LEFT JOIN propre.intervenants AS ti
            ON ti.id_chargement = ri.id_chargement_reference
           AND ti.num_ligne_source = ri.num_ligne_reference
    ),
    remuneration AS (
        SELECT b.id_fait_intervention, r.salaire_brut_mensuel, r.taux_activite, r.retenue,
               ROW_NUMBER() OVER (
                   PARTITION BY b.id_fait_intervention
                   ORDER BY r.date_effet DESC,
                            r.fichier_source COLLATE Latin1_General_100_BIN2,
                            r.feuille_source COLLATE Latin1_General_100_BIN2,
                            r.num_ligne_source) AS rang
        FROM base AS b
        JOIN propre.remunerations AS r
            ON r.matricule = b.matricule COLLATE Latin1_General_100_BIN2
           AND r.date_effet <= b.date_debut
    ),
    couts_annee AS (
        SELECT c.*,
               ROW_NUMBER() OVER (
                   PARTITION BY c.annee
                   ORDER BY c.fichier_source COLLATE Latin1_General_100_BIN2,
                            c.feuille_source COLLATE Latin1_General_100_BIN2,
                            c.num_ligne_source) AS rang
        FROM propre.parametres_couts AS c
        WHERE c.annee IS NOT NULL
    ),
    entrees AS (
        SELECT b.*,
               r.salaire_brut_mensuel, r.taux_activite, r.retenue AS remuneration_retenue,
               c.annee, c.cout_km, c.heures_annuelles, c.retenue AS couts_retenus,
               CASE t.colonne_taux
                   WHEN N'taux_charges_cdi_cdd' THEN c.taux_charges_cdi_cdd
                   WHEN N'taux_charges_apprenti' THEN c.taux_charges_apprenti
               END AS taux_charges
        FROM base AS b
        LEFT JOIN remuneration AS r ON r.id_fait_intervention = b.id_fait_intervention AND r.rang = 1
        LEFT JOIN couts_annee AS c ON c.annee = YEAR(b.date_debut) AND c.rang = 1
        LEFT JOIN dw.parametre_taux_charges AS t
            ON t.type_contrat = b.type_contrat COLLATE Latin1_General_100_BIN2
    ),
    horaire AS (
        SELECT e.*,
               CASE WHEN e.salaire_brut_mensuel IS NOT NULL AND e.taux_charges IS NOT NULL
                         AND e.heures_annuelles > 0 AND e.taux_activite > 0
                         AND e.intervenant_retenu = 1 AND e.remuneration_retenue = 1
                         AND e.couts_retenus = 1
                    THEN CAST(ROUND(
                        CAST(CAST(CAST(e.salaire_brut_mensuel AS decimal(16, 6)) * 12
                                  AS decimal(18, 6))
                             * (1 + CAST(e.taux_charges AS decimal(10, 6)))
                             AS decimal(24, 12))
                        / CAST(CAST(e.heures_annuelles AS decimal(12, 6))
                               * CAST(e.taux_activite AS decimal(10, 6)) AS decimal(18, 6)),
                        4) AS decimal(19, 4))
               END AS cout_horaire
        FROM entrees AS e
    ),
    lignes AS (
        SELECT l.id_fait_intervention,
               SUM(CASE WHEN l.retenue = 1 THEN l.montant_ht ELSE 0 END) AS ca,
               SUM(CASE WHEN l.retenue = 0 THEN 1 ELSE 0 END) AS exclues
        FROM dw.fait_ligne_facture AS l
        WHERE l.id_fait_intervention IS NOT NULL
        GROUP BY l.id_fait_intervention
    ),
    pieces AS (
        SELECT c.id_fait_intervention,
               SUM(CASE WHEN c.retenue = 1 THEN c.cout_ht ELSE 0 END) AS cout,
               SUM(CASE WHEN c.retenue = 1 AND c.cout_ht IS NULL THEN 1 ELSE 0 END) AS inconnus,
               SUM(CASE WHEN c.retenue = 0 THEN 1 ELSE 0 END) AS exclues
        FROM dw.fait_consommation AS c
        WHERE c.id_fait_intervention IS NOT NULL
        GROUP BY c.id_fait_intervention
    ),
    composantes AS (
        SELECT h.id_fait_intervention,
               CASE WHEN COALESCE(l.exclues, 0) = 0
                    THEN CAST(ROUND(COALESCE(l.ca, 0), 2) AS decimal(19, 2))
               END AS ca_ht,
               CASE WHEN h.cout_horaire IS NOT NULL AND h.duree_min IS NOT NULL
                         AND h.duree_trajet_min IS NOT NULL
                    THEN CAST(ROUND(
                        CAST(CAST(h.duree_min + h.duree_trajet_min AS decimal(12, 0))
                             * h.cout_horaire AS decimal(28, 12)) / CAST(60 AS decimal(2, 0)),
                        2) AS decimal(19, 2))
               END AS cout_salarial,
               CASE WHEN h.distance_km IS NOT NULL AND h.cout_km IS NOT NULL
                         AND h.couts_retenus = 1
                    THEN CAST(ROUND(CAST(h.distance_km AS decimal(18, 6))
                                    * CAST(h.cout_km AS decimal(18, 6)), 2) AS decimal(19, 2))
               END AS cout_deplacement,
               CASE WHEN COALESCE(k.inconnus, 0) = 0 AND COALESCE(k.exclues, 0) = 0
                    THEN CAST(COALESCE(k.cout, 0) AS decimal(19, 2))
               END AS cout_pieces,
               CASE
                   WHEN h.date_debut IS NULL THEN N'date vide'
                   WHEN h.duree_min IS NULL OR h.duree_trajet_min IS NULL THEN N'durée vide'
                   WHEN h.matricule IS NULL THEN N'intervenant non rattaché'
                   WHEN h.intervenant_retenu = 0 THEN N'intervenant non retenu'
                   WHEN h.remuneration_retenue = 0 THEN N'rémunération non retenue'
                   WHEN h.salaire_brut_mensuel IS NULL THEN N'rémunération inconnue à la date'
                   WHEN h.couts_retenus = 0
                       THEN N'paramètres de coûts de l''année non retenus'
                   WHEN h.annee IS NULL THEN N'paramètres de coûts de l''année absents'
                   WHEN h.taux_charges IS NULL THEN N'taux de charges inconnu'
                   WHEN h.cout_horaire IS NULL
                       THEN N'heures annuelles ou taux d''activité vides ou nuls'
                   WHEN h.distance_km IS NULL OR h.cout_km IS NULL
                       THEN N'distance ou coût kilométrique vide'
                   WHEN COALESCE(k.inconnus, 0) > 0 THEN N'coût d''une pièce inconnu'
                   WHEN COALESCE(l.exclues, 0) > 0 THEN N'ligne de facture non retenue'
                   WHEN COALESCE(k.exclues, 0) > 0 THEN N'consommation non retenue'
               END AS motif
        FROM horaire AS h
        LEFT JOIN lignes AS l ON l.id_fait_intervention = h.id_fait_intervention
        LEFT JOIN pieces AS k ON k.id_fait_intervention = h.id_fait_intervention
    )
    UPDATE f
    SET ca_ht = c.ca_ht,
        cout_salarial = c.cout_salarial,
        cout_deplacement = c.cout_deplacement,
        cout_pieces = c.cout_pieces,
        marge = c.ca_ht - c.cout_salarial - c.cout_deplacement - c.cout_pieces,
        motif_calcul = c.motif
    FROM dw.fait_intervention AS f
    JOIN composantes AS c ON c.id_fait_intervention = f.id_fait_intervention;

    DECLARE @lignes int = (SELECT COUNT(*) FROM dw.fait_intervention WHERE marge IS NOT NULL);
    EXEC dw.inscrire_etape @id_execution, N'marges', @lignes, @debut;
END;
GO
