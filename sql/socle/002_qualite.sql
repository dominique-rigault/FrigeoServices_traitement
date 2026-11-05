/*
  Socle, script 002 : tables du schéma qualite.

  Ces tables reprennent les fichiers produits par le traitement Python
  (anomalies, non évaluables, bilans, journal et bilan du nettoyage,
  décisions du métier), sous les noms de colonnes de ces fichiers, sauf
  « table », mot réservé de T-SQL, devenue table_source.

  Historique : chaque ligne porte l'exécution qui l'a produite. Une exécution
  couvre toute la période de 2025 à periode_fin; rejouer la même periode_fin
  remplace l'exécution précédente de cette période, une nouvelle période
  s'ajoute.

  Lignage : les tables au grain d'une ligne source portent fichier_source,
  feuille_source, num_ligne_source et id_chargement. id_chargement est
  facultatif, certains écarts n'ayant pas de ligne source (écart de totaux
  porté par une période).

  Aucune suppression en cascade : le remplacement d'une exécution supprime
  explicitement les lignes filles, puis l'exécution, dans une transaction.
*/

/* Une exécution du traitement. */
CREATE TABLE qualite.execution (
    id_execution        int IDENTITY(1, 1) NOT NULL,
    periode_fin         char(7)            NOT NULL,
    debut               datetime2(0)       NOT NULL
        CONSTRAINT df_execution_debut DEFAULT SYSUTCDATETIME(),
    fin                 datetime2(0)       NULL,
    version_traitement  nvarchar(100)      NULL,
    statut              nvarchar(20)       NOT NULL
        CONSTRAINT df_execution_statut DEFAULT N'en cours',
    detail              nvarchar(4000)     NULL,
    CONSTRAINT pk_execution PRIMARY KEY (id_execution),
    CONSTRAINT ck_execution_periode
        CHECK (periode_fin LIKE '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    CONSTRAINT ck_execution_statut
        CHECK (statut IN (N'en cours', N'réussie', N'échouée'))
);
GO

/* Un fichier (ou une feuille de classeur) chargé dans une exécution. */
CREATE TABLE qualite.journal_chargement (
    id_chargement     int IDENTITY(1, 1) NOT NULL,
    id_execution      int                NOT NULL,
    fichier_source    nvarchar(260)      NOT NULL,
    feuille_source    nvarchar(128)      NULL,
    periode_export    nvarchar(20)       NULL,
    empreinte_sha256  char(64)           NOT NULL,
    nb_lignes         int                NOT NULL,
    date_chargement   datetime2(0)       NOT NULL
        CONSTRAINT df_journal_chargement_date DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_journal_chargement PRIMARY KEY (id_chargement),
    CONSTRAINT fk_journal_chargement_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution),
    CONSTRAINT uq_journal_chargement_fichier
        UNIQUE (id_execution, fichier_source, feuille_source)
);
GO

/*
  Une anomalie, dans un état (brut ou nettoyé). valeur reste vide pour les
  colonnes sensibles, comme dans les fichiers du traitement. decision_metier
  n'est renseignée qu'après nettoyage.
*/
CREATE TABLE qualite.anomalie (
    id_execution      int             NOT NULL,
    etat              nvarchar(10)    NOT NULL,
    id_anomalie       nvarchar(32)    NOT NULL,
    id_chargement     int             NULL,
    etape             nvarchar(50)    NOT NULL,
    controle          nvarchar(400)   NOT NULL,
    table_source      nvarchar(128)   NULL,
    fichier_source    nvarchar(260)   NULL,
    feuille_source    nvarchar(128)   NULL,
    num_ligne_source  int             NULL,
    periode_export    nvarchar(20)    NULL,
    cle               nvarchar(1000)  NULL,
    champ             nvarchar(128)   NULL,
    valeur            nvarchar(4000)  NULL,
    regle             nvarchar(400)   NULL,
    constat           nvarchar(4000)  NULL,
    issue             nvarchar(50)    NULL,
    statut_regle      nvarchar(50)    NULL,
    detail            nvarchar(4000)  NULL,
    proposition       nvarchar(4000)  NULL,
    gravite           nvarchar(50)    NULL,
    indicateurs       nvarchar(400)   NULL,
    decision_metier   nvarchar(50)    NULL,
    CONSTRAINT pk_anomalie PRIMARY KEY (id_execution, etat, id_anomalie),
    CONSTRAINT ck_anomalie_etat CHECK (etat IN (N'brut', N'nettoyé')),
    CONSTRAINT fk_anomalie_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution),
    CONSTRAINT fk_anomalie_chargement
        FOREIGN KEY (id_chargement) REFERENCES qualite.journal_chargement (id_chargement)
);
GO

/*
  Une ligne qu'un contrôle ne peut pas juger, dans un état. ref est le
  préfixe du libellé du contrôle : numéro de la règle de gestion (R01 à R22)
  ou famille de la règle (decoupage, existence, calcul...).
*/
CREATE TABLE qualite.non_evaluable (
    id_non_evaluable  int IDENTITY(1, 1) NOT NULL,
    id_execution      int             NOT NULL,
    etat              nvarchar(10)    NOT NULL,
    id_chargement     int             NULL,
    etape             nvarchar(50)    NOT NULL,
    controle          nvarchar(400)   NOT NULL,
    ref               nvarchar(50)    NULL,
    table_source      nvarchar(128)   NULL,
    fichier_source    nvarchar(260)   NULL,
    feuille_source    nvarchar(128)   NULL,
    num_ligne_source  int             NULL,
    periode_export    nvarchar(20)    NULL,
    cle               nvarchar(1000)  NULL,
    CONSTRAINT pk_non_evaluable PRIMARY KEY (id_non_evaluable),
    CONSTRAINT ck_non_evaluable_etat CHECK (etat IN (N'brut', N'nettoyé')),
    CONSTRAINT fk_non_evaluable_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution),
    CONSTRAINT fk_non_evaluable_chargement
        FOREIGN KEY (id_chargement) REFERENCES qualite.journal_chargement (id_chargement)
);
GO
CREATE INDEX ix_non_evaluable_execution ON qualite.non_evaluable (id_execution);
GO

/* Un contrôle, dans un état : lignes contrôlées, anomalies, taux. */
CREATE TABLE qualite.bilan_controle (
    id_bilan_controle  int IDENTITY(1, 1) NOT NULL,
    id_execution       int             NOT NULL,
    etat               nvarchar(10)    NOT NULL,
    etape              nvarchar(50)    NOT NULL,
    controle           nvarchar(400)   NOT NULL,
    table_source       nvarchar(128)   NULL,
    champ              nvarchar(128)   NULL,
    regle              nvarchar(400)   NULL,
    controlees         int             NULL,
    anomalies          int             NULL,
    a_arbitrer         int             NULL,
    informations       int             NULL,
    taux               decimal(9, 4)   NULL,
    lignes_distinctes  int             NULL,
    gravite            nvarchar(50)    NULL,
    indicateurs        nvarchar(400)   NULL,
    CONSTRAINT pk_bilan_controle PRIMARY KEY (id_bilan_controle),
    CONSTRAINT ck_bilan_controle_etat CHECK (etat IN (N'brut', N'nettoyé')),
    CONSTRAINT fk_bilan_controle_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO
CREATE INDEX ix_bilan_controle_execution ON qualite.bilan_controle (id_execution);
GO

/*
  Une cellule modifiée ou une ligne retirée par le nettoyage. Pour une
  colonne sensible, les valeurs restent vides et seules les empreintes
  (hachage à clé secrète) sont renseignées.
*/
CREATE TABLE qualite.journal_nettoyage (
    id_journal_nettoyage  int IDENTITY(1, 1) NOT NULL,
    id_execution          int             NOT NULL,
    id_chargement         int             NULL,
    regle_nettoyage       nvarchar(400)   NOT NULL,
    table_source          nvarchar(128)   NULL,
    fichier_source        nvarchar(260)   NULL,
    feuille_source        nvarchar(128)   NULL,
    num_ligne_source      int             NULL,
    periode_export        nvarchar(20)    NULL,
    cle                   nvarchar(1000)  NULL,
    colonne               nvarchar(128)   NULL,
    action                nvarchar(50)    NULL,
    source                nvarchar(260)   NULL,
    valeur_avant          nvarchar(4000)  NULL,
    valeur_apres          nvarchar(4000)  NULL,
    empreinte_avant       nvarchar(128)   NULL,
    empreinte_apres       nvarchar(128)   NULL,
    detail                nvarchar(4000)  NULL,
    CONSTRAINT pk_journal_nettoyage PRIMARY KEY (id_journal_nettoyage),
    CONSTRAINT fk_journal_nettoyage_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution),
    CONSTRAINT fk_journal_nettoyage_chargement
        FOREIGN KEY (id_chargement) REFERENCES qualite.journal_chargement (id_chargement)
);
GO
CREATE INDEX ix_journal_nettoyage_execution ON qualite.journal_nettoyage (id_execution);
GO

/* Une règle de nettoyage : cellules visées, corrigées, non corrigées. */
CREATE TABLE qualite.bilan_nettoyage (
    id_bilan_nettoyage  int IDENTITY(1, 1) NOT NULL,
    id_execution        int             NOT NULL,
    regle_nettoyage     nvarchar(400)   NOT NULL,
    table_source        nvarchar(128)   NULL,
    colonne             nvarchar(128)   NULL,
    visees              int             NULL,
    corrigees           int             NULL,
    non_corrigees       int             NULL,
    raisons             nvarchar(4000)  NULL,
    CONSTRAINT pk_bilan_nettoyage PRIMARY KEY (id_bilan_nettoyage),
    CONSTRAINT fk_bilan_nettoyage_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO
CREATE INDEX ix_bilan_nettoyage_execution ON qualite.bilan_nettoyage (id_execution);
GO

/*
  Une décision du métier, telle qu'enregistrée au moment de l'exécution.
  id_decision est l'id_anomalie de l'écart décidé. decide_le est l'heure
  locale du poste où le classeur d'arbitrage a été importé, pas l'heure UTC.
*/
CREATE TABLE qualite.decision (
    id_execution      int             NOT NULL,
    id_decision       nvarchar(32)    NOT NULL,
    sorte             nvarchar(50)    NOT NULL,
    table_source      nvarchar(128)   NULL,
    fichier_source    nvarchar(260)   NULL,
    feuille_source    nvarchar(128)   NULL,
    num_ligne_source  int             NULL,
    champ             nvarchar(128)   NULL,
    constat           nvarchar(4000)  NULL,
    empreinte         nvarchar(128)   NULL,
    decision          nvarchar(50)    NOT NULL,
    valeur_retenue    nvarchar(4000)  NULL,
    nature            nvarchar(100)   NULL,
    commentaire       nvarchar(4000)  NULL,
    decide_le         datetime2(0)    NULL,
    classeur          nvarchar(260)   NULL,
    CONSTRAINT pk_decision PRIMARY KEY (id_execution, id_decision),
    CONSTRAINT fk_decision_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO

/*
  Un code en doublon et le code principal retenu (clients, fournisseurs).
  Table encore vide : la source de ces correspondances sera arrêtée avec
  le dédoublonnage des dimensions (étape 7.3).
*/
CREATE TABLE qualite.correspondance_cle (
    id_execution    int            NOT NULL,
    table_source    nvarchar(128)  NOT NULL,
    code_doublon    nvarchar(100)  NOT NULL,
    code_principal  nvarchar(100)  NOT NULL,
    origine         nvarchar(260)  NULL,
    CONSTRAINT pk_correspondance_cle
        PRIMARY KEY (id_execution, table_source, code_doublon),
    CONSTRAINT fk_correspondance_cle_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO