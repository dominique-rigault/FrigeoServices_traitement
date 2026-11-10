/*
  Pack services_intervention, script 003 : faits du modèle en étoile.

  Chaque fait est vidé par dw.vider_faits (script 001) avant la reconstruction
  des dimensions, puis rempli par sa procédure dw.construire_fait_<nom>,
  appelée par dw.reconstruire après les dimensions et inscrite dans
  dw.journal_reconstruction.

  Une ligne de fait par ligne de propre, sans filtre : les lignes annulées,
  non facturables ou en anomalie restent, et se distinguent par leurs
  colonnes. Clé technique numérotée dans l'ordre du lignage (fichier, feuille,
  numéro de ligne), de sorte que les mêmes données redonnent les mêmes clés.
  Le lignage de la ligne de propre est conservé (id_chargement et
  num_ligne_source sont uniques ensemble); il n'a pas de clé étrangère vers
  qualite.journal_chargement, dont les lignes d'une période rejouée sont
  supprimées avant la reconstruction.

  Membre de dimension d'une ligne :
  - clé vide dans propre : -1 « non renseigné »;
  - clé citant un référentiel : par qualite.rattachement (étape 7.3d), la
    ligne du référentiel que cite la ligne, son code, puis le membre de ce
    code; sans rattachement, ou si le code de la ligne du référentiel n'est
    pas dans la dimension : -2 « introuvable »;
  - colonne sans référentiel (catégorie) : égalité binaire du code, sinon -2;
  - date : le jour du calendrier, -2 hors calendrier.
  Les rattachements lus sont déclarés dans dw.contrat_rattachement : un
  rattachement absent de l'exécution fait échouer la reconstruction.

  Lignes retenues (étape 7.4a) : retenue reprend la colonne retenue de la
  ligne de propre (0 pour une ligne qui porte une anomalie bloquante que le
  métier n'a pas résolue, exclue des indicateurs). Une ligne de document
  (facture, pièce d'achat) n'est retenue que si son en-tête trouvé l'est
  aussi; une ligne sans en-tête garde sa propre retenue, l'en-tête introuvable
  étant une anomalie de la ligne. Ces héritages sont déclarés dans
  dw.contrat_retenue, pour la vérification de l'écriture. Une ligne liée à une
  intervention non retenue (consommation, ligne de facture) reste retenue : le
  CA et le stock ne dépendent pas de l'intervention.

  Mesures et dates : chaque colonne numérique d'un fait reprise de propre est
  déclarée dans dw.contrat_mesure, et chaque date lue sur la ligne même du
  fait dans dw.contrat_date, pour la vérification de l'écriture.

  Lien vers une autre ligne de fait (une consommation ou une ligne de facture
  vers son intervention) : la clé de la ligne de fait que désigne le
  rattachement, NULL sinon, avec lien_intervention qui dit pourquoi
  (rattachée, non renseignée, introuvable).

  Document à en-tête et lignes (facture, pièce d'achat) : un fait par ligne,
  les attributs de l'en-tête (dates, client ou fournisseur, type de pièce)
  descendant sur ses lignes par le rattachement de la ligne à son en-tête;
  les totaux de l'en-tête ne sont pas repris, la somme des lignes les donnant.
  lien_entete dit si l'en-tête est trouvé; sans en-tête, ses dimensions
  pointent vers -1 si le numéro du document est vide, -2 sinon.

  Client et fournisseur : la ligne du référentiel désignée par le
  rattachement donne un code; si le métier l'a rattaché à un code principal
  (dw.correspondances), le membre est celui du code principal.

  Écritures comptables : une ligne par ligne du FEC, sans client ni
  fournisseur (le compte auxiliaire n'a pas la forme de leur code). La
  référence de pièce est rapprochée des factures et des pièces d'achat par
  les rattachements, sans filtre par journal : une écriture de tout journal
  dont la référence de pièce est le numéro d'un document le désigne.

  Données personnelles : l'intervenant et le client d'une intervention ne
  sont portés que par leur dimension; le nom du client, l'adresse et le
  commentaire de l'intervention n'entrent pas dans dw.
*/

/* Colonnes de propre lues par les faits. */
INSERT INTO dw.contrat_entree (table_propre, colonne, famille) VALUES
    (N'interventions', N'id_intervention', N'texte'),
    (N'interventions', N'date_debut', N'date'),
    (N'interventions', N'heure_debut', N'heure'),
    (N'interventions', N'duree_min', N'entier'),
    (N'interventions', N'duree_trajet_min', N'entier'),
    (N'interventions', N'distance_km', N'décimal'),
    (N'interventions', N'intervenant', N'texte'),
    (N'interventions', N'code_client', N'texte'),
    (N'interventions', N'lieu_cp', N'texte'),
    (N'interventions', N'lieu_ville', N'texte'),
    (N'interventions', N'categorie', N'texte'),
    (N'interventions', N'statut', N'texte'),
    (N'interventions', N'facturable', N'texte'),
    (N'pieces_interventions', N'id_consommation', N'texte'),
    (N'pieces_interventions', N'id_intervention', N'texte'),
    (N'pieces_interventions', N'date_sortie', N'date'),
    (N'pieces_interventions', N'ref_piece', N'texte'),
    (N'pieces_interventions', N'quantite', N'décimal'),
    (N'pieces_interventions', N'unite', N'texte');
GO

/* Rattachements lus par les faits (noms du dictionnaire), avec la colonne du
   fait qui les reflète ligne à ligne. */
