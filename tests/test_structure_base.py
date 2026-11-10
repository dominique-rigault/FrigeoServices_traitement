"""Tests sans base de données du module frigeo.structure_base."""

import pytest

from frigeo.structure_base import (
    COLONNES_CORRESPONDANCE,
    COLONNES_RESUME,
    FAMILLE_DATE,
    FAMILLE_DECIMAL,
    FAMILLE_ENTIER,
    FAMILLE_HEURE,
    FAMILLE_TEXTE,
    SCHEMA_CHARGEMENT,
    SCHEMA_PROPRE,
    ErreurStructure,
    colonnes_techniques,
    construire_structure,
    ddl_structure,
    ddl_suppression,
    ddl_table,
    est_code,
    famille_propre,
    lignes_correspondance,
    nom_sql,
    probleme_nom,
    resumer_structure,
)


def regles(nature="texte", valeurs="aucune", format_="aucune"):
    """Règles d'une colonne du dictionnaire, réduites à ce qu'utilise la structure."""
    return {
        "obligatoire": {"regle": "obligatoire"},
        "nature": {"regle": nature},
        "valeurs": {"regle": valeurs},
        "format": {"regle": format_},
    }


# --- Noms ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, attendu",
    [
        ("num_facture", "num_facture"),
        ("JournalCode", "journal_code"),
        ("CompAuxNum", "comp_aux_num"),
        ("Montantdevise", "montantdevise"),
        ("ValidDate", "valid_date"),
        ("HTTPServeur", "http_serveur"),
        ("Libellé pièce", "libelle_piece"),
        ("Œuvre", "oeuvre"),
        ("CŒUR", "coeur"),
        ("  taux--TVA (%) ", "taux_tva"),
        ("TVA20", "tva20"),
    ],
)
def test_nom_sql(source, attendu):
    assert nom_sql(source) == attendu


def test_probleme_nom():
    assert probleme_nom("journal_code") is None
    assert "vide" in probleme_nom(nom_sql("%%"))
    assert "chiffre" in probleme_nom(nom_sql("2025_total"))
    assert "réservé" in probleme_nom(nom_sql("Order"))
    assert "dépasse" in probleme_nom("a" * 101)
    assert probleme_nom("a" * 100) is None


# --- Types -----------------------------------------------------------------------


def test_est_code():
    assert est_code(regles(format_="formes fermées"))
    assert est_code(regles(valeurs="liste fermée"))
    assert est_code(regles(), {"cle_luhn": True})
    assert est_code(regles(), {"motif": r"\d{5}"})
    assert not est_code(regles())
    assert not est_code(regles(), {"bornes": {"min": 0}, "duree": "minutes"})
    assert not est_code(regles(), {"cle_luhn": False})


@pytest.mark.parametrize(
    "nature, code, attendue",
    [
        ("date native", False, FAMILLE_DATE),
        ("date JJ/MM/AAAA", False, FAMILLE_DATE),
        ("date AAAAMMJJ", False, FAMILLE_DATE),
        ("date AAAA-MM-JJ", False, FAMILLE_DATE),
        ("heure HH:MM", False, FAMILLE_HEURE),
        ("entier (texte)", False, FAMILLE_ENTIER),
        ("entier (texte)", True, FAMILLE_TEXTE),
        ("nombre natif", False, FAMILLE_DECIMAL),
        ("nombre natif", True, FAMILLE_DECIMAL),
        ("décimal virgule (texte)", False, FAMILLE_DECIMAL),
        ("décimal point (texte)", False, FAMILLE_DECIMAL),
        ("texte", False, FAMILLE_TEXTE),
        ("aucune", False, FAMILLE_TEXTE),
        ("à décider", False, FAMILLE_TEXTE),
    ],
)
def test_famille_propre(nature, code, attendue):
    assert famille_propre(nature, code) == attendue


def test_colonnes_techniques():
    propre = [c.nom for c in colonnes_techniques(SCHEMA_PROPRE)]
    chargement = [c.nom for c in colonnes_techniques(SCHEMA_CHARGEMENT)]
    communes = [
        "id_ligne",
        "id_chargement",
        "periode_export",
        "fichier_source",
        "feuille_source",
        "num_ligne_source",
    ]
    assert propre == [*communes, "retenue"]
    assert chargement == [*communes, "nb_champs_source", "champs_excedentaires"]
    identites = [c.nom for c in colonnes_techniques(SCHEMA_PROPRE) if c.identite]
    assert identites == ["id_ligne"]
    with pytest.raises(ValueError):
        colonnes_techniques("dw")


# --- Structure -------------------------------------------------------------------


def dictionnaire_exemple():
    return {
        "interventions": {
            "id_intervention": regles(format_="formes fermées"),
            "date_debut": regles("date JJ/MM/AAAA"),
            "heure_debut": regles("heure HH:MM"),
            "duree_min": regles("entier (texte)"),
            "lieu_cp": regles("entier (texte)", format_="formes fermées"),
            "distance_km": regles("décimal virgule (texte)"),
            "client": regles(),
        },
        "fec": {
            "JournalCode": regles(valeurs="liste fermée"),
            "CompteNum": regles("entier (texte)", format_="formes fermées"),
            "Debit": regles("décimal virgule (texte)"),
        },
        "clients": {
            "siret": regles("entier (texte)"),
        },
    }


def test_structure_dans_l_ordre_du_dictionnaire():
    structure = construire_structure(
        dictionnaire_exemple(),
        {"interventions": frozenset({"client"})},
        {"interventions": {"duree_min": {"duree": "minutes"}}, "clients": {"siret": {"cle_luhn": True}}},
    )
    assert list(structure) == ["interventions", "fec", "clients"]
    interventions = structure["interventions"]
    assert interventions.nom == "interventions"
    assert [c.source for c in interventions.colonnes] == list(dictionnaire_exemple()["interventions"])
    types = {c.source: c.type_propre for c in interventions.colonnes}
    assert types == {
        "id_intervention": "nvarchar(4000)",
        "date_debut": "date",
        "heure_debut": "time(0)",
        "duree_min": "bigint",
        "lieu_cp": "nvarchar(4000)",
        "distance_km": "decimal(28, 8)",
        "client": "nvarchar(4000)",
    }
    assert interventions.colonne("client").sensible
    assert not interventions.colonne("duree_min").sensible
    fec = structure["fec"]
    assert [c.nom for c in fec.colonnes] == ["journal_code", "compte_num", "debit"]
    assert fec.colonne("CompteNum").famille == FAMILLE_TEXTE
    assert structure["clients"].colonne("siret").famille == FAMILLE_TEXTE


def test_structure_sans_regles_complementaires():
    structure = construire_structure(dictionnaire_exemple(), {})
    assert structure["clients"].colonne("siret").famille == FAMILLE_ENTIER


def test_colonne_absente():
    structure = construire_structure(dictionnaire_exemple(), {})
    with pytest.raises(KeyError):
        structure["fec"].colonne("Credit")


def test_tous_les_problemes_en_une_fois():
    dictionnaire = {
        "fec": {
            "DateLet": regles("date AAAAMMJJ"),
            "date_let": regles("date AAAAMMJJ"),
            "Order": regles(),
            "2025": regles(),
            "id_ligne": regles(),
            "Num-Ligne Source": regles(),
        },
        "Fec": {"x": regles()},
        "select": {"y": regles()},
    }
    sensibles = {"fec": frozenset({"CompAuxLib"}), "clients": frozenset({"siret"})}
    with pytest.raises(ErreurStructure) as erreur:
        construire_structure(dictionnaire, sensibles)
    message = str(erreur.value)
    for attendu in (
        "Colonnes fec.DateLet et fec.date_let : même nom en base date_let",
        "Colonne fec.Order : le nom en base order est un mot réservé de T-SQL",
        "Colonne fec.2025 : le nom en base 2025 commence par un chiffre",
        "Colonne fec.id_ligne : le nom en base id_ligne est celui d'une colonne technique",
        "Colonne fec.Num-Ligne Source : le nom en base num_ligne_source est celui d'une "
        "colonne technique",
        "Tables fec et Fec : même nom en base fec",
        "Table select : le nom en base select est un mot réservé de T-SQL",
        "Colonne fec.CompAuxLib classée sensible mais absente du dictionnaire",
        "Table clients classée sensible mais absente du dictionnaire",
    ):
        assert attendu in message


