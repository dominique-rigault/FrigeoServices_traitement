"""Tests de la décision de liste fermée (frigeo.dictionnaire)."""

import pandas as pd

from frigeo.dictionnaire import proposer_liste, proposer_obligatoire


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