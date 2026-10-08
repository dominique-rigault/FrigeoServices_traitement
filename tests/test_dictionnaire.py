"""Tests de la génération, du contrôle et de l'écriture du dictionnaire (frigeo.dictionnaire)."""

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
    assert resultat["effectifs"] == [700, 250, 40]
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
    assert colonne["obligatoire"]["proposition"] == "obligatoire"
    assert colonne["obligatoire"]["a_arbitrer"] == {"vides": 5}
    assert colonne["nature"]["regle"] == "texte"
    valeurs = colonne["valeurs"]
    assert valeurs["regle"] == valeurs["proposition"] == "liste fermée"
    assert valeurs["a_arbitrer"] == {"valeurs": 2}
    # Valeurs principales puis valeurs rares, chacune avec son effectif.
    assert [(v["valeur"], v["origine"], v["effectif"]) for v in valeurs["liste"]] == [
        ("Réalisée", "liste proposée", 700),
        ("Annulée", "liste proposée", 250),
        ("Reportée", "liste proposée", 40),
        ("OK", "à arbitrer", 3),
        ("Fait", "à arbitrer", 2),
    ]
    assert valeurs["liste"][0] == {
        "valeur": "Réalisée",
        "origine": "liste proposée",
        "effectif": 700,
        "statut": "observé",
        "commentaire": "",
        "revu_le": None,
        "remplacement": None,
    }


def test_generer_colonne_sans_liste_fermee():
    colonne = generer_table(_table_fictive(), "clients", SENSIBLES)["commentaire"]
    assert colonne["obligatoire"]["regle"] == "facultatif"
    assert colonne["valeurs"]["regle"] == colonne["valeurs"]["proposition"] == "aucune"
    assert colonne["valeurs"]["a_arbitrer"] == {}
    assert colonne["valeurs"]["liste"] == []


def test_colonne_sensible_ne_laisse_fuiter_aucune_valeur():
    dictionnaire = generer_dictionnaire({"clients": _table_fictive()}, SENSIBLES)
    colonne = dictionnaire["clients"]["type_commerce"]
    assert colonne["valeurs"]["regle"] == "aucune"
    assert colonne["valeurs"]["motif"] == "colonne sensible"
    assert colonne["valeurs"]["liste"] == []
    assert "Boulangerie" not in repr(colonne)
    assert "Restaurant" not in repr(colonne)


def test_tout_est_au_statut_observe_et_la_regle_est_la_proposition():
    dictionnaire = generer_dictionnaire({"clients": _table_fictive()}, SENSIBLES)
    regles = [
        regle
        for colonnes in dictionnaire.values()
        for colonne in colonnes.values()
        for regle in colonne.values()
    ]
    assert len(regles) == 9
    valeurs = [valeur for regle in regles for valeur in regle.get("liste", [])]
    assert len(valeurs) == 5
    for element in regles + valeurs:
        assert element["statut"] == "observé"
        assert element["commentaire"] == ""
        assert element["revu_le"] is None
    assert all(regle["regle"] == regle["proposition"] for regle in regles)
    assert all(valeur["remplacement"] is None for valeur in valeurs)


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



def _regle(regle, statut="observé", a_arbitrer=None, revu_le=None):
    return {
        "regle": regle,
        "proposition": regle,
        "statut": statut,
        "motif": "motif fictif",
        "a_arbitrer": {} if a_arbitrer is None else a_arbitrer,
        "commentaire": "",
        "revu_le": revu_le,
    }


def _valeur(valeur, origine="liste proposée", effectif=1, statut="observé", **champs):
    element = {
        "valeur": valeur,
        "origine": origine,
        "effectif": effectif,
        "statut": statut,
        "commentaire": "",
        "revu_le": None if statut == "observé" else "2026-10-08",
        "remplacement": None,
    }
    element.update(champs)
    return element


def _dictionnaire_fictif(liste=None, statut="observé", revu_le=None):
    """Une colonne, avec une liste fermée si `liste` (des valeurs ou des textes) est donnée."""
    liste = [v if isinstance(v, dict) else _valeur(v) for v in liste or []]
    valeurs = _regle("liste fermée" if liste else "aucune", statut, revu_le=revu_le)
    valeurs["liste"] = liste
    return {
        "clients": {
            "ville": {
                "obligatoire": _regle("obligatoire", a_arbitrer={"vides": 0}),
                "nature": _regle("texte", a_arbitrer={"hors_nature": 0}),
                "valeurs": valeurs,
            }
        }
    }


def _ecrire_brut(chemin, tables, structure=2):
    """Écrit un fichier sans passer par `ecrire_dictionnaire` (cas d'un fichier modifié à la main)."""
    texte = yaml.safe_dump(
        {"meta": {"structure": structure}, "tables": tables}, allow_unicode=True
    )
    chemin.write_text(texte, encoding="utf-8")


def _erreur_chargement(tmp_path, tables) -> str:
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, tables)
    with pytest.raises(ValueError) as erreur:
        charger_dictionnaire(chemin)
    return str(erreur.value)


def test_aller_retour_du_dictionnaire_genere(tmp_path):
    dictionnaire = generer_dictionnaire({"clients": _table_fictive()}, SENSIBLES)
    chemin = ecrire_dictionnaire(dictionnaire, "2026-03", tmp_path / "config" / "dictionnaire.yaml")
    assert charger_dictionnaire(chemin) == dictionnaire
    contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    assert contenu["meta"]["structure"] == 2
    assert contenu["meta"]["periode_fin"] == "2026-03"
    assert contenu["meta"]["seuils"]["effectif_min"] == 200
    assert "Boulangerie" not in chemin.read_text(encoding="utf-8")


def test_aller_retour_des_valeurs_que_yaml_pourrait_deformer(tmp_path):
    pieges = [
        "O", "N", "Oui", "Non", "yes", "no", "on", "off", "true", "null", "~",
        "27", "076", "1e3", "46.80", "2026-03-01", "Gisors  ", "  Gisors",
        "a b", "Réalisée", "30 j fin de mois", "clé: valeur", "# note", "- tiret",
    ]
    chemin = tmp_path / "dictionnaire.yaml"
    dictionnaire = _dictionnaire_fictif(liste=pieges)
    # Une date de revue ressemble à une date pour YAML : elle doit rester un texte.
    dictionnaire["clients"]["ville"]["valeurs"]["liste"][0].update(
        statut="invalide", revu_le="2026-10-08", commentaire="non: prévu"
    )
    ecrire_dictionnaire(dictionnaire, "2026-03", chemin)
    relu = charger_dictionnaire(chemin)
    assert relu == dictionnaire
    liste = relu["clients"]["ville"]["valeurs"]["liste"]
    assert [element["valeur"] for element in liste] == pieges
    assert all(isinstance(element["valeur"], str) for element in liste)
    assert liste[0]["revu_le"] == "2026-10-08"


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


def test_fichier_a_l_ancienne_structure_refuse(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ancien = {"clients": {"ville": {"valeurs": {"regle": ["A"], "statut": "observé"}}}}
    chemin.write_text(yaml.safe_dump({"meta": {}, "tables": ancien}), encoding="utf-8")
    with pytest.raises(ValueError, match="structure None, attendue 2") as erreur:
        charger_dictionnaire(chemin)
    # Un seul message, sans la liste des écarts règle par règle.
    assert "\n" not in str(erreur.value)
    # L'écriture ne remplace pas ce fichier sans qu'on le demande.
    with pytest.raises(ValueError, match="à régénérer"):
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin, ecraser=True)
    assert charger_dictionnaire(chemin) == _dictionnaire_fictif()


def test_chargement_liste_tous_les_problemes_en_une_fois(tmp_path):
    tables = _dictionnaire_fictif(statut="à voir")
    tables["clients"]["ville"]["nature"]["statut"] = "ok"
    tables["clients"]["code"] = {"obligatoire": _regle("obligatoire")}
    del tables["clients"]["ville"]["obligatoire"]["motif"]
    message = _erreur_chargement(tmp_path, tables)
    assert "clients.ville, règle valeurs : statut inconnu 'à voir'" in message
    assert "clients.ville, règle nature : statut inconnu 'ok'" in message
    assert "clients.ville, règle obligatoire : champs attendus" in message
    assert "clients.code : règles attendues" in message


def test_statut_en_forme_decomposee_est_normalise(tmp_path):
    decompose = "observé"
    assert decompose != "observé"
    chemin = tmp_path / "dictionnaire.yaml"
    tables = _dictionnaire_fictif(liste=[_valeur("A", statut=decompose)], statut=decompose)
    _ecrire_brut(chemin, tables)
    valeurs = charger_dictionnaire(chemin)["clients"]["ville"]["valeurs"]
    assert valeurs["statut"] == "observé"
    assert valeurs["liste"][0]["statut"] == "observé"


def test_regle_en_vigueur_et_proposition(tmp_path):
    # Non revue, la règle est la proposition.
    tables = _dictionnaire_fictif()
    tables["clients"]["ville"]["obligatoire"]["regle"] = "facultatif"
    message = _erreur_chargement(tmp_path, tables)
    assert "au statut observé, la règle ('facultatif') doit être la proposition" in message
    # Revue, elle peut s'en écarter : le métier a donné sa règle.
    tables["clients"]["ville"]["obligatoire"].update(statut="documenté", revu_le="2026-10-08")
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, tables)
    relu = charger_dictionnaire(chemin)["clients"]["ville"]["obligatoire"]
    assert (relu["regle"], relu["proposition"]) == ("facultatif", "obligatoire")


def test_decision_sans_date_et_date_mal_formee(tmp_path):
    tables = _dictionnaire_fictif(
        liste=[
            _valeur("A", statut="valide", revu_le=None),
            _valeur("B", statut="invalide", revu_le="08/10/2026"),
            _valeur("C", revu_le=20261008, commentaire=None),
        ],
        statut="valide",
    )
    message = _erreur_chargement(tmp_path, tables)
    assert "règle valeurs : statut valide sans date de revue" in message
    assert "valeur 'A' : statut valide sans date de revue" in message
    assert "valeur 'B' : revu_le '08/10/2026' (type str)" in message
    assert "valeur 'C' : revu_le 20261008 (type int)" in message
    assert "valeur 'C' : commentaire None (type NoneType)" in message


def test_ecrasement_refuse_si_une_decision_a_ete_prise(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    # Tant que tout est au statut observé, la régénération est libre.
    ecrire_dictionnaire(_dictionnaire_fictif(liste=["A", "B"]), "2026-03", chemin)
    revu = _dictionnaire_fictif(
        liste=["A", _valeur("B", statut="invalide")], statut="valide", revu_le="2026-10-08"
    )
    _ecrire_brut(chemin, revu)
    # Une règle et une valeur revues.
    with pytest.raises(FileExistsError, match="2 décisions de revue"):
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-04", chemin)
    assert charger_dictionnaire(chemin) == revu
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-04", chemin, ecraser=True)
    assert charger_dictionnaire(chemin) == _dictionnaire_fictif()


def test_valeurs_ecrites_a_la_main_sans_guillemets_rejetees(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    dictionnaire = _dictionnaire_fictif(
        liste=["Oui", "PIEGE1", "PIEGE2", "PIEGE3", "PIEGE4", _valeur("PIEGE5", "à arbitrer", 3)]
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
        liste=[
            "A",
            "A",
            "  ",
            _valeur("A", "à arbitrer", 2),
            _valeur("B", "à arbitrer", 0),
            _valeur("C", "à arbitrer", True),
            _valeur("D", "à arbitrer", 0, statut="invalide"),
            _valeur("E", "inventée"),
            {"valeur": "F", "effectif": 1},
        ]
    )
    message = _erreur_chargement(tmp_path, tables)
    assert message.count("valeur 'A' présente plusieurs fois") == 2
    assert "valeur vide ou composée d'espaces" in message
    assert "valeur 'B' : effectif 0 (type int), un entier d'au moins 1" in message
    assert "valeur 'C' : effectif True (type bool)" in message
    # Une valeur revue qui n'est plus observée garde sa décision, avec un effectif nul.
    assert "valeur 'D'" not in message
    assert "valeur 'E' : origine inconnue 'inventée'" in message
    assert "champs attendus valeur, origine, effectif" in message


def test_statut_d_une_valeur_selon_son_origine(tmp_path):
    tables = _dictionnaire_fictif(
        liste=[
            _valeur("A", statut="documenté"),
            _valeur("B", "ajoutée", 0, statut="valide"),
            _valeur("C", "ajoutée", 0, statut="documenté"),
        ]
    )
    message = _erreur_chargement(tmp_path, tables)
    assert "valeur 'A' : statut 'documenté' impossible sur une valeur observée" in message
    assert "valeur 'B' : une valeur ajoutée doit porter le statut documenté" in message
    assert "valeur 'C'" not in message


def test_remplacement_d_une_valeur_invalide(tmp_path):
    liste = [
        _valeur("Réalisée", statut="valide"),
        _valeur("Terminée", "ajoutée", 0, statut="documenté"),
        _valeur("OK", "à arbitrer", 3, statut="invalide", remplacement="Réalisée"),
        _valeur("Fini", "à arbitrer", 2, statut="invalide", remplacement="Terminée"),
        _valeur("???", "à arbitrer", 1, statut="invalide"),
    ]
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(liste=liste), "2026-03", chemin)
    relu = charger_dictionnaire(chemin)["clients"]["ville"]["valeurs"]["liste"]
    assert [v["remplacement"] for v in relu] == [None, None, "Réalisée", "Terminée", None]


def test_remplacements_refuses(tmp_path):
    tables = _dictionnaire_fictif(
        liste=[
            _valeur("Réalisée", statut="valide", remplacement="Annulée"),
            _valeur("Annulée"),
            _valeur("OK", "à arbitrer", 3, statut="invalide", remplacement="Annulée"),
            _valeur("Fait", "à arbitrer", 2, statut="invalide", remplacement="OK"),
            _valeur("Fini", "à arbitrer", 2, statut="invalide", remplacement="Inconnue"),
            _valeur("Vu", "à arbitrer", 1, statut="invalide", remplacement="Vu"),
            _valeur("27", "à arbitrer", 1, statut="invalide", remplacement=27),
        ]
    )
    message = _erreur_chargement(tmp_path, tables)
    assert "valeur 'Réalisée' : remplacement réservé au statut invalide" in message
    # La cible doit être valide ou documentée : ni non revue, ni invalide (pas de chaîne).
    for valeur, cible in (("OK", "'Annulée'"), ("Fait", "'OK'"), ("Fini", "'Inconnue'"),
                          ("Vu", "'Vu'"), ("27", "27")):
        assert f"valeur {valeur!r} : remplacement {cible} (type" in message
    assert len(message.splitlines()) == 1 + 6


@pytest.mark.parametrize(
    ("modification", "attendu"),
    [
        ({"liste": []}, "liste fermée sans aucune valeur"),
        ({"regle": ["A"], "proposition": ["A"]}, "regle ['A'] (type list) au lieu de"),
        ({"regle": False, "proposition": False}, "proposition False (type bool) au lieu de"),
        ({"liste": {"A": 1}}, "une liste est attendue"),
    ],
)
def test_regle_valeurs_mal_formee(tmp_path, modification, attendu):
    tables = _dictionnaire_fictif(liste=["A"])
    tables["clients"]["ville"]["valeurs"].update(modification)
    assert attendu in _erreur_chargement(tmp_path, tables)