def test_resume():
    structure = construire_structure(dictionnaire_exemple(), {"interventions": frozenset({"client"})})
    resume = resumer_structure(structure)
    assert list(resume.columns) == COLONNES_RESUME
    assert len(resume) == 11
    ligne = resume[(resume["table"] == "fec") & (resume["colonne"] == "JournalCode")].iloc[0]
    assert ligne["colonne_base"] == "journal_code"
    assert ligne["type_propre"] == "nvarchar(4000)"
    assert resume["sensible"].sum() == 1


# --- SQL des tables de données ------------------------------------------------------


def structure_exemple():
    return construire_structure(
        dictionnaire_exemple(),
        {"interventions": frozenset({"client"})},
        {"clients": {"siret": {"cle_luhn": True}}},
    )


def test_ddl_table_propre():
    sql = ddl_table(structure_exemple()["interventions"], SCHEMA_PROPRE)
    assert sql.startswith("CREATE TABLE propre.interventions (\n")
    assert sql.endswith("\n);")
    lignes = [ligne.strip().rstrip(",") for ligne in sql.splitlines()[1:-1]]
    assert lignes[:7] == [
        "id_ligne bigint IDENTITY(1, 1) NOT NULL",
        "id_chargement int NOT NULL",
        "periode_export nvarchar(20) NULL",
        "fichier_source nvarchar(260) NOT NULL",
        "feuille_source nvarchar(128) NULL",
        "num_ligne_source int NOT NULL",
        "retenue bit NOT NULL",
    ]
    assert lignes[7:14] == [
        "id_intervention nvarchar(4000) NULL",
        "date_debut date NULL",
        "heure_debut time(0) NULL",
        "duree_min bigint NULL",
        "lieu_cp nvarchar(4000) NULL",
        "distance_km decimal(28, 8) NULL",
        "client nvarchar(4000) NULL",
    ]
    assert lignes[14:] == [
        "CONSTRAINT pk_interventions PRIMARY KEY (id_ligne)",
        "CONSTRAINT uq_interventions_lignage UNIQUE "
        "(fichier_source, feuille_source, num_ligne_source)",
        "CONSTRAINT fk_interventions_chargement FOREIGN KEY (id_chargement) "
        "REFERENCES qualite.journal_chargement (id_chargement)",
    ]


def test_ddl_table_chargement_en_texte():
    sql = ddl_table(structure_exemple()["fec"], SCHEMA_CHARGEMENT)
    assert sql.startswith("CREATE TABLE chargement.fec (\n")
    for attendu in (
        "nb_champs_source int NULL",
        "champs_excedentaires nvarchar(4000) NULL",
        "journal_code nvarchar(4000) NULL",
        "compte_num nvarchar(4000) NULL",
        "debit nvarchar(4000) NULL",
    ):
        assert attendu in sql
    assert "decimal" not in sql


def test_ddl_structure_chargement_puis_propre():
    instructions = ddl_structure(structure_exemple())
    entetes = [i.splitlines()[0] for i in instructions]
    assert entetes == [
        "CREATE TABLE chargement.interventions (",
        "CREATE TABLE chargement.fec (",
        "CREATE TABLE chargement.clients (",
        "CREATE TABLE propre.interventions (",
        "CREATE TABLE propre.fec (",
        "CREATE TABLE propre.clients (",
    ]


def test_ddl_suppression():
    assert ddl_suppression([("chargement", "fec"), ("propre", "ancienne]table")]) == [
        "DROP TABLE [chargement].[fec];",
        "DROP TABLE [propre].[ancienne]]table];",
    ]
    assert ddl_suppression([]) == []
    with pytest.raises(ValueError, match="qualite.execution"):
        ddl_suppression([("propre", "fec"), ("qualite", "execution")])


def test_lignes_correspondance():
    lignes = lignes_correspondance(structure_exemple())
    assert len(lignes) == 11
    assert all(set(ligne) == set(COLONNES_CORRESPONDANCE) for ligne in lignes)
    fec = [ligne for ligne in lignes if ligne["table_source"] == "fec"]
    assert [ligne["ordre"] for ligne in fec] == [1, 2, 3]
    assert fec[1] == {
        "table_source": "fec",
        "colonne_source": "CompteNum",
        "table_base": "fec",
        "colonne_base": "compte_num",
        "ordre": 2,
        "nature": "entier (texte)",
        "famille": "texte",
        "type_propre": "nvarchar(4000)",
        "sensible": False,
    }
    assert sum(ligne["sensible"] for ligne in lignes) == 1
