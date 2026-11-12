/*
  Pack services_intervention, script 005 : vues pbi.

  Une vue par dimension et par fait du modèle, plus [Chantiers] et [Stock
  mensuel des pièces], en noms métier en clair : Power BI les importe
  telles quelles, sans filtre, sans renommage, sans colonne calculée.
  Chaque vue et ses colonnes sont déclarées dans dw.source_vue et
  dw.contrat_vue (socle, script 006) : c'est le contrat avec le rapport,
  que la vérification compare à la base dans les deux sens.

  Exposition décidée à la sous-étape 7.6 : les membres spéciaux -1 et -2
  restent (les faits les citent); les colonnes internes (id_chargement,
  lignes_source, codes_en_doublon, statut des valeurs de liste) et les
  dates des référentiels (entrée, sortie, création, fin de relation) ne
  sortent pas; aucune donnée personnelle au-delà du nom, du prénom et du
  poste de l'intervenant, nécessaires au pilotage. Le coût salarial et la
  marge sont exposés au grain de l'intervention : les masquer serait
  illusoire, la marge et les autres composantes les redonnant par
  soustraction; la protection est l'accès au rapport (README). Le lignage
  (fichier, feuille, ligne) reste sur chaque fait, pour la descente
  jusqu'aux lignes. Les colonnes [Intervenant], [Client] et [Fournisseur]
  donnent un libellé d'affichage (nom complet ou raison sociale, sinon le
  code), calculé ici plutôt que dans le rapport.
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

CREATE VIEW pbi.[Interventions] AS
SELECT id_fait_intervention AS [Clé intervention],
       id_intervention AS [N° d'intervention],
       id_date AS [Clé date],
       heure_debut AS [Heure de début],
       id_intervenant AS [Clé intervenant],
       id_client AS [Clé client],
       id_categorie AS [Clé catégorie],
       duree_min AS [Durée (min)],
       duree_trajet_min AS [Durée de trajet (min)],
       distance_km AS [Distance (km)],
       statut AS [Statut],
       facturable AS [Facturable],
       lieu_cp AS [Code postal du lieu],
       lieu_ville AS [Ville du lieu],
       id_chantier AS [Clé chantier],
       jour_chantier AS [Jour du chantier],
       nb_jours_chantier AS [Jours du chantier],
       ca_ht AS [CA HT],
       cout_salarial AS [Coût salarial],
       cout_deplacement AS [Coût de déplacement],
       cout_pieces AS [Coût des pièces],
       marge AS [Marge opérationnelle],
       motif_calcul AS [Motif de calcul],
       retenue AS [Retenue pour les indicateurs],
       fichier_source AS [Fichier source],
       feuille_source AS [Feuille source],
       num_ligne_source AS [Ligne source]
FROM dw.fait_intervention;
GO

CREATE VIEW pbi.[Consommations de pièces] AS
SELECT id_fait_consommation AS [Clé consommation],
       id_consommation AS [N° de consommation],
       id_fait_intervention AS [Clé intervention],
       lien_intervention AS [Lien à l'intervention],
       id_date AS [Clé date],
       id_piece AS [Clé pièce],
       quantite AS [Quantité],
       unite AS [Unité],
       cump_applique AS [CUMP appliqué],
       cout_ht AS [Coût HT],
       motif_calcul AS [Motif de calcul],
       retenue AS [Retenue pour les indicateurs],
       fichier_source AS [Fichier source],
       feuille_source AS [Feuille source],
       num_ligne_source AS [Ligne source]
FROM dw.fait_consommation;
GO

CREATE VIEW pbi.[Lignes de facture] AS
SELECT id_fait_ligne_facture AS [Clé ligne de facture],
       num_facture AS [N° de facture],
       num_ligne AS [N° de ligne],
       lien_entete AS [Lien à l'en-tête],
       type_piece AS [Type de pièce],
       mode_reglement AS [Mode de règlement],
       facture_origine AS [Facture d'origine],
       id_date AS [Clé date],
       id_date_echeance AS [Clé date d'échéance],
       id_client AS [Clé client],
       id_article AS [Clé article],
       id_piece AS [Clé pièce],
       id_fait_intervention AS [Clé intervention],
       lien_intervention AS [Lien à l'intervention],
       quantite AS [Quantité],
       unite AS [Unité],
       pu_ht AS [Prix unitaire HT],
       remise_pct AS [Remise (%)],
       montant_ht AS [Montant HT],
       taux_tva AS [Taux de TVA],
       retenue AS [Retenue pour les indicateurs],
       fichier_source AS [Fichier source],
       feuille_source AS [Feuille source],
       num_ligne_source AS [Ligne source]
FROM dw.fait_ligne_facture;
GO

CREATE VIEW pbi.[Achats] AS
SELECT id_fait_achat AS [Clé achat],
       num_piece_achat AS [N° de pièce d'achat],
       num_ligne AS [N° de ligne],
       lien_entete AS [Lien à l'en-tête],
       type_piece AS [Type de pièce],
       ref_facture_fournisseur AS [Référence de facture fournisseur],
       id_date AS [Clé date],
       id_date_echeance AS [Clé date d'échéance],
       id_fournisseur AS [Clé fournisseur],
       id_piece AS [Clé pièce],
       id_compte AS [Clé compte],
       quantite AS [Quantité],
       unite AS [Unité],
       pu_achat_ht AS [Prix unitaire d'achat HT],
       montant_ht AS [Montant HT],
       retenue AS [Retenue pour les indicateurs],
       fichier_source AS [Fichier source],
       feuille_source AS [Feuille source],
       num_ligne_source AS [Ligne source]
FROM dw.fait_achat;
GO

CREATE VIEW pbi.[Écritures comptables] AS
SELECT id_fait_ecriture AS [Clé écriture],
       journal_code AS [Code journal],
       ecriture_num AS [N° d'écriture],
       id_date AS [Clé date],
       id_date_piece AS [Clé date de pièce],
       id_compte AS [Clé compte],
       comp_aux_num AS [Compte auxiliaire],
       piece_ref AS [Référence de pièce],
       num_facture AS [N° de facture],
       num_piece_achat AS [N° de pièce d'achat],
       ecriture_let AS [Lettrage],
       debit AS [Débit],
       credit AS [Crédit],
       solde AS [Solde],
       retenue AS [Retenue pour les indicateurs],
       fichier_source AS [Fichier source],
       feuille_source AS [Feuille source],
       num_ligne_source AS [Ligne source]
FROM dw.fait_ecriture;
GO

CREATE VIEW pbi.[Stock mensuel des pièces] AS
SELECT id_piece AS [Clé pièce],
       mois AS [Mois],
       stock_debut AS [Stock de début],
       cump_debut AS [CUMP de début],
       quantite_achetee AS [Quantité achetée],
       valeur_achats AS [Valeur des achats],
       quantite_consommee AS [Quantité consommée],
       stock_fin AS [Stock de fin],
       cump_fin AS [CUMP de fin]
FROM dw.cump_mensuel;
GO

/*
  Chantiers : une ligne par chantier (toute intervention en est un, d'un ou
  plusieurs jours), sommée depuis ses jours. La marge applique le principe
  « pas de marge fausse » : vide dès qu'un jour est sans marge, [Jours sans
  marge] pesant ce qui manque. Le CA et les coûts restent la somme des
  valeurs connues, comme dans le rapport. Les clés de date, de client et
  d'intervenant sont celles du premier jour. [Retenue pour les indicateurs]
  vaut 1 quand tous les jours sont retenus, [Jours non retenus] les compte.
*/
CREATE VIEW pbi.[Chantiers] AS
SELECT id_chantier AS [Clé chantier],
       MAX(CASE WHEN jour_chantier = 1 THEN id_date END) AS [Clé date de début],
       MAX(CASE WHEN jour_chantier = nb_jours_chantier THEN id_date END)
           AS [Clé date de fin],
       MAX(CASE WHEN jour_chantier = 1 THEN id_client END) AS [Clé client],
       MAX(CASE WHEN jour_chantier = 1 THEN id_intervenant END) AS [Clé intervenant],
       MAX(nb_jours_chantier) AS [Nombre de jours],
       SUM(CASE WHEN marge IS NULL THEN 1 ELSE 0 END) AS [Jours sans marge],
       SUM(1 - CAST(retenue AS int)) AS [Jours non retenus],
       MIN(CAST(retenue AS int)) AS [Retenue pour les indicateurs],
       SUM(ca_ht) AS [CA HT],
       SUM(cout_salarial) AS [Coût salarial],
       SUM(cout_deplacement) AS [Coût de déplacement],
       SUM(cout_pieces) AS [Coût des pièces],
       CASE WHEN SUM(CASE WHEN marge IS NULL THEN 1 ELSE 0 END) = 0
            THEN SUM(marge) END AS [Marge opérationnelle]
FROM dw.fait_intervention
GROUP BY id_chantier;
GO

/* Déclaration des vues : le contrat avec le rapport. */
INSERT INTO dw.source_vue (vue, source) VALUES
    (N'Calendrier', N'dw.dim_date'),
    (N'Catégories d''intervention', N'dw.dim_categorie'),
    (N'Articles facturés', N'dw.dim_article'),
    (N'Pièces', N'dw.dim_piece'),
    (N'Comptes', N'dw.dim_compte'),
    (N'Intervenants', N'dw.dim_intervenant'),
    (N'Clients', N'dw.dim_client'),
    (N'Fournisseurs', N'dw.dim_fournisseur'),
    (N'Interventions', N'dw.fait_intervention'),
    (N'Consommations de pièces', N'dw.fait_consommation'),
    (N'Lignes de facture', N'dw.fait_ligne_facture'),
    (N'Achats', N'dw.fait_achat'),
    (N'Écritures comptables', N'dw.fait_ecriture'),
    (N'Stock mensuel des pièces', N'dw.cump_mensuel'),
    (N'Chantiers', N'dw.fait_intervention (par chantier)');
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
    (N'Fournisseurs', N'Statut'),
    (N'Interventions', N'Clé intervention'),
    (N'Interventions', N'N° d''intervention'),
    (N'Interventions', N'Clé date'),
    (N'Interventions', N'Heure de début'),
    (N'Interventions', N'Clé intervenant'),
    (N'Interventions', N'Clé client'),
    (N'Interventions', N'Clé catégorie'),
    (N'Interventions', N'Durée (min)'),
    (N'Interventions', N'Durée de trajet (min)'),
    (N'Interventions', N'Distance (km)'),
    (N'Interventions', N'Statut'),
    (N'Interventions', N'Facturable'),
    (N'Interventions', N'Code postal du lieu'),
    (N'Interventions', N'Ville du lieu'),
    (N'Interventions', N'Clé chantier'),
    (N'Interventions', N'Jour du chantier'),
    (N'Interventions', N'Jours du chantier'),
    (N'Interventions', N'CA HT'),
    (N'Interventions', N'Coût salarial'),
    (N'Interventions', N'Coût de déplacement'),
    (N'Interventions', N'Coût des pièces'),
    (N'Interventions', N'Marge opérationnelle'),
    (N'Interventions', N'Motif de calcul'),
    (N'Interventions', N'Retenue pour les indicateurs'),
    (N'Interventions', N'Fichier source'),
    (N'Interventions', N'Feuille source'),
    (N'Interventions', N'Ligne source'),
    (N'Consommations de pièces', N'Clé consommation'),
    (N'Consommations de pièces', N'N° de consommation'),
    (N'Consommations de pièces', N'Clé intervention'),
    (N'Consommations de pièces', N'Lien à l''intervention'),
    (N'Consommations de pièces', N'Clé date'),
    (N'Consommations de pièces', N'Clé pièce'),
    (N'Consommations de pièces', N'Quantité'),
    (N'Consommations de pièces', N'Unité'),
    (N'Consommations de pièces', N'CUMP appliqué'),
    (N'Consommations de pièces', N'Coût HT'),
    (N'Consommations de pièces', N'Motif de calcul'),
    (N'Consommations de pièces', N'Retenue pour les indicateurs'),
    (N'Consommations de pièces', N'Fichier source'),
    (N'Consommations de pièces', N'Feuille source'),
    (N'Consommations de pièces', N'Ligne source'),
    (N'Lignes de facture', N'Clé ligne de facture'),
    (N'Lignes de facture', N'N° de facture'),
    (N'Lignes de facture', N'N° de ligne'),
    (N'Lignes de facture', N'Lien à l''en-tête'),
    (N'Lignes de facture', N'Type de pièce'),
    (N'Lignes de facture', N'Mode de règlement'),
    (N'Lignes de facture', N'Facture d''origine'),
    (N'Lignes de facture', N'Clé date'),
    (N'Lignes de facture', N'Clé date d''échéance'),
    (N'Lignes de facture', N'Clé client'),
    (N'Lignes de facture', N'Clé article'),
    (N'Lignes de facture', N'Clé pièce'),
    (N'Lignes de facture', N'Clé intervention'),
    (N'Lignes de facture', N'Lien à l''intervention'),
    (N'Lignes de facture', N'Quantité'),
    (N'Lignes de facture', N'Unité'),
    (N'Lignes de facture', N'Prix unitaire HT'),
    (N'Lignes de facture', N'Remise (%)'),
    (N'Lignes de facture', N'Montant HT'),
    (N'Lignes de facture', N'Taux de TVA'),
    (N'Lignes de facture', N'Retenue pour les indicateurs'),
    (N'Lignes de facture', N'Fichier source'),
    (N'Lignes de facture', N'Feuille source'),
    (N'Lignes de facture', N'Ligne source'),
    (N'Achats', N'Clé achat'),
    (N'Achats', N'N° de pièce d''achat'),
    (N'Achats', N'N° de ligne'),
    (N'Achats', N'Lien à l''en-tête'),
    (N'Achats', N'Type de pièce'),
    (N'Achats', N'Référence de facture fournisseur'),
    (N'Achats', N'Clé date'),
    (N'Achats', N'Clé date d''échéance'),
    (N'Achats', N'Clé fournisseur'),
    (N'Achats', N'Clé pièce'),
    (N'Achats', N'Clé compte'),
    (N'Achats', N'Quantité'),
    (N'Achats', N'Unité'),
    (N'Achats', N'Prix unitaire d''achat HT'),
    (N'Achats', N'Montant HT'),
    (N'Achats', N'Retenue pour les indicateurs'),
    (N'Achats', N'Fichier source'),
    (N'Achats', N'Feuille source'),
    (N'Achats', N'Ligne source'),
    (N'Écritures comptables', N'Clé écriture'),
    (N'Écritures comptables', N'Code journal'),
    (N'Écritures comptables', N'N° d''écriture'),
    (N'Écritures comptables', N'Clé date'),
    (N'Écritures comptables', N'Clé date de pièce'),
    (N'Écritures comptables', N'Clé compte'),
    (N'Écritures comptables', N'Compte auxiliaire'),
    (N'Écritures comptables', N'Référence de pièce'),
    (N'Écritures comptables', N'N° de facture'),
    (N'Écritures comptables', N'N° de pièce d''achat'),
    (N'Écritures comptables', N'Lettrage'),
    (N'Écritures comptables', N'Débit'),
    (N'Écritures comptables', N'Crédit'),
    (N'Écritures comptables', N'Solde'),
    (N'Écritures comptables', N'Retenue pour les indicateurs'),
    (N'Écritures comptables', N'Fichier source'),
    (N'Écritures comptables', N'Feuille source'),
    (N'Écritures comptables', N'Ligne source'),
    (N'Stock mensuel des pièces', N'Clé pièce'),
    (N'Stock mensuel des pièces', N'Mois'),
    (N'Stock mensuel des pièces', N'Stock de début'),
    (N'Stock mensuel des pièces', N'CUMP de début'),
    (N'Stock mensuel des pièces', N'Quantité achetée'),
    (N'Stock mensuel des pièces', N'Valeur des achats'),
    (N'Stock mensuel des pièces', N'Quantité consommée'),
    (N'Stock mensuel des pièces', N'Stock de fin'),
    (N'Stock mensuel des pièces', N'CUMP de fin'),
    (N'Chantiers', N'Clé chantier'),
    (N'Chantiers', N'Clé date de début'),
    (N'Chantiers', N'Clé date de fin'),
    (N'Chantiers', N'Clé client'),
    (N'Chantiers', N'Clé intervenant'),
    (N'Chantiers', N'Nombre de jours'),
    (N'Chantiers', N'Jours sans marge'),
    (N'Chantiers', N'Jours non retenus'),
    (N'Chantiers', N'Retenue pour les indicateurs'),
    (N'Chantiers', N'CA HT'),
    (N'Chantiers', N'Coût salarial'),
    (N'Chantiers', N'Coût de déplacement'),
    (N'Chantiers', N'Coût des pièces'),
    (N'Chantiers', N'Marge opérationnelle');
GO
