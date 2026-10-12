"""Tests des contrôles des règles de gestion (frigeo.gestion)."""

import datetime as dt
from copy import deepcopy

import pandas as pd
import pytest

from frigeo import gestion
from frigeo.controles import VALEUR_MASQUEE
from frigeo.gestion import (
    COLONNES_BILAN_GESTION,
    COLONNES_CATALOGUE,
    COLONNES_ECARTS_GESTION,
    CONSTAT_DATE_ANTERIEURE,
    CONSTAT_DATE_POSTERIEURE,
    CONSTAT_INFERIEURE,
    CONSTAT_RAPPORT_INFERIEUR,
    CONSTAT_RAPPORT_NON_CALCULABLE,
    CONSTAT_RAPPORT_SUPERIEUR,
    CONSTAT_SUPERIEURE,
    ISSUE_INFORMATION,
    VUE_SANS_SURNOMBRE,
    VUE_TOUTES,
    Constats,
    TypeRegle,
    catalogue_types,
    charger_regles_gestion,
    controler_gestion,
    problemes_regles_gestion,
)

AUCUNE_SENSIBLE = {}


def _table(fichier="t.csv", periode="2025", premiere_ligne=2, **colonnes) -> pd.DataFrame:
    """Table fictive avec son lignage et sa période d'export."""
    nombre = len(next(iter(colonnes.values())))
    donnees = pd.DataFrame(colonnes, dtype=object)
    donnees.insert(0, "periode_export", periode)
    donnees.insert(0, "num_ligne_source", range(premiere_ligne, premiere_ligne + nombre))
    donnees.insert(0, "feuille_source", None)
    donnees.insert(0, "fichier_source", fichier)
    return donnees


def _dictionnaire(table="t", **natures):
    """Dictionnaire réduit à la règle `nature` de chaque colonne."""
    return {table: {colonne: {"nature": {"regle": n}} for colonne, n in natures.items()}}


def _regle(colonne="d", table="t", ref="decoupage", **autres):
    return {
        "ref": ref,
        "libelle": "Date dans la période de l'export",
        "type": "date_dans_periode_export",
        "table": table,
        "colonne": colonne,
        **autres,
    }


def _controler(donnees, natures, regles=None, declarations=None, sensibles=AUCUNE_SENSIBLE,
               dictionnaire=None, doublons=None):
    """Contrôle d'une table « t »; aucune lecture des fichiers de config/."""
    return controler_gestion(
        {"t": donnees},
        dictionnaire if dictionnaire is not None else _dictionnaire(**natures),
        [_regle()] if regles is None else regles,
        {} if declarations is None else declarations,
        doublons,
        sensibles,
    )


def _lignes(ecarts, *colonnes):
    return [
        tuple(None if pd.isna(valeur) else valeur for valeur in ligne)
        for ligne in ecarts[list(colonnes)].itertuples(index=False)
    ]


def _bilan(bilan, rang=0):
    return bilan.iloc[rang].to_dict()


def test_date_hors_periode_d_un_export_annuel_et_mensuel():
    donnees = pd.concat(
        [
            _table(
                "a.csv",
                "2025",
                d=["14/03/2025", "14/03/2052", "31/12/2024", "", "2025-03-14", "01/01/2026"],
            ),
            _table("b.csv", "2026-01", d=["31/01/2026", "01/02/2026", "31/12/2025"]),
        ],
        ignore_index=True,
    )
    ecarts, bilan = _controler(donnees, {"d": "date JJ/MM/AAAA"})
    assert list(ecarts.columns) == list(COLONNES_ECARTS_GESTION)
    assert list(bilan.columns) == list(COLONNES_BILAN_GESTION)
    assert _lignes(
        ecarts, "fichier_source", "num_ligne_source", "constat", "issue", "valeur", "proposition"
    ) == [
        ("a.csv", 3, CONSTAT_DATE_POSTERIEURE, "à arbitrer", "14/03/2052", "14/03/2025"),
        ("a.csv", 4, CONSTAT_DATE_ANTERIEURE, "à arbitrer", "31/12/2024", "31/12/2025"),
        ("a.csv", 7, CONSTAT_DATE_POSTERIEURE, "à arbitrer", "01/01/2026", "01/01/2025"),
        ("b.csv", 3, CONSTAT_DATE_POSTERIEURE, "à arbitrer", "01/02/2026", None),
        ("b.csv", 4, CONSTAT_DATE_ANTERIEURE, "à arbitrer", "31/12/2025", None),
    ]
    assert set(ecarts["ref"]) == {"decoupage"}
    assert set(ecarts["colonnes"]) == {"d"}
    assert _bilan(bilan) == {
        "ref": "decoupage",
        "type": "date_dans_periode_export",
        "libelle": "Date dans la période de l'export",
        "table": "t",
        "colonnes": "d",
        "vue": VUE_TOUTES,
        "filtre": None,
        "lignes": 9,
        "ecartees_doublons": 0,
        "hors_champ": 0,
        "non_evaluables": 2,
        "controlees": 7,
        "anomalies": 0,
        "a_arbitrer": 5,
        "informations": 0,
    }


def test_proposition_dans_la_forme_de_la_nature():
    donnees = _table(d=[dt.datetime(2052, 3, 14), dt.datetime(2024, 2, 29), "14/03/2052"])
    ecarts, bilan = _controler(donnees, {"d": "date native"})
    # Le 29 février n'existe pas en 2025 : aucune proposition. Une date en texte
    # dans une colonne de dates natives n'est pas évaluable.
    assert _lignes(ecarts, "valeur", "proposition") == [
        ("2052-03-14 00:00:00", "2025-03-14"),
        ("2024-02-29 00:00:00", None),
    ]
    assert _bilan(bilan)["non_evaluables"] == 1
    ecarts, _ = _controler(_table(d=["20520314"]), {"d": "date AAAAMMJJ"})
    assert _lignes(ecarts, "valeur", "proposition") == [("20520314", "20250314")]


def test_ligne_sans_periode_lisible_non_evaluable():
    donnees = _table(d=["14/03/2052", "14/03/2052", "14/03/2052"])
    donnees["periode_export"] = ["2025", None, "2025-13"]
    ecarts, bilan = _controler(donnees, {"d": "date JJ/MM/AAAA"})
    assert _lignes(ecarts, "num_ligne_source") == [(2,)]
    assert _bilan(bilan)["non_evaluables"] == 2


def test_cle_valeur_et_proposition_masquees():
    donnees = _table(code=["A1", "A2"], d=["14/03/2052", "14/03/2025"])
    declarations = {"t": {"cle": ["code"]}}
    natures = {"code": "texte", "d": "date JJ/MM/AAAA"}
    ecarts, _ = _controler(donnees, natures, declarations=declarations)
    assert _lignes(ecarts, "cle", "valeur", "proposition") == [("A1", "14/03/2052", "14/03/2025")]
    ecarts, _ = _controler(donnees, natures, declarations=declarations,
                           sensibles={"t": frozenset({"code"})})
    assert _lignes(ecarts, "cle", "valeur", "proposition") == [
        (VALEUR_MASQUEE, "14/03/2052", "14/03/2025")
    ]
    ecarts, _ = _controler(donnees, natures, declarations=declarations,
                           sensibles={"t": frozenset({"d"})})
    assert _lignes(ecarts, "cle", "valeur", "proposition") == [
        ("A1", VALEUR_MASQUEE, VALEUR_MASQUEE)
    ]
    # Une colonne marquée sensible par le dictionnaire est masquée elle aussi.
    dictionnaire = _dictionnaire(**natures)
    dictionnaire["t"]["d"]["valeurs"] = {"motif": "colonne sensible"}
    ecarts, _ = _controler(donnees, natures, declarations=declarations, dictionnaire=dictionnaire)
    assert _lignes(ecarts, "valeur", "proposition") == [(VALEUR_MASQUEE, VALEUR_MASQUEE)]


def test_cle_sur_plusieurs_colonnes_et_table_sans_cle():
    donnees = _table(num=["F1"], rang=[2], d=["14/03/2052"])
    natures = {"num": "texte", "rang": "texte", "d": "date JJ/MM/AAAA"}
    ecarts, _ = _controler(donnees, natures, declarations={"t": {"cle": ["num", "rang"]}})
    assert _lignes(ecarts, "cle") == [("F1 | 2",)]
    ecarts, _ = _controler(donnees, natures)
    assert _lignes(ecarts, "cle") == [(None,)]


def test_structure_des_regles_tous_les_problemes_listes():
    regles = [
        "decoupage",
        {"ref": "R1", "libelle": "x", "table": "t"},
        _regle(type="date_inconnue"),
        _regle(colonnes="d"),
        {key: valeur for key, valeur in _regle().items() if key != "colonne"},
        _regle(libelle=""),
        _regle(table=["t"]),
        _regle(ref="R2"),
        _regle(ref="R3"),
    ]
    problemes = problemes_regles_gestion(regles)
    assert problemes == [
        "règle n° 1 : un dictionnaire de clés est attendu",
        "règle n° 2 (R1) : clé manquante (type)",
        "règle n° 3 (decoupage) : type inconnu 'date_inconnue' (types possibles : "
        "date_dans_periode_export, plage, plage_selon_valeur, rapport_dans_plage)",
        "règle n° 4 (decoupage) : clé inconnue colonnes (clés possibles pour le type "
        "date_dans_periode_export : ref, libelle, type, table, filtre, issue, colonne)",
        "règle n° 5 (decoupage) : paramètre manquant (colonne)",
        "règle n° 6 (decoupage), libelle : un texte non vide est attendu",
        "règle n° 7 (decoupage), table : un texte non vide est attendu",
        "règle n° 9 (R3) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 8 (R2))",
    ]
    assert problemes_regles_gestion({"regles": []}) == [
        "une liste de règles est attendue (chaque règle commence par un tiret)"
    ]
    assert problemes_regles_gestion([]) == []


def test_regles_confrontees_aux_donnees_et_au_dictionnaire():
    tables = {
        "t": _table(d=["14/03/2025"], e=["x"], f=["01/01/2025"]),
        "r": _table(d=["14/03/2025"], periode=None),
    }
    dictionnaire = {
        **_dictionnaire(d="date JJ/MM/AAAA", e="à décider"),
        **_dictionnaire("r", d="date JJ/MM/AAAA"),
    }
    regles = [
        _regle(table="absente"),
        _regle(colonne="absente"),
        _regle(colonne="e"),
        _regle(colonne="f"),
        _regle(table="r"),
    ]
    with pytest.raises(ValueError) as erreur:
        controler_gestion(tables, dictionnaire, regles, {}, None, AUCUNE_SENSIBLE)
    message = str(erreur.value)
    for attendu in (
        "règle n° 1 (decoupage) : table absente absente des données chargées",
        "règle n° 2 (decoupage), colonne : colonne t.absente absente des données chargées",
        "règle n° 3 (decoupage), colonne : la nature en vigueur de t.e est 'à décider', "
        "une date est attendue",
        "règle n° 4 (decoupage), colonne : colonne t.f absente du dictionnaire",
        "règle n° 5 (decoupage) : table r, la table n'est pas un export périodique",
    ):
        assert attendu in message
    # Une colonne de lignage n'est pas une colonne de données.
    with pytest.raises(ValueError, match="colonne t.periode_export absente des données"):
        controler_gestion(
            tables, dictionnaire, [_regle(colonne="periode_export")], {}, None, AUCUNE_SENSIBLE
        )


def test_structure_verifiee_avant_les_donnees():
    with pytest.raises(ValueError, match="type inconnu"):
        controler_gestion({}, {}, [_regle(type="autre")], {}, None, AUCUNE_SENSIBLE)


def test_sensibilite_incoherente():
    with pytest.raises(RuntimeError, match="sensibilité"):
        _controler(_table(d=["14/03/2025"]), {"d": "date JJ/MM/AAAA"},
                   sensibles={"t": frozenset({"absente"})})


def test_aucune_regle():
    ecarts, bilan = _controler(_table(d=["14/03/2025"]), {"d": "date JJ/MM/AAAA"}, regles=[])
    assert list(ecarts.columns) == list(COLONNES_ECARTS_GESTION)
    assert ecarts.empty and bilan.empty


def test_ordre_des_ecarts_par_regle_puis_par_ligne():
    donnees = pd.concat(
        [
            _table("b.csv", d=["14/03/2052"], e=["14/03/2052"]),
            _table("a.csv", d=["14/03/2052", "14/03/2025"], e=["14/03/2025", "14/03/2052"]),
        ],
        ignore_index=True,
    )
    regles = [_regle("e", ref="R2"), _regle("d", ref="R1")]
    natures = {"d": "date JJ/MM/AAAA", "e": "date JJ/MM/AAAA"}
    ecarts, bilan = _controler(donnees, natures, regles=regles)
    assert _lignes(ecarts, "ref", "fichier_source", "num_ligne_source") == [
        ("R2", "a.csv", 3),
        ("R2", "b.csv", 2),
        ("R1", "a.csv", 2),
        ("R1", "b.csv", 2),
    ]
    assert list(bilan["ref"]) == ["R2", "R1"]


def test_arguments_non_modifies():
    donnees = _table(d=["14/03/2052", ""])
    tables = {"t": donnees}
    copie = donnees.copy()
    dictionnaire = _dictionnaire(d="date JJ/MM/AAAA")
    regles = [_regle()]
    avant = deepcopy((dictionnaire, regles))
    controler_gestion(tables, dictionnaire, regles, {}, None, AUCUNE_SENSIBLE)
    pd.testing.assert_frame_equal(donnees, copie)
    assert (dictionnaire, regles) == avant


def _toutes_en_information(donnees, parametres, natures):
    """Type d'essai : chaque ligne de la vue donne une information."""
    return Constats(
        pd.Series(True, index=donnees.index, dtype=bool),
        pd.DataFrame({"constat": "vue", "proposition": None}, index=donnees.index),
    )


@pytest.fixture
def type_sans_surnombre(monkeypatch):
    types = dict(gestion.TYPES)
    types["essai_vue"] = TypeRegle(
        description="essai",
        parametres={"colonne": gestion.GENRE_COLONNE_DATE},
        vue=VUE_SANS_SURNOMBRE,
        controler=_toutes_en_information,
        issue=ISSUE_INFORMATION,
    )
    monkeypatch.setattr(gestion, "TYPES", types)


def test_vue_sans_les_doublons_exacts_en_surnombre(type_sans_surnombre):
    donnees = pd.concat(
        [
            _table("a.csv", d=["14/03/2025", "15/03/2025", "14/03/2025", "14/03/2025"]),
            _table("b.csv", d=["15/03/2025"]),
        ],
        ignore_index=True,
    )
    regles = [_regle(type="essai_vue")]
    ecarts, bilan = _controler(donnees, {"d": "date JJ/MM/AAAA"}, regles=regles)
    # Premières lignes gardées : a.csv 2 et 3; écartées : a.csv 4 et 5, b.csv 2.
    assert _lignes(ecarts, "fichier_source", "num_ligne_source", "issue") == [
        ("a.csv", 2, ISSUE_INFORMATION),
        ("a.csv", 3, ISSUE_INFORMATION),
    ]
    resume = _bilan(bilan)
    assert (resume["vue"], resume["lignes"], resume["ecartees_doublons"]) == (
        VUE_SANS_SURNOMBRE,
        5,
        3,
    )
    assert (resume["controlees"], resume["informations"]) == (2, 2)
    # Une table des doublons fournie est utilisée telle quelle.
    vide = pd.DataFrame(columns=["table", "constat", "groupe", "fichier_source",
                                 "feuille_source", "num_ligne_source"])
    _, bilan = _controler(donnees, {"d": "date JJ/MM/AAAA"}, regles=regles, doublons=vide)
    assert _bilan(bilan)["ecartees_doublons"] == 0


