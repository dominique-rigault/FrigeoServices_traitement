"""Tests de la génération, du contrôle et de l'écriture du dictionnaire (frigeo.dictionnaire)."""

from copy import deepcopy
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
import yaml

from frigeo.dictionnaire import (
    charger_dictionnaire,
    charger_meta,
    dossier_sauvegardes,
    ecrire_dictionnaire,
    horodater,
    lire_instant,
    problemes_dictionnaire,
    generer_dictionnaire,
    generer_table,
    proposer_format,
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
    assert len(regles) == 12
    valeurs = [
        valeur
        for colonne in dictionnaire["clients"].values()
        for valeur in colonne["valeurs"]["liste"]
    ]
    assert len(valeurs) == 5
    formes = [
        forme
        for colonne in dictionnaire["clients"].values()
        for forme in colonne["format"]["liste"]
    ]
    assert len(formes) == 3
    for element in regles + valeurs + formes:
        assert element["statut"] == "observé"
        assert element["commentaire"] == ""
        assert element["revu_le"] is None
    assert all(regle["regle"] == regle["proposition"] for regle in regles)
    assert all(valeur["remplacement"] is None for valeur in valeurs)
    # Ni la colonne à liste proposée ni la colonne sensible n'ont de forme.
    assert dictionnaire["clients"]["statut"]["format"]["liste"] == []
    assert dictionnaire["clients"]["type_commerce"]["format"]["liste"] == []


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
        "nb_observees",
        "motif_liste",
        "formes_fermees",
        "nb_formes",
        "nb_formes_a_arbitrer",
        "nb_formes_observees",
        "motif_format",
    ]
    assert list(resume["formes_fermees"]) == [False, False, True]
    assert resume.loc["statut", "motif_format"] == "liste de valeurs proposée"
    assert resume.loc["type_commerce", "motif_format"] == "colonne sensible"
    assert resume.loc["commentaire", "nb_formes"] == 3
    assert resume.loc["commentaire", "nb_formes_a_arbitrer"] == 0
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


def _forme(forme, origine="liste proposée", effectif=1, statut="observé", **champs):
    element = _valeur(forme, origine, effectif, statut, **champs)
    del element["valeur"], element["remplacement"]
    return {"forme": forme, **element}


def _dictionnaire_fictif(liste=None, statut="observé", revu_le=None, formes=None):
    """Une colonne, avec une liste fermée si `liste` (des valeurs ou des textes) est donnée.

    De même, avec des formes fermées si `formes` (des formes ou des textes) est donnée.
    """
    liste = [v if isinstance(v, dict) else _valeur(v) for v in liste or []]
    valeurs = _regle("liste fermée" if liste else "aucune", statut, revu_le=revu_le)
    valeurs["liste"] = liste
    regle_format = _regle("formes fermées" if formes else "aucune")
    regle_format["liste"] = [f if isinstance(f, dict) else _forme(f) for f in formes or []]
    return {
        "clients": {
            "ville": {
                "obligatoire": _regle("obligatoire", a_arbitrer={"vides": 0}),
                "nature": _regle("texte", a_arbitrer={"hors_nature": 0}),
                "valeurs": valeurs,
                "format": regle_format,
            }
        }
    }


def _ecrire_brut(chemin, tables, structure=3):
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
    assert contenu["meta"]["structure"] == 3
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
        statut="invalide", revu_le="2026-10-08 21:45:03", commentaire="non: prévu"
    )
    ecrire_dictionnaire(dictionnaire, "2026-03", chemin)
    relu = charger_dictionnaire(chemin)
    assert relu == dictionnaire
    liste = relu["clients"]["ville"]["valeurs"]["liste"]
    assert [element["valeur"] for element in liste] == pieges
    assert all(isinstance(element["valeur"], str) for element in liste)
    assert liste[0]["revu_le"] == "2026-10-08 21:45:03"


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
    with pytest.raises(ValueError, match="structure None, attendue 3") as erreur:
        charger_dictionnaire(chemin)
    # Un seul message, sans la liste des écarts règle par règle.
    assert "\n" not in str(erreur.value)
    # L'écriture ne remplace pas ce fichier sans qu'on le demande : il porte
    # peut-être des décisions qu'on ne sait plus lire.
    illisible = chemin.read_bytes()
    with pytest.raises(ValueError, match="est illisible") as refus:
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    assert "à régénérer" in str(refus.value)
    assert chemin.read_bytes() == illisible
    assert not dossier_sauvegardes(chemin).exists()
    # Avec ecraser=True, il est copié à l'identique avant d'être remplacé.
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin, ecraser=True)
    assert charger_dictionnaire(chemin) == _dictionnaire_fictif()
    copies = list(dossier_sauvegardes(chemin).iterdir())
    assert len(copies) == 1 and copies[0].name.startswith("dictionnaire_illisible_")
    assert copies[0].read_bytes() == illisible


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
            _valeur("D", statut="valide", revu_le="2026-10-08 25:00:00"),
            _valeur("E", statut="valide", revu_le="2026-10-08T10:00:00"),
            _valeur("F", statut="valide", revu_le="2026-10-08 10:00"),
            # Les deux formats admis : date seule (avant la 4d), date et heure.
            _valeur("G", statut="valide", revu_le="2026-10-08"),
            _valeur("H", statut="valide", revu_le="2026-10-08 10:00:00"),
        ],
        statut="valide",
    )
    message = _erreur_chargement(tmp_path, tables)
    for valeur, texte in (("D", "2026-10-08 25:00:00"), ("E", "2026-10-08T10:00:00"),
                          ("F", "2026-10-08 10:00")):
        assert f"valeur {valeur!r} : revu_le {texte!r} (type str)" in message
    assert "valeur 'G'" not in message and "valeur 'H'" not in message
    assert "règle valeurs : statut valide sans date de revue" in message
    assert "valeur 'A' : statut valide sans date de revue" in message
    assert "valeur 'B' : revu_le '08/10/2026' (type str)" in message
    assert "valeur 'C' : revu_le 20261008 (type int)" in message
    assert "valeur 'C' : commentaire None (type NoneType)" in message


def test_regeneration_refusee_si_une_decision_serait_perdue(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    # Tant que tout est au statut observé, la régénération est libre, sans copie.
    ecrire_dictionnaire(_dictionnaire_fictif(liste=["A", "B"]), "2026-03", chemin)
    assert not dossier_sauvegardes(chemin).exists()
    revu = _dictionnaire_fictif(
        liste=["A", _valeur("B", statut="invalide")], statut="valide", revu_le="2026-10-08"
    )
    _ecrire_brut(chemin, revu)
    avant = chemin.read_bytes()
    # Une règle et une valeur revues : toutes deux listées, ecraser n'y change rien.
    for ecraser in (False, True):
        with pytest.raises(ValueError, match="2 décisions de revue seraient perdues") as refus:
            ecrire_dictionnaire(_dictionnaire_fictif(), "2026-04", chemin, ecraser=ecraser)
        assert "clients.ville, règle valeurs : statut 'valide' devenu 'observé'" in str(refus.value)
        assert "clients.ville, valeur 'B' : décision (invalide) absente" in str(refus.value)
    assert chemin.read_bytes() == avant
    assert not dossier_sauvegardes(chemin).exists()


def _fichier_revu(tmp_path, jour="2026-10-08"):
    """Fichier en place portant une règle validée, une valeur invalidée et une revue au journal."""
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(liste=["A", "B", "C"]), "2026-03", chemin)
    revu = _dictionnaire_fictif(liste=["A", "B", "C"])
    colonne = revu["clients"]["ville"]
    colonne["obligatoire"].update(statut="valide", revu_le=jour)
    colonne["valeurs"]["liste"][1].update(statut="invalide", revu_le=jour, commentaire="faute")
    ecrire_dictionnaire(revu, "2026-03", chemin, revue=_entree(jour))
    return chemin, revu


def test_ecriture_sans_revue_conserve_chaque_decision_a_l_identique(tmp_path):
    chemin, revu = _fichier_revu(tmp_path)
    avant = chemin.read_bytes()
    # Ce que la génération observe peut changer : proposition, motif, effectif, origine.
    fusionne = deepcopy(revu)
    colonne = fusionne["clients"]["ville"]
    colonne["obligatoire"].update(proposition="facultatif", motif="12.00 % de vides")
    colonne["valeurs"]["liste"][1].update(effectif=0, origine="à arbitrer")
    colonne["nature"]["commentaire"] = "note sur une règle non revue"
    ecrire_dictionnaire(fusionne, "2026-04", chemin)
    assert charger_dictionnaire(chemin) == fusionne
    copies = list(dossier_sauvegardes(chemin).iterdir())
    assert len(copies) == 1 and copies[0].read_bytes() == avant
    assert copies[0].name.startswith("dictionnaire_2026-03_") and copies[0].suffix == ".yaml"

    # Chaque composante d'une décision est protégée, et aucune décision n'apparaît.
    for modification, attendu in (
        (lambda c: c["obligatoire"].update(commentaire="autre"), "commentaire '' devenu 'autre'"),
        (lambda c: c["obligatoire"].update(revu_le="2026-10-08 10:00:00"), "revu_le '2026-10-08' devenu"),
        (lambda c: c["obligatoire"].update(statut="documenté", regle="facultatif"),
         "statut 'valide' devenu 'documenté', regle 'obligatoire' devenu 'facultatif'"),
        (lambda c: c["valeurs"]["liste"][0].update(statut="valide", revu_le="2026-10-09"),
         "valeur 'A' : décision (valide) absente du fichier en place"),
        (lambda c: c["valeurs"]["liste"].pop(1), "valeur 'B' : décision (invalide) absente"),
    ):
        essai = deepcopy(fusionne)
        modification(essai["clients"]["ville"])
        with pytest.raises(ValueError, match="1 décisions de revue") as refus:
            ecrire_dictionnaire(essai, "2026-04", chemin)
        assert attendu in str(refus.value)
    assert charger_dictionnaire(chemin) == fusionne
    assert len(list(dossier_sauvegardes(chemin).iterdir())) == 1


def test_ecriture_avec_revue_n_admet_que_les_decisions_datees_de_la_revue(tmp_path):
    chemin, revu = _fichier_revu(tmp_path)
    instant = "2026-10-08 21:45:03"
    # Une date seule, écrite avant l'horodatage, vaut minuit : la revue du soir passe.
    suivant = deepcopy(revu)
    colonne = suivant["clients"]["ville"]
    colonne["obligatoire"].update(statut="documenté", regle="facultatif", revu_le=instant)
    colonne["nature"].update(statut="valide", revu_le=instant)
    colonne["valeurs"]["liste"][0].update(statut="valide", revu_le=instant)
    # Décision annulée, valeur retirée, commentaire seul.
    colonne["valeurs"]["liste"][1].update(statut="observé", revu_le=None, commentaire="")
    del colonne["valeurs"]["liste"][2]
    ecrire_dictionnaire(suivant, "2026-03", chemin, revue=_entree(instant, "revue2.xlsx"))
    assert charger_dictionnaire(chemin) == suivant
    assert [r["date"] for r in charger_meta(chemin)["revues"]] == ["2026-10-08", instant]
    assert len(list(dossier_sauvegardes(chemin).iterdir())) == 1

    plus_tard = "2026-10-09 08:00:00"
    for modification, attendu in (
        # Décision changée sans prendre la date de la revue.
        (lambda c: c["nature"].update(statut="invalide", regle="aucune"),
         f"règle nature : décision changée, mais sa date ({instant}) n'est pas celle de la revue"),
        # Décision nouvelle datée d'un autre moment.
        (lambda c: c["valeurs"]["liste"][1].update(statut="valide", revu_le="2026-10-09 07:00:00"),
         "valeur 'B' : décision changée, mais sa date (2026-10-09 07:00:00)"),
        # Date déplacée sans changement de décision.
        (lambda c: c["nature"].update(revu_le=plus_tard),
         f"règle nature : revu_le {instant!r} devenu {plus_tard!r} sans changement de décision"),
        # Colonne disparue avec ses décisions.
        (lambda c: c.pop("nature"), "règle nature : décision (valide) absente"),
    ):
        essai = deepcopy(suivant)
        modification(essai["clients"]["ville"])
        if "nature" not in essai["clients"]["ville"]:
            essai["clients"]["autre"] = essai["clients"].pop("ville")
            essai["clients"]["autre"]["nature"] = _regle("texte")
        with pytest.raises(ValueError, match="écriture refusée") as refus:
            ecrire_dictionnaire(essai, "2026-03", chemin, revue=_entree(plus_tard, "revue3.xlsx"))
        assert attendu in str(refus.value)
    assert charger_dictionnaire(chemin) == suivant
    assert len(charger_meta(chemin)["revues"]) == 2


def test_revue_refusee_si_elle_n_est_pas_posterieure_a_la_derniere(tmp_path):
    chemin, revu = _fichier_revu(tmp_path, "2026-10-08 21:45:03")
    suivant = deepcopy(revu)
    for instant in ("2026-10-08 21:45:03", "2026-10-08 21:45:02", "2026-10-08"):
        suivant["clients"]["ville"]["nature"].update(statut="valide", revu_le=instant)
        with pytest.raises(ValueError, match="doit être postérieure à la dernière revue"):
            ecrire_dictionnaire(suivant, "2026-03", chemin, revue=_entree(instant))
    assert charger_dictionnaire(chemin) == revu
    suivant["clients"]["ville"]["nature"].update(statut="valide", revu_le="2026-10-08 21:45:04")
    ecrire_dictionnaire(suivant, "2026-03", chemin, revue=_entree("2026-10-08 21:45:04"))
    assert len(charger_meta(chemin)["revues"]) == 2


def test_une_copie_de_sauvegarde_n_est_jamais_ecrasee(tmp_path, monkeypatch):
    chemin, revu = _fichier_revu(tmp_path)
    monkeypatch.setattr(
        "frigeo.dictionnaire._maintenant", lambda: datetime(2026, 10, 8, 21, 45, 3)
    )
    ecrire_dictionnaire(revu, "2026-03", chemin)
    copie = dossier_sauvegardes(chemin) / "dictionnaire_2026-03_2026-10-08_214503.yaml"
    assert [c.name for c in dossier_sauvegardes(chemin).iterdir()] == [copie.name]
    contenu, en_place = copie.read_bytes(), chemin.read_bytes()
    # Seconde écriture dans la même seconde : ni la copie ni le fichier ne bougent.
    autre = deepcopy(revu)
    autre["clients"]["ville"]["nature"]["motif"] = "autre motif"
    with pytest.raises(FileExistsError, match="existe déjà : rien n'est écrit"):
        ecrire_dictionnaire(autre, "2026-03", chemin)
    assert copie.read_bytes() == contenu and chemin.read_bytes() == en_place
    assert [c.name for c in tmp_path.iterdir() if c.is_file()] == ["dictionnaire.yaml"]


def test_journal_seul_suffit_a_declencher_la_copie(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin, revue=_entree())
    assert not dossier_sauvegardes(chemin).exists()
    # Plus aucune décision, mais un journal : le fichier est copié avant remplacement.
    ecrire_dictionnaire(_dictionnaire_fictif(liste=["A"]), "2026-04", chemin)
    assert len(list(dossier_sauvegardes(chemin).iterdir())) == 1


def test_lire_instant_et_horodater():
    assert lire_instant("2026-10-08 21:45:03") == datetime(2026, 10, 8, 21, 45, 3)
    assert lire_instant("2026-10-08") == datetime(2026, 10, 8)
    for refuse in ("2026-10-8", "2026-02-30", "08/10/2026", "2026-10-08 21:45", "", None, 20261008,
                   date(2026, 10, 8)):
        assert lire_instant(refuse) is None
    assert horodater(datetime(2026, 10, 8, 21, 45, 3, 999)) == "2026-10-08 21:45:03"
    assert horodater(date(2026, 10, 8)) == horodater("2026-10-08") == "2026-10-08 00:00:00"
    assert lire_instant(horodater()) is not None
    with pytest.raises(ValueError, match="AAAA-MM-JJ HH:MM:SS"):
        horodater("08/10/2026")


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


# Cohérence entre statut et règle en vigueur, journal des revues (morceau 4c).


@pytest.mark.parametrize(
    "regle, champs, attendu",
    [
        ("obligatoire", dict(statut="invalide"), "au statut invalide, la règle ('obligatoire') doit être « aucune »"),
        ("obligatoire", dict(statut="valide", regle="à décider"), "au statut valide, la règle ne peut pas être « à décider »"),
        ("valeurs", dict(statut="valide"), "au statut valide, la règle ne peut pas être « aucune »"),
        ("nature", dict(statut="documenté", regle="presque texte"), "au statut documenté, la règle ('presque texte') doit être parmi texte, nombre natif"),
        ("valeurs", dict(statut="documenté"), "au statut documenté, la règle ('aucune') doit être parmi liste fermée"),
    ],
)
def test_statut_et_regle_en_vigueur_incoherents(tmp_path, regle, champs, attendu):
    tables = _dictionnaire_fictif()
    tables["clients"]["ville"][regle].update(revu_le="2026-10-08", **champs)
    assert attendu in _erreur_chargement(tmp_path, tables)
    assert any(attendu in probleme for probleme in problemes_dictionnaire(tables))


def test_statut_et_regle_en_vigueur_coherents(tmp_path):
    tables = _dictionnaire_fictif(liste=["A", "B"])
    colonne = tables["clients"]["ville"]
    colonne["obligatoire"].update(statut="invalide", regle="aucune", revu_le="2026-10-08")
    colonne["nature"].update(statut="documenté", regle="date native", revu_le="2026-10-08")
    # Liste écartée : la règle ne vaut plus rien, les valeurs restent.
    colonne["valeurs"].update(statut="invalide", regle="aucune", revu_le="2026-10-08")
    assert problemes_dictionnaire(tables) == []
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, tables)
    assert charger_dictionnaire(chemin) == tables


def _entree(jour="2026-10-09", classeur="revue.xlsx"):
    return {
        "date": jour,
        "classeur": classeur,
        "regles_changees": 2,
        "valeurs_changees": 1,
        "valeurs_ajoutees": 0,
        "formes_changees": 0,
        "formes_ajoutees": 0,
        "commentaires_changes": 0,
    }


def test_journal_vide_a_la_generation_et_pour_un_fichier_anterieur(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    meta = charger_meta(chemin)
    assert (meta["structure"], meta["periode_fin"], meta["revues"]) == (3, "2026-03", [])
    # Fichier écrit avant le journal : pas de clé « revues ».
    _ecrire_brut(chemin, _dictionnaire_fictif())
    assert charger_meta(chemin)["revues"] == []


def test_revue_ajoutee_au_journal_sans_toucher_au_reste_de_meta(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    contenu["meta"]["genere_le"] = "2026-09-30"
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")

    revu = _dictionnaire_fictif()
    revu["clients"]["ville"]["obligatoire"].update(statut="valide", revu_le="2026-10-09")
    ecrire_dictionnaire(revu, "2026-03", chemin, revue=_entree())
    meta = charger_meta(chemin)
    # L'application d'un classeur ne régénère rien : la date de génération reste.
    assert meta["genere_le"] == "2026-09-30"
    assert meta["revues"] == [_entree()]
    assert charger_dictionnaire(chemin) == revu

    ecrire_dictionnaire(revu, "2026-03", chemin, revue=_entree("2026-11-02", "revue2.xlsx"))
    assert [r["classeur"] for r in charger_meta(chemin)["revues"]] == ["revue.xlsx", "revue2.xlsx"]


def test_regeneration_conserve_le_journal(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin, revue=_entree())
    # Mois suivant : le bloc meta est refait, le journal est repris.
    ecrire_dictionnaire(_dictionnaire_fictif(liste=["A"]), "2026-04", chemin)
    meta = charger_meta(chemin)
    assert meta["periode_fin"] == "2026-04"
    assert meta["revues"] == [_entree()]


def test_revue_refusee_sans_dictionnaire_en_place_ou_pour_une_autre_periode(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    with pytest.raises(ValueError, match="aucun dictionnaire lisible en place"):
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin, revue=_entree())
    assert not chemin.exists()
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    with pytest.raises(ValueError, match="dictionnaire de la période 2026-03"):
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-04", chemin, revue=_entree())
    assert charger_meta(chemin)["revues"] == []


def test_journal_mal_forme_refuse(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    mauvaise = {**_entree(jour="09/10/2026"), "valeurs_ajoutees": -1}
    with pytest.raises(ValueError) as erreur:
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin, revue=mauvaise)
    assert "date '09/10/2026'" in str(erreur.value)
    assert "valeurs_ajoutees -1" in str(erreur.value)
    assert charger_meta(chemin)["revues"] == []
    # Journal modifié à la main dans le fichier.
    contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    contenu["meta"]["revues"] = [{"date": "2026-10-09"}]
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="journal des revues, entrée 1"):
        charger_meta(chemin)


# Liste fermée déclarée par le métier (morceau 5a).


def test_liste_declaree_par_le_metier(tmp_path):
    tables = _dictionnaire_fictif()
    regle = tables["clients"]["ville"]["valeurs"]
    regle.update(statut="documenté", regle="liste fermée", revu_le="2026-10-09 10:00:00")
    # Sans valeur du tout, puis avec une seule valeur observée et non revue.
    assert "liste fermée sans aucune valeur" in _erreur_chargement(tmp_path, tables)
    regle["liste"] = [_valeur("Gisors", "à arbitrer", 3)]
    attendu = "clients.ville, liste de valeurs : liste déclarée sans aucune valeur valide ou documentée"
    assert attendu in _erreur_chargement(tmp_path, tables)
    assert attendu in problemes_dictionnaire(tables)
    # Une valeur ajoutée par le métier suffit; la proposition reste « aucune ».
    regle["liste"].append(_valeur("Vernon", "ajoutée", 0, statut="documenté"))
    assert problemes_dictionnaire(tables) == []
    chemin = tmp_path / "declaree.yaml"
    _ecrire_brut(chemin, tables)
    assert charger_dictionnaire(chemin) == tables


# Colonnes candidates et effectif masqué des colonnes sensibles (morceau 5b).


def test_colonne_candidate_rend_ses_valeurs_observees():
    # Sous le seuil d'effectif : pas de liste proposée, mais les valeurs sont rendues.
    petite = _serie(("Actif", 20), ("Inactif", 5), ("actif", 1), (None, 2))
    resultat = proposer_liste(petite)
    assert not resultat["liste_fermee"]
    assert resultat["motif"] == "effectif insuffisant (26 valeurs renseignées, 200 requises)"
    assert resultat["observees"] == [
        {"valeur": "Actif", "effectif": 20},
        {"valeur": "Inactif", "effectif": 5},
        {"valeur": "actif", "effectif": 1},
    ]
    assert all(type(v["effectif"]) is int for v in resultat["observees"])
    # Une nature non textuelle n'empêche pas d'être candidate (codes de secteur).
    assert len(proposer_liste(_serie(("27", 10), ("76", 8)))["observees"]) == 2
    # Aucune valeur répétée (identifiant), ou trop de valeurs distinctes : rien.
    assert proposer_liste(_serie(*((f"C{i}", 1) for i in range(10))))["observees"] == []
    assert proposer_liste(_serie(*((f"V{i}", 2) for i in range(13))))["observees"] == []
    # Plus d'une valeur distincte pour deux valeurs renseignées : presque individuel.
    presque = _serie(("Dupont", 2), *((f"Nom{i}", 1) for i in range(7)))
    assert proposer_liste(presque)["observees"] == []
    assert len(proposer_liste(_serie(("A", 1), ("B", 1), ("C", 4)))["observees"]) == 3
    # Colonne sensible : aucune valeur, même candidate.
    sensible = proposer_liste(petite, "clients", "type_commerce", SENSIBLES)
    assert (sensible["motif"], sensible["observees"]) == ("colonne sensible", [])
    # Au-dessus du seuil, une colonne sans liste proposée ne rend rien.
    grande = _serie(*((f"V{i}", 20) for i in range(13)))
    assert proposer_liste(grande)["observees"] == []


def test_generer_colonne_candidate():
    table = pd.DataFrame({"statut": ["Actif"] * 20 + ["Inactif"] * 5 + ["actif"]}, dtype=object)
    regle = generer_table(table, "fournisseurs", {})["statut"]["valeurs"]
    assert (regle["regle"], regle["proposition"], regle["a_arbitrer"]) == ("aucune", "aucune", {})
    assert [(v["valeur"], v["origine"], v["effectif"], v["statut"]) for v in regle["liste"]] == [
        ("Actif", "observée", 20, "observé"),
        ("Inactif", "observée", 5, "observé"),
        ("actif", "observée", 1, "observé"),
    ]
    dictionnaire = {"fournisseurs": generer_table(table, "fournisseurs", {})}
    assert problemes_dictionnaire(dictionnaire) == []
    assert resumer_dictionnaire(dictionnaire).loc[0, "nb_observees"] == 3


def test_effectif_masque_reserve_aux_colonnes_sensibles(tmp_path):
    tables = _dictionnaire_fictif()
    regle = tables["clients"]["ville"]["valeurs"]
    regle.update(motif="colonne sensible", statut="documenté", regle="liste fermée",
                 revu_le="2026-10-09 10:00:00")
    regle["liste"] = [_valeur("Retraite", "ajoutée", None, statut="documenté")]
    assert problemes_dictionnaire(tables) == []
    chemin = ecrire_dictionnaire(tables, "2026-03", tmp_path / "dictionnaire.yaml")
    assert charger_dictionnaire(chemin) == tables
    assert "effectif: null" in chemin.read_text(encoding="utf-8")
    # Colonne sensible : ni effectif, même nul, ni valeur non revue.
    regle["liste"] = [
        _valeur("Retraite", "ajoutée", 0, statut="documenté"),
        _valeur("Démission", "observée", None),
    ]
    problemes = problemes_dictionnaire(tables)
    assert any("valeur 'Retraite' : effectif 0 (type int) dans une colonne sensible" in p
               for p in problemes)
    assert any("valeur 'Démission' : valeur non revue dans une colonne sensible" in p
               for p in problemes)
    # Ailleurs, un effectif masqué est refusé.
    tables = _dictionnaire_fictif(liste=[_valeur("Gisors", effectif=None)])
    assert any("effectif None (type NoneType), un entier d'au moins 1" in p
               for p in problemes_dictionnaire(tables))


@pytest.mark.parametrize(
    ("valeurs", "candidate"),
    [
        ([("31/01/2026", 5), ("28/02/2026", 4)], False),
        ([("2026-01-31", 5), ("2026-02-28", 4)], False),
        ([(datetime(2026, 1, 31), 5), (datetime(2026, 2, 28), 4)], False),
        ([("08:00", 5), ("14:00", 4)], False),
        ([("2100,50", 5), ("1850,00", 4)], False),
        ([("0.8", 5), ("1.0", 4)], False),
        ([(0.8, 5), (1.0, 4)], False),
        ([(27, 5), (76, 4)], True),
        ([(27.0, 5), (76.0, 4)], True),
        ([("27", 5), ("76", 4)], True),
        # Quelques valeurs ressemblant à des dates ne changent pas la nature d'un libellé.
        ([("Actif", 6), ("Inactif", 3), ("31/01/2026", 2)], True),
    ],
)
def test_nature_d_une_colonne_candidate(valeurs, candidate):
    assert bool(proposer_liste(_serie(*valeurs))["observees"]) is candidate


# Règle de format : formes fermées, colonnes candidates et structure 3 (morceau 6a).


def _codes(*modeles) -> pd.Series:
    """Série de codes tous distincts, à partir de couples (modèle, effectif).

    Des valeurs distinctes écartent la liste de valeurs : seule la forme se répète.
    """
    return pd.Series(
        [modele.format(i) for modele, n in modeles for i in range(n)], dtype=object
    )


def test_format_propose_avec_formes_rares_a_arbitrer():
    codes = pd.concat(
        [
            _codes(("CL-{:04d}", 993), ("CL{:04d}", 4), ("cl-{:04d}", 3)),
            pd.Series([None, "", "  ", None, ""], dtype=object),
        ],
        ignore_index=True,
    )
    resultat = proposer_format(codes)
    assert resultat["formes_fermees"] is True
    assert resultat["motif"] == "1 formes principales couvrant 99.3 % des valeurs renseignées"
    assert (resultat["formes"], resultat["effectifs"]) == (["AA-9999"], [993])
    # Jamais déclarées valides : à arbitrer, par effectif décroissant.
    assert resultat["a_arbitrer"] == [
        {"forme": "AA9999", "effectif": 4},
        {"forme": "aa-9999", "effectif": 3},
    ]
    assert resultat["observees"] == []


def test_format_jusqu_a_trois_formes_principales_pour_un_texte():
    trois = _codes(("AB-{:03d}", 400), ("ABC-{:03d}", 300), ("A-{:03d}", 300))
    # À effectif égal, l'ordre alphabétique des formes départage.
    assert proposer_format(trois)["formes"] == ["AA-999", "A-999", "AAA-999"]
    quatre = _codes(
        ("AB-{:03d}", 400), ("ABC-{:03d}", 300), ("A-{:03d}", 200), ("ABCD-{:03d}", 100)
    )
    resultat = proposer_format(quatre)
    assert resultat["formes_fermees"] is False
    assert resultat["motif"] == "4 formes principales (maximum 3)"
    assert resultat["formes"] == resultat["a_arbitrer"] == resultat["observees"] == []


def test_format_une_seule_forme_pour_un_entier():
    # Un code postal a une longueur fixe, une durée non.
    codes_postaux = _codes(("27{:03d}", 600), ("76{:03d}", 398), ("27{:02d}", 2))
    resultat = proposer_format(codes_postaux)
    assert resultat["formes"] == ["99999"]
    assert resultat["a_arbitrer"] == [{"forme": "9999", "effectif": 2}]
    durees = pd.Series(
        [str(10 + i % 90) for i in range(600)] + [str(100 + i % 300) for i in range(400)],
        dtype=object,
    )
    assert proposer_format(durees)["motif"] == "2 formes principales (maximum 1)"


def test_format_couverture_insuffisante():
    serie = pd.Series(
        [f"AB-{i:03d}" for i in range(900)] + [f"X{'y' * i}" for i in range(100)], dtype=object
    )
    resultat = proposer_format(serie)
    assert resultat["formes_fermees"] is False
    assert resultat["motif"] == (
        "formes principales couvrant 90.0 % des valeurs renseignées (minimum 95 %)"
    )


def test_format_ecarte_par_la_liste_de_valeurs_la_nature_ou_la_sensibilite():
    statut = _serie(("Actif", 700), ("Inactif", 300))
    assert proposer_format(statut)["motif"] == "liste de valeurs proposée"
    petite_liste = _serie(("CDI", 12), ("CDD", 6))
    assert proposer_format(petite_liste)["motif"] == "colonne candidate à une liste de valeurs"
    dates = pd.Series([f"{j:02d}/03/2025" for j in range(1, 29)] * 10, dtype=object)
    assert proposer_format(dates)["motif"] == "nature date JJ/MM/AAAA"
    montants = pd.Series([f"{i},50" for i in range(300)], dtype=object)
    assert proposer_format(montants)["motif"] == "nature décimal virgule (texte)"
    natifs = pd.Series(range(1000, 1300), dtype=object)
    assert proposer_format(natifs)["motif"] == "nature nombre natif"
    assert proposer_format(pd.Series([None, " "], dtype=object))["motif"] == (
        "aucune valeur renseignée"
    )
    codes = pd.Series([f"CL-{i:04d}" for i in range(300)], dtype=object)
    sensible = proposer_format(codes, "clients", "code", {"clients": frozenset({"code"})})
    assert sensible == {
        "formes_fermees": False,
        "motif": "colonne sensible",
        "formes": [],
        "effectifs": [],
        "a_arbitrer": [],
        "observees": [],
    }
    assert proposer_format(codes, "clients", "code", {"clients": frozenset()})["formes"] == [
        "AA-9999"
    ]


def test_format_colonne_candidate_sous_le_seuil_d_effectif():
    matricules = pd.Series([f"M{i:03d}" for i in range(18)], dtype=object)
    resultat = proposer_format(matricules)
    assert resultat["formes_fermees"] is False
    assert resultat["motif"] == "effectif insuffisant (18 valeurs renseignées, 200 requises)"
    assert resultat["observees"] == [{"forme": "A999", "effectif": 18}]
    # Trop de formes distinctes : rien n'est rendu.
    libres = _codes(("Ab{:02d}", 5), ("Abc{:02d}", 5), ("Abcd{:02d}", 5), ("Abcde{:02d}", 5))
    assert proposer_format(libres)["motif"].startswith("effectif insuffisant")
    assert proposer_format(libres)["observees"] == []
    # Un entier n'admet qu'une forme, même sous le seuil.
    codes = _codes(("27{:03d}", 20), ("27{:02d}", 6))
    assert proposer_format(codes)["motif"].startswith("effectif insuffisant")
    assert proposer_format(codes)["observees"] == []
    assert proposer_format(_codes(("27{:03d}", 26)))["observees"] == [
        {"forme": "99999", "effectif": 26}
    ]
    # Une date ou un nombre natif ne sont pas des codes.
    dates = pd.Series([f"{j:02d}/03/2025" for j in range(1, 21)], dtype=object)
    assert proposer_format(dates)["motif"] == "nature date JJ/MM/AAAA"
    assert proposer_format(pd.Series(range(100, 120), dtype=object))["motif"] == (
        "nature nombre natif"
    )


def test_format_seuils_parametrables():
    codes = _codes(("AB-{:02d}", 30), ("ABC-{:02d}", 20))
    assert proposer_format(codes)["formes_fermees"] is False
    resultat = proposer_format(codes, effectif_min=50)
    assert resultat["formes"] == ["AA-99", "AAA-99"]
    assert proposer_format(codes, effectif_min=50, max_formes=1)["formes_fermees"] is False
    rare = _codes(("AB-{:03d}", 97), ("ab-{:03d}", 3))
    assert proposer_format(rare, effectif_min=50)["formes"] == ["AA-999", "aa-999"]
    assert proposer_format(rare, effectif_min=50, part_min=0.05)["a_arbitrer"] == [
        {"forme": "aa-999", "effectif": 3}
    ]
    assert proposer_format(rare, effectif_min=50, part_min=0.05, couverture_min=0.99)[
        "formes_fermees"
    ] is False


def _table_de_codes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code_client": pd.Series(
                [f"CL-{i:04d}" for i in range(996)] + ["CL0996", "cl-0997", "", None],
                dtype=object,
            ),
            "matricule": pd.Series([f"M{i % 18:03d}" for i in range(1000)], dtype=object),
            "salaire": pd.Series([f"S-{i:04d}" for i in range(1000)], dtype=object),
        }
    )


def test_generer_colonne_avec_format():
    table = generer_table(_table_de_codes(), "paie", {"paie": frozenset({"salaire"})})
    assert list(table["code_client"]) == ["obligatoire", "nature", "valeurs", "format"]
    regle = table["code_client"]["format"]
    assert regle["regle"] == regle["proposition"] == "formes fermées"
    assert regle["statut"] == "observé"
    assert regle["a_arbitrer"] == {"formes": 2}
    assert [(f["forme"], f["origine"], f["effectif"]) for f in regle["liste"]] == [
        ("AA-9999", "liste proposée", 996),
        ("AA9999", "à arbitrer", 1),
        ("aa-9999", "à arbitrer", 1),
    ]
    assert regle["liste"][0] == {
        "forme": "AA-9999",
        "origine": "liste proposée",
        "effectif": 996,
        "statut": "observé",
        "commentaire": "",
        "revu_le": None,
    }
    # 18 valeurs distinctes pour 1000 lignes : ni liste (trop de valeurs), ni colonne
    # candidate à une liste, mais une seule forme.
    assert table["matricule"]["valeurs"]["liste"] == []
    assert [f["forme"] for f in table["matricule"]["format"]["liste"]] == ["A999"]
    # Colonne sensible : aucune forme observée, et le motif qui masque les effectifs.
    sensible = table["salaire"]["format"]
    assert (sensible["regle"], sensible["motif"], sensible["liste"]) == (
        "aucune", "colonne sensible", [],
    )
    assert "A-9999" not in repr(table["salaire"])


def test_generer_colonne_candidate_a_un_format():
    donnees = pd.DataFrame({"matricule": pd.Series([f"M{i:03d}" for i in range(18)], dtype=object)})
    regle = generer_table(donnees, "intervenants", {})["matricule"]["format"]
    assert (regle["regle"], regle["proposition"], regle["a_arbitrer"]) == ("aucune", "aucune", {})
    assert [(f["forme"], f["origine"], f["effectif"]) for f in regle["liste"]] == [
        ("A999", "observée", 18)
    ]


def test_aller_retour_d_un_dictionnaire_avec_formats(tmp_path):
    dictionnaire = generer_dictionnaire(
        {"paie": _table_de_codes()}, {"paie": frozenset({"salaire"})}
    )
    chemin = ecrire_dictionnaire(dictionnaire, "2026-03", tmp_path / "dictionnaire.yaml")
    assert charger_dictionnaire(chemin) == dictionnaire
    assert charger_meta(chemin)["structure"] == 3


def test_fichier_de_structure_2_complete_a_la_lecture(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    tables = _dictionnaire_fictif(liste=[_valeur("A", statut="valide")], statut="valide",
                                  revu_le="2026-10-08")
    tables["clients"]["salaire"] = deepcopy(_dictionnaire_fictif()["clients"]["ville"])
    tables["clients"]["salaire"]["valeurs"]["motif"] = "colonne sensible"
    attendu = deepcopy(tables)
    for colonne in tables["clients"].values():
        del colonne["format"]
    _ecrire_brut(chemin, tables, structure=2)
    avant = chemin.read_bytes()

    relu = charger_dictionnaire(chemin)
    regle = relu["clients"]["ville"]["format"]
    assert set(relu["clients"]["ville"]) == {"obligatoire", "nature", "valeurs", "format"}
    assert (regle["regle"], regle["proposition"], regle["statut"], regle["liste"]) == (
        "aucune", "aucune", "observé", [],
    )
    assert regle["motif"] == "règle absente du fichier (structure 2), à régénérer puis fusionner"
    assert relu["clients"]["salaire"]["format"]["motif"] == "colonne sensible"
    # Les décisions sont lues telles quelles, et la lecture ne modifie pas le fichier.
    assert relu["clients"]["ville"]["valeurs"] == attendu["clients"]["ville"]["valeurs"]
    assert charger_meta(chemin)["structure"] == 3
    assert chemin.read_bytes() == avant

    # L'écriture passe à la structure 3, après copie du fichier qui porte des décisions.
    ecrire_dictionnaire(relu, "2026-03", chemin)
    assert yaml.safe_load(chemin.read_text(encoding="utf-8"))["meta"]["structure"] == 3
    assert charger_dictionnaire(chemin) == relu
    copies = list(dossier_sauvegardes(chemin).iterdir())
    assert len(copies) == 1 and copies[0].read_bytes() == avant
    # Une régénération brute reste refusée : elle perdrait les décisions.
    with pytest.raises(ValueError, match="écriture refusée, 2 décisions"):
        ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)


def test_fichier_de_structure_inconnue_refuse(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    for structure in (1, 4, "3"):
        _ecrire_brut(chemin, _dictionnaire_fictif(), structure=structure)
        with pytest.raises(ValueError, match="attendue 3. Le fichier est à régénérer"):
            charger_dictionnaire(chemin)


def test_structure_3_exige_la_regle_format(tmp_path):
    tables = _dictionnaire_fictif()
    del tables["clients"]["ville"]["format"]
    message = _erreur_chargement(tmp_path, tables)
    assert "clients.ville : règles attendues obligatoire, nature, valeurs, format" in message


def test_liste_de_formes_controlee_au_chargement(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    correct = _dictionnaire_fictif(
        formes=[
            _forme("AA-9999", effectif=990),
            _forme("AA9999", "à arbitrer", 6, statut="invalide"),
            _forme("AA-99999", "ajoutée", 0, statut="documenté"),
        ]
    )
    _ecrire_brut(chemin, correct)
    assert charger_dictionnaire(chemin) == correct

    tables = _dictionnaire_fictif(
        formes=[
            _forme("AA-9999"),
            _forme("AA-9999"),
            _forme("CL-0001"),
            _forme(9999),
            _forme(" "),
            _forme("AA", "ajoutée", 0),
            _forme("A9", statut="documenté"),
            _forme("A99", effectif=0),
            _forme("A999", origine="inventée"),
            {**_forme("A9999"), "remplacement": None},
        ]
    )
    message = _erreur_chargement(tmp_path, tables)
    ou = "clients.ville"
    for attendu in (
        f"{ou}, liste de formes : forme 'AA-9999' présente plusieurs fois",
        f"{ou}, forme 'CL-0001' : ce n'est pas une forme (9 pour un chiffre",
        f"{ou}, liste de formes : 9999 (type int) n'est pas un texte, mettre la forme entre",
        f"{ou}, liste de formes : forme vide ou composée d'espaces",
        f"{ou}, forme 'AA' : une forme ajoutée doit porter le statut documenté",
        f"{ou}, forme 'A9' : statut 'documenté' impossible sur une forme observée",
        f"{ou}, forme 'A99' : effectif 0 (type int), un entier d'au moins 1 est attendu",
        f"{ou}, forme 'A999' : origine inconnue 'inventée'",
        f"{ou}, liste de formes : champs attendus forme, origine, effectif, statut",
    ):
        assert attendu in message, attendu


def test_regle_format_mal_formee_ou_incoherente(tmp_path):
    tables = _dictionnaire_fictif()
    tables["clients"]["ville"]["format"].update(
        regle="formes fermées", proposition="formes fermées"
    )
    message = _erreur_chargement(tmp_path, tables)
    assert "liste de formes : formes fermées sans aucune forme" in message

    tables = _dictionnaire_fictif()
    tables["clients"]["ville"]["format"].update(regle="liste fermée", proposition="liste fermée")
    message = _erreur_chargement(tmp_path, tables)
    assert (
        "règle format : regle 'liste fermée' (type str) au lieu de « formes fermées » ou « aucune »"
        in message
    )

    # Format déclaré par le métier : au moins une forme valide ou documentée.
    tables = _dictionnaire_fictif(formes=[_forme("A999", "observée", 18)])
    tables["clients"]["ville"]["format"].update(
        regle="formes fermées", proposition="aucune", statut="documenté", revu_le="2026-10-09"
    )
    message = _erreur_chargement(tmp_path, tables)
    assert "liste de formes : format déclaré sans aucune forme valide ou documentée" in message
    tables["clients"]["ville"]["format"]["liste"][0].update(statut="valide", revu_le="2026-10-09")
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, tables)
    assert charger_dictionnaire(chemin) == tables


def test_forme_d_une_colonne_sensible_sans_effectif(tmp_path):
    tables = _dictionnaire_fictif(
        formes=[_forme("A-9999", "ajoutée", None, statut="documenté")]
    )
    regle = tables["clients"]["ville"]["format"]
    regle.update(
        regle="formes fermées", proposition="aucune", statut="documenté",
        revu_le="2026-10-09", motif="colonne sensible",
    )
    chemin = tmp_path / "dictionnaire.yaml"
    _ecrire_brut(chemin, tables)
    assert charger_dictionnaire(chemin) == tables
    regle["liste"][0]["effectif"] = 0
    regle["liste"].append(_forme("A-999", "observée", 3))
    message = _erreur_chargement(tmp_path, tables)
    assert "forme 'A-9999' : effectif 0 (type int) dans une colonne sensible" in message
    assert "forme 'A-999' : forme non revue dans une colonne sensible" in message


def test_decisions_sur_les_formes_protegees_a_l_ecriture(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    revu = _dictionnaire_fictif(
        formes=[
            _forme("AA-9999", effectif=990, statut="valide"),
            _forme("AA9999", "à arbitrer", 6, statut="invalide", commentaire="tiret oublié"),
        ]
    )
    revu["clients"]["ville"]["format"].update(statut="valide", revu_le="2026-10-08")
    ecrire_dictionnaire(revu, "2026-03", chemin)
    # Une régénération brute perdrait les trois décisions.
    brut = _dictionnaire_fictif(
        formes=[_forme("AA-9999", effectif=995), _forme("AA9999", "à arbitrer", 7)]
    )
    with pytest.raises(ValueError, match="écriture refusée, 3 décisions") as erreur:
        ecrire_dictionnaire(brut, "2026-04", chemin)
    assert str(erreur.value).splitlines()[1:] == [
        (
            "  clients.ville, règle format : statut 'valide' devenu 'observé', revu_le "
            "'2026-10-08' devenu None"
        ),
        (
            "  clients.ville, forme 'AA-9999' : statut 'valide' devenu 'observé', revu_le "
            "'2026-10-08' devenu None"
        ),
        (
            "  clients.ville, forme 'AA9999' : statut 'invalide' devenu 'observé', "
            "commentaire 'tiret oublié' devenu '', revu_le '2026-10-08' devenu None"
        ),
    ]
    # Seuls les effectifs changent : l'écriture passe.
    mis_a_jour = deepcopy(revu)
    mis_a_jour["clients"]["ville"]["format"]["liste"][0]["effectif"] = 995
    ecrire_dictionnaire(mis_a_jour, "2026-04", chemin)
    assert charger_dictionnaire(chemin) == mis_a_jour


# Journal des revues et compteurs de formes (morceau 6b).


def test_journal_ecrit_avant_la_revue_des_formes(tmp_path, monkeypatch):
    # Une copie de sauvegarde par écriture : chaque écriture a sa propre seconde.
    secondes = iter(range(60))
    monkeypatch.setattr(
        "frigeo.dictionnaire._maintenant", lambda: datetime(2026, 11, 2, 9, 0, next(secondes))
    )
    chemin = tmp_path / "dictionnaire.yaml"
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    # Entrée telle qu'elle était écrite avant les compteurs de formes.
    ancienne = {
        champ: valeur
        for champ, valeur in _entree().items()
        if champ not in ("formes_changees", "formes_ajoutees")
    }
    contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    contenu["meta"]["revues"] = [ancienne]
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    # Elle est lue avec ses compteurs de formes à 0, dans l'ordre des champs.
    lue = charger_meta(chemin)["revues"]
    assert lue == [_entree()]
    assert list(lue[0]) == list(_entree())
    # Le fichier est complété à l'écriture suivante, régénération ou revue.
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin)
    brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))["meta"]["revues"]
    assert brut == [_entree()]
    suivante = {**_entree("2026-11-02", "revue2.xlsx"), "formes_changees": 3}
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", chemin, revue=suivante)
    assert charger_meta(chemin)["revues"] == [_entree(), suivante]
    # Une entrée à laquelle il manque autre chose reste refusée.
    del contenu["meta"]["revues"][0]["classeur"]
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="journal des revues, entrée 1"):
        charger_meta(chemin)
    # Une revue se fournit avec tous ses compteurs.
    ecrire_dictionnaire(_dictionnaire_fictif(), "2026-03", tmp_path / "autre.yaml")
    with pytest.raises(ValueError, match="champs attendus"):
        ecrire_dictionnaire(
            _dictionnaire_fictif(), "2026-03", tmp_path / "autre.yaml", revue=ancienne
        )
