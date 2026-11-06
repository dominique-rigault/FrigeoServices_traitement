/*
  Socle, script 003 : structure des tables de données, dans le schéma qualite.

  Les tables des schémas chargement et propre ne sont pas créées par un script
  numéroté : le traitement Python les génère à partir du dictionnaire revu
  (module frigeo.structure_base), puis les supprime et les recrée à chaque
  exécution. Elles reflètent donc toujours la dernière exécution. Une vue
  construite sur elles ne doit pas être créée WITH SCHEMABINDING, ce qui
  empêcherait leur suppression.

  correspondance_colonne garde, pour chaque exécution, le nom en base, la nature
  et le type de chaque colonne de données. Elle relie qualite.anomalie.champ
  (nom source, CompteNum) à la colonne de propre (compte_num).

  decision reçoit empreinte_valeur_retenue : pour une colonne sensible,
  valeur_retenue reste vide et seule son empreinte est renseignée (hachage à clé
  secrète, avec la clé du journal du nettoyage).
*/

/* Une colonne de données d'une table générée, dans une exécution. */
CREATE TABLE qualite.correspondance_colonne (
    id_execution    int            NOT NULL,
    table_source    nvarchar(128)  NOT NULL,
    colonne_source  nvarchar(128)  NOT NULL,
    table_base      nvarchar(128)  NOT NULL,
    colonne_base    nvarchar(128)  NOT NULL,
    ordre           int            NOT NULL,
    nature          nvarchar(100)  NULL,
    famille         nvarchar(20)   NOT NULL,
    type_propre     nvarchar(50)   NOT NULL,
    sensible        bit            NOT NULL,
    CONSTRAINT pk_correspondance_colonne
        PRIMARY KEY (id_execution, table_source, colonne_source),
    CONSTRAINT uq_correspondance_colonne_base
        UNIQUE (id_execution, table_base, colonne_base),
    CONSTRAINT fk_correspondance_colonne_execution
        FOREIGN KEY (id_execution) REFERENCES qualite.execution (id_execution)
);
GO

ALTER TABLE qualite.decision
    ADD empreinte_valeur_retenue nvarchar(128) NULL;
GO