def test_chargement_du_fichier(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    assert charger_regles_gestion(chemin) == []
    chemin.write_text("", encoding="utf-8")
    assert charger_regles_gestion(chemin) == []
    chemin.write_text("regle:\n  - ref: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clé inconnue : regle"):
        charger_regles_gestion(chemin)
    chemin.write_text("- ref: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="seule clé"):
        charger_regles_gestion(chemin)
    chemin.write_text(
        "regles:\n  - ref: decoupage\n    libelle: x\n    type: autre\n    table: t\n"
        "  - ref: R2\n    libelle: y\n    table: t\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as erreur:
        charger_regles_gestion(chemin)
    assert "type inconnu 'autre'" in str(erreur.value)
    assert "règle n° 2 (R2) : clé manquante (type)" in str(erreur.value)
    chemin.write_text(
        "regles:\n  - ref: decoupage\n    libelle: Date de début\n"
        "    type: date_dans_periode_export\n    table: interventions\n"
        "    colonne: date_debut\n",
        encoding="utf-8",
    )
    assert charger_regles_gestion(chemin) == [
        {
            "ref": "decoupage",
            "libelle": "Date de début",
            "type": "date_dans_periode_export",
            "table": "interventions",
            "colonne": "date_debut",
        }
    ]


def test_catalogue_des_types():
    catalogue = catalogue_types()
    assert list(catalogue.columns) == list(COLONNES_CATALOGUE)
    assert list(catalogue["type"]) == list(gestion.TYPES)
    ligne = catalogue.iloc[0].to_dict()
    assert ligne["parametres"] == "colonne (colonne de date)"
    assert ligne["vue"] == VUE_TOUTES
    assert ligne["issue"] == "à arbitrer"
    plage = catalogue.set_index("type").loc["plage"].to_dict()
    assert plage["parametres"] == (
        "colonne (colonne de nombre), min (nombre, facultatif), max (nombre, facultatif)"
    )
    assert plage["issue"] == "anomalie"


# Morceau 4b1 : plages de valeurs, filtre et issue déclarée.

DECIMAL = "décimal virgule (texte)"
ENTIER = "entier (texte)"
PLAGES = {"Contrôle": {"min": 30, "max": 90}, "Dépannage": {"min": 30}, "Pose": {"max": 600}}


def _instance(type_regle="plage", ref="R22", table="t", **parametres):
    return {"ref": ref, "libelle": "Plage", "type": type_regle, "table": table, **parametres}


def test_plage_bornes_incluses_et_valeurs_non_evaluables():
    donnees = _table(km=["2,0", "120,0", "1,9", "120,1", "", "18.4", "50,0"])
    ecarts, bilan = _controler(
        donnees, {"km": DECIMAL}, regles=[_instance(colonne="km", min=2, max=120)]
    )
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (4, CONSTAT_INFERIEURE, "anomalie", "km", "1,9"),
        (5, CONSTAT_SUPERIEURE, "anomalie", "km", "120,1"),
    ]
    assert set(ecarts["proposition"].isna()) == {True}
    resume = _bilan(bilan)
    assert (resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (2, 5, 2)
    assert (resume["colonnes"], resume["filtre"], resume["hors_champ"]) == ("km", None, 0)


def test_plage_avec_une_seule_borne():
    donnees = _table(n=["1", "5", "500"])
    ecarts, _ = _controler(donnees, {"n": ENTIER}, regles=[_instance(colonne="n", min=5)])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [(2, CONSTAT_INFERIEURE)]
    ecarts, _ = _controler(donnees, {"n": ENTIER}, regles=[_instance(colonne="n", max=5)])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [(4, CONSTAT_SUPERIEURE)]


def test_plage_selon_valeur():
    donnees = _table(
        duree=["20", "30", "91", "1000", "10", "20", "20", "", "20"],
        cat=["Contrôle", "Contrôle", "Contrôle", "Dépannage", "Pose", "Inconnue", None,
             "Contrôle", "Contrôle "],
    )
    regle = _instance("plage_selon_valeur", "R02", colonne="duree", selon="cat", plages=PLAGES)
    ecarts, bilan = _controler(donnees, {"duree": ENTIER, "cat": "texte"}, regles=[regle])
    # Dépannage sans maximum, Pose sans minimum; une catégorie inconnue, vide ou
    # mal saisie n'a pas de plage : la ligne est non évaluable, sans écart.
    assert _lignes(ecarts, "num_ligne_source", "constat", "colonnes", "valeur") == [
        (2, CONSTAT_INFERIEURE, "duree, cat", "20 | Contrôle"),
        (4, CONSTAT_SUPERIEURE, "duree, cat", "91 | Contrôle"),
    ]
    resume = _bilan(bilan)
    assert (resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (4, 5, 2)


def test_valeur_masquee_si_la_colonne_de_choix_est_sensible():
    donnees = _table(duree=["20"], cat=["Contrôle"])
    regle = _instance("plage_selon_valeur", colonne="duree", selon="cat", plages=PLAGES)
    ecarts, _ = _controler(donnees, {"duree": ENTIER, "cat": "texte"}, regles=[regle],
                           sensibles={"t": frozenset({"cat"})})
    assert _lignes(ecarts, "valeur", "proposition") == [(VALEUR_MASQUEE, None)]


def test_rapport_dans_plage():
    donnees = _table(
        km=["17,5", "10,0", "40,0", "5,0", "0,0", "", "18,4", "3,0"],
        mn=["15", "30", "30", "0", "0", "10", "", "6"],
    )
    regle = _instance("rapport_dans_plage", numerateur="km", denominateur="mn", facteur=60,
                      min=30, max=70)
    ecarts, bilan = _controler(donnees, {"km": DECIMAL, "mn": ENTIER}, regles=[regle])
    # 17,5 km en 15 min font exactement 70 km/h, dans la plage. Un dénominateur nul
    # est un écart, même avec un numérateur nul.
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (3, CONSTAT_RAPPORT_INFERIEUR, "10,0 | 30"),
        (4, CONSTAT_RAPPORT_SUPERIEUR, "40,0 | 30"),
        (5, CONSTAT_RAPPORT_NON_CALCULABLE, "5,0 | 0"),
        (6, CONSTAT_RAPPORT_NON_CALCULABLE, "0,0 | 0"),
    ]
    resume = _bilan(bilan)
    assert (resume["colonnes"], resume["non_evaluables"], resume["controlees"]) == (
        "km, mn",
        2,
        6,
    )
    # Sans facteur, le rapport est le simple quotient.
    regle = _instance("rapport_dans_plage", numerateur="km", denominateur="mn", max=1)
    ecarts, _ = _controler(donnees, {"km": DECIMAL, "mn": ENTIER}, regles=[regle])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [
        (2, CONSTAT_RAPPORT_SUPERIEUR),
        (4, CONSTAT_RAPPORT_SUPERIEUR),
        (5, CONSTAT_RAPPORT_NON_CALCULABLE),
        (6, CONSTAT_RAPPORT_NON_CALCULABLE),
    ]
    # 0,3 / 0,1 vaut 2,9999999999999996 en virgule flottante : le rapport est arrondi.
    regle = _instance("rapport_dans_plage", numerateur="a", denominateur="b", min=3)
    ecarts, _ = _controler(_table(a=["0,3"], b=["0,1"]), {"a": DECIMAL, "b": DECIMAL},
                           regles=[regle])
    assert ecarts.empty


def test_filtre_hors_champ_et_bilan():
    donnees = _table(
        km=["0,0", "0,0", "0,0", "0,0", "0,0", "0,0", "0,0"],
        statut=["Réalisée", "Annulée", "Reportée", "", "Réalisée ", None, "Réalisée"],
        type=["A", "A", "A", "A", "A", "A", "B"],
    )
    filtre = [{"colonne": "statut", "valeurs": ["Réalisée"]}]
    regle = _instance(colonne="km", min=2, filtre=filtre)
    natures = {"km": DECIMAL, "statut": "texte", "type": "texte"}
    ecarts, bilan = _controler(donnees, natures, regles=[regle])
    # Valeurs comparées telles quelles : « Réalisée » suivi d'une espace est hors champ.
    assert _lignes(ecarts, "num_ligne_source") == [(2,), (8,)]
    resume = _bilan(bilan)
    assert resume["filtre"] == "statut = Réalisée"
    assert (resume["lignes"], resume["hors_champ"], resume["non_evaluables"],
            resume["controlees"]) == (7, 5, 0, 2)
    # Plusieurs valeurs : l'une ou l'autre; plusieurs conditions : toutes.
    filtre = [
        {"colonne": "statut", "valeurs": ["Réalisée", "Annulée"]},
        {"colonne": "type", "valeurs": ["A"]},
    ]
    ecarts, bilan = _controler(donnees, natures, regles=[_instance(colonne="km", min=2,
                                                                  filtre=filtre)])
    assert _lignes(ecarts, "num_ligne_source") == [(2,), (3,)]
    assert _bilan(bilan)["filtre"] == "statut = Réalisée ou Annulée et type = A"
    assert _bilan(bilan)["hors_champ"] == 5


def test_filtre_apres_les_doublons_en_surnombre(type_sans_surnombre):
    donnees = _table(d=["14/03/2025", "14/03/2025", "15/03/2025"], s=["O", "O", "N"])
    filtre = [{"colonne": "s", "valeurs": ["O"]}]
    regles = [_regle(type="essai_vue", filtre=filtre)]
    _, bilan = _controler(donnees, {"d": "date JJ/MM/AAAA", "s": "texte"}, regles=regles)
    resume = _bilan(bilan)
    assert (resume["ecartees_doublons"], resume["hors_champ"], resume["controlees"]) == (1, 1, 1)


def test_issue_declaree_par_la_regle():
    donnees = _table(d=["14/03/2052"], n=["1"])
    natures = {"d": "date JJ/MM/AAAA", "n": ENTIER}
    regles = [
        _regle(issue="anomalie"),
        _instance(colonne="n", min=2, issue="information"),
        _instance(colonne="n", min=3, issue="à arbitrer"),
    ]
    ecarts, bilan = _controler(donnees, natures, regles=regles)
    assert list(ecarts["issue"]) == ["anomalie", "information", "à arbitrer"]
    assert list(bilan["anomalies"]) == [1, 0, 0]
    assert list(bilan["informations"]) == [0, 1, 0]
    assert list(bilan["a_arbitrer"]) == [0, 0, 1]


def test_structure_des_plages_filtres_et_issues():
    regles = [
        _instance(colonne="n", issue="grave"),
        _instance(colonne="n", min="2", max=True),
        _instance(colonne="n", min=5, max=2),
        _instance(colonne="n", min=1, filtre={"colonne": "s"}),
        _instance(colonne="n", min=1, filtre=[
            "s", {"colonne": "s", "valeur": ["O"]}, {"colonne": "", "valeurs": []},
            {"colonne": "s", "valeurs": ["O", 1]},
        ]),
        _instance("plage_selon_valeur", colonne="n", selon="c", plages={}),
        _instance("plage_selon_valeur", colonne="n", selon="c", plages={
            1: {"min": 1}, "A": 5, "B": {"mini": 1}, "C": {}, "D": {"min": 3, "max": 1},
        }),
        _instance("rapport_dans_plage", numerateur="n", denominateur="m", facteur=0, max=1),
        _instance("rapport_dans_plage", numerateur="n", min=1),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (R22), issue : issue inconnue 'grave' (issues possibles : anomalie, "
        "à arbitrer, information)",
        "règle n° 1 (R22) : min ou max attendu",
        "règle n° 2 (R22), min : un nombre est attendu",
        "règle n° 2 (R22), max : un nombre est attendu",
        "règle n° 3 (R22) : min (5) supérieur à max (2)",
        "règle n° 4 (R22), filtre : une liste de conditions est attendue (chaque condition "
        "commence par un tiret)",
        "règle n° 5 (R22), filtre, condition n° 1 : un dictionnaire est attendu (clés "
        "colonne et valeurs)",
        "règle n° 5 (R22), filtre, condition n° 2 : clé inconnue valeur (clés possibles : "
        "colonne, valeurs)",
        "règle n° 5 (R22), filtre, condition n° 2 : clé manquante (valeurs)",
        "règle n° 5 (R22), filtre, condition n° 3, colonne : un nom de colonne est attendu",
        "règle n° 5 (R22), filtre, condition n° 3, valeurs : une liste non vide est attendue",
        "règle n° 5 (R22), filtre, condition n° 4, valeurs : 1 n'est pas un texte (mettre "
        "un nombre entre guillemets)",
        "règle n° 6 (R22), plages : un dictionnaire non vide est attendu (valeur vers min "
        "et max)",
        "règle n° 7 (R22), plages : valeur 1 : un texte est attendu (mettre un nombre entre "
        "guillemets)",
        "règle n° 7 (R22), plages : valeur 'A' : un dictionnaire min et max est attendu",
        "règle n° 7 (R22), plages : valeur 'B' : clé inconnue mini (clés possibles : min, "
        "max)",
        "règle n° 7 (R22), plages : valeur 'C' : min ou max attendu",
        "règle n° 7 (R22), plages : valeur 'D' : min (3) supérieur à max (1)",
        "règle n° 8 (R22) : facteur : un nombre non nul est attendu",
        "règle n° 9 (R22) : paramètre manquant (denominateur)",
    ]


def test_regle_en_double_selon_les_parametres_et_le_filtre():
    filtre = [{"colonne": "s", "valeurs": ["O"]}]
    autre = [{"colonne": "s", "valeurs": ["N"]}]
    regles = [
        _instance(colonne="n", min=1, max=2),
        _instance(colonne="n", max=2.0, min=1, libelle="Autre libellé", issue="information"),
        _instance(colonne="n", min=1, max=2, filtre=filtre),
        _instance(colonne="n", min=1, max=2, filtre=autre),
        _instance("plage_selon_valeur", colonne="n", selon="c", plages=PLAGES),
        _instance("plage_selon_valeur", colonne="n", selon="c", plages=dict(PLAGES)),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 2 (R22) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 1 (R22))",
        "règle n° 6 (R22) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 5 (R22))",
    ]


def test_colonnes_de_nombre_et_de_filtre_confrontees_aux_donnees():
    tables = {"t": _table(n=["1"], m=["x"], c=["A"])}
    dictionnaire = _dictionnaire(n=ENTIER, m="à décider", c="texte")
    regles = [
        _instance(colonne="m", min=1),
        _instance(colonne="n", min=1, filtre=[{"colonne": "absente", "valeurs": ["O"]}]),
        _instance("plage_selon_valeur", colonne="n", selon="autre", plages=PLAGES),
        _instance("rapport_dans_plage", numerateur="n", denominateur="c", max=1),
    ]
    with pytest.raises(ValueError) as erreur:
        controler_gestion(tables, dictionnaire, regles, {}, None, AUCUNE_SENSIBLE)
    message = str(erreur.value)
    for attendu in (
        "règle n° 1 (R22), colonne : la nature en vigueur de t.m est 'à décider', un "
        "nombre est attendu",
        "règle n° 2 (R22), filtre : colonne t.absente absente des données chargées",
        "règle n° 3 (R22), selon : colonne t.autre absente des données chargées",
        "règle n° 4 (R22), denominateur : la nature en vigueur de t.c est 'texte', un "
        "nombre est attendu",
    ):
        assert attendu in message
    # Une colonne de choix n'a pas de nature imposée.
    ecarts, _ = controler_gestion(
        tables, dictionnaire,
        [_instance("plage_selon_valeur", colonne="n", selon="c", plages={"A": {"min": 2}})],
        {}, None, AUCUNE_SENSIBLE,
    )
    assert _lignes(ecarts, "constat") == [(CONSTAT_INFERIEURE,)]


def test_chargement_d_une_regle_avec_filtre(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: R22\n    libelle: Distance\n    type: plage\n    table: interventions\n"
        "    colonne: distance_km\n    min: 2\n    max: 120\n"
        "    filtre:\n      - colonne: statut\n        valeurs: [Réalisée]\n"
        "    issue: anomalie\n",
        encoding="utf-8",
    )
    assert charger_regles_gestion(chemin) == [
        {
            "ref": "R22",
            "libelle": "Distance",
            "type": "plage",
            "table": "interventions",
            "colonne": "distance_km",
            "min": 2,
            "max": 120,
            "filtre": [{"colonne": "statut", "valeurs": ["Réalisée"]}],
            "issue": "anomalie",
        }
    ]
