/*
  Socle, script 004 : rattachement des lignes aux référentiels.

  Une ligne de fait cite un référentiel par une clé écrite telle que saisie
  (le nom de l'intervenant, le code du client). Les règles de gestion de
  config/gestion.yaml savent rapprocher ces clés de leur référentiel, avec une
  comparaison déclarée (telle quelle, après normalisation, mots dans le
  désordre) et parfois une date qui doit tomber dans une période. Le
  traitement Python applique ces règles et écrit ici, pour chaque ligne, la
  ligne du référentiel qu'elle cite (module frigeo.rattachement) : les
  procédures du pack s'en servent pour relier chaque fait au bon membre de
  dimension, sans réécrire la comparaison des clés en SQL.

  Aucune valeur du client n'est écrite : une ligne est désignée par son
  lignage, id_chargement (le fichier et la feuille) et num_ligne_source,
  comme dans les tables générées de propre. Une clé vide ou absente du
  référentiel n'a pas de ligne.

  Historique : comme les autres tables de qualite, chaque ligne porte
  l'exécution qui l'a produite; rejouer la même periode_fin remplace
  l'exécution précédente de cette période.
*/

/*
  Un rattachement : la clé d'une table vers la clé d'un référentiel, selon une
  comparaison, avec la colonne de date et les bornes de période d'une règle
  date_dans_periode_reference s'il y en a une. id_regle numérote les
  rattachements d'une exécution à partir de 1, dans l'ordre des règles de
  config/gestion.yaml. Noms de tables et de colonnes du dictionnaire (comme dans
  correspondance_colonne), colonnes d'une clé reliées par « , ». refs donne
  les références des règles de gestion reprises (deux règles de même clé et
  de même référentiel ne font qu'un rattachement).
*/
CREATE TABLE qualite.regle_rattachement (
    id_execution     int             NOT NULL,
    id_regle         int             NOT NULL,
    table_source     nvarchar(128)   NOT NULL,
    cle              nvarchar(1000)  NOT NULL,
    table_reference  nvarchar(128)   NOT NULL,
    cle_reference    nvarchar(1000)  NOT NULL,
    comparaison      nvarchar(50)    NOT NULL,
    colonne_date     nvarchar(128)   NULL,
    debut            nvarchar(128)   NULL,
    fin              nvarchar(128)   NULL,
    refs             nvarchar(1000)  NOT NULL,
    CONSTRAINT pk_regle_rattachement PRIMARY KEY (id_execution, id_regle),
    CONSTRAINT ck_regle_rattachement_id CHECK (id_regle >= 1),
    CONSTRAINT ck_regle_rattachement_comparaison
        CHECK (comparaison IN (N'telle quelle', N'après normalisation',
                               N'mots dans le désordre')),
    CONSTRAINT ck_regle_rattachement_date
        CHECK ((colonne_date IS NULL AND debut IS NULL AND fin IS NULL)
               OR (colonne_date IS NOT NULL AND debut IS NOT NULL)),
    CONSTRAINT fk_regle_rattachement_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO

/*
  Une ligne rattachée : la ligne source (id_chargement, num_ligne_source) et
  la ligne du référentiel qu'elle cite (id_chargement_reference,
  num_ligne_reference). candidates compte les lignes du référentiel qui
  portaient la clé; quand il y en a plusieurs, choix_par_date dit si la ligne
  retenue est la seule dont la période contient la date de la ligne source,
  sinon c'est la première dans l'ordre du lignage.
*/
CREATE TABLE qualite.rattachement (
    id_execution             int  NOT NULL,
    id_regle                 int  NOT NULL,
    id_chargement            int  NOT NULL,
    num_ligne_source         int  NOT NULL,
    id_chargement_reference  int  NOT NULL,
    num_ligne_reference      int  NOT NULL,
    candidates               int  NOT NULL,
    choix_par_date           bit  NOT NULL,
    CONSTRAINT pk_rattachement
        PRIMARY KEY (id_execution, id_regle, id_chargement, num_ligne_source),
    CONSTRAINT ck_rattachement_candidates CHECK (candidates >= 1),
    CONSTRAINT ck_rattachement_choix CHECK (choix_par_date = 0 OR candidates >= 2),
    CONSTRAINT fk_rattachement_regle
        FOREIGN KEY (id_execution, id_regle)
        REFERENCES qualite.regle_rattachement (id_execution, id_regle),
    CONSTRAINT fk_rattachement_chargement
        FOREIGN KEY (id_chargement) REFERENCES qualite.journal_chargement (id_chargement),
    CONSTRAINT fk_rattachement_chargement_reference
        FOREIGN KEY (id_chargement_reference)
        REFERENCES qualite.journal_chargement (id_chargement)
);
GO
