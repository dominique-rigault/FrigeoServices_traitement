"""Tests de la détection des doublons (frigeo.doublons)."""

from copy import deepcopy

import pandas as pd
import pytest

from frigeo.controles import VALEUR_MASQUEE, charger_regles_complementaires
from frigeo.doublons import (
    COLONNES_BILAN_DOUBLONS,
    COLONNES_DOUBLONS,
    COLONNES_NON_CHERCHES,
    charger_declarations_doublons,
    detecter_doublons,
    doublons_non_cherches,
    normaliser,
    problemes_declarations_doublons,
)

AUCUNE_SENSIBLE = {}


def _table(fichier="t.csv", premiere_ligne=2, **colonnes) -> pd.DataFrame:
    """Table fictive avec son lignage, la première ligne de données étant la ligne 2."""
    nombre = len(next(iter(colonnes.values())))
    donnees = pd.DataFrame(colonnes, dtype=object)
    donnees.insert(0, "num_ligne_source", range(premiere_ligne, premiere_ligne + nombre))
    donnees.insert(0, "feuille_source", None)
    donnees.insert(0, "fichier_source", fichier)
    return donnees


def _detecter(donnees, declaration=None, sensibles=AUCUNE_SENSIBLE):
    """Détection sur une table « t », avec sa seule déclaration."""
    return detecter_doublons({"t": donnees}, {"t": declaration} if declaration else {}, sensibles)


def _lignes(doublons, *colonnes):
    """Doublons réduits à quelques colonnes, sous forme de liste de tuples."""
    return [
        tuple(None if pd.isna(valeur) else valeur for valeur in ligne)
        for ligne in doublons[list(colonnes)].itertuples(index=False)
    ]


def _bilan(bilan, constat, colonnes=None):
    """Ligne du bilan d'un contrôle, sous forme de dictionnaire."""
    lignes = bilan[bilan["constat"] == constat]
    if colonnes is not None:
        lignes = lignes[lignes["colonnes"] == colonnes]
    assert len(lignes) == 1
    return lignes.iloc[0].to_dict()


def test_normalisation_des_textes():
    assert normaliser("  Boulangerie   du Marché ") == "boulangerie du marche"
    assert normaliser("BOULANGERIE DU MARCHE") == "boulangerie du marche"
    assert normaliser(chr(160) + "A\tb" + chr(160)) == "a b"
    assert normaliser("") == ""


def test_doublon_exact_dans_un_fichier_et_entre_exports():
    donnees = pd.concat(
        [
            _table("a.csv", code=["A", "B", "A", "C"], libelle=["x", "y", "x", "z"]),
            _table("b.csv", code=["B", "D"], libelle=["y", "w"]),
        ],
        ignore_index=True,
    )
    doublons, bilan = _detecter(donnees)
    assert list(doublons.columns) == list(COLONNES_DOUBLONS)
    assert list(bilan.columns) == list(COLONNES_BILAN_DOUBLONS)
    assert _lignes(
        doublons, "fichier_source", "num_ligne_source", "constat", "issue", "portee", "groupe"
    ) == [
        ("a.csv", 2, "doublon exact", "anomalie", "même fichier", 1),
        ("a.csv", 4, "doublon exact", "anomalie", "même fichier", 1),
        ("a.csv", 3, "doublon exact", "anomalie", "entre exports", 2),
        ("b.csv", 2, "doublon exact", "anomalie", "entre exports", 2),
    ]
    assert set(doublons["taille_groupe"]) == {2}
    assert set(doublons["comparaison"]) == {"telle quelle"}
    assert doublons["cle"].isna().all() and doublons["valeur"].isna().all()
    assert bilan.to_dict("records") == [
        {
            "table": "t",
            "constat": "doublon exact",
            "colonnes": "toutes",
            "issue": "anomalie",
            "comparees": 6,
            "groupes": 2,
            "lignes": 4,
            "en_surnombre": 2,
            "entre_exports": 1,
            "apres_normalisation": 0,
        }
    ]


def test_doublon_exact_apres_normalisation_et_ligne_vide():
    donnees = _table(
        code=["A", "a ", None, "", "B"],
        libelle=["Marché", "MARCHE", None, "  ", "x"],
    )
    doublons, bilan = _detecter(donnees)
    assert _lignes(doublons, "num_ligne_source", "comparaison") == [
        (2, "après normalisation"),
        (3, "après normalisation"),
    ]
    ligne = _bilan(bilan, "doublon exact")
    # Les deux lignes entièrement vides ne sont pas comparées.
    assert ligne["comparees"] == 3 and ligne["apres_normalisation"] == 1


def test_valeur_en_double_sur_la_cle():
    donnees = _table(
        code=["A", "A", "B", "B", "C", "C", "C"],
        libelle=["x", "y", "z", "z", "u", "u", "v"],
    )
    doublons, bilan = _detecter(donnees, {"cle": ["code"]})
    en_double = doublons[doublons["constat"] == "valeur en double"]
    # B : deux lignes identiques, c'est un doublon exact et non une valeur en double.
    # C : deux lignes identiques et une troisième différente, les trois sont du groupe.
    assert _lignes(
        en_double, "num_ligne_source", "colonnes", "issue", "groupe", "taille_groupe", "cle"
    ) == [
        (2, "code", "anomalie", 1, 2, "A"),
        (3, "code", "anomalie", 1, 2, "A"),
        (6, "code", "anomalie", 2, 3, "C"),
        (7, "code", "anomalie", 2, 3, "C"),
        (8, "code", "anomalie", 2, 3, "C"),
    ]
    assert list(en_double["valeur"]) == ["A", "A", "C", "C", "C"]
    ligne = _bilan(bilan, "valeur en double")
    assert (ligne["comparees"], ligne["groupes"]) == (7, 2)
    assert (ligne["lignes"], ligne["en_surnombre"]) == (5, 3)
    exact = _bilan(bilan, "doublon exact")
    assert (exact["groupes"], exact["lignes"]) == (2, 4)


def test_une_valeur_vide_n_est_jamais_comparee():
    donnees = _table(
        code=["1", "2", "3", "4", "5", "6"],
        siret=[None, "", "  ", float("nan"), "9", "9"],
        cp=["76", "76", "76", "76", "27", None],
    )
    doublons, bilan = _detecter(
        donnees, {"cle": ["code"], "unique": [["siret"], ["siret", "cp"]]}
    )
    en_double = doublons[doublons["constat"] == "valeur en double"]
    assert _lignes(en_double, "num_ligne_source", "colonnes", "valeur") == [
        (6, "siret", "9"),
        (7, "siret", "9"),
    ]
    assert _bilan(bilan, "valeur en double", "siret")["comparees"] == 2
    # La ligne 7 n'a pas de code postal : le couple n'y est pas comparé.
    couple = _bilan(bilan, "valeur en double", "siret, cp")
    assert (couple["comparees"], couple["groupes"]) == (1, 0)


def test_groupe_de_colonnes_unique():
    donnees = _table(
        code=["1", "2", "3", "4"],
        fournisseur=["F1", "F1", "F2", "F1"],
        reference=["R1", "R2", "R1", "R1"],
    )
    doublons, _ = _detecter(donnees, {"unique": [["fournisseur", "reference"]]})
    assert _lignes(doublons, "num_ligne_source", "colonnes", "valeur", "cle") == [
        (2, "fournisseur, reference", "F1 | R1", None),
        (5, "fournisseur, reference", "F1 | R1", None),
    ]


def test_colonne_presumee_unique_a_arbitrer_apres_normalisation():
    donnees = _table(
        code=["1", "2", "3", "4"],
        nom=["Boulangerie du Marché", "BOULANGERIE DU MARCHE ", "Bar", "Bar"],
        cp=["76000", "76000", "27000", "76000"],
    )
    doublons, bilan = _detecter(
        donnees, {"cle": ["code"], "presume_unique": [["nom", "cp"]]}
    )
    en_double = doublons[doublons["constat"] == "valeur en double"]
    assert _lignes(en_double, "num_ligne_source", "issue", "comparaison", "valeur") == [
        (2, "à arbitrer", "après normalisation", "Boulangerie du Marché | 76000"),
        (3, "à arbitrer", "après normalisation", "BOULANGERIE DU MARCHE  | 76000"),
    ]
    ligne = _bilan(bilan, "valeur en double", "nom, cp")
    assert (ligne["issue"], ligne["groupes"], ligne["apres_normalisation"]) == ("à arbitrer", 1, 1)
    assert _bilan(bilan, "valeur en double", "code")["issue"] == "anomalie"


def test_identique_hors_cle_toujours_a_arbitrer():
    donnees = _table(
        code=["1", "2", "3", "4", "5"],
        client=["C1", "C1", "C2", None, ""],
        montant=[10.5, 10.5, 10.5, None, None],
    )
    doublons, bilan = _detecter(donnees, {"cle": ["code"]})
    assert _lignes(
        doublons, "num_ligne_source", "constat", "colonnes", "issue", "cle", "valeur"
    ) == [
        (2, "identique hors clé", "toutes sauf code", "à arbitrer", "1", None),
        (3, "identique hors clé", "toutes sauf code", "à arbitrer", "2", None),
    ]
    # Les lignes 5 et 6, vides hors de leur clé, ne sont pas comparées.
    ligne = _bilan(bilan, "identique hors clé")
    assert (ligne["comparees"], ligne["groupes"], ligne["en_surnombre"]) == (3, 1, 1)


def test_identique_hors_cle_ecarte_par_le_metier():
    donnees = _table(code=["1", "2"], article=["P", "P"])
    declaration = {"cle": ["code"], "identique_hors_cle": False}
    doublons, bilan = _detecter(donnees, declaration)
    assert doublons.empty and list(doublons.columns) == list(COLONNES_DOUBLONS)
    assert list(bilan["constat"]) == ["doublon exact", "valeur en double"]
    non_cherches = doublons_non_cherches({"t": donnees}, {"t": declaration})
    assert list(non_cherches.columns) == list(COLONNES_NON_CHERCHES)
    assert non_cherches.to_dict("records") == [
        {"table": "t", "constat": "identique hors clé", "raison": "écarté par le métier"}
    ]


def test_cles_identiques_apres_normalisation_ne_sont_pas_des_cles_differentes():
    donnees = _table(code=["C1", "c1 "], nom=["x", "x"])
    doublons, _ = _detecter(donnees, {"cle": ["code"]})
    assert _lignes(doublons, "constat", "comparaison") == [
        ("doublon exact", "après normalisation"),
        ("doublon exact", "après normalisation"),
    ]


def test_colonnes_sensibles_masquees_mais_comparees():
    donnees = _table(
        code=["1", "2", "3"],
        nom=["Dupont", "DUPONT", "Martin"],
        ville=["Rouen", "Rouen", "Rouen"],
    )
    declaration = {"cle": ["code"], "presume_unique": [["nom", "ville"]], "unique": [["ville"]]}
    doublons, _ = _detecter(donnees, declaration, {"t": frozenset({"nom"})})
    en_double = doublons[doublons["constat"] == "valeur en double"]
    assert _lignes(en_double, "num_ligne_source", "colonnes", "cle", "valeur") == [
        (2, "ville", "1", "Rouen"),
        (3, "ville", "2", "Rouen"),
        (4, "ville", "3", "Rouen"),
        (2, "nom, ville", "1", VALEUR_MASQUEE),
        (3, "nom, ville", "2", VALEUR_MASQUEE),
    ]
    # Dupont et DUPONT sont rapprochés bien que le nom ne soit jamais affiché.
    hors_cle = doublons[doublons["constat"] == "identique hors clé"]
    assert _lignes(hors_cle, "num_ligne_source", "cle") == [(2, "1"), (3, "2")]
    assert hors_cle["valeur"].isna().all()
    doublons, _ = _detecter(donnees, declaration, {"t": frozenset({"code"})})
    assert set(doublons["cle"]) == {VALEUR_MASQUEE}
    assert "Rouen" in set(doublons["valeur"])


def test_une_ligne_sous_plusieurs_constats_et_ordre_des_controles():
    donnees = _table(
        code=["1", "1", "2"],
        siret=["9", "8", "9"],
        nom=["a", "b", "a"],
    )
    doublons, bilan = _detecter(
        donnees, {"cle": ["code"], "unique": [["siret"]], "presume_unique": [["nom"]]}
    )
    assert _lignes(doublons, "num_ligne_source", "constat", "colonnes", "issue") == [
        (2, "valeur en double", "code", "anomalie"),
        (3, "valeur en double", "code", "anomalie"),
        (2, "valeur en double", "siret", "anomalie"),
        (4, "valeur en double", "siret", "anomalie"),
        (2, "valeur en double", "nom", "à arbitrer"),
        (4, "valeur en double", "nom", "à arbitrer"),
        (2, "identique hors clé", "toutes sauf code", "à arbitrer"),
        (4, "identique hors clé", "toutes sauf code", "à arbitrer"),
    ]
    assert list(bilan["constat"]) == [
        "doublon exact",
        "valeur en double",
        "valeur en double",
        "valeur en double",
        "identique hors clé",
    ]


def test_les_lignes_d_un_groupe_se_suivent():
    donnees = _table(code=["A", "B", "A", "B", "A"], nom=["1", "2", "3", "4", "5"])
    doublons, _ = _detecter(donnees, {"cle": ["code"]})
    assert _lignes(doublons, "groupe", "num_ligne_source", "taille_groupe") == [
        (1, 2, 3),
        (1, 4, 3),
        (1, 6, 3),
        (2, 3, 2),
        (2, 5, 2),
    ]


def test_valeurs_natives_comparees_par_leur_texte():
    donnees = _table(
        code=[1, 1, "1", 2.0, 2.0],
        date=[pd.Timestamp("2025-03-21"), pd.Timestamp("2025-03-22"), None, None, None],
    )
    doublons, _ = _detecter(donnees, {"cle": ["code"]})
    # 1 et « 1 » ont le même texte, 2.0 s'écrit « 2.0 ».
    assert _lignes(doublons, "num_ligne_source", "constat", "valeur") == [
        (5, "doublon exact", None),
        (6, "doublon exact", None),
        (2, "valeur en double", "1"),
        (3, "valeur en double", "1"),
        (4, "valeur en double", "1"),
    ]


def test_table_sans_declaration_et_constats_non_cherches():
    tables = {
        "avec": _table("a.csv", code=["1", "2"], nom=["x", "x"]),
        "sans": _table("s.csv", a=["1", "1"], b=["x", "y"]),
        "cle_seule": _table("c.csv", code=["1", "2"]),
    }
    declarations = {"avec": {"cle": ["code"]}, "cle_seule": {"cle": ["code"]}}
    doublons, bilan = detecter_doublons(tables, declarations, AUCUNE_SENSIBLE)
    assert _lignes(bilan, "table", "constat") == [
        ("avec", "doublon exact"),
        ("avec", "valeur en double"),
        ("avec", "identique hors clé"),
        ("sans", "doublon exact"),
        ("cle_seule", "doublon exact"),
        ("cle_seule", "valeur en double"),
    ]
    assert set(doublons["table"]) == {"avec"}
    assert doublons_non_cherches(tables, declarations).to_dict("records") == [
        {"table": "sans", "constat": "valeur en double", "raison": "aucune clé déclarée"},
        {"table": "sans", "constat": "identique hors clé", "raison": "aucune clé déclarée"},
        {
            "table": "cle_seule",
            "constat": "identique hors clé",
            "raison": "aucune colonne hors clé",
        },
    ]


def test_table_sans_lignage_et_index_quelconque():
    donnees = pd.DataFrame({"code": ["A", "A", "B"]}, index=[10, 20, 30])
    doublons, bilan = _detecter(donnees)
    assert len(doublons) == 2 and doublons["fichier_source"].isna().all()
    assert set(doublons["portee"]) == {"même fichier"}
    vide, bilan = _detecter(pd.DataFrame({"code": []}, dtype=object), {"cle": ["code"]})
    assert vide.empty and list(bilan["comparees"]) == [0, 0]


def test_les_arguments_ne_sont_pas_modifies():
    donnees = _table(code=["A", "A"], nom=["x", "y"])
    declarations = {"t": {"cle": ["code"], "presume_unique": [["nom"]]}}
    avant, avant_declarations = donnees.copy(deep=True), deepcopy(declarations)
    detecter_doublons({"t": donnees}, declarations, AUCUNE_SENSIBLE)
    pd.testing.assert_frame_equal(donnees, avant)
    assert declarations == avant_declarations


def test_table_ou_colonne_declaree_inconnue():
    donnees = _table(code=["A"])
    with pytest.raises(ValueError) as erreur:
        detecter_doublons(
            {"t": donnees},
            {"t": {"cle": ["cod"], "unique": [["code", "siret"]]}, "u": {"cle": ["code"]}},
            AUCUNE_SENSIBLE,
        )
    texte = str(erreur.value)
    for attendu in (
        "Déclarations de doublons invalides",
        "colonne t.cod absente des données chargées",
        "colonne t.siret absente des données chargées",
        "table u absente des données chargées",
    ):
        assert attendu in texte
    # Une colonne de lignage n'est pas une colonne de données.
    with pytest.raises(ValueError, match="colonne t.fichier_source absente"):
        _detecter(donnees, {"cle": ["fichier_source"]})


def test_problemes_des_declarations_listes_en_une_fois():
    declarations = {
        "a": {"cle": "code"},
        "b": {"cle": ["code", "code"]},
        "c": {"unique": ["siret"]},
        "d": {"cles": ["code"]},
        "e": {"cle": ["code"], "identique_hors_cle": True},
        "f": {"unique": [["siret"]], "identique_hors_cle": False},
        "g": {"cle": ["code"], "unique": [["code"]]},
        "h": None,
        "i": {"presume_unique": []},
    }
    problemes = problemes_declarations_doublons(declarations)
    texte = "\n".join(problemes)
    for attendu in (
        "a, cle : une liste de noms de colonnes est attendue",
        "b, cle : une colonne est citée deux fois",
        "c, unique : une liste de noms de colonnes est attendue",
        "d : clé inconnue 'cles'",
        "d : rien n'est déclaré",
        "e, identique_hors_cle : la valeur attendue est false",
        "f, identique_hors_cle : sans clé déclarée",
        "g : les colonnes code sont déclarées deux fois (cle et unique)",
        "h : une déclaration est attendue",
        "i, presume_unique : une liste de groupes de colonnes est attendue",
    ):
        assert attendu in texte
    assert len(problemes) == 10
    assert problemes_declarations_doublons([]) == ["un dictionnaire de tables est attendu"]
    assert problemes_declarations_doublons(
        {"t": {"cle": ["a", "b"], "unique": [["a"], ["c", "a"]], "presume_unique": [["d"]]}}
    ) == []
    with pytest.raises(ValueError, match="clé inconnue 'cles'"):
        _detecter(_table(code=["A"]), {"cles": ["code"]})


def test_classification_de_sensibilite_incoherente():
    with pytest.raises(RuntimeError, match="Classification de sensibilité incohérente"):
        _detecter(_table(code=["A"]), sensibles={"t": frozenset({"absente"})})


def test_lecture_des_declarations(tmp_path):
    chemin = tmp_path / "controles.yaml"
    assert charger_declarations_doublons(chemin) == {}
    chemin.write_text("regles:\n  clients:\n    siret: {cle_luhn: true}\n", encoding="utf-8")
    assert charger_declarations_doublons(chemin) == {}
    chemin.write_text(
        "regles:\n"
        "  clients:\n"
        "    siret: {cle_luhn: true}\n"
        "doublons:\n"
        "  clients:\n"
        "    cle: [code_client]\n"
        "    unique:\n"
        "      - [siret]\n"
        "    presume_unique:\n"
        "      - [raison_sociale, cp]\n"
        "  achats_lignes:\n"
        "    cle: [num_piece_achat, num_ligne]\n"
        "    identique_hors_cle: false\n",
        encoding="utf-8",
    )
    assert charger_declarations_doublons(chemin) == {
        "clients": {
            "cle": ["code_client"],
            "unique": [["siret"]],
            "presume_unique": [["raison_sociale", "cp"]],
        },
        "achats_lignes": {"cle": ["num_piece_achat", "num_ligne"], "identique_hors_cle": False},
    }
    # Les deux clés du fichier se lisent indépendamment l'une de l'autre.
    assert charger_regles_complementaires(chemin) == {"clients": {"siret": {"cle_luhn": True}}}
    chemin.write_text("doublons:\n", encoding="utf-8")
    assert charger_declarations_doublons(chemin) == {}
    chemin.write_text("doublon:\n  clients:\n    cle: [code_client]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clé inconnue : doublon"):
        charger_declarations_doublons(chemin)
    chemin.write_text("doublons:\n  clients:\n    cle: code_client\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clients, cle : une liste de noms de colonnes"):
        charger_declarations_doublons(chemin)