INSERT INTO dw.contrat_rattachement
    (table_source, cle, table_reference, table_fait, colonne_fait, forme) VALUES
    (N'interventions', N'intervenant', N'intervenants',
     N'fait_intervention', N'id_intervenant', N'membre'),
    (N'interventions', N'code_client', N'clients',
     N'fait_intervention', N'id_client', N'membre'),
    (N'pieces_interventions', N'ref_piece', N'catalogue_pieces',
     N'fait_consommation', N'id_piece', N'membre'),
    (N'pieces_interventions', N'id_intervention', N'interventions',
     N'fait_consommation', N'lien_intervention', N'lien');
GO

/* Faits et tables dont ils ont une ligne par ligne de propre. */
INSERT INTO dw.source_fait (table_fait, table_source) VALUES
    (N'fait_intervention', N'interventions'),
    (N'fait_consommation', N'pieces_interventions'),
    (N'fait_ligne_facture', N'factures_lignes'),
    (N'fait_achat', N'achats_lignes'),
    (N'fait_ecriture', N'fec');
GO

/* Mesures et dates des faits des interventions et des consommations. */
INSERT INTO dw.contrat_mesure
    (table_fait, colonne_fait, table_propre, colonne_propre, signe) VALUES
    (N'fait_intervention', N'duree_min', N'interventions', N'duree_min', 1),
    (N'fait_intervention', N'duree_trajet_min', N'interventions', N'duree_trajet_min', 1),
    (N'fait_intervention', N'distance_km', N'interventions', N'distance_km', 1),
    (N'fait_consommation', N'quantite', N'pieces_interventions', N'quantite', 1);
GO

INSERT INTO dw.contrat_date (table_fait, colonne_fait, table_propre, colonne_propre) VALUES
    (N'fait_intervention', N'id_date', N'interventions', N'date_debut'),
    (N'fait_consommation', N'id_date', N'pieces_interventions', N'date_sortie');
GO

/*
  Interventions : une ligne par ligne de propre.interventions. Intervenant par
  le rattachement interventions.intervenant vers intervenants (son matricule),
  client par interventions.code_client vers clients, date de début, catégorie.
*/
CREATE TABLE dw.fait_intervention (
    id_fait_intervention  int             NOT NULL,
    id_intervention       nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    id_date               int             NOT NULL,
    heure_debut           time(0)         NULL,
    id_intervenant        int             NOT NULL,
    id_client             int             NOT NULL,
    id_categorie          int             NOT NULL,
    duree_min             bigint          NULL,
    duree_trajet_min      bigint          NULL,
    distance_km           decimal(28, 8)  NULL,
    statut                nvarchar(4000)  NULL,
    facturable            nvarchar(4000)  NULL,
    lieu_cp               nvarchar(4000)  NULL,
    lieu_ville            nvarchar(4000)  NULL,
    retenue               bit             NOT NULL,
    id_chargement         int             NOT NULL,
    fichier_source        nvarchar(260)   NOT NULL,
    feuille_source        nvarchar(128)   NULL,
    num_ligne_source      int             NOT NULL,
    CONSTRAINT pk_fait_intervention PRIMARY KEY (id_fait_intervention),
    CONSTRAINT uq_fait_intervention_lignage UNIQUE (id_chargement, num_ligne_source),
    CONSTRAINT fk_fait_intervention_date
        FOREIGN KEY (id_date) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_intervention_intervenant
        FOREIGN KEY (id_intervenant) REFERENCES dw.dim_intervenant (id_intervenant),
    CONSTRAINT fk_fait_intervention_client
        FOREIGN KEY (id_client) REFERENCES dw.dim_client (id_client),
    CONSTRAINT fk_fait_intervention_categorie
        FOREIGN KEY (id_categorie) REFERENCES dw.dim_categorie (id_categorie)
);
GO

CREATE PROCEDURE dw.construire_fait_intervention
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @r_intervenant int =
        dw.regle_rattachement(@id_execution, N'interventions', N'intervenant', N'intervenants');
    DECLARE @r_client int =
        dw.regle_rattachement(@id_execution, N'interventions', N'code_client', N'clients');

    DELETE FROM dw.fait_intervention;
    INSERT INTO dw.fait_intervention (
        id_fait_intervention, id_intervention, id_date, heure_debut, id_intervenant, id_client,
        id_categorie, duree_min, duree_trajet_min, distance_km, statut, facturable, lieu_cp,
        lieu_ville, retenue, id_chargement, fichier_source, feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY p.fichier_source, p.feuille_source, p.num_ligne_source),
           p.id_intervention,
           CASE WHEN p.date_debut IS NULL THEN -1 ELSE COALESCE(dd.id_date, -2) END,
           p.heure_debut,
           CASE WHEN p.intervenant IS NULL THEN -1 ELSE COALESCE(di.id_intervenant, -2) END,
           CASE WHEN p.code_client IS NULL THEN -1 ELSE COALESCE(dc.id_client, -2) END,
           CASE WHEN p.categorie IS NULL THEN -1 ELSE COALESCE(dk.id_categorie, -2) END,
           p.duree_min,
           p.duree_trajet_min,
           p.distance_km,
           p.statut,
           p.facturable,
           p.lieu_cp,
           p.lieu_ville,
           p.retenue,
           p.id_chargement, p.fichier_source, p.feuille_source, p.num_ligne_source
    FROM propre.interventions AS p
    LEFT JOIN dw.dim_date AS dd ON dd.date_jour = p.date_debut
    LEFT JOIN qualite.rattachement AS ri
        ON ri.id_execution = @id_execution AND ri.id_regle = @r_intervenant
       AND ri.id_chargement = p.id_chargement AND ri.num_ligne_source = p.num_ligne_source
    LEFT JOIN propre.intervenants AS ti
        ON ti.id_chargement = ri.id_chargement_reference
       AND ti.num_ligne_source = ri.num_ligne_reference
    LEFT JOIN dw.dim_intervenant AS di
        ON di.matricule = ti.matricule COLLATE Latin1_General_100_BIN2
    LEFT JOIN qualite.rattachement AS rc
        ON rc.id_execution = @id_execution AND rc.id_regle = @r_client
       AND rc.id_chargement = p.id_chargement AND rc.num_ligne_source = p.num_ligne_source
    LEFT JOIN propre.clients AS tc
        ON tc.id_chargement = rc.id_chargement_reference
       AND tc.num_ligne_source = rc.num_ligne_reference
    LEFT JOIN dw.correspondances(@id_execution, N'clients') AS cc
        ON cc.code_doublon = tc.code_client COLLATE Latin1_General_100_BIN2
    LEFT JOIN dw.dim_client AS dc
        ON dc.code_client = COALESCE(cc.code_principal,
                                     tc.code_client COLLATE Latin1_General_100_BIN2)
    LEFT JOIN dw.dim_categorie AS dk
        ON dk.categorie = p.categorie COLLATE Latin1_General_100_BIN2;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'fait_intervention', @lignes, @debut;
END;
GO

/*
  Pièces consommées : une ligne par ligne de propre.pieces_interventions.
  Pièce par le rattachement pieces_interventions.ref_piece vers
  catalogue_pieces, date de sortie, intervention par le rattachement
  pieces_interventions.id_intervention vers interventions (la ligne de
  fait_intervention de même lignage que la ligne rattachée).
*/
CREATE TABLE dw.fait_consommation (
    id_fait_consommation  int             NOT NULL,
    id_consommation       nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    id_fait_intervention  int             NULL,
    lien_intervention     nvarchar(20)    NOT NULL,
    id_date               int             NOT NULL,
    id_piece              int             NOT NULL,
    quantite              decimal(28, 8)  NULL,
    unite                 nvarchar(4000)  NULL,
    retenue               bit             NOT NULL,
    id_chargement         int             NOT NULL,
    fichier_source        nvarchar(260)   NOT NULL,
    feuille_source        nvarchar(128)   NULL,
    num_ligne_source      int             NOT NULL,
    CONSTRAINT pk_fait_consommation PRIMARY KEY (id_fait_consommation),
    CONSTRAINT uq_fait_consommation_lignage UNIQUE (id_chargement, num_ligne_source),
    CONSTRAINT ck_fait_consommation_lien
        CHECK ((lien_intervention = N'rattachée' AND id_fait_intervention IS NOT NULL)
               OR (lien_intervention IN (N'non renseignée', N'introuvable')
                   AND id_fait_intervention IS NULL)),
    CONSTRAINT fk_fait_consommation_intervention
        FOREIGN KEY (id_fait_intervention)
        REFERENCES dw.fait_intervention (id_fait_intervention),
    CONSTRAINT fk_fait_consommation_date
        FOREIGN KEY (id_date) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_consommation_piece
        FOREIGN KEY (id_piece) REFERENCES dw.dim_piece (id_piece)
);
GO

CREATE PROCEDURE dw.construire_fait_consommation
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @r_piece int =
        dw.regle_rattachement(@id_execution, N'pieces_interventions', N'ref_piece',
                              N'catalogue_pieces');
    DECLARE @r_intervention int =
        dw.regle_rattachement(@id_execution, N'pieces_interventions', N'id_intervention',
                              N'interventions');

    DELETE FROM dw.fait_consommation;
    WITH lignes AS (
        SELECT p.*, fi.id_fait_intervention AS intervention_liee,
               CASE WHEN p.ref_piece IS NULL THEN -1 ELSE COALESCE(dp.id_piece, -2) END AS piece,
               CASE WHEN p.date_sortie IS NULL THEN -1 ELSE COALESCE(dd.id_date, -2) END AS jour
        FROM propre.pieces_interventions AS p
        LEFT JOIN dw.dim_date AS dd ON dd.date_jour = p.date_sortie
        LEFT JOIN qualite.rattachement AS rp
            ON rp.id_execution = @id_execution AND rp.id_regle = @r_piece
           AND rp.id_chargement = p.id_chargement AND rp.num_ligne_source = p.num_ligne_source
        LEFT JOIN propre.catalogue_pieces AS tp
            ON tp.id_chargement = rp.id_chargement_reference
           AND tp.num_ligne_source = rp.num_ligne_reference
        LEFT JOIN dw.dim_piece AS dp
            ON dp.ref_piece = tp.ref_piece COLLATE Latin1_General_100_BIN2
        LEFT JOIN qualite.rattachement AS rv
            ON rv.id_execution = @id_execution AND rv.id_regle = @r_intervention
           AND rv.id_chargement = p.id_chargement AND rv.num_ligne_source = p.num_ligne_source
        LEFT JOIN dw.fait_intervention AS fi
            ON fi.id_chargement = rv.id_chargement_reference
           AND fi.num_ligne_source = rv.num_ligne_reference
    )
    INSERT INTO dw.fait_consommation (
        id_fait_consommation, id_consommation, id_fait_intervention, lien_intervention, id_date,
        id_piece, quantite, unite, retenue, id_chargement, fichier_source, feuille_source,
        num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY l.fichier_source, l.feuille_source, l.num_ligne_source),
           l.id_consommation,
           l.intervention_liee,
           CASE WHEN l.intervention_liee IS NOT NULL THEN N'rattachée'
                WHEN l.id_intervention IS NULL THEN N'non renseignée'
                ELSE N'introuvable' END,
           l.jour,
           l.piece,
           l.quantite,
           l.unite,
           l.retenue,
           l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM lignes AS l;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'fait_consommation', @lignes, @debut;
END;
GO

/* Colonnes de propre lues par les faits des documents. */
INSERT INTO dw.contrat_entree (table_propre, colonne, famille) VALUES
    (N'factures_entetes', N'num_facture', N'texte'),
    (N'factures_entetes', N'type_piece', N'texte'),
    (N'factures_entetes', N'date_facture', N'date'),
    (N'factures_entetes', N'code_client', N'texte'),
    (N'factures_entetes', N'date_echeance', N'date'),
    (N'factures_entetes', N'mode_reglement', N'texte'),
    (N'factures_entetes', N'facture_origine', N'texte'),
    (N'factures_lignes', N'num_facture', N'texte'),
    (N'factures_lignes', N'num_ligne', N'décimal'),
    (N'factures_lignes', N'id_intervention', N'texte'),
    (N'factures_lignes', N'ref_piece', N'texte'),
    (N'factures_lignes', N'quantite', N'décimal'),
    (N'factures_lignes', N'unite', N'texte'),
    (N'factures_lignes', N'pu_ht', N'décimal'),
    (N'factures_lignes', N'remise_pct', N'décimal'),
    (N'factures_lignes', N'montant_ht', N'décimal'),
    (N'factures_lignes', N'taux_tva', N'décimal'),
    (N'achats_entetes', N'num_piece_achat', N'texte'),
    (N'achats_entetes', N'ref_facture_fournisseur', N'texte'),
    (N'achats_entetes', N'type_piece', N'texte'),
    (N'achats_entetes', N'code_fournisseur', N'texte'),
    (N'achats_entetes', N'date_facture', N'date'),
    (N'achats_entetes', N'date_echeance', N'date'),
    (N'achats_lignes', N'num_piece_achat', N'texte'),
    (N'achats_lignes', N'num_ligne', N'décimal'),
    (N'achats_lignes', N'ref_piece', N'texte'),
    (N'achats_lignes', N'quantite', N'décimal'),
    (N'achats_lignes', N'unite', N'texte'),
    (N'achats_lignes', N'pu_achat_ht', N'décimal'),
    (N'achats_lignes', N'montant_ht', N'décimal'),
    (N'achats_lignes', N'compte_charge', N'texte');
GO

/* Rattachements lus par les faits des documents. Le client d'une facture et
   le fournisseur d'une pièce d'achat sont rattachés par en-tête : ils se
   comptent par document, pas par ligne du fait, et n'ont pas de colonne à
   vérifier. */
INSERT INTO dw.contrat_rattachement
    (table_source, cle, table_reference, table_fait, colonne_fait, forme) VALUES
    (N'factures_lignes', N'num_facture', N'factures_entetes',
     N'fait_ligne_facture', N'lien_entete', N'lien'),
    (N'factures_entetes', N'code_client', N'clients', NULL, NULL, NULL),
    (N'factures_lignes', N'ref_piece', N'catalogue_pieces',
     N'fait_ligne_facture', N'id_piece', N'membre'),
    (N'factures_lignes', N'id_intervention', N'interventions',
     N'fait_ligne_facture', N'lien_intervention', N'lien'),
    (N'achats_lignes', N'num_piece_achat', N'achats_entetes',
     N'fait_achat', N'lien_entete', N'lien'),
    (N'achats_entetes', N'code_fournisseur', N'fournisseurs', NULL, NULL, NULL),
    (N'achats_lignes', N'ref_piece', N'catalogue_pieces',
     N'fait_achat', N'id_piece', N'membre');
GO

/* Une ligne de document n'est retenue que si son en-tête l'est aussi : ses
   date, client ou fournisseur et type de pièce viennent de l'en-tête. */
INSERT INTO dw.contrat_retenue (table_fait, table_source, cle, table_reference) VALUES
    (N'fait_ligne_facture', N'factures_lignes', N'num_facture', N'factures_entetes'),
    (N'fait_achat', N'achats_lignes', N'num_piece_achat', N'achats_entetes');
GO

/* Mesures des faits des documents. Leurs dates venant de l'en-tête, elles ne
   sont pas déclarées dans dw.contrat_date. */
INSERT INTO dw.contrat_mesure
    (table_fait, colonne_fait, table_propre, colonne_propre, signe) VALUES
    (N'fait_ligne_facture', N'num_ligne', N'factures_lignes', N'num_ligne', 1),
    (N'fait_ligne_facture', N'quantite', N'factures_lignes', N'quantite', 1),
    (N'fait_ligne_facture', N'pu_ht', N'factures_lignes', N'pu_ht', 1),
    (N'fait_ligne_facture', N'remise_pct', N'factures_lignes', N'remise_pct', 1),
    (N'fait_ligne_facture', N'montant_ht', N'factures_lignes', N'montant_ht', 1),
    (N'fait_ligne_facture', N'taux_tva', N'factures_lignes', N'taux_tva', 1),
    (N'fait_achat', N'num_ligne', N'achats_lignes', N'num_ligne', 1),
    (N'fait_achat', N'quantite', N'achats_lignes', N'quantite', 1),
    (N'fait_achat', N'pu_achat_ht', N'achats_lignes', N'pu_achat_ht', 1),
    (N'fait_achat', N'montant_ht', N'achats_lignes', N'montant_ht', 1);
GO

/*
  Lignes de facture : une ligne par ligne de propre.factures_lignes. En-tête
  par le rattachement factures_lignes.num_facture vers factures_entetes, dont
  la ligne donne la date de facture, la date d'échéance, le type de pièce
  (facture ou avoir), le mode de règlement, la facture d'origine d'un avoir et
  le client (rattachement factures_entetes.code_client vers clients). Article
  par égalité du code (aucun référentiel), pièce par le rattachement
  factures_lignes.ref_piece vers catalogue_pieces, intervention par
  factures_lignes.id_intervention vers interventions.
*/
CREATE TABLE dw.fait_ligne_facture (
    id_fait_ligne_facture  int             NOT NULL,
    num_facture            nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    num_ligne              decimal(28, 8)  NULL,
    lien_entete            nvarchar(20)    NOT NULL,
    type_piece             nvarchar(4000)  NULL,
    mode_reglement         nvarchar(4000)  NULL,
    facture_origine        nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    id_date                int             NOT NULL,
    id_date_echeance       int             NOT NULL,
    id_client              int             NOT NULL,
    id_article             int             NOT NULL,
    id_piece               int             NOT NULL,
    id_fait_intervention   int             NULL,
    lien_intervention      nvarchar(20)    NOT NULL,
    quantite               decimal(28, 8)  NULL,
    unite                  nvarchar(4000)  NULL,
    pu_ht                  decimal(28, 8)  NULL,
    remise_pct             decimal(28, 8)  NULL,
    montant_ht             decimal(28, 8)  NULL,
    taux_tva               decimal(28, 8)  NULL,
    retenue                bit             NOT NULL,
    id_chargement          int             NOT NULL,
    fichier_source         nvarchar(260)   NOT NULL,
    feuille_source         nvarchar(128)   NULL,
    num_ligne_source       int             NOT NULL,
    CONSTRAINT pk_fait_ligne_facture PRIMARY KEY (id_fait_ligne_facture),
    CONSTRAINT uq_fait_ligne_facture_lignage UNIQUE (id_chargement, num_ligne_source),
    CONSTRAINT ck_fait_ligne_facture_entete
        CHECK (lien_entete IN (N'rattachée', N'non renseignée', N'introuvable')),
    CONSTRAINT ck_fait_ligne_facture_lien
        CHECK ((lien_intervention = N'rattachée' AND id_fait_intervention IS NOT NULL)
               OR (lien_intervention IN (N'non renseignée', N'introuvable')
                   AND id_fait_intervention IS NULL)),
    CONSTRAINT fk_fait_ligne_facture_intervention
        FOREIGN KEY (id_fait_intervention)
        REFERENCES dw.fait_intervention (id_fait_intervention),
    CONSTRAINT fk_fait_ligne_facture_date
        FOREIGN KEY (id_date) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_ligne_facture_echeance
        FOREIGN KEY (id_date_echeance) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_ligne_facture_client
        FOREIGN KEY (id_client) REFERENCES dw.dim_client (id_client),
    CONSTRAINT fk_fait_ligne_facture_article
        FOREIGN KEY (id_article) REFERENCES dw.dim_article (id_article),
    CONSTRAINT fk_fait_ligne_facture_piece
        FOREIGN KEY (id_piece) REFERENCES dw.dim_piece (id_piece)
);
GO

CREATE PROCEDURE dw.construire_fait_ligne_facture
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @r_entete int =
        dw.regle_rattachement(@id_execution, N'factures_lignes', N'num_facture',
                              N'factures_entetes');
    DECLARE @r_client int =
        dw.regle_rattachement(@id_execution, N'factures_entetes', N'code_client', N'clients');
    DECLARE @r_piece int =
        dw.regle_rattachement(@id_execution, N'factures_lignes', N'ref_piece',
                              N'catalogue_pieces');
    DECLARE @r_intervention int =
        dw.regle_rattachement(@id_execution, N'factures_lignes', N'id_intervention',
                              N'interventions');

    DELETE FROM dw.fait_ligne_facture;
    WITH lignes AS (
        SELECT p.*,
               h.id_chargement AS entete_trouve,
               h.retenue AS entete_retenue,
               CASE WHEN h.id_chargement IS NOT NULL THEN NULL
                    WHEN p.num_facture IS NULL THEN -1 ELSE -2 END AS sans_entete,
               h.type_piece, h.mode_reglement, h.facture_origine,
               h.date_facture, h.date_echeance, h.code_client,
               dd.id_date AS jour, de.id_date AS echeance, dc.id_client AS client,
               da.id_article AS article, dp.id_piece AS piece,
               fi.id_fait_intervention AS intervention_liee
        FROM propre.factures_lignes AS p
        LEFT JOIN qualite.rattachement AS re
            ON re.id_execution = @id_execution AND re.id_regle = @r_entete
           AND re.id_chargement = p.id_chargement AND re.num_ligne_source = p.num_ligne_source
        LEFT JOIN propre.factures_entetes AS h
            ON h.id_chargement = re.id_chargement_reference
           AND h.num_ligne_source = re.num_ligne_reference
        LEFT JOIN dw.dim_date AS dd ON dd.date_jour = h.date_facture
        LEFT JOIN dw.dim_date AS de ON de.date_jour = h.date_echeance
        LEFT JOIN qualite.rattachement AS rc
            ON rc.id_execution = @id_execution AND rc.id_regle = @r_client
           AND rc.id_chargement = h.id_chargement AND rc.num_ligne_source = h.num_ligne_source
        LEFT JOIN propre.clients AS tc
            ON tc.id_chargement = rc.id_chargement_reference
           AND tc.num_ligne_source = rc.num_ligne_reference
        LEFT JOIN dw.correspondances(@id_execution, N'clients') AS cc
            ON cc.code_doublon = tc.code_client COLLATE Latin1_General_100_BIN2
        LEFT JOIN dw.dim_client AS dc
            ON dc.code_client = COALESCE(cc.code_principal,
                                         tc.code_client COLLATE Latin1_General_100_BIN2)
        LEFT JOIN dw.dim_article AS da
            ON da.code_article = p.code_article COLLATE Latin1_General_100_BIN2
        LEFT JOIN qualite.rattachement AS rp
            ON rp.id_execution = @id_execution AND rp.id_regle = @r_piece
           AND rp.id_chargement = p.id_chargement AND rp.num_ligne_source = p.num_ligne_source
        LEFT JOIN propre.catalogue_pieces AS tp
            ON tp.id_chargement = rp.id_chargement_reference
           AND tp.num_ligne_source = rp.num_ligne_reference
        LEFT JOIN dw.dim_piece AS dp
            ON dp.ref_piece = tp.ref_piece COLLATE Latin1_General_100_BIN2
        LEFT JOIN qualite.rattachement AS rv
            ON rv.id_execution = @id_execution AND rv.id_regle = @r_intervention
           AND rv.id_chargement = p.id_chargement AND rv.num_ligne_source = p.num_ligne_source
        LEFT JOIN dw.fait_intervention AS fi
            ON fi.id_chargement = rv.id_chargement_reference
           AND fi.num_ligne_source = rv.num_ligne_reference
    )
    INSERT INTO dw.fait_ligne_facture (
        id_fait_ligne_facture, num_facture, num_ligne, lien_entete, type_piece, mode_reglement,
        facture_origine, id_date, id_date_echeance, id_client, id_article, id_piece,
        id_fait_intervention, lien_intervention, quantite, unite, pu_ht, remise_pct, montant_ht,
        taux_tva, retenue, id_chargement, fichier_source, feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY l.fichier_source, l.feuille_source, l.num_ligne_source),
           l.num_facture,
           l.num_ligne,
           CASE WHEN l.entete_trouve IS NOT NULL THEN N'rattachée'
                WHEN l.num_facture IS NULL THEN N'non renseignée'
                ELSE N'introuvable' END,
           l.type_piece,
           l.mode_reglement,
           l.facture_origine,
           COALESCE(l.sans_entete,
                    CASE WHEN l.date_facture IS NULL THEN -1 ELSE COALESCE(l.jour, -2) END),
           COALESCE(l.sans_entete,
                    CASE WHEN l.date_echeance IS NULL THEN -1 ELSE COALESCE(l.echeance, -2) END),
           COALESCE(l.sans_entete,
                    CASE WHEN l.code_client IS NULL THEN -1 ELSE COALESCE(l.client, -2) END),
           CASE WHEN l.code_article IS NULL THEN -1 ELSE COALESCE(l.article, -2) END,
           CASE WHEN l.ref_piece IS NULL THEN -1 ELSE COALESCE(l.piece, -2) END,
           l.intervention_liee,
           CASE WHEN l.intervention_liee IS NOT NULL THEN N'rattachée'
                WHEN l.id_intervention IS NULL THEN N'non renseignée'
                ELSE N'introuvable' END,
           l.quantite,
           l.unite,
           l.pu_ht,
           l.remise_pct,
           l.montant_ht,
           l.taux_tva,
           CASE WHEN l.retenue = 0 OR l.entete_retenue = 0 THEN 0 ELSE 1 END,
           l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM lignes AS l;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'fait_ligne_facture', @lignes, @debut;
END;
GO

/*
  Lignes d'achat : une ligne par ligne de propre.achats_lignes. En-tête par
  le rattachement achats_lignes.num_piece_achat vers achats_entetes, dont la
  ligne donne la date de facture, la date d'échéance, le type de pièce, la
  référence de la facture du fournisseur et le fournisseur (rattachement
  achats_entetes.code_fournisseur vers fournisseurs). Pièce par le
  rattachement achats_lignes.ref_piece vers catalogue_pieces, compte de
  charge par égalité du code avec les comptes du FEC.
*/
CREATE TABLE dw.fait_achat (
    id_fait_achat            int             NOT NULL,
    num_piece_achat          nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    num_ligne                decimal(28, 8)  NULL,
    lien_entete              nvarchar(20)    NOT NULL,
    type_piece               nvarchar(4000)  NULL,
    ref_facture_fournisseur  nvarchar(4000)  NULL,
    id_date                  int             NOT NULL,
    id_date_echeance         int             NOT NULL,
    id_fournisseur           int             NOT NULL,
    id_piece                 int             NOT NULL,
    id_compte                int             NOT NULL,
    quantite                 decimal(28, 8)  NULL,
    unite                    nvarchar(4000)  NULL,
    pu_achat_ht              decimal(28, 8)  NULL,
    montant_ht               decimal(28, 8)  NULL,
    retenue                  bit             NOT NULL,
    id_chargement            int             NOT NULL,
    fichier_source           nvarchar(260)   NOT NULL,
    feuille_source           nvarchar(128)   NULL,
    num_ligne_source         int             NOT NULL,
    CONSTRAINT pk_fait_achat PRIMARY KEY (id_fait_achat),
    CONSTRAINT uq_fait_achat_lignage UNIQUE (id_chargement, num_ligne_source),
    CONSTRAINT ck_fait_achat_entete
        CHECK (lien_entete IN (N'rattachée', N'non renseignée', N'introuvable')),
    CONSTRAINT fk_fait_achat_date
        FOREIGN KEY (id_date) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_achat_echeance
        FOREIGN KEY (id_date_echeance) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_achat_fournisseur
        FOREIGN KEY (id_fournisseur) REFERENCES dw.dim_fournisseur (id_fournisseur),
    CONSTRAINT fk_fait_achat_piece
        FOREIGN KEY (id_piece) REFERENCES dw.dim_piece (id_piece),
    CONSTRAINT fk_fait_achat_compte
        FOREIGN KEY (id_compte) REFERENCES dw.dim_compte (id_compte)
);
GO

CREATE PROCEDURE dw.construire_fait_achat
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @r_entete int =
        dw.regle_rattachement(@id_execution, N'achats_lignes', N'num_piece_achat',
                              N'achats_entetes');
    DECLARE @r_fournisseur int =
        dw.regle_rattachement(@id_execution, N'achats_entetes', N'code_fournisseur',
                              N'fournisseurs');
    DECLARE @r_piece int =
        dw.regle_rattachement(@id_execution, N'achats_lignes', N'ref_piece',
                              N'catalogue_pieces');

    DELETE FROM dw.fait_achat;
    WITH lignes AS (
        SELECT p.*,
               h.id_chargement AS entete_trouve,
               h.retenue AS entete_retenue,
               CASE WHEN h.id_chargement IS NOT NULL THEN NULL
                    WHEN p.num_piece_achat IS NULL THEN -1 ELSE -2 END AS sans_entete,
               h.type_piece, h.ref_facture_fournisseur, h.date_facture, h.date_echeance,
               h.code_fournisseur,
               dd.id_date AS jour, de.id_date AS echeance, df.id_fournisseur AS fournisseur,
               dp.id_piece AS piece, dk.id_compte AS compte
        FROM propre.achats_lignes AS p
        LEFT JOIN qualite.rattachement AS re
            ON re.id_execution = @id_execution AND re.id_regle = @r_entete
           AND re.id_chargement = p.id_chargement AND re.num_ligne_source = p.num_ligne_source
        LEFT JOIN propre.achats_entetes AS h
            ON h.id_chargement = re.id_chargement_reference
           AND h.num_ligne_source = re.num_ligne_reference
        LEFT JOIN dw.dim_date AS dd ON dd.date_jour = h.date_facture
        LEFT JOIN dw.dim_date AS de ON de.date_jour = h.date_echeance
        LEFT JOIN qualite.rattachement AS rf
            ON rf.id_execution = @id_execution AND rf.id_regle = @r_fournisseur
           AND rf.id_chargement = h.id_chargement AND rf.num_ligne_source = h.num_ligne_source
        LEFT JOIN propre.fournisseurs AS tf
            ON tf.id_chargement = rf.id_chargement_reference
           AND tf.num_ligne_source = rf.num_ligne_reference
        LEFT JOIN dw.correspondances(@id_execution, N'fournisseurs') AS cf
            ON cf.code_doublon = tf.code_fournisseur COLLATE Latin1_General_100_BIN2
        LEFT JOIN dw.dim_fournisseur AS df
            ON df.code_fournisseur = COALESCE(cf.code_principal,
                                              tf.code_fournisseur COLLATE Latin1_General_100_BIN2)
        LEFT JOIN qualite.rattachement AS rp
            ON rp.id_execution = @id_execution AND rp.id_regle = @r_piece
           AND rp.id_chargement = p.id_chargement AND rp.num_ligne_source = p.num_ligne_source
        LEFT JOIN propre.catalogue_pieces AS tp
            ON tp.id_chargement = rp.id_chargement_reference
           AND tp.num_ligne_source = rp.num_ligne_reference
        LEFT JOIN dw.dim_piece AS dp
            ON dp.ref_piece = tp.ref_piece COLLATE Latin1_General_100_BIN2
        LEFT JOIN dw.dim_compte AS dk
            ON dk.compte_num = p.compte_charge COLLATE Latin1_General_100_BIN2
    )
    INSERT INTO dw.fait_achat (
        id_fait_achat, num_piece_achat, num_ligne, lien_entete, type_piece,
        ref_facture_fournisseur, id_date, id_date_echeance, id_fournisseur, id_piece, id_compte,
        quantite, unite, pu_achat_ht, montant_ht, retenue, id_chargement, fichier_source,
        feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY l.fichier_source, l.feuille_source, l.num_ligne_source),
           l.num_piece_achat,
           l.num_ligne,
           CASE WHEN l.entete_trouve IS NOT NULL THEN N'rattachée'
                WHEN l.num_piece_achat IS NULL THEN N'non renseignée'
                ELSE N'introuvable' END,
           l.type_piece,
           l.ref_facture_fournisseur,
           COALESCE(l.sans_entete,
                    CASE WHEN l.date_facture IS NULL THEN -1 ELSE COALESCE(l.jour, -2) END),
           COALESCE(l.sans_entete,
                    CASE WHEN l.date_echeance IS NULL THEN -1 ELSE COALESCE(l.echeance, -2) END),
           COALESCE(l.sans_entete,
                    CASE WHEN l.code_fournisseur IS NULL THEN -1
                         ELSE COALESCE(l.fournisseur, -2) END),
           CASE WHEN l.ref_piece IS NULL THEN -1 ELSE COALESCE(l.piece, -2) END,
           CASE WHEN l.compte_charge IS NULL THEN -1 ELSE COALESCE(l.compte, -2) END,
           l.quantite,
           l.unite,
           l.pu_achat_ht,
           l.montant_ht,
           CASE WHEN l.retenue = 0 OR l.entete_retenue = 0 THEN 0 ELSE 1 END,
           l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM lignes AS l;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'fait_achat', @lignes, @debut;
END;
GO

/* Colonnes de propre lues par le fait des écritures (compte_num et
   compte_lib le sont déjà par dim_compte). */
INSERT INTO dw.contrat_entree (table_propre, colonne, famille) VALUES
    (N'fec', N'journal_code', N'texte'),
    (N'fec', N'ecriture_num', N'texte'),
    (N'fec', N'ecriture_date', N'date'),
    (N'fec', N'comp_aux_num', N'texte'),
    (N'fec', N'piece_ref', N'texte'),
    (N'fec', N'piece_date', N'date'),
    (N'fec', N'debit', N'décimal'),
    (N'fec', N'credit', N'décimal'),
    (N'fec', N'ecriture_let', N'texte');
GO

/* Rattachements lus par le fait des écritures (PieceRef est le nom du
   dictionnaire, piece_ref celui de propre). */
INSERT INTO dw.contrat_rattachement
    (table_source, cle, table_reference, table_fait, colonne_fait, forme) VALUES
    (N'fec', N'PieceRef', N'factures_entetes', N'fait_ecriture', N'num_facture', N'numero'),
    (N'fec', N'PieceRef', N'achats_entetes', N'fait_ecriture', N'num_piece_achat', N'numero');
GO

/* Mesures et dates du fait des écritures : le solde est la somme du débit et
   de l'opposé du crédit. */
INSERT INTO dw.contrat_mesure
    (table_fait, colonne_fait, table_propre, colonne_propre, signe) VALUES
    (N'fait_ecriture', N'debit', N'fec', N'debit', 1),
    (N'fait_ecriture', N'credit', N'fec', N'credit', 1),
    (N'fait_ecriture', N'solde', N'fec', N'debit', 1),
    (N'fait_ecriture', N'solde', N'fec', N'credit', -1);
GO

INSERT INTO dw.contrat_date (table_fait, colonne_fait, table_propre, colonne_propre) VALUES
    (N'fait_ecriture', N'id_date', N'fec', N'ecriture_date'),
    (N'fait_ecriture', N'id_date_piece', N'fec', N'piece_date');
GO

/*
  Écritures : une ligne par ligne de propre.fec. Date d'écriture et date de
  pièce, compte par égalité du code avec dim_compte (construite à partir du
  FEC). solde vaut débit moins crédit, un montant vide comptant pour zéro.
  num_facture et num_piece_achat sont les numéros des en-têtes que désigne la
  référence de pièce (rattachements fec.PieceRef vers factures_entetes et vers
  achats_entetes), NULL sinon : ils mènent aux lignes de fait_ligne_facture et
  de fait_achat. Le libellé du compte auxiliaire, sensible, n'entre pas dans
  dw.
*/
CREATE TABLE dw.fait_ecriture (
    id_fait_ecriture  int             NOT NULL,
    journal_code      nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    ecriture_num      nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    id_date           int             NOT NULL,
    id_date_piece     int             NOT NULL,
    id_compte         int             NOT NULL,
    comp_aux_num      nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    piece_ref         nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    num_facture       nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    num_piece_achat   nvarchar(450)   COLLATE Latin1_General_100_BIN2 NULL,
    ecriture_let      nvarchar(4000)  NULL,
    debit             decimal(28, 8)  NULL,
    credit            decimal(28, 8)  NULL,
    solde             decimal(28, 8)  NOT NULL,
    retenue           bit             NOT NULL,
    id_chargement     int             NOT NULL,
    fichier_source    nvarchar(260)   NOT NULL,
    feuille_source    nvarchar(128)   NULL,
    num_ligne_source  int             NOT NULL,
    CONSTRAINT pk_fait_ecriture PRIMARY KEY (id_fait_ecriture),
    CONSTRAINT uq_fait_ecriture_lignage UNIQUE (id_chargement, num_ligne_source),
    CONSTRAINT fk_fait_ecriture_date
        FOREIGN KEY (id_date) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_ecriture_date_piece
        FOREIGN KEY (id_date_piece) REFERENCES dw.dim_date (id_date),
    CONSTRAINT fk_fait_ecriture_compte
        FOREIGN KEY (id_compte) REFERENCES dw.dim_compte (id_compte)
);
GO

CREATE PROCEDURE dw.construire_fait_ecriture
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    DECLARE @r_facture int =
        dw.regle_rattachement(@id_execution, N'fec', N'PieceRef', N'factures_entetes');
    DECLARE @r_achat int =
        dw.regle_rattachement(@id_execution, N'fec', N'PieceRef', N'achats_entetes');

    DELETE FROM dw.fait_ecriture;
    INSERT INTO dw.fait_ecriture (
        id_fait_ecriture, journal_code, ecriture_num, id_date, id_date_piece, id_compte,
        comp_aux_num, piece_ref, num_facture, num_piece_achat, ecriture_let, debit, credit,
        solde, retenue, id_chargement, fichier_source, feuille_source, num_ligne_source)
    SELECT ROW_NUMBER() OVER (ORDER BY p.fichier_source, p.feuille_source, p.num_ligne_source),
           p.journal_code,
           p.ecriture_num,
           CASE WHEN p.ecriture_date IS NULL THEN -1 ELSE COALESCE(dd.id_date, -2) END,
           CASE WHEN p.piece_date IS NULL THEN -1 ELSE COALESCE(dp.id_date, -2) END,
           CASE WHEN p.compte_num IS NULL THEN -1 ELSE COALESCE(dk.id_compte, -2) END,
           p.comp_aux_num,
           p.piece_ref,
           hf.num_facture,
           ha.num_piece_achat,
           p.ecriture_let,
           p.debit,
           p.credit,
           COALESCE(p.debit, 0) - COALESCE(p.credit, 0),
           p.retenue,
           p.id_chargement, p.fichier_source, p.feuille_source, p.num_ligne_source
    FROM propre.fec AS p
    LEFT JOIN dw.dim_date AS dd ON dd.date_jour = p.ecriture_date
    LEFT JOIN dw.dim_date AS dp ON dp.date_jour = p.piece_date
    LEFT JOIN dw.dim_compte AS dk
        ON dk.compte_num = p.compte_num COLLATE Latin1_General_100_BIN2
    LEFT JOIN qualite.rattachement AS rf
        ON rf.id_execution = @id_execution AND rf.id_regle = @r_facture
       AND rf.id_chargement = p.id_chargement AND rf.num_ligne_source = p.num_ligne_source
    LEFT JOIN propre.factures_entetes AS hf
        ON hf.id_chargement = rf.id_chargement_reference
       AND hf.num_ligne_source = rf.num_ligne_reference
    LEFT JOIN qualite.rattachement AS ra
        ON ra.id_execution = @id_execution AND ra.id_regle = @r_achat
       AND ra.id_chargement = p.id_chargement AND ra.num_ligne_source = p.num_ligne_source
    LEFT JOIN propre.achats_entetes AS ha
        ON ha.id_chargement = ra.id_chargement_reference
       AND ha.num_ligne_source = ra.num_ligne_reference;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'fait_ecriture', @lignes, @debut;
END;
GO
