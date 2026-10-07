"""Tests de la décision de liste fermée (frigeo.dictionnaire)."""

import numpy as np
import pandas as pd
import pytest
import yaml

from frigeo.dictionnaire import (
    charger_dictionnaire,
    ecrire_dictionnaire,
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



def _regle(regle, statut="observé", a_arbitrer=None):
    return {
        "regle": regle,
        "statut": statut,
        "motif": "motif fictif",
        "a_arbitrer": {} if a_arbitrer is None else a_arbitrer,
    }


def _dictionnaire_fictif(valeurs="aucune", statut="observé", a_arbitrer=None):
    return {
        "clients": {
            "ville": {
                "obligatoire": _regle("obligatoire", a_arbitrer={"vides": 0}),
                "nature": _regle("texte", a_arbitrer={"hors_nature": 0}),
                "valeurs": _regle(valeurs, statut, [] if a_arbitrer is None else a_arbitrer),
            }
        }
    }


def _ecrire_brut(chemin, tables):
    """Écrit un fichier sans passer par `ecrire_dictionnaire` (cas d'un fichier modifié à la main)."""
    texte = yaml.safe_dump({"meta": {}, "tables": tables}, allow_unicode=True)
    chemin.write_text(texte, encoding="utf-8")


def test_aller_retour_du_dictionnaire_genere(tmp_path):
    dictionnaire = generer_dictionnaire({"clients": _table_fictive()}, SENSIBLES)
    chemin = ecrire_dictionnaire(dictionnaire, "2026-03", tmp_path / "config" / "dictionnaire.yaml")
    assert charger_dictionnaire(chemin) == dictionnaire
    contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    assert contenu["meta"]["periode_fin"] == "2026-03"
    assert contenu["meta"]["seuils"]["effectif_min"] == 200
    assert "Boulangerie" not in chemin.read_text(encoding="utf-8")


def test_aller_retour_des_valeurs_que_yaml_pourrait_deformer(tmp_path):
    pieges = [
        "O", "N", "Oui", "Non", "yes", "no", "on", "off", "true", "null", "~",
        "27", "076", "1e3", "46.80", "2026-03-01", "Gisors  ", "  Gisors",
        "a\u00a0b", "Réalisée", "30 j fin de mois", "clé: valeur", "# note", "- tiret",
    ]
    chemin = tmp_path / "dictionnaire.yaml"

    ecrire_dictionnaire(_dictionnaire_fictif(valeurs=pieges), "2026-03", chemin)
    relu = charger_dictionnaire(chemin)["clients"]["ville"]["valeurs"]
    assert relu["regle"] == pieges
    assert all(isinstance(valeur, str) for valeur in relu["regle"])

    a_arbitrer = [{"valeur": valeur, "effectif": 1} for valeur in pieges]
    ecrire_dictionnaire(
        _dictionnaire_fictif(valeurs=["A"], a_arbitrer=a_arbitrer), "2026-03", chemin
    )
    relu = charger_dictionnaire(chemin)["clients"]["ville"]["valeurs"]
    assert [element["valeur"] for element in relu["a_arbitrer"]] == pieges
    assert all(isinstance(element["valeur"], str) for element in relu["a_arbitrer"])


def test_les_types_numpy_sont_convertis_en_types_natifs(tmp_path):
    dictionnaire = _dictionnaire_fictif()
    dictionnaire["clients"]["ville"]["obligatoire"]["a_arbitrer"] = {"vides": np.int64(3)}
    chemin = ecrire_dictionnaire(dictionnaire, "2026-03", tmp_path / "dictionnaire.yaml")
    vides = charger_dictionnaire(chemin)["clients"]["ville"]["obligatoire"]["a_arbitrer"]["vides"]
    assert vides == 3
    assert type(vides) is int


def test_type_inattendu_refuse_sans_rien_ecrire(tmp_path):
    dictionnaire = _dictionnaire_fictif()
    dictionnaire["clients"]["ville"]["nature"]["a_arbitrer"] = {"date": pd.Timestamp("2026-03-01")}
    with pytest.raises(TypeError, match="Timestamp"):
        ecrire_dictionnaire(dictionnaire, "2026-03", tmp_path / "dictionnaire.yaml")
    assert list(tmp_path.iterdir()) == []


def test_statut_inconnu_refuse_a_l_ecriture_sans_laisser_de_fichier(tmp_path):
    dictionnaire = _dictionnaire_fictif(statut="validé")
    with pytest.raises(ValueError, match="statut inconnu"):
        ecrire_dictionnaire(dictionnaire, "2026-03", tmp_path / "dictionnaire.yaml")
    assert list(tmp_path.iterdir()) == []


def test_chargement_liste_tous_les_problemes_en_une_fois(tmp_path):
    tables = _dictionnaire_fictif(statut="à voir")
    tables["clients"]["ville"]["nature"]["statut"] = "ok"
    tables["clients"]["code"] = {"obligatoire": _regle("obligatoire")}
    del tables["clients"]["ville"]["obligatoire"]["motif"]
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, tables)
    with pytest.raises(ValueError) as erreur:
        charger_dictionnaire(chemin)
    message = str(erreur.value)
    assert "clients.ville, règle valeurs : statut inconnu 'à voir'" in message
    assert "clients.ville, règle nature : statut inconnu 'ok'" in message
    assert "clients.ville, règle obligatoire : champs attendus" in message
    assert "clients.code : règles attendues" in message


