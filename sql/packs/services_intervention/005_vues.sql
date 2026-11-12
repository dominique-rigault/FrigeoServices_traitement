/*
  Pack services_intervention, script 005 : vues pbi des dimensions.

  Une vue par dimension du modèle, en noms métier en clair : Power BI les
  importe telles quelles, sans filtre, sans renommage, sans colonne
  calculée. Chaque vue et ses colonnes sont déclarées dans dw.source_vue et
  dw.contrat_vue (socle, script 006) : c'est le contrat avec le rapport, que
  la vérification compare à la base dans les deux sens.

  Exposition décidée à la sous-étape 7.6 : les membres spéciaux -1 et -2
  restent (les faits les citent); les colonnes internes (lignage,
  lignes_source, codes_en_doublon, statut des valeurs de liste) et les
  dates des référentiels (entrée, sortie, création, fin de relation) ne
  sortent pas; aucune donnée personnelle au-delà du nom, du prénom et du
  poste de l'intervenant, nécessaires au pilotage. Les colonnes
  [Intervenant], [Client] et [Fournisseur] donnent un libellé d'affichage
  (nom complet ou raison sociale, sinon le code), calculé ici plutôt que
  dans le rapport.
*/

CREATE VIEW pbi.[Calendrier] AS
SELECT id_date AS [Clé date],
       date_jour AS [Date],
       libelle AS [Libellé],
       annee AS [Année],
       trimestre AS [Trimestre],
       mois AS [Mois],
       libelle_mois AS [Nom du mois],
       annee_mois AS [Année-mois],
       jour_semaine AS [N° de jour de semaine],
       libelle_jour AS [Nom du jour],
       feries_declares AS [Jours fériés déclarés],
       ferie AS [Férié],
       ouvre AS [Ouvré]
FROM dw.dim_date;
GO

CREATE VIEW pbi.[Catégories d'intervention] AS
SELECT id_categorie AS [Clé catégorie],
       categorie AS [Catégorie]
FROM dw.dim_categorie;
GO

CREATE VIEW pbi.[Articles facturés] AS
SELECT id_article AS [Clé article],
       code_article AS [Code article],
       libelle AS [Libellé]
FROM dw.dim_article;
GO

CREATE VIEW pbi.[Pièces] AS
SELECT id_piece AS [Clé pièce],
       ref_piece AS [Référence pièce],
       libelle AS [Libellé],
       famille AS [Famille],
       unite AS [Unité],
       code_fournisseur_principal AS [Code du fournisseur principal]
FROM dw.dim_piece;
GO

CREATE VIEW pbi.[Comptes] AS
SELECT id_compte AS [Clé compte],
       compte_num AS [N° de compte],
       compte_lib AS [Libellé du compte],
       classe AS [Classe]
FROM dw.dim_compte;
GO

CREATE VIEW pbi.[Intervenants] AS
SELECT id_intervenant AS [Clé intervenant],
       matricule AS [Matricule],
       COALESCE(NULLIF(TRIM(CONCAT(prenom, N' ', nom)), N''),
                matricule COLLATE DATABASE_DEFAULT) AS [Intervenant],
       nom AS [Nom],
       prenom AS [Prénom],
       poste AS [Poste],
       type_contrat AS [Type de contrat],
       secteur AS [Secteur]
FROM dw.dim_intervenant;
GO

CREATE VIEW pbi.[Clients] AS
SELECT id_client AS [Clé client],
       code_client AS [Code client],
       COALESCE(NULLIF(raison_sociale, N''),
                code_client COLLATE DATABASE_DEFAULT) AS [Client],
       raison_sociale AS [Raison sociale],
       type_commerce AS [Type de commerce],
       cp AS [Code postal],
       ville AS [Ville],
       contrat_maintenance AS [Contrat de maintenance],
       statut AS [Statut]
FROM dw.dim_client;
GO

CREATE VIEW pbi.[Fournisseurs] AS
SELECT id_fournisseur AS [Clé fournisseur],
       code_fournisseur AS [Code fournisseur],
       COALESCE(NULLIF(raison_sociale, N''),
                code_fournisseur COLLATE DATABASE_DEFAULT) AS [Fournisseur],
       raison_sociale AS [Raison sociale],
       categorie AS [Catégorie],
       cp AS [Code postal],
       ville AS [Ville],
       delai_paiement AS [Délai de paiement],
       statut AS [Statut]
FROM dw.dim_fournisseur;
GO

/* Déclaration des vues : le contrat avec le rapport. */
INSERT INTO dw.source_vue (vue, source) VALUES    (N'Calendrier', N'dw.dim_date'),
    (N'Catégories d''intervention', N'dw.dim_categorie'),
    (N'Articles facturés', N'dw.dim_article'),
    (N'Pièces', N'dw.dim_piece'),
    (N'Comptes', N'dw.dim_compte'),
    (N'Intervenants', N'dw.dim_intervenant'),
    (N'Clients', N'dw.dim_client'),
    (N'Fournisseurs', N'dw.dim_fournisseur');
GO

INSERT INTO dw.contrat_vue (vue, colonne) VALUES
    (N'Calendrier', N'Clé date'),
    (N'Calendrier', N'Date'),
    (N'Calendrier', N'Libellé'),
    (N'Calendrier', N'Année'),
    (N'Calendrier', N'Trimestre'),
    (N'Calendrier', N'Mois'),
    (N'Calendrier', N'Nom du mois'),
    (N'Calendrier', N'Année-mois'),
    (N'Calendrier', N'N° de jour de semaine'),
    (N'Calendrier', N'Nom du jour'),
    (N'Calendrier', N'Jours fériés déclarés'),
    (N'Calendrier', N'Férié'),
    (N'Calendrier', N'Ouvré'),
    (N'Catégories d''intervention', N'Clé catégorie'),
    (N'Catégories d''intervention', N'Catégorie'),
    (N'Articles facturés', N'Clé article'),
    (N'Articles facturés', N'Code article'),
    (N'Articles facturés', N'Libellé'),
    (N'Pièces', N'Clé pièce'),
    (N'Pièces', N'Référence pièce'),
    (N'Pièces', N'Libellé'),
    (N'Pièces', N'Famille'),
    (N'Pièces', N'Unité'),
    (N'Pièces', N'Code du fournisseur principal'),
    (N'Comptes', N'Clé compte'),
    (N'Comptes', N'N° de compte'),
    (N'Comptes', N'Libellé du compte'),
    (N'Comptes', N'Classe'),
    (N'Intervenants', N'Clé intervenant'),
    (N'Intervenants', N'Matricule'),
    (N'Intervenants', N'Intervenant'),
    (N'Intervenants', N'Nom'),
    (N'Intervenants', N'Prénom'),
    (N'Intervenants', N'Poste'),
    (N'Intervenants', N'Type de contrat'),
    (N'Intervenants', N'Secteur'),
    (N'Clients', N'Clé client'),
    (N'Clients', N'Code client'),
    (N'Clients', N'Client'),
    (N'Clients', N'Raison sociale'),
    (N'Clients', N'Type de commerce'),
    (N'Clients', N'Code postal'),
    (N'Clients', N'Ville'),
    (N'Clients', N'Contrat de maintenance'),
    (N'Clients', N'Statut'),
    (N'Fournisseurs', N'Clé fournisseur'),
    (N'Fournisseurs', N'Code fournisseur'),
    (N'Fournisseurs', N'Fournisseur'),
    (N'Fournisseurs', N'Raison sociale'),
    (N'Fournisseurs', N'Catégorie'),
    (N'Fournisseurs', N'Code postal'),
    (N'Fournisseurs', N'Ville'),
    (N'Fournisseurs', N'Délai de paiement'),
    (N'Fournisseurs', N'Statut');
GO
