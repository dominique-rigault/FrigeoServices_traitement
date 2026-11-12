/*
  Socle, script 006 : cadre des vues pbi.

  Power BI n'importe que les vues du schéma pbi, telles quelles : leurs noms
  et leurs colonnes forment l'interface convenue avec le rapport. Tant
  qu'ils ne changent pas, le rapport fonctionne. Chaque vue et chacune de
  ses colonnes sont donc déclarées ici par le script qui la crée, et la
  vérification compare cette déclaration à la base dans les deux sens : une
  colonne disparue ou renommée sort en non conforme avant que le rapport ne
  casse.

  Les vues métier appartiennent au pack (sql/packs/<pack>/005_vues.sql),
  les vues génériques du tableau qualité au socle. Aucune vue n'est
  SCHEMABINDING : les tables de dw ne sont pas supprimées à la
  reconstruction, seulement vidées et remplies.
*/

/* Une vue pbi et l'objet dont elle compte les lignes (schéma.objet). */
CREATE TABLE dw.source_vue (
    vue     nvarchar(128)  NOT NULL,
    source  nvarchar(260)  NOT NULL,
    CONSTRAINT pk_source_vue PRIMARY KEY (vue)
);
GO

/* Les colonnes convenues d'une vue pbi : le contrat avec le rapport. */
CREATE TABLE dw.contrat_vue (
    vue      nvarchar(128)  NOT NULL,
    colonne  nvarchar(128)  NOT NULL,
    CONSTRAINT pk_contrat_vue PRIMARY KEY (vue, colonne),
    CONSTRAINT fk_contrat_vue_source
        FOREIGN KEY (vue) REFERENCES dw.source_vue (vue)
);
GO
