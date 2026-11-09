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

  Lien vers une autre ligne de fait (une consommation vers son
  intervention) : la clé de la ligne de fait que désigne le rattachement,
  NULL sinon, avec lien_intervention qui dit pourquoi (rattachée, non
  renseignée, introuvable).

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

/* Rattachements lus par les faits (noms du dictionnaire). */
INSERT INTO dw.contrat_rattachement (table_source, cle, table_reference) VALUES
    (N'interventions', N'intervenant', N'intervenants'),
    (N'interventions', N'code_client', N'clients'),
    (N'pieces_interventions', N'ref_piece', N'catalogue_pieces'),
    (N'pieces_interventions', N'id_intervention', N'interventions');
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
        lieu_ville, id_chargement, fichier_source, feuille_source, num_ligne_source)
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
    LEFT JOIN dw.dim_client AS dc
        ON dc.code_client = tc.code_client COLLATE Latin1_General_100_BIN2
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
        id_piece, quantite, unite, id_chargement, fichier_source, feuille_source,
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
           l.id_chargement, l.fichier_source, l.feuille_source, l.num_ligne_source
    FROM lignes AS l;

    DECLARE @lignes int = @@ROWCOUNT;
    EXEC dw.inscrire_etape @id_execution, N'fait_consommation', @lignes, @debut;
END;
GO