def test_statut_en_forme_decomposee_est_normalise(tmp_path):
    decompose = "observe\u0301"
    assert decompose != "observ\u00e9"
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, _dictionnaire_fictif(statut=decompose))
    statut = charger_dictionnaire(chemin)["clients"]["ville"]["valeurs"]["statut"]
    assert statut == "observ\u00e9"


def test_ecrasement_refuse_si_une_regle_a_ete_revue(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    # Tant que tout est au statut observé, la régénération est libre.
    ecrire_dictionnaire(_dictionnaire_fictif(valeurs=["A", "B"]), "2026-03", chemin)
    _ecrire_brut(chemin, _dictionnaire_fictif(valeurs=["A", "B"], statut="valide"))
    with pytest.raises(FileExistsError, match="1 règles déjà revues"):
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-04", chemin)
    assert charger_dictionnaire(chemin)["clients"]["ville"]["valeurs"]["statut"] == "valide"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-04", chemin, ecraser=True)
    assert charger_dictionnaire(chemin) == _dictionnaire_fictif()


def test_valeurs_ecrites_a_la_main_sans_guillemets_rejetees(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    dictionnaire = _dictionnaire_fictif(
        valeurs=["Oui", "PIEGE1", "PIEGE2", "PIEGE3", "PIEGE4"],
        a_arbitrer=[{"valeur": "PIEGE5", "effectif": 3}],
    )
    ecrire_dictionnaire(dictionnaire, "2026-03", chemin)
    # Saisie à la main, sans guillemets, de valeurs que YAML ne lit pas comme du texte.
    texte = chemin.read_text(encoding="utf-8")
    saisies = {
        "PIEGE1": "No",
        "PIEGE2": "27",
        "PIEGE3": "2026-03-01",
        "PIEGE4": "~",
        "PIEGE5": "Yes",
    }
    for repere, saisie in saisies.items():
        texte = texte.replace(repere, saisie)
    chemin.write_text(texte, encoding="utf-8")

    with pytest.raises(ValueError) as erreur:
        charger_dictionnaire(chemin)
    message = str(erreur.value)
    assert "False (type bool)" in message
    assert "27 (type int)" in message
    assert "(type date)" in message
    assert "None (type NoneType)" in message
    assert "True (type bool)" in message
    assert message.count("mettre la valeur entre guillemets") == 5


def test_valeurs_vides_doublons_et_effectifs_rejetes(tmp_path):
    tables = _dictionnaire_fictif(
        valeurs=["A", "A", "  "],
        a_arbitrer=[
            {"valeur": "A", "effectif": 2},
            {"valeur": "B", "effectif": 0},
            {"valeur": "C", "effectif": True},
            {"valeur": "D"},
        ],
    )
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, tables)
    with pytest.raises(ValueError) as erreur:
        charger_dictionnaire(chemin)
    message = str(erreur.value)
    assert message.count("valeur 'A' présente plusieurs fois") == 2
    assert "valeur vide ou composée d'espaces" in message
    assert "effectif 0 (type int) pour 'B'" in message
    assert "effectif True (type bool) pour 'C'" in message
    assert "champs attendus valeur, effectif" in message


@pytest.mark.parametrize(
    ("valeurs", "a_arbitrer", "attendu"),
    [
        ([], [], "liste vide"),
        (False, [], "False (type bool) au lieu de"),
        (["A"], {"B": 1}, "une liste est attendue"),
    ],
)
def test_regle_valeurs_mal_formee(tmp_path, valeurs, a_arbitrer, attendu):
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, _dictionnaire_fictif(valeurs=valeurs, a_arbitrer=a_arbitrer))
    with pytest.raises(ValueError) as erreur:
        charger_dictionnaire(chemin)
    assert attendu in str(erreur.value)