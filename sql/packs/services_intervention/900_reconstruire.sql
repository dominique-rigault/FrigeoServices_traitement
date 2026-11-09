/*
  Pack services_intervention, script 900 : procédure dw.reconstruire.

  Dernier script du pack, pour être créé après les procédures qu'il appelle.
  Il enchaîne la vérification du contrat d'entrée (colonnes de propre et
  rattachements de l'exécution), le vidage des faits, la construction des
  dimensions (script 002), puis celle des faits (script 003), un fait lié à
  un autre (une consommation à son intervention) après celui-ci. Chaque étape
  de construction est inscrite dans dw.journal_reconstruction.
*/

/* Reconstruit dw pour une exécution, dans la transaction de l'appelant. */
CREATE PROCEDURE dw.reconstruire
    @id_execution int
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    IF @@TRANCOUNT = 0
        THROW 50001, N'dw.reconstruire s''exécute dans une transaction ouverte par l''appelant (cellule # BASE ou python -m frigeo.base --reconstruire).', 1;
    IF NOT EXISTS (SELECT 1 FROM qualite.execution WHERE id_execution = @id_execution)
        THROW 50002, N'dw.reconstruire : exécution inconnue de qualite.execution.', 1;

    DELETE FROM dw.journal_reconstruction;

    DECLARE @debut datetime2(0) = SYSUTCDATETIME();
    EXEC dw.verifier_contrat @id_execution;
    DECLARE @colonnes int = (SELECT COUNT(*) FROM dw.contrat_entree);
    EXEC dw.inscrire_etape @id_execution, N'contrat d''entrée', @colonnes, @debut;

    /* Faits vidés avant les dimensions qu'ils référencent. */
    EXEC dw.vider_faits;

    /* Dimensions (script 002). */
    EXEC dw.construire_dim_date @id_execution;
    EXEC dw.construire_dim_categorie @id_execution;
    EXEC dw.construire_dim_article @id_execution;
    EXEC dw.construire_dim_piece @id_execution;
    EXEC dw.construire_dim_compte @id_execution;
    EXEC dw.construire_dim_intervenant @id_execution;
    EXEC dw.construire_dim_client @id_execution;
    EXEC dw.construire_dim_fournisseur @id_execution;

    /* Faits (script 003). */
    EXEC dw.construire_fait_intervention @id_execution;
    EXEC dw.construire_fait_consommation @id_execution;
    EXEC dw.construire_fait_ligne_facture @id_execution;
    EXEC dw.construire_fait_achat @id_execution;
    EXEC dw.construire_fait_ecriture @id_execution;
END;
GO
