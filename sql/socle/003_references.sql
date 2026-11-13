/*
  Socle, script 003 : tables de référence issues de la configuration.

  Ces tables reprennent, pour chaque exécution, des données que les fichiers
  du client ne portent pas mais que la base doit connaître pour construire
  ses dimensions (étape 7.3) : les jours fériés de config/gestion.yaml et les
  valeurs admises des listes fermées du dictionnaire revu. Le traitement
  Python les écrit dans la même transaction que les autres tables de qualite,
  à partir des fichiers qu'il a lus : aucune règle n'est écrite deux fois.

  Historique : comme les autres tables de qualite, chaque ligne porte
  l'exécution qui l'a produite; rejouer la même periode_fin remplace
  l'exécution précédente de cette période.
*/

/*
  Un jour férié déclaré sous la clé jours_feries de config/gestion.yaml.
  Une année déclarée sans jour férié (liste vide) donne une ligne sans jour,
  pour la distinguer d'une année non déclarée : une seule par année, la
  contrainte d'unicité n'admettant qu'un NULL par couple exécution, année.
*/
CREATE TABLE qualite.jour_ferie (
    id_execution  int       NOT NULL,
    annee         smallint  NOT NULL,
    jour          date      NULL,
    CONSTRAINT uq_jour_ferie UNIQUE (id_execution, annee, jour),
    CONSTRAINT ck_jour_ferie_annee CHECK (jour IS NULL OR YEAR(jour) = annee),
    CONSTRAINT fk_jour_ferie_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO

/*
  Une valeur admise d'une colonne dont la règle valeurs en vigueur est une
  liste fermée : valide, documentée, ou proposée et pas encore revue
  (statut observé). Les valeurs invalides ou à arbitrer ne sont pas reprises,
  ni les colonnes sensibles. table_source et colonne_source sont les noms du
  dictionnaire, comme dans correspondance_colonne. rang suit l'ordre de la
  liste du dictionnaire parmi les valeurs admises.
*/
CREATE TABLE qualite.valeur_liste (
    id_execution    int             NOT NULL,
    table_source    nvarchar(128)   NOT NULL,
    colonne_source  nvarchar(128)   NOT NULL,
    rang            int             NOT NULL,
    valeur          nvarchar(4000)  NOT NULL,
    statut          nvarchar(20)    NOT NULL,
    CONSTRAINT pk_valeur_liste
        PRIMARY KEY (id_execution, table_source, colonne_source, rang),
    CONSTRAINT ck_valeur_liste_rang CHECK (rang >= 1),
    CONSTRAINT ck_valeur_liste_statut
        CHECK (statut IN (N'observé', N'valide', N'documenté')),
    CONSTRAINT fk_valeur_liste_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO
