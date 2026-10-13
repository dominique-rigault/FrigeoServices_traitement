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
    CONSTAT_ABSENTE,
    CONSTAT_ANNEE_ABSENTE,
    CONSTAT_ANNEE_DU_NUMERO,
    CONSTAT_BATTEMENT,
    CONSTAT_CHEVAUCHEMENT,
    CONSTAT_DATE_ANTERIEURE,
    CONSTAT_DATE_AVANT_PRECEDENT,
    CONSTAT_DATE_POSTERIEURE,
    CONSTAT_DESEQUILIBRE,
    CONSTAT_ECART_CALCUL,
    CONSTAT_HORS_HORAIRES,
    CONSTAT_HORS_PERIODES,
    CONSTAT_INFERIEURE,
    CONSTAT_NUMEROS_MANQUANTS,
    CONSTAT_PERIODE_NON_COUVERTE,
    CONSTAT_RAPPORT_INFERIEUR,
    CONSTAT_RAPPORT_NON_CALCULABLE,
    CONSTAT_RAPPORT_SUPERIEUR,
    CONSTAT_SANS_LIGNE,
    CONSTAT_SUPERIEURE,
    CONSTAT_TOTAL_DIFFERENT,
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
        "avertissements": None,
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
        "date_dans_periode_export, plage, plage_selon_valeur, rapport_dans_plage, "
        "numerotation_continue, numerotation_chronologique, intervalles_sans_chevauchement, "
        "hors_horaires_selon_valeur, egalite_calculee, total_des_lignes, equilibre_par_groupe, "
        "existence_dans_reference, date_dans_periode_reference, "
        "periodes_couvertes_par_paliers, annee_dans_reference)",
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


# Morceau 4b2 : numérotation continue et chronologique.

MOTIF_SERIES = r"(?P<prefixe>[AB])-(?P<annee>\d{4})-(?P<numero>\d{3})"
MOTIF_INT = r"INT-(?P<annee>\d{4})-(?P<numero>\d{3})"
DATE = "date JJ/MM/AAAA"


def _numeros_a_trous():
    # La dernière ligne est la copie exacte de la deuxième.
    return _table(
        num=["A-2025-001", "A-2025-002", "A-2025-004", "A-2025-007", "A-2025-007",
             "A-2025-010", "A-2025-009", "B-2025-003", "", "A-2025-0011", "A-2025-002"],
        x=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "b"],
    )


def test_numerotation_continue():
    regle = _instance("numerotation_continue", "R01", colonne="num", motif=MOTIF_SERIES)
    ecarts, bilan = _controler(_numeros_a_trous(), {"num": "texte"}, regles=[regle])
    # Un trou est porté par la première ligne du numéro qui le suit, dans l'ordre
    # des numéros et non dans celui des lignes; un numéro répété ne crée pas de trou.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (4, CONSTAT_NUMEROS_MANQUANTS, "anomalie", "num", "A-2025-003 (1 numéro)"),
        (5, CONSTAT_NUMEROS_MANQUANTS, "anomalie", "num",
         "A-2025-005 à A-2025-006 (2 numéros)"),
        (8, CONSTAT_NUMEROS_MANQUANTS, "anomalie", "num", "A-2025-008 (1 numéro)"),
    ]
    resume = _bilan(bilan)
    assert (resume["vue"], resume["lignes"], resume["ecartees_doublons"]) == (
        VUE_SANS_SURNOMBRE, 11, 1,
    )
    # Une valeur vide ou qui ne suit pas le motif sur toute sa longueur est non
    # évaluable.
    assert (resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (2, 8, 3)


def test_numerotation_continue_avec_un_debut():
    regle = _instance("numerotation_continue", "R01", colonne="num", motif=MOTIF_SERIES,
                      debut=1)
    ecarts, _ = _controler(_numeros_a_trous(), {"num": "texte"}, regles=[regle])
    assert _lignes(ecarts, "num_ligne_source", "valeur") == [
        (4, "A-2025-003 (1 numéro)"),
        (5, "A-2025-005 à A-2025-006 (2 numéros)"),
        (8, "A-2025-008 (1 numéro)"),
        (9, "B-2025-001 à B-2025-002 (2 numéros)"),
    ]
    # Un numéro inférieur au début ne fait pas de trou.
    regle["debut"] = 3
    ecarts, _ = _controler(_numeros_a_trous(), {"num": "texte"}, regles=[regle])
    assert _lignes(ecarts, "num_ligne_source") == [(4,), (5,), (8,)]


def test_plage_manquante_masquee_si_la_colonne_est_sensible():
    regle = _instance("numerotation_continue", "R01", colonne="num", motif=MOTIF_SERIES)
    ecarts, _ = _controler(_numeros_a_trous(), {"num": "texte"}, regles=[regle],
                           sensibles={"t": frozenset({"num"})})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def _numeros_dates():
    return _table(
        num=["INT-2025-001", "INT-2025-002", "INT-2025-003", "INT-2025-004", "INT-2025-005",
             "INT-2025-006", "INT-2025-006", "INT-2025-007", "INT-2025-008", "INT-2026-001",
             "INT-2026-002", "X"],
        d=["10/01/2025", "09/01/2025", "14/03/2052", "15/01/2025", "", "16/01/2025",
           "01/01/2025", "10/01/2025", "10/01/2025", "31/12/2025", "05/01/2025",
           "01/01/2025"],
    )


def test_numerotation_chronologique():
    regle = _instance("numerotation_chronologique", "R01", colonne="num", motif=MOTIF_INT,
                      date="d")
    ecarts, bilan = _controler(_numeros_dates(), {"num": "texte", "d": DATE}, regles=[regle])
    # La ligne 6 (numéro 5 sans date) est sautée : le numéro 6 est comparé au 4.
    # Chaque ligne d'un numéro répété est jugée, mais seule la première représente
    # ce numéro pour le suivant. Une date égale n'est pas un écart. Une ligne peut
    # porter deux écarts.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (3, CONSTAT_DATE_AVANT_PRECEDENT, "à arbitrer", "num, d",
         "09/01/2025 (numéro précédent INT-2025-001 : 10/01/2025)"),
        (4, CONSTAT_ANNEE_DU_NUMERO, "à arbitrer", "num, d", "INT-2025-003 | 14/03/2052"),
        (5, CONSTAT_DATE_AVANT_PRECEDENT, "à arbitrer", "num, d",
         "15/01/2025 (numéro précédent INT-2025-003 : 14/03/2052)"),
        (8, CONSTAT_DATE_AVANT_PRECEDENT, "à arbitrer", "num, d",
         "01/01/2025 (numéro précédent INT-2025-004 : 15/01/2025)"),
        (9, CONSTAT_DATE_AVANT_PRECEDENT, "à arbitrer", "num, d",
         "10/01/2025 (numéro précédent INT-2025-006 : 16/01/2025)"),
        (11, CONSTAT_ANNEE_DU_NUMERO, "à arbitrer", "num, d", "INT-2026-001 | 31/12/2025"),
        (12, CONSTAT_DATE_AVANT_PRECEDENT, "à arbitrer", "num, d",
         "05/01/2025 (numéro précédent INT-2026-001 : 31/12/2025)"),
        (12, CONSTAT_ANNEE_DU_NUMERO, "à arbitrer", "num, d", "INT-2026-002 | 05/01/2025"),
    ]
    resume = _bilan(bilan)
    assert (resume["non_evaluables"], resume["controlees"], resume["a_arbitrer"]) == (2, 10, 8)
    assert resume["anomalies"] == 0


def test_numerotation_chronologique_sans_groupe_annee():
    regle = _instance("numerotation_chronologique", "R01", colonne="num",
                      motif=r"INT-(?P<an>\d{4})-(?P<numero>\d{3})", date="d")
    ecarts, _ = _controler(_numeros_dates(), {"num": "texte", "d": DATE}, regles=[regle])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [
        (3, CONSTAT_DATE_AVANT_PRECEDENT),
        (5, CONSTAT_DATE_AVANT_PRECEDENT),
        (8, CONSTAT_DATE_AVANT_PRECEDENT),
        (9, CONSTAT_DATE_AVANT_PRECEDENT),
        (12, CONSTAT_DATE_AVANT_PRECEDENT),
    ]


def test_numero_qui_n_est_pas_fait_de_chiffres_non_evaluable():
    donnees = _table(num=["N01", "NAB", "N03"])
    regle = _instance("numerotation_continue", "R01", colonne="num", motif=r"N(?P<numero>\w{2})")
    ecarts, bilan = _controler(donnees, {"num": "texte"}, regles=[regle])
    assert _lignes(ecarts, "num_ligne_source", "valeur") == [(4, "N02 (1 numéro)")]
    assert (_bilan(bilan)["non_evaluables"], _bilan(bilan)["controlees"]) == (1, 2)


def test_structure_des_regles_de_numerotation():
    regles = [
        _instance("numerotation_continue", colonne="n", motif=r"INT-(\d+"),
        _instance("numerotation_continue", colonne="n", motif=r"INT-(?P<annee>\d{4})"),
        _instance("numerotation_continue", colonne="n", motif=12),
        _instance("numerotation_continue", colonne="n", motif=r"(?P<numero>\d+)", debut=-1),
        _instance("numerotation_continue", colonne="n", motif=r"(?P<numero>\d+)", debut=1.5),
        _instance("numerotation_chronologique", colonne="n", motif=r"(?P<numero>\d+)"),
    ]
    problemes = problemes_regles_gestion(regles)
    assert len(problemes) == 6
    assert problemes[0].startswith("règle n° 1 (R22), motif : expression régulière invalide (")
    assert problemes[1:] == [
        "règle n° 2 (R22), motif : groupe nommé numero attendu, par exemple "
        r"(?P<numero>\d{6})",
        "règle n° 3 (R22), motif : une expression régulière est attendue",
        "règle n° 4 (R22) : debut : un entier positif ou nul est attendu",
        "règle n° 5 (R22) : debut : un entier positif ou nul est attendu",
        "règle n° 6 (R22) : paramètre manquant (date)",
    ]


def test_catalogue_des_types_de_numerotation():
    catalogue = catalogue_types().set_index("type")
    continue_ = catalogue.loc["numerotation_continue"].to_dict()
    assert continue_["parametres"] == (
        "colonne (colonne), motif (motif de numéro), debut (nombre, facultatif)"
    )
    assert (continue_["vue"], continue_["issue"]) == (VUE_SANS_SURNOMBRE, "anomalie")
    chronologique = catalogue.loc["numerotation_chronologique"].to_dict()
    assert chronologique["parametres"] == (
        "colonne (colonne), motif (motif de numéro), date (colonne de date)"
    )
    assert (chronologique["vue"], chronologique["issue"]) == (VUE_SANS_SURNOMBRE, "à arbitrer")


def test_chargement_d_une_regle_de_numerotation(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: R01\n    libelle: Numérotation\n    type: numerotation_continue\n"
        "    table: interventions\n    colonne: id_intervention\n"
        "    motif: 'INT-(?P<annee>\\d{4})-(?P<numero>\\d{6})'\n    debut: 1\n",
        encoding="utf-8",
    )
    regle = charger_regles_gestion(chemin)[0]
    assert regle["motif"] == r"INT-(?P<annee>\d{4})-(?P<numero>\d{6})"
    assert regle["debut"] == 1


# Morceau 4b3 : intervalles sans chevauchement et horaires.

DATE = "date JJ/MM/AAAA"
HEURE = "heure HH:MM"
NATURES_INTERVALLES = {"g": "texte", "d": DATE, "h": HEURE, "m": ENTIER}


def _intervalles(**autres):
    return _instance(
        "intervalles_sans_chevauchement", ref="R03", groupe="g", date="d", heure="h",
        duree="m", **autres,
    )


def test_intervalles_sans_chevauchement():
    donnees = _table(
        g=["A", "A", "A", "A", "A", "A", "B", "B", "B", "", "A", "A", "A"],
        d=["14/03/2025"] * 7 + ["15/03/2025", "14/03/2025", "14/03/2025", "14/03/2052",
                                "14/03/2025", "14/03/2025"],
        h=["08:00", "09:20", "09:55", "10:00", "10:30", "12:00", "23:30", "00:15", "08:00",
           "08:00", "08:00", "", "13:00"],
        m=["60", "30", "30", "120", "15", "30", "60", "30", "60", "60", "60", "30", "-5"],
    )
    ecarts, bilan = _controler(
        donnees, NATURES_INTERVALLES, regles=[_intervalles(battement=20)]
    )
    # Lignes 2 à 7 : A le 14/03; ligne 3 à 20 minutes exactement de la ligne 2.
    # La ligne 7 (12:00) suit la ligne 5 (10:00 à 12:00), qui finit le plus tard,
    # et non la ligne 6 (10:30 à 10:45) qu'elle contient.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (4, CONSTAT_BATTEMENT, "anomalie",
         "14/03/2025 09:55 à 10:25, après 14/03/2025 09:20 à 09:50 (t.csv, ligne 3)"),
        (5, CONSTAT_CHEVAUCHEMENT, "anomalie",
         "14/03/2025 10:00 à 12:00, après 14/03/2025 09:55 à 10:25 (t.csv, ligne 4)"),
        (6, CONSTAT_CHEVAUCHEMENT, "anomalie",
         "14/03/2025 10:30 à 10:45, après 14/03/2025 10:00 à 12:00 (t.csv, ligne 5)"),
        (7, CONSTAT_BATTEMENT, "anomalie",
         "14/03/2025 12:00 à 12:30, après 14/03/2025 10:00 à 12:00 (t.csv, ligne 5)"),
        (9, CONSTAT_CHEVAUCHEMENT, "anomalie",
         "15/03/2025 00:15 à 00:45, après 14/03/2025 23:30 à 15/03/2025 00:30 "
         "(t.csv, ligne 8)"),
    ]
    assert set(ecarts["colonnes"]) == {"g, d, h, m"}
    resume = _bilan(bilan)
    # Non évaluables : groupe vide, heure vide, durée négative.
    assert (resume["vue"], resume["non_evaluables"], resume["controlees"]) == (
        VUE_SANS_SURNOMBRE, 3, 10,
    )
    assert (resume["anomalies"], resume["avertissements"]) == (5, None)
    # Sans battement, seuls les chevauchements restent.
    ecarts, _ = _controler(donnees, NATURES_INTERVALLES, regles=[_intervalles()])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [
        (5, CONSTAT_CHEVAUCHEMENT), (6, CONSTAT_CHEVAUCHEMENT), (9, CONSTAT_CHEVAUCHEMENT),
    ]


def test_intervalles_comparaison_sans_heure_et_doublons():
    donnees = _table(
        g=["Dupont Jean", "DUPONT  Jean ", "Dupônt jean", "Dupont Jean"],
        d=["14/03/2025", "14/03/2025", "15/03/2025", "14/03/2025"],
        m=["60", "45", "60", "60"],
    )
    natures = {"g": "texte", "d": DATE, "m": ENTIER}
    sans_heure = _instance(
        "intervalles_sans_chevauchement", ref="R03", groupe="g", date="d", duree="m"
    )
    ecarts, bilan = _controler(donnees, natures, regles=[sans_heure])
    # Telle quelle : la ligne 5 est une copie exacte de la ligne 2, écartée.
    assert ecarts.empty
    assert _bilan(bilan)["ecartees_doublons"] == 1
    normalisee = {**sans_heure, "comparaison": "après normalisation"}
    ecarts, _ = _controler(donnees, natures, regles=[normalisee])
    # À début égal, la ligne qui finit la première est prise d'abord.
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (2, CONSTAT_CHEVAUCHEMENT,
         "14/03/2025 00:00 à 01:00, après 14/03/2025 00:00 à 00:45 (t.csv, ligne 3)"),
    ]
    # Groupe sensible : valeur masquée.
    ecarts, _ = _controler(donnees, natures, regles=[normalisee], sensibles={"t": {"g"}})
    assert list(ecarts["valeur"]) == [VALEUR_MASQUEE]


HORAIRES = {
    "lundi": [{"debut": "07:30", "fin": "18:00"}],
    "mardi": [{"debut": "07:30", "fin": "18:00"}],
    "mercredi": [{"debut": "07:30", "fin": "18:00"}],
    "jeudi": [{"debut": "07:30", "fin": "18:00"}],
    "vendredi": [{"debut": "07:30", "fin": "18:00"}],
}
NATURES_HORAIRES = {"d": DATE, "h": HEURE, "c": "texte"}


def _horaires(horaires=None, feries=None, valeurs=("Dépannage",), **autres):
    return _instance(
        "hors_horaires_selon_valeur", ref="R04", date="d", heure="h",
        horaires=HORAIRES if horaires is None else horaires,
        feries={2025: ["2025-05-01"]} if feries is None else feries,
        colonne="c", valeurs=list(valeurs), **autres,
    )


def test_hors_horaires_selon_valeur():
    donnees = _table(
        d=["03/03/2025", "03/03/2025", "03/03/2025", "08/03/2025", "01/05/2025",
           "09/03/2025", "04/03/2025", "14/03/2052", "04/03/2025", "14/03/2025"],
        h=["07:30", "18:00", "07:29", "09:00", "10:00", "10:00", "", "10:00", "10:00", "18:30"],
        c=["Maintenance", "Maintenance", "Dépannage", "Maintenance", "Contrôle", "", "Contrôle",
           "Maintenance", "", "dépannage"],
    )
    ecarts, bilan = _controler(donnees, NATURES_HORAIRES, regles=[_horaires()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (3, CONSTAT_HORS_HORAIRES, "anomalie", "lundi 03/03/2025 18:00 | Maintenance"),
        (5, CONSTAT_HORS_HORAIRES, "anomalie", "samedi 08/03/2025 09:00 | Maintenance"),
        (6, CONSTAT_HORS_HORAIRES, "anomalie", "férié 01/05/2025 10:00 | Contrôle"),
        (11, CONSTAT_HORS_HORAIRES, "anomalie", "vendredi 14/03/2025 18:30 | dépannage"),
    ]
    assert set(ecarts["colonnes"]) == {"d, h, c"}
    resume = _bilan(bilan)
    # Non évaluables : dimanche sans catégorie, heure vide, année 2052 sans jours
    # fériés. Une catégorie vide dans les horaires est évaluable. Les valeurs admises
    # sont comparées telles quelles (« dépannage » n'est pas admise).
    assert (resume["vue"], resume["non_evaluables"], resume["controlees"]) == (VUE_TOUTES, 3, 7)
    assert resume["avertissements"] == (
        "année 2052 absente des jours fériés déclarés : 1 ligne non évaluable"
    )


def test_astreinte_creneaux_d_un_jour_ferie_et_aucune_valeur_admise():
    horaires = {
        **{jour: [{"debut": "07:30", "fin": "21:00"}] for jour in HORAIRES},
        "samedi": [{"debut": "07:30", "fin": "13:00"}],
        "dimanche": [{"debut": "00:00", "fin": "24:00"}],
        "ferie": [{"debut": "07:30", "fin": "21:00"}],
    }
    donnees = _table(
        d=["03/03/2025", "08/03/2025", "08/03/2025", "01/05/2025", "01/05/2025", "09/03/2025"],
        h=["20:59", "12:59", "13:00", "20:00", "21:30", "23:59"],
        c=["Dépannage"] * 6,
    )
    ecarts, bilan = _controler(
        donnees, NATURES_HORAIRES, regles=[_horaires(horaires, valeurs=(), issue="à arbitrer")]
    )
    assert _lignes(ecarts, "num_ligne_source", "issue", "valeur") == [
        (4, "à arbitrer", "samedi 08/03/2025 13:00 | Dépannage"),
        (6, "à arbitrer", "férié 01/05/2025 21:30 | Dépannage"),
    ]
    assert (_bilan(bilan)["controlees"], _bilan(bilan)["a_arbitrer"]) == (6, 2)


def test_avertissements_sur_les_jours_feries():
    donnees = _table(
        d=["03/03/2025", "03/03/2026", "04/03/2026", "03/03/2027"],
        h=["10:00"] * 4,
        c=["Maintenance"] * 4,
    )
    feries = {2025: ["2025-01-01", "2025-05-01"], "2026": [], 2028: ["2028-01-01"]}
    _, bilan = _controler(
        donnees, NATURES_HORAIRES, regles=[_horaires(feries=feries, feries_minimum=10)]
    )
    resume = _bilan(bilan)
    assert resume["avertissements"] == (
        "année 2025 : 2 jours fériés déclarés, moins que feries_minimum (10); "
        "année 2026 : aucun jour férié déclaré; "
        "année 2027 absente des jours fériés déclarés : 1 ligne non évaluable"
    )
    assert (resume["non_evaluables"], resume["controlees"]) == (1, 3)
    for regle in (_horaires(feries=feries), _horaires(feries=feries, feries_minimum=2)):
        _, bilan = _controler(donnees, NATURES_HORAIRES, regles=[regle])
        assert _bilan(bilan)["avertissements"] == (
            "année 2026 : aucun jour férié déclaré; "
            "année 2027 absente des jours fériés déclarés : 1 ligne non évaluable"
        )


def test_structure_des_intervalles_et_des_horaires():
    regles = [
        _intervalles(battement=-1, comparaison="approchée"),
        _horaires(
            horaires={
                "lundy": [],
                "mardi": [{"debut": 450, "fin": "18:00"}],
                "mercredi": [{"debut": "18:00", "fin": "07:30"}],
                "jeudi": [{"debut": "07:30"}],
                "vendredi": "07:30",
                "samedi": [{"debut": "08:00", "fin": "08:00"}],
                "dimanche": [{"debut": "7:30", "fin": "25:00"}],
            },
            feries={
                "2025": ["2025-01-01", "2026-05-01", "2025-02-30", "2025-01-01"],
                2025: [],
                "an": [],
                2026: "2026-01-01",
            },
            feries_minimum=1.5,
        ),
        {**_horaires(), "valeurs": "Dépannage", "horaires": {}},
    ]
    problemes = problemes_regles_gestion(regles)
    assert problemes == [
        "règle n° 1 (R03), comparaison : comparaison inconnue 'approchée' (comparaisons "
        "possibles : telle quelle, après normalisation, mots dans le désordre)",
        "règle n° 2 (R04), horaires : jour inconnu 'lundy' (jours possibles : lundi, mardi, "
        "mercredi, jeudi, vendredi, samedi, dimanche, ferie)",
        "règle n° 2 (R04), horaires : mardi, créneau n° 1, debut : une heure HH:MM entre "
        "guillemets est attendue (par exemple '07:30')",
        "règle n° 2 (R04), horaires : mercredi, créneau n° 1 : debut (18:00) n'est pas avant "
        "fin (07:30)",
        "règle n° 2 (R04), horaires : jeudi, créneau n° 1 : clés debut et fin attendues",
        "règle n° 2 (R04), horaires : vendredi : une liste de créneaux est attendue (chaque "
        "créneau commence par un tiret, liste vide [] pour aucun)",
        "règle n° 2 (R04), horaires : samedi, créneau n° 1 : debut (08:00) n'est pas avant "
        "fin (08:00)",
        "règle n° 2 (R04), horaires : dimanche, créneau n° 1, debut : une heure HH:MM entre "
        "guillemets est attendue (par exemple '07:30')",
        "règle n° 2 (R04), horaires : dimanche, créneau n° 1, fin : une heure HH:MM entre "
        "guillemets est attendue (par exemple '07:30')",
        "règle n° 2 (R04), feries : année 2025 : 2026-05-01 n'est pas de cette année",
        "règle n° 2 (R04), feries : année 2025 : '2025-02-30' n'est pas une date AAAA-MM-JJ",
        "règle n° 2 (R04), feries : année 2025 : 2025-01-01 déclaré deux fois",
        "règle n° 2 (R04), feries : année 2025 déclarée deux fois",
        "règle n° 2 (R04), feries : année 'an' : une année AAAA est attendue",
        "règle n° 2 (R04), feries : année 2026 : une liste de dates est attendue (liste vide "
        "[] pour aucune)",
        "règle n° 3 (R04), horaires : un dictionnaire non vide est attendu (jour vers "
        "créneaux, jours possibles : lundi, mardi, mercredi, jeudi, vendredi, samedi, "
        "dimanche, ferie)",
        "règle n° 3 (R04), valeurs : une liste de valeurs est attendue (liste vide [] pour "
        "n'en admettre aucune)",
    ]
    # Les problèmes propres au type ne sont cherchés que si les paramètres sont bien formés.
    assert problemes_regles_gestion(
        [_intervalles(battement=-1), _horaires(feries_minimum=1.5)]
    ) == [
        "règle n° 1 (R03) : battement : un nombre positif ou nul est attendu",
        "règle n° 2 (R04) : feries_minimum : un entier positif ou nul est attendu",
    ]


def test_colonne_d_heure_confrontee_au_dictionnaire():
    donnees = _table(g=["A"], d=["14/03/2025"], h=["08:00"], m=["60"])
    with pytest.raises(ValueError) as erreur:
        _controler(donnees, {**NATURES_INTERVALLES, "h": "texte"}, regles=[_intervalles()])
    assert (
        "règle n° 1 (R03), heure : la nature en vigueur de t.h est 'texte', une heure est "
        "attendue" in str(erreur.value)
    )


def test_catalogue_des_types_du_4b3():
    catalogue = catalogue_types().set_index("type")
    intervalles = catalogue.loc["intervalles_sans_chevauchement"].to_dict()
    assert intervalles["parametres"] == (
        "groupe (colonne), date (colonne de date), heure (colonne d'heure, facultatif), "
        "duree (colonne de nombre), battement (nombre, facultatif), comparaison "
        "(comparaison, facultatif)"
    )
    assert (intervalles["vue"], intervalles["issue"]) == (VUE_SANS_SURNOMBRE, "anomalie")
    horaires = catalogue.loc["hors_horaires_selon_valeur"].to_dict()
    assert horaires["parametres"] == (
        "date (colonne de date), heure (colonne d'heure), horaires (horaires), feries "
        "(jours fériés), feries_minimum (nombre, facultatif), colonne (colonne), valeurs "
        "(liste de valeurs)"
    )
    assert (horaires["vue"], horaires["issue"]) == (VUE_TOUTES, "anomalie")


def test_chargement_d_une_regle_d_horaires(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    texte = (
        "regles:\n"
        "  - ref: R04\n    libelle: Hors horaires\n    type: hors_horaires_selon_valeur\n"
        "    table: interventions\n    date: date_debut\n    heure: heure_debut\n"
        "    horaires:\n      lundi: [{debut: '07:30', fin: FIN}]\n"
        "    feries:\n      2025: [2025-01-01, '2025-05-01']\n"
        "    feries_minimum: 10\n    colonne: categorie\n    valeurs: []\n"
    )
    chemin.write_text(texte.replace("FIN", "'18:00'"), encoding="utf-8")
    regle = charger_regles_gestion(chemin)[0]
    assert regle["horaires"] == {"lundi": [{"debut": "07:30", "fin": "18:00"}]}
    assert regle["feries"] == {2025: [dt.date(2025, 1, 1), "2025-05-01"]}
    assert regle["valeurs"] == []
    # Sans guillemets, 18:00 est lu par YAML comme un nombre (1080).
    chemin.write_text(texte.replace("FIN", "18:00"), encoding="utf-8")
    with pytest.raises(ValueError, match="lundi, créneau n° 1, fin : une heure HH:MM"):
        charger_regles_gestion(chemin)


# Morceau 4c : calculs dans une ligne, totaux des lignes liées, équilibre par groupe.

NATIF = "nombre natif"


def _tva(termes=None, **autres):
    return _instance(
        "egalite_calculee", ref="R05", cible="tva",
        termes={"ht": 0.2} if termes is None else termes, **autres,
    )


def test_egalite_calculee_avec_tolerance():
    donnees = _table(
        ht=[181.45, 181.45, 10.025, 10.0, -50.0, None, "x", 100.0],
        tva=[36.29, 36.30, 2.0, 2.006, -10.0, 1.0, 1.0, ""],
    )
    natures = {"ht": NATIF, "tva": NATIF}
    ecarts, bilan = _controler(donnees, natures, regles=[_tva(tolerance=0.005)])
    # 36,29 est exactement 0,2 x 181,45; 2,005 est à 0,005 de 2 (tolérance incluse).
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (3, CONSTAT_ECART_CALCUL, "anomalie", "tva, ht",
         "36,3 pour un calcul de 36,29 (écart 0,01)"),
        (5, CONSTAT_ECART_CALCUL, "anomalie", "tva, ht",
         "2,006 pour un calcul de 2 (écart 0,006)"),
    ]
    resume = _bilan(bilan)
    assert (resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (3, 5, 2)
    # Sans tolérance, l'écart d'arrondi de 0,005 en est un.
    ecarts, _ = _controler(donnees, natures, regles=[_tva()])
    assert _lignes(ecarts, "num_ligne_source") == [(3,), (4,), (5,)]


def test_egalite_calculee_somme_de_plusieurs_termes():
    donnees = _table(ht=["0,1", "10,00", "10,00"], tva=["0,2", "2,00", "2,00"],
                     ttc=["0,3", "12,00", "12,01"])
    ecarts, _ = _controler(
        donnees,
        {"ht": DECIMAL, "tva": DECIMAL, "ttc": DECIMAL},
        regles=[_instance("egalite_calculee", ref="R05", cible="ttc",
                          termes={"ht": 1, "tva": 1})],
    )
    # 0,1 + 0,2 ne fait pas un écart malgré le calcul en virgule flottante.
    assert _lignes(ecarts, "num_ligne_source", "colonnes", "valeur") == [
        (4, "ttc, ht, tva", "12,01 pour un calcul de 12 (écart 0,01)")
    ]


def _total(ref="R05", **autres):
    parametres = {"cle": ["num"], "colonne": "total", "table_lignes": "l",
                  "colonne_lignes": "montant", **autres}
    return _instance("total_des_lignes", ref=ref, **parametres)


NATURES_TOTAL = {
    "t": {"num": "texte", "total": NATIF},
    "l": {"num": "texte", "rang": "texte", "montant": DECIMAL},
}


def _dictionnaire_total(**natures):
    dictionnaire = {}
    for table, colonnes in {**NATURES_TOTAL, **natures}.items():
        dictionnaire.update(_dictionnaire(table, **colonnes))
    return dictionnaire


def _controler_total(entetes, lignes, regles=None, sensibles=AUCUNE_SENSIBLE,
                     dictionnaire=None, declarations=None):
    return controler_gestion(
        {"t": entetes, "l": lignes},
        _dictionnaire_total() if dictionnaire is None else dictionnaire,
        [_total()] if regles is None else regles,
        {} if declarations is None else declarations,
        None,
        sensibles,
    )


def _entetes_et_lignes():
    entetes = _table(
        "e.xlsx",
        num=["F1", "F2", "F3", "F4", "F5", "F6", "F6", "", "F1"],
        total=[30.3, 10.0, 7.0, 5.0, "x", 1.0, 2.0, 3.0, 30.3],
    )
    lignes = _table(
        "l.xlsx",
        num=["F1", "F1", "F1", "F2", "F4", "F4", "F5", "F6", "", "F1", "G9"],
        rang=["1", "2", "3", "1", "1", "2", "1", "1", "1", "1", "1"],
        montant=["10,1", "10,1", "10,1", "9,99", "5,00", "", "1,00", "1,00", "4,00",
                 "10,1", "1,00"],
    )
    # Le dernier en-tête F1 et la dernière ligne F1 sont des doublons exacts.
    return entetes, lignes


def test_total_des_lignes():
    entetes, lignes = _entetes_et_lignes()
    lignes = lignes.drop(index=[2])
    ecarts, bilan = _controler_total(entetes, lignes)
    # F1 : 10,1 + 10,1 et la copie exacte d'une ligne, écartée; F2 : 0,01 d'écart;
    # F3 sans ligne; F4 a un montant vide; F5 un total illisible; F6 est répété.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (2, CONSTAT_TOTAL_DIFFERENT, "anomalie", "num, total, l.num, l.montant",
         "30,3 pour une somme de 20,2 sur 2 lignes liées (écart 10,1)"),
        (3, CONSTAT_TOTAL_DIFFERENT, "anomalie", "num, total, l.num, l.montant",
         "10 pour une somme de 9,99 sur 1 ligne liée (écart 0,01)"),
        (4, CONSTAT_SANS_LIGNE, "anomalie", "num, total, l.num, l.montant", "F3 | 7.0"),
    ]
    assert _bilan(bilan) == {
        "ref": "R05",
        "type": "total_des_lignes",
        "libelle": "Plage",
        "table": "t",
        "colonnes": "num, total, l.num, l.montant",
        "vue": VUE_SANS_SURNOMBRE,
        "filtre": None,
        "lignes": 9,
        "ecartees_doublons": 1,
        "hors_champ": 0,
        "non_evaluables": 5,
        "controlees": 3,
        "anomalies": 3,
        "a_arbitrer": 0,
        "informations": 0,
        "avertissements": None,
    }


def test_total_des_lignes_tolerance_et_somme_exacte():
    entetes, lignes = _entetes_et_lignes()
    ecarts, _ = _controler_total(entetes, lignes, regles=[_total(tolerance=0.01)])
    # 10,1 x 3 fait 30,3 sans écart; l'écart de 0,01 de F2 est toléré.
    assert _lignes(ecarts, "num_ligne_source", "constat") == [(4, CONSTAT_SANS_LIGNE)]


def test_total_des_lignes_masque_si_une_colonne_liee_est_sensible():
    entetes, lignes = _entetes_et_lignes()
    for sensibles in ({"l": frozenset({"montant"})}, {"t": frozenset({"total"})}):
        ecarts, _ = _controler_total(entetes, lignes, sensibles=sensibles)
        assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}
    ecarts, _ = _controler_total(entetes, lignes, declarations={"t": {"cle": ["num"]}})
    assert _lignes(ecarts, "cle") == [("F2",), ("F3",)]


def _equilibre(groupe=("j", "n"), **autres):
    return _instance(
        "equilibre_par_groupe", ref="R06", groupe=list(groupe) if isinstance(groupe, tuple)
        else groupe, debit="d", credit="c", **autres,
    )


NATURES_EQUILIBRE = {"j": "texte", "n": "texte", "d": DECIMAL, "c": DECIMAL}


def test_equilibre_par_groupe():
    donnees = _table(
        j=["VT", "VT", "VT", "AC", "AC", "AC", "BQ", "BQ", "OD", "VT", "OD"],
        n=["1", "1", "1", "1", "1", "1", "2", "2", "3", "2", " "],
        d=["100,00", "0,00", "0,00", "0,00", "50,00", "0,00", "x", "0,00", "1,00", "5,00",
           "1,00"],
        c=["0,00", "80,00", "20,00", "40,00", "0,00", "0,00", "1,00", "0,00", "0,00", "0,00",
           "0,00"],
    )
    ecarts, bilan = _controler(donnees, NATURES_EQUILIBRE, regles=[_equilibre()])
    # VT 1 équilibrée; AC 1 déséquilibrée sur ses trois lignes; BQ 2 a un débit
    # illisible; VT 2 n'a qu'une ligne au débit; un groupe fait d'espaces est vide.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (5, CONSTAT_DESEQUILIBRE, "anomalie", "j, n, d, c",
         "AC | 1 : débit 50, crédit 40 (écart 10, 3 lignes)"),
        (6, CONSTAT_DESEQUILIBRE, "anomalie", "j, n, d, c",
         "AC | 1 : débit 50, crédit 40 (écart 10, 3 lignes)"),
        (7, CONSTAT_DESEQUILIBRE, "anomalie", "j, n, d, c",
         "AC | 1 : débit 50, crédit 40 (écart 10, 3 lignes)"),
        (10, CONSTAT_DESEQUILIBRE, "anomalie", "j, n, d, c",
         "OD | 3 : débit 1, crédit 0 (écart 1, 1 ligne)"),
        (11, CONSTAT_DESEQUILIBRE, "anomalie", "j, n, d, c",
         "VT | 2 : débit 5, crédit 0 (écart 5, 1 ligne)"),
    ]
    resume = _bilan(bilan)
    assert (resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (3, 8, 5)
    ecarts, _ = _controler(donnees, NATURES_EQUILIBRE, regles=[_equilibre(tolerance=5)])
    assert _lignes(ecarts, "num_ligne_source") == [(5,), (6,), (7,)]


def test_equilibre_sans_les_doublons_exacts_en_surnombre():
    donnees = _table(j=["VT", "VT", "VT"], n=["1", "1", "1"], d=["10,00", "0,00", "0,00"],
                     c=["0,00", "10,00", "10,00"])
    ecarts, bilan = _controler(donnees, NATURES_EQUILIBRE, regles=[_equilibre()])
    assert ecarts.empty
    assert (_bilan(bilan)["ecartees_doublons"], _bilan(bilan)["controlees"]) == (1, 2)


def test_structure_des_types_du_4c():
    regles = [
        _tva(termes=[]),
        _tva(termes={"ht": "0,2", "": 1}),
        _total(cle=[], table_lignes=""),
        _total(cle=["num", "num"], colonne_lignes=3),
        _equilibre(groupe="j"),
        _equilibre(groupe=["j", 1]),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (R05), termes : un dictionnaire non vide est attendu (colonne vers "
        "coefficient, par exemple {total_ht: 1, total_tva: 1})",
        "règle n° 2 (R05), termes : ht : un nombre est attendu comme coefficient",
        "règle n° 2 (R05), termes : '' n'est pas un nom de colonne",
        "règle n° 3 (R05), cle : une liste non vide de noms de colonnes est attendue "
        "(colonnes des deux tables)",
        "règle n° 3 (R05), table_lignes : un nom de table est attendu",
        "règle n° 4 (R05), cle : colonne citée deux fois",
        "règle n° 4 (R05), colonne_lignes : un nom de colonne est attendu (colonne de "
        "nombre de la table liée)",
        "règle n° 5 (R06), groupe : une liste non vide de noms de colonnes est attendue "
        "(liste de colonnes)",
        "règle n° 6 (R06), groupe : 1 n'est pas un nom de colonne",
    ]
    assert problemes_regles_gestion(
        [_tva(tolerance=-0.01), _total(tolerance=-1), _equilibre(tolerance=-1)]
    ) == [
        "règle n° 1 (R05) : tolerance : un nombre positif ou nul est attendu",
        "règle n° 2 (R05) : tolerance : un nombre positif ou nul est attendu",
        "règle n° 3 (R06) : tolerance : un nombre positif ou nul est attendu",
    ]


def test_table_et_colonnes_liees_confrontees_aux_donnees():
    entetes, lignes = _entetes_et_lignes()
    with pytest.raises(ValueError) as erreur:
        controler_gestion(
            {"t": entetes}, _dictionnaire_total(), [_total()], {}, None, AUCUNE_SENSIBLE
        )
    # La table absente n'est signalée qu'une fois, malgré ses deux colonnes citées.
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R05), table_lignes : table l absente des données chargées"
    ]
    with pytest.raises(ValueError) as erreur:
        _controler_total(
            entetes,
            lignes.drop(columns=["num"]),
            regles=[_total(), _total(ref="R5b", colonne_lignes="autre")],
            dictionnaire=_dictionnaire_total(l={"num": "texte", "montant": "texte"}),
        )
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R05), cle : colonne l.num absente des données chargées",
        "règle n° 1 (R05), colonne_lignes : la nature en vigueur de l.montant est 'texte', "
        "un nombre est attendu (à trancher dans la revue du dictionnaire, notebook "
        "02c_dictionnaire)",
        "règle n° 2 (R5b), cle : colonne l.num absente des données chargées",
        "règle n° 2 (R5b), colonne_lignes : colonne l.autre absente des données chargées",
    ]
    donnees = _table(ht=[1.0], tva=[0.2])
    with pytest.raises(ValueError) as erreur:
        _controler(donnees, {"ht": "texte", "tva": NATIF}, regles=[_tva()])
    assert "règle n° 1 (R05), termes : la nature en vigueur de t.ht est 'texte'" in str(
        erreur.value
    )


def test_catalogue_des_types_du_4c():
    catalogue = catalogue_types().set_index("type")
    assert catalogue.loc["egalite_calculee", "parametres"] == (
        "cible (colonne de nombre), termes (termes), tolerance (nombre, facultatif)"
    )
    assert catalogue.loc["total_des_lignes", "parametres"] == (
        "cle (colonnes des deux tables), colonne (colonne de nombre), table_lignes (table), "
        "colonne_lignes (colonne de nombre de la table liée), tolerance (nombre, facultatif)"
    )
    assert catalogue.loc["equilibre_par_groupe", "parametres"] == (
        "groupe (liste de colonnes), debit (colonne de nombre), credit (colonne de nombre), "
        "tolerance (nombre, facultatif)"
    )
    assert list(catalogue.loc[["egalite_calculee", "total_des_lignes", "equilibre_par_groupe"],
                              "vue"]) == [VUE_TOUTES, VUE_SANS_SURNOMBRE, VUE_SANS_SURNOMBRE]
    assert set(catalogue.loc[["egalite_calculee", "total_des_lignes", "equilibre_par_groupe"],
                             "issue"]) == {"anomalie"}


def test_chargement_des_regles_du_4c(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: R05\n    libelle: TVA\n    type: egalite_calculee\n"
        "    table: factures_entetes\n    cible: total_tva\n"
        "    termes: {total_ht: 0.2}\n    tolerance: 0.005\n"
        "  - ref: R05\n    libelle: Lignes\n    type: total_des_lignes\n"
        "    table: factures_entetes\n    cle: [num_facture]\n    colonne: total_ht\n"
        "    table_lignes: factures_lignes\n    colonne_lignes: montant_ht\n"
        "  - ref: R06\n    libelle: Equilibre\n    type: equilibre_par_groupe\n"
        "    table: fec\n    groupe: [JournalCode, EcritureNum]\n"
        "    debit: Debit\n    credit: Credit\n",
        encoding="utf-8",
    )
    regles = charger_regles_gestion(chemin)
    assert regles[0]["termes"] == {"total_ht": 0.2}
    assert regles[1]["cle"] == ["num_facture"]
    assert regles[2]["groupe"] == ["JournalCode", "EcritureNum"]


# Morceau 4d : confrontation aux référentiels (existence, périodes, paliers, années).

NATIVE = "date native"


def _reference(type_regle, ref="R10", **parametres):
    return _instance(type_regle, ref=ref, table_reference="r", **parametres)


def _controler_reference(donnees, reference, natures, natures_reference, regles,
                         sensibles=AUCUNE_SENSIBLE, declarations=None):
    """Contrôle d'une table « t » face à un référentiel « r »; aucune lecture de config/."""
    return controler_gestion(
        {"t": donnees, "r": reference},
        {**_dictionnaire("t", **natures), **_dictionnaire("r", **natures_reference)},
        regles,
        {} if declarations is None else declarations,
        None,
        sensibles,
    )


def _existence(**autres):
    return _reference("existence_dans_reference", ref="existence", **{"cle": ["c"], **autres})


def test_existence_dans_reference():
    donnees = _table(c=["A1", "B2", " ", "Z9", "a1 ", None, "Z9"],
                     f=["o", "o", "o", "o", "o", "o", "n"])
    reference = _table("r.csv", c=["A1", "B2", "", "C3"])
    natures = {"c": "texte", "f": "texte"}
    ecarts, bilan = _controler_reference(
        donnees, reference, natures, {"c": "texte"}, [_existence()]
    )
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (5, CONSTAT_ABSENTE, "anomalie", "c, r.c", "Z9"),
        (6, CONSTAT_ABSENTE, "anomalie", "c, r.c", "a1 "),
        (8, CONSTAT_ABSENTE, "anomalie", "c, r.c", "Z9"),
    ]
    resume = _bilan(bilan)
    assert (resume["vue"], resume["hors_champ"], resume["non_evaluables"],
            resume["controlees"], resume["anomalies"]) == (VUE_TOUTES, 0, 2, 5, 3)
    # Après normalisation, « a1 » rejoint « A1 ».
    ecarts, _ = _controler_reference(
        donnees, reference, natures, {"c": "texte"},
        [_existence(comparaison="après normalisation")],
    )
    assert _lignes(ecarts, "num_ligne_source") == [(5,), (8,)]
    # Clé facultative : les clés vides sont hors champ, comptées avec celles du filtre.
    ecarts, bilan = _controler_reference(
        donnees, reference, natures, {"c": "texte"},
        [_existence(cle_facultative=True, filtre=[{"colonne": "f", "valeurs": ["o"]}])],
    )
    assert _lignes(ecarts, "num_ligne_source") == [(5,), (6,)]
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"]) == (3, 0, 4)


def test_existence_cle_de_plusieurs_colonnes_et_mots_dans_le_desordre():
    donnees = _table(nom=["LEROUX Mathieu", "Mathieu Leroux", "leroux  mathieu", "LEROUX M.",
                          "DUPONT Jean"])
    reference = _table("r.csv", n=["LEROUX", "DUPONT"], p=["Mathieu", ""])
    natures, natures_reference = {"nom": "texte"}, {"n": "texte", "p": "texte"}

    def absentes(comparaison):
        regle = _reference("existence_dans_reference", cle=["nom"], cle_reference=["n", "p"],
                           comparaison=comparaison)
        ecarts, _ = _controler_reference(
            donnees, reference, natures, natures_reference, [regle]
        )
        return [ligne for (ligne,) in _lignes(ecarts, "num_ligne_source")]

    # Le prénom vide de DUPONT rend sa clé vide : elle n'est rattachée à rien.
    assert absentes("telle quelle") == [3, 4, 5, 6]
    assert absentes("après normalisation") == [3, 5, 6]
    assert absentes("mots dans le désordre") == [5, 6]
    regle = _reference("existence_dans_reference", cle=["nom"], cle_reference=["n", "p"])
    ecarts, _ = _controler_reference(
        donnees, reference, natures, natures_reference, [regle], sensibles={"r": {"n"}}
    )
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}
    assert set(ecarts["colonnes"]) == {"nom, r.n, r.p"}


def _periodes(**autres):
    return _reference("date_dans_periode_reference",
                      **{"cle": ["i"], "date": "d", "debut": "e", **autres})


NATURES_PERIODES = ({"i": "texte", "d": DATE}, {"i": "texte", "e": NATIVE, "s": NATIVE})


def _personnes_et_periodes():
    jour = dt.datetime
    reference = _table(
        "r.xlsx",
        i=["A", "A", "B", "B", "C", "D", "", "F"],
        e=[jour(2025, 3, 1), jour(2020, 1, 1, 9, 0), "x", jour(2020, 1, 1), jour(2025, 6, 30),
           None, jour(2020, 1, 1), jour(2020, 1, 1)],
        s=[None, jour(2024, 12, 31), None, jour(2020, 12, 31), jour(2025, 1, 1), None, None,
           "y"],
    )
    donnees = _table(
        i=["A", "A", "A", "A", "B", "B", "C", "E", "A", "", "A", "F", "A"],
        d=["15/06/2024", "31/12/2024", "15/01/2025", "01/03/2025", "15/06/2020", "15/06/2025",
           "15/03/2025", "15/03/2025", "", "15/03/2025", "32/01/2025", "15/03/2025",
           "01/01/2020"],
    )
    return donnees, reference


def test_date_dans_periode_reference():
    donnees, reference = _personnes_et_periodes()
    ecarts, bilan = _controler_reference(donnees, reference, *NATURES_PERIODES,
                                         [_periodes(fin="s")])
    # A : deux périodes, données dans le désordre, la plus récente ouverte; un début à
    # 9 h compte pour le jour entier.
    # B et F ont une ligne inutilisable, C n'a que la sienne; E est absent.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (4, CONSTAT_HORS_PERIODES, "anomalie", "i, d, r.i, r.e, r.s",
         "15/01/2025 (périodes du 01/01/2020 au 31/12/2024 et depuis le 01/03/2025)"),
        (9, CONSTAT_ABSENTE, "anomalie", "i, d, r.i, r.e, r.s", "E | 15/03/2025"),
    ]
    resume = _bilan(bilan)
    assert (resume["lignes"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"]) == (13, 6, 7, 2)
    assert resume["avertissements"] == (
        "5 lignes de la table r inutilisables : clé vide 1, début vide 1, début illisible 1, "
        "fin illisible 1, début après fin 1"
    )
    # Sans fin, toutes les périodes sont ouvertes.
    ecarts, bilan = _controler_reference(donnees, reference, *NATURES_PERIODES, [_periodes()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "colonnes", "valeur") == [
        (8, CONSTAT_HORS_PERIODES, "i, d, r.i, r.e", "15/03/2025 (période depuis le 30/06/2025)"),
        (9, CONSTAT_ABSENTE, "i, d, r.i, r.e", "E | 15/03/2025"),
    ]
    assert _bilan(bilan)["avertissements"] == (
        "3 lignes de la table r inutilisables : clé vide 1, début vide 1, début illisible 1"
    )


def test_date_dans_periode_reference_cle_facultative_cle_et_masquage():
    donnees, reference = _personnes_et_periodes()
    _, bilan = _controler_reference(donnees, reference, *NATURES_PERIODES,
                                    [_periodes(fin="s", cle_facultative=True)])
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"]) == (1, 5, 7)
    ecarts, _ = _controler_reference(donnees, reference, *NATURES_PERIODES, [_periodes(fin="s")],
                                     declarations={"t": {"cle": ["i"]}})
    assert _lignes(ecarts, "cle") == [("A",), ("E",)]
    ecarts, _ = _controler_reference(donnees, reference, *NATURES_PERIODES, [_periodes(fin="s")],
                                     sensibles={"r": {"s"}})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def _paliers(**autres):
    return _instance("periodes_couvertes_par_paliers", ref="R21", cle=["m"], debut="e",
                     table_paliers="r", date_palier="d", **autres)


def _periodes_et_paliers():
    jour = dt.datetime
    periodes = _table(
        "p.xlsx",
        m=["M1", "M1", "M2", "M3", "M4", "M6", "M6", "M7", "M8", "M8", ""],
        e=[jour(2020, 1, 1), jour(2024, 1, 1), jour(2021, 5, 1), jour(2023, 1, 1), "x",
           jour(2020, 1, 1), "y", jour(2022, 1, 1), jour(2019, 1, 1), jour(2021, 1, 1),
           jour(2020, 1, 1)],
        s=[jour(2022, 6, 30), None, None, None, None, None, None, None, "w", None, None],
    )
    paliers = _table(
        "r.xlsx",
        m=["M1", "M1", "M1", "M1", "M2", "M7", "M8", "", "M9"],
        d=[jour(2020, 1, 1), jour(2022, 6, 30), jour(2025, 1, 1), jour(2024, 2, 1),
           jour(2021, 4, 15), "z", jour(2019, 1, 1), jour(2020, 1, 1), None],
    )
    return periodes, paliers


NATURES_PALIERS = ({"m": "texte", "e": NATIVE, "s": NATIVE}, {"m": "texte", "d": NATIVE})


def test_periodes_couvertes_par_paliers():
    periodes, paliers = _periodes_et_paliers()
    ecarts, bilan = _controler_reference(periodes, paliers, *NATURES_PALIERS,
                                         [_paliers(fin="s")])
    # M1 : le palier du 30/06/2022, jour de la fin de la première période, ne couvre pas
    # la seconde. M3 n'a aucun palier.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (3, CONSTAT_PERIODE_NON_COUVERTE, "anomalie", "m, e, s, r.m, r.d",
         "période du 01/01/2024, premier palier le 01/02/2024"),
        (5, CONSTAT_PERIODE_NON_COUVERTE, "anomalie", "m, e, s, r.m, r.d",
         "période du 01/01/2023, aucun palier ensuite"),
    ]
    resume = _bilan(bilan)
    # Non évaluables : début illisible (M4), autre période illisible (M6, deux lignes),
    # palier illisible (M7), fin précédente illisible (M8), clé vide.
    assert (resume["vue"], resume["lignes"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"]) == (VUE_SANS_SURNOMBRE, 11, 6, 5, 2)
    assert resume["avertissements"] == (
        "3 lignes de la table r inutilisables : clé vide 1, date vide 1, date illisible 1"
    )
    # Un palier le lendemain de la fin de la première période couvre la seconde.
    plus = pd.concat([paliers, _table("r.xlsx", premiere_ligne=11, m=["M1"],
                                      d=[dt.datetime(2022, 7, 1)])], ignore_index=True)
    ecarts, _ = _controler_reference(periodes, plus, *NATURES_PALIERS, [_paliers(fin="s")])
    assert _lignes(ecarts, "num_ligne_source") == [(5,)]


def test_annee_dans_reference():
    donnees = _table(d=["14/03/2025", "01/01/2026", "14/03/2052", "", "x", "02/02/2052",
                        "05/05/2062"])
    reference = _table("r.xlsx", a=[2025, 2026.0, 2026.5, None, "deux"])
    regle = _reference("annee_dans_reference", ref="R21", date="d", colonne_annee="a")
    ecarts, bilan = _controler_reference(donnees, reference, {"d": DATE}, {"a": NATIF}, [regle])
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (4, CONSTAT_ANNEE_ABSENTE, "anomalie", "d, r.a", "14/03/2052 (année 2052)"),
        (7, CONSTAT_ANNEE_ABSENTE, "anomalie", "d, r.a", "02/02/2052 (année 2052)"),
        (8, CONSTAT_ANNEE_ABSENTE, "anomalie", "d, r.a", "05/05/2062 (année 2062)"),
    ]
    resume = _bilan(bilan)
    assert (resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (2, 5, 3)
    assert resume["avertissements"] == (
        "3 lignes de la table r inutilisables : année vide 1, année illisible 2; "
        "année 2052 absente de r.a : 2 lignes; année 2062 absente de r.a : 1 ligne"
    )


def test_intervalles_mots_dans_le_desordre():
    donnees = _table(g=["Dupont Jean", "jean  DUPONT"], d=["14/03/2025", "14/03/2025"],
                     m=["60", "30"])
    natures = {"g": "texte", "d": DATE, "m": ENTIER}
    regle = _instance("intervalles_sans_chevauchement", ref="R03", groupe="g", date="d",
                      duree="m", comparaison="mots dans le désordre")
    ecarts, _ = _controler(donnees, natures, regles=[regle])
    # À début égal, la plus longue porte l'écart.
    assert _lignes(ecarts, "num_ligne_source", "constat") == [(2, CONSTAT_CHEVAUCHEMENT)]


def test_structure_des_types_du_4d():
    regles = [
        _existence(cle="c"),
        _existence(cle_reference=[], cle_facultative="oui", comparaison="approchée"),
        {key: valeur for key, valeur in _periodes(debut=3).items() if key != "date"},
        _reference("annee_dans_reference", date="d"),
        _paliers(cle_paliers=["m", "m"]),
        _existence(),
        _existence(cle_reference=["c"]),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (existence), cle : une liste non vide de noms de colonnes est attendue "
        "(liste de colonnes)",
        "règle n° 2 (existence), cle_reference : une liste non vide de noms de colonnes est "
        "attendue (liste de colonnes de la table liée)",
        "règle n° 2 (existence), comparaison : comparaison inconnue 'approchée' (comparaisons "
        "possibles : telle quelle, après normalisation, mots dans le désordre)",
        "règle n° 2 (existence), cle_facultative : true ou false est attendu",
        "règle n° 3 (R10) : paramètre manquant (date)",
        "règle n° 3 (R10), debut : un nom de colonne est attendu (colonne de date de la table "
        "liée)",
        "règle n° 4 (R10) : paramètre manquant (colonne_annee)",
        "règle n° 5 (R21), cle_paliers : colonne citée deux fois",
        # La clé du référentiel reprend par défaut celle de la table.
        "règle n° 7 (existence) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 6 (existence))",
    ]


def test_referentiel_confronte_aux_donnees():
    donnees, reference = _personnes_et_periodes()
    with pytest.raises(ValueError) as erreur:
        controler_gestion({"t": donnees}, _dictionnaire("t", **NATURES_PERIODES[0]),
                          [_periodes(fin="s")], {}, None, AUCUNE_SENSIBLE)
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R10), table_reference : table r absente des données chargées"
    ]
    with pytest.raises(ValueError) as erreur:
        _controler_reference(
            donnees, reference.drop(columns=["i"]), NATURES_PERIODES[0],
            {"i": "texte", "e": "texte", "s": NATIVE},
            [_periodes(fin="s"), _existence(cle=["i"], cle_reference=["x"])],
        )
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R10), cle_reference : colonne r.i absente des données chargées",
        "règle n° 1 (R10), debut : la nature en vigueur de r.e est 'texte', une date est "
        "attendue (à trancher dans la revue du dictionnaire, notebook 02c_dictionnaire)",
        "règle n° 2 (existence), cle_reference : colonne r.x absente des données chargées",
    ]


def test_catalogue_des_types_du_4d():
    catalogue = catalogue_types().set_index("type")
    assert catalogue.loc["existence_dans_reference", "parametres"] == (
        "cle (liste de colonnes), table_reference (table), cle_reference (liste de colonnes "
        "de la table liée, facultatif), comparaison (comparaison, facultatif), "
        "cle_facultative (true ou false, facultatif)"
    )
    assert catalogue.loc["date_dans_periode_reference", "parametres"] == (
        "cle (liste de colonnes), date (colonne de date), table_reference (table), "
        "cle_reference (liste de colonnes de la table liée, facultatif), debut (colonne de "
        "date de la table liée), fin (colonne de date de la table liée, facultatif), "
        "comparaison (comparaison, facultatif), cle_facultative (true ou false, facultatif)"
    )
    assert catalogue.loc["periodes_couvertes_par_paliers", "parametres"] == (
        "cle (liste de colonnes), debut (colonne de date), fin (colonne de date, facultatif), "
        "table_paliers (table), cle_paliers (liste de colonnes de la table liée, facultatif), "
        "date_palier (colonne de date de la table liée)"
    )
    assert catalogue.loc["annee_dans_reference", "parametres"] == (
        "date (colonne de date), table_reference (table), colonne_annee (colonne de nombre de "
        "la table liée)"
    )
    types = ["existence_dans_reference", "date_dans_periode_reference",
             "periodes_couvertes_par_paliers", "annee_dans_reference"]
    assert list(catalogue.loc[types, "vue"]) == [VUE_TOUTES, VUE_TOUTES, VUE_SANS_SURNOMBRE,
                                                 VUE_TOUTES]
    assert set(catalogue.loc[types, "issue"]) == {"anomalie"}


def test_chargement_des_regles_du_4d(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: existence\n    libelle: Pièce\n    type: existence_dans_reference\n"
        "    table: achats_lignes\n    cle: [ref_piece]\n"
        "    table_reference: catalogue_pieces\n    cle_facultative: true\n"
        "  - ref: R10\n    libelle: Intervenant\n    type: date_dans_periode_reference\n"
        "    table: interventions\n    cle: [intervenant]\n    date: date_debut\n"
        "    table_reference: intervenants\n    cle_reference: [nom, prenom]\n"
        "    debut: date_entree\n    fin: date_sortie\n"
        "    comparaison: mots dans le désordre\n",
        encoding="utf-8",
    )
    regles = charger_regles_gestion(chemin)
    assert regles[0]["cle_facultative"] is True
    assert regles[1]["cle_reference"] == ["nom", "prenom"]
