"""Tests de la décision de liste fermée (frigeo.dictionnaire)."""

import pandas as pd
import pytest

from frigeo.dictionnaire import (
    generer_dictionnaire,
    generer_table,
    proposer_liste,
    proposer_nature,
    proposer_obligatoire,
    resumer_dictionnaire,
)


def _serie(*comptes) -> pd.Series:
    """Série d'objets construite à partir de couples (valeur, effectif)."""
    return pd.Series([v for v, n in comptes for _ in range(n)], dtype=object)


def test_liste_fermee_variantes_a_arbitrer_et_vides_exclus():
    statut = _serie(
        ("Réalisée", 700),
        ("Annulée", 250),
        ("Reportée", 40),
        ("OK", 3),
        ("Fait", 2),
        (None, 3),
        ("   ", 2),
    )
    resultat = proposer_liste(statut)
    assert resultat["liste_fermee"] is True
    assert resultat["valeurs"] == ["Réalisée", "Annulée", "Reportée"]
    assert resultat["a_arbitrer"] == [
        {"valeur": "OK", "effectif": 3},
        {"valeur": "Fait", "effectif": 2},
    ]


def test_defauts_nombreux_mais_rares_n_empechent_pas_la_liste():
    categorie = _serie(
        ("Préventif", 290),
        ("Maintenance", 200),
        ("Dépannage", 290),
        ("Contrôle", 150),
        ("Installation", 50),
        *[(f"variante_{i:02d}", 1) for i in range(20)],
    )
    assert categorie.nunique() == 25
    resultat = proposer_liste(categorie)
    assert resultat["liste_fermee"] is True
    assert len(resultat["valeurs"]) == 5
    assert len(resultat["a_arbitrer"]) == 20


def test_valeurs_comparees_telles_quelles():
    ville = _serie(("Gisors", 600), ("Evreux", 396), ("Gisors  ", 4))
    resultat = proposer_liste(ville)
    assert resultat["valeurs"] == ["Gisors", "Evreux"]
    assert resultat["a_arbitrer"] == [{"valeur": "Gisors  ", "effectif": 4}]


def test_trop_de_valeurs_principales():
    colonne = _serie(*[(f"V{i:02d}", 100) for i in range(14)])
    resultat = proposer_liste(colonne)
    assert resultat["liste_fermee"] is False
    assert resultat["motif"] == "14 valeurs principales (maximum 12)"
    assert resultat["valeurs"] == []


def test_couverture_insuffisante():
    colonne = _serie(
        ("A", 460), ("B", 460), *[(f"rare_{i:02d}", 4) for i in range(20)]
    )
    resultat = proposer_liste(colonne)
    assert resultat["liste_fermee"] is False
    assert resultat["motif"].startswith("valeurs principales couvrant")
    assert resultat["a_arbitrer"] == []


def test_effectif_insuffisant_petite_table():
    colonne = _serie(("CDI", 12), ("CDD", 4), ("Apprentissage", 2))
    resultat = proposer_liste(colonne)
    assert resultat["liste_fermee"] is False
    assert resultat["motif"].startswith("effectif insuffisant")


def test_nature_non_texte():
    colonne = pd.Series([i % 5 for i in range(1000)], dtype=object)
    resultat = proposer_liste(colonne)
    assert resultat["liste_fermee"] is False
    assert resultat["motif"].startswith("nature dominante")


def test_colonne_sensible_n_expose_aucune_valeur():
    colonne = _serie(("Boulangerie", 600), ("Restaurant", 400))
    sensibles = {"clients": frozenset({"type_commerce"})}
    resultat = proposer_liste(colonne, "clients", "type_commerce", sensibles)
    assert resultat["liste_fermee"] is False
    assert resultat["motif"] == "colonne sensible"
    assert resultat["valeurs"] == []
    assert resultat["a_arbitrer"] == []
    # La même série, dans une colonne non sensible de la même table, est proposée.
    autre = proposer_liste(colonne, "clients", "statut", sensibles)
    assert autre["liste_fermee"] is True


def test_seuils_parametrables():
    colonne = _serie(*[(f"V{i}", 200) for i in range(5)])
    assert proposer_liste(colonne)["liste_fermee"] is True
    assert proposer_liste(colonne, max_valeurs=3)["liste_fermee"] is False

def test_obligatoire_compte_les_trois_formes_de_vide():
    colonne = _serie(("x", 990), (None, 4), ("", 3), ("  ", 3))
    resultat = proposer_obligatoire(colonne)
    assert resultat["regle"] == "obligatoire"
    assert resultat["a_arbitrer"] == {"vides": 10}


def test_obligatoire_sans_aucun_vide():
    resultat = proposer_obligatoire(_serie(("x", 1000)))
    assert resultat["regle"] == "obligatoire"
    assert resultat["a_arbitrer"] == {"vides": 0}


def test_limite_de_2_pour_cent_incluse():
    assert proposer_obligatoire(_serie(("x", 980), ("", 20)))["regle"] == "obligatoire"
    assert proposer_obligatoire(_serie(("x", 979), ("", 21)))["regle"] == "facultatif"


def test_facultatif_entre_les_deux_bornes():
    resultat = proposer_obligatoire(_serie(("x", 500), (None, 500)))
    assert resultat["regle"] == "facultatif"
    assert resultat["a_arbitrer"] == {}


def test_presque_toujours_vide_a_partir_de_98_pour_cent():
    assert proposer_obligatoire(_serie(("x", 21), ("", 979)))["regle"] == "facultatif"
    limite = proposer_obligatoire(_serie(("x", 20), ("", 980)))
    assert limite["regle"] == "presque toujours vide"
    rare = proposer_obligatoire(_serie(("x", 11), (None, 989)))
    assert rare["regle"] == "presque toujours vide"
    assert rare["a_arbitrer"] == {"renseignees": 11}


def test_toujours_vide_seulement_a_100_pour_cent():
    colonne = _serie((None, 100), ("", 100), ("  ", 100))
    assert proposer_obligatoire(colonne)["regle"] == "toujours vide"
    une_valeur = _serie(("x", 1), (None, 999))
    assert proposer_obligatoire(une_valeur)["regle"] == "presque toujours vide"


def test_petite_table_avec_un_vide_est_a_decider():
    resultat = proposer_obligatoire(_serie(("x", 17), (None, 1)))
    assert resultat["regle"] == "à décider"
    assert resultat["motif"].startswith("effectif insuffisant")
    assert resultat["a_arbitrer"] == {"vides": 1}


def test_petite_table_sans_vide_et_table_vide():
    assert proposer_obligatoire(_serie(("x", 18)))["regle"] == "obligatoire"
    vide = proposer_obligatoire(pd.Series([], dtype=object))
    assert vide["regle"] == "à décider"
    assert vide["motif"] == "aucune ligne"

def test_nature_texte_libre():
    resultat = proposer_nature(_serie(("Réalisée", 500), ("Annulée", 500)))
    assert resultat["regle"] == "texte"
    assert resultat["a_arbitrer"] == {"hors_nature": 0}


def test_nature_specifique_toutes_conformes():
    resultat = proposer_nature(_serie(("12", 1000)))
    assert resultat["regle"] not in ("texte", "à décider")
    assert resultat["a_arbitrer"] == {"hors_nature": 0}


def test_nature_hors_nature_a_arbitrer():
    nature = proposer_nature(_serie(("12", 1000)))["regle"]
    resultat = proposer_nature(_serie(("12", 990), ("abc", 10)))
    assert resultat["regle"] == nature
    assert resultat["a_arbitrer"] == {"hors_nature": 10}


def test_nature_a_decider_si_couverture_insuffisante():
    nature = proposer_nature(_serie(("12", 1000)))["regle"]
    resultat = proposer_nature(_serie(("12", 800), ("abc", 200)))
    assert resultat["regle"] == "à décider"
    assert resultat["a_arbitrer"] == {"nature_dominante": nature, "hors_nature": 200}


def test_nature_negligeable_devient_texte():
    colonne = _serie(("abc", 600), ("def", 396), ("12", 4))
    resultat = proposer_nature(colonne)
    assert resultat["regle"] == "texte"
    assert resultat["a_arbitrer"] == {"hors_nature": 0}


def test_nature_petite_table():
    nature = proposer_nature(_serie(("12", 1000)))["regle"]
    assert proposer_nature(_serie(("12", 18)))["regle"] == nature
    resultat = proposer_nature(_serie(("12", 17), ("abc", 1)))
    assert resultat["regle"] == "à décider"
    assert resultat["motif"].startswith("effectif insuffisant")


def test_nature_sans_aucune_valeur():
    resultat = proposer_nature(_serie((None, 10), ("", 5)))
    assert resultat["regle"] == "à décider"
    assert resultat["motif"] == "aucune valeur renseignée"


def test_liste_fermee_malgre_quelques_valeurs_ressemblant_a_des_nombres():
    statut = _serie(("Réalisée", 700), ("Annulée", 296), ("12", 4))
    resultat = proposer_liste(statut)
    assert resultat["liste_fermee"] is True
    assert resultat["valeurs"] == ["Réalisée", "Annulée"]
    assert resultat["a_arbitrer"] == [{"valeur": "12", "effectif": 4}]

SENSIBLES = {"clients": frozenset({"type_commerce"})}


def _table_fictive() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "statut": _serie(
                ("Réalisée", 700),
                ("Annulée", 250),
                ("Reportée", 40),
                ("OK", 3),
                ("Fait", 2),
                (None, 5),
            ),
            "type_commerce": _serie(("Boulangerie", 600), ("Restaurant", 400)),
            "commentaire": pd.Series(
                [""] * 600 + [f"note {i}" for i in range(400)], dtype=object
            ),
            "fichier_source": ["f.csv"] * 1000,
            "num_ligne_source": range(2, 1002),
        }
    )


def test_generer_table_exclut_les_colonnes_de_lignage():
    table = generer_table(_table_fictive(), "clients", SENSIBLES)
    assert list(table) == ["statut", "type_commerce", "commentaire"]


def test_generer_colonne_avec_liste_fermee():
    colonne = generer_table(_table_fictive(), "clients", SENSIBLES)["statut"]
    assert colonne["obligatoire"]["regle"] == "obligatoire"
    assert colonne["obligatoire"]["a_arbitrer"] == {"vides": 5}
    assert colonne["nature"]["regle"] == "texte"
    assert colonne["valeurs"]["regle"] == ["Réalisée", "Annulée", "Reportée"]
    assert colonne["valeurs"]["a_arbitrer"] == [
        {"valeur": "OK", "effectif": 3},
        {"valeur": "Fait", "effectif": 2},
    ]


def test_generer_colonne_sans_liste_fermee():
    colonne = generer_table(_table_fictive(), "clients", SENSIBLES)["commentaire"]
    assert colonne["obligatoire"]["regle"] == "facultatif"
    assert colonne["valeurs"]["regle"] == "aucune"
    assert colonne["valeurs"]["a_arbitrer"] == []


def test_colonne_sensible_ne_laisse_fuiter_aucune_valeur():
    dictionnaire = generer_dictionnaire({"clients": _table_fictive()}, SENSIBLES)
    colonne = dictionnaire["clients"]["type_commerce"]
    assert colonne["valeurs"]["regle"] == "aucune"
    assert colonne["valeurs"]["motif"] == "colonne sensible"
    assert "Boulangerie" not in repr(colonne)
    assert "Restaurant" not in repr(colonne)


def test_toutes_les_regles_sont_au_statut_observe():
    dictionnaire = generer_dictionnaire({"clients": _table_fictive()}, SENSIBLES)
    regles = [
        regle
        for colonnes in dictionnaire.values()
        for colonne in colonnes.values()
        for regle in colonne.values()
    ]
    assert len(regles) == 9
    assert {regle["statut"] for regle in regles} == {"observé"}


def test_incoherence_de_sensibilite_arrete_la_generation():
    tables = {"clients": _table_fictive()}
    with pytest.raises(RuntimeError, match="Classification de sensibilité incohérente"):
        generer_dictionnaire(tables, {"clients": frozenset({"colonne_inconnue"})})
    with pytest.raises(RuntimeError):
        generer_dictionnaire(tables, {"autre_table": frozenset({"x"})})

def test_resumer_dictionnaire():
    dictionnaire = generer_dictionnaire({"clients": _table_fictive()}, SENSIBLES)
    resume = resumer_dictionnaire(dictionnaire).set_index("colonne")
    assert list(resume.columns) == [
        "table",
        "obligatoire",
        "nature",
        "liste_fermee",
        "nb_valeurs",
        "nb_a_arbitrer",
        "motif_liste",
    ]
    assert resume.loc["statut", "liste_fermee"]
    assert resume.loc["statut", "nb_valeurs"] == 3
    assert resume.loc["statut", "nb_a_arbitrer"] == 2
    assert not resume.loc["type_commerce", "liste_fermee"]
    assert resume.loc["type_commerce", "motif_liste"] == "colonne sensible"