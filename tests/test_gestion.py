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
    CONSTAT_AUCUNE_LIGNE_CONFORME,
    CONSTAT_ANNEE_DU_NUMERO,
    CONSTAT_AUCUNE_NON_NULLE,
    CONSTAT_BATTEMENT,
    CONSTAT_CHEVAUCHEMENT,
    CONSTAT_DATE_ANTERIEURE,
    CONSTAT_DATE_AVANT_PRECEDENT,
    CONSTAT_DATE_DIFFERENTE,
    CONSTAT_DATE_POSTERIEURE,
    CONSTAT_DELAI_NON_ECHU,
    CONSTAT_DESEQUILIBRE,
    CONSTAT_ECART_CALCUL,
    CONSTAT_HORS_DELAI,
    CONSTAT_HORS_HORAIRES,
    CONSTAT_HORS_PERIODES,
    CONSTAT_INFERIEURE,
    CONSTAT_LIGNES_INATTENDUES,
    CONSTAT_NON_CONFORME,
    CONSTAT_NON_CONFORME_DANS_HORAIRES,
    CONSTAT_NON_CONFORME_HORS_HORAIRES,
    CONSTAT_NUMEROS_MANQUANTS,
    CONSTAT_PERIODE_NON_COUVERTE,
    CONSTAT_PLUSIEURS_NON_NULLES,
    CONSTAT_PLUSIEURS_DOCUMENTS,
    CONSTAT_PLUSIEURS_GROUPES,
    CONSTAT_QUANTITES_DIFFERENTES,
    CONSTAT_RAPPORT_INFERIEUR,
    CONSTAT_RAPPORT_NON_CALCULABLE,
    CONSTAT_RAPPORT_SUPERIEUR,
    CONSTAT_SANS_DOCUMENT,
    CONSTAT_SANS_LIGNE,
    CONSTAT_SOMME_DIFFERENTE,
    CONSTAT_SOMMES_DIFFERENTES,
    CONSTAT_SUPERIEURE,
    CONSTAT_TOTAL_DIFFERENT,
    CONSTAT_VALEURS_DIFFERENTES,
    PREFIXE_PRATIQUE,
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
        "periodes_couvertes_par_paliers, annee_dans_reference, "
        "rattachement_unique_dans_delai, reference_conforme, concordance_entre_references, "
        "sans_ligne_liee, ligne_liee_attendue, conforme_selon_horaires, "
        "quantites_concordantes, produit_calcule, somme_liee_arrondie, au_plus_une_non_nulle, "
        "sommes_liees_concordantes, totaux_par_periode)",
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
        "colonne et valeurs ou motif)",
        "règle n° 5 (R22), filtre, condition n° 2 : clé inconnue valeur (clés possibles : "
        "colonne, valeurs, motif)",
        "règle n° 5 (R22), filtre, condition n° 2 : clé manquante (valeurs ou motif)",
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


# Morceau 4e : rattachement à un document, référence conforme, concordance, aucune ligne
# liée; conditions par motif, exceptions (pratiques normales) et date de coupure.

COUPURE = dt.date(2026, 3, 31)


def _controler_tables(tables, natures, regles, sensibles=AUCUNE_SENSIBLE, date_coupure=COUPURE):
    """Contrôle de plusieurs tables fictives; aucune lecture des fichiers de config/."""
    dictionnaire = {}
    for nom, natures_table in natures.items():
        dictionnaire.update(_dictionnaire(nom, **natures_table))
    return controler_gestion(
        tables, dictionnaire, regles, {}, None, sensibles, date_coupure=date_coupure
    )


def _date(texte):
    return dt.datetime.strptime(texte, "%d/%m/%Y")


def _rattachement(**autres):
    return _instance(
        "rattachement_unique_dans_delai",
        ref="R12",
        **{
            "cle": ["i"],
            "date": "d",
            "table_lignes": "l",
            "document": ["n"],
            "filtre_lignes": [{"colonne": "n", "motif": "FA-.*"}],
            "table_documents": "e",
            "date_document": "f",
            "delai_min": 0,
            "delai_max": 30,
            "filtre": [{"colonne": "s", "valeurs": ["R"]}],
            **autres,
        },
    )


NATURES_RATTACHEMENT = {
    "t": {"i": "texte", "d": DATE, "s": "texte"},
    "l": {"i": "texte", "n": "texte"},
    "e": {"n": "texte", "f": NATIVE},
}


def _interventions_et_factures():
    """Interventions « t », lignes de facture « l » et factures « e », avec un doublon
    exact dans « t » et dans « e »."""
    interventions = _table(
        i=["I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "", "I9", "I10", "I10", "I11",
           "I12", "I13", "I14", "I15", "I1"],
        d=["10/03/2025", "01/03/2025", "01/03/2025", "10/03/2025", "01/02/2026",
           "15/03/2026", "05/03/2025", "05/03/2025", "05/03/2025", "2025-03-05",
           "05/03/2025", "06/03/2025", "05/03/2025", "05/03/2025", "05/03/2025",
           "05/03/2025", "05/03/2025", "10/03/2025"],
        s=["R"] * 16 + ["A", "R"],
    )
    lignes = _table(
        "l.csv",
        i=["I1", "I2", "I3", "I4", "I7", "I7", "I8", "I8", "I11", "I12", "I13", "I14", "I10",
           "I1", "I1"],
        n=["FA-1", "FA-2", "FA-3", "FA-4", "FA-5", "FA-6", "FA-7", "AV-1", " ", "FA-8", "FA-9",
           "FA-10", "FA-11", "FA-1", ""],
    )
    factures = _table(
        "e.csv",
        n=["FA-1", "FA-2", "FA-3", "FA-4", "FA-5", "FA-6", "FA-7", "AV-1", "FA-9", "FA-9",
           "FA-10", "FA-11", "FA-1"],
        f=[_date("10/03/2025"), _date("31/03/2025"), _date("01/04/2025"), _date("09/03/2025"),
           _date("06/03/2025"), _date("07/03/2025"), _date("06/03/2025"), _date("07/03/2025"),
           _date("01/04/2025"), _date("02/04/2025"), "x", _date("06/03/2025"),
           _date("10/03/2025")],
    )
    return {"t": interventions, "l": lignes, "e": factures}


def test_rattachement_unique_dans_delai():
    tables = _interventions_et_factures()
    ecarts, bilan = _controler_tables(tables, NATURES_RATTACHEMENT, [_rattachement()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (4, CONSTAT_HORS_DELAI, "anomalie",
         "01/03/2025, document FA-3 du 01/04/2025 (écart de 31 jours)"),
        (5, CONSTAT_HORS_DELAI, "anomalie",
         "10/03/2025, document FA-4 du 09/03/2025 (écart de -1 jour)"),
        (6, CONSTAT_SANS_DOCUMENT, "anomalie", "I5 | 01/02/2026"),
        (7, CONSTAT_DELAI_NON_ECHU, ISSUE_INFORMATION,
         "15/03/2026 (délai jusqu'au 14/04/2026, coupure au 31/03/2026)"),
        (8, CONSTAT_PLUSIEURS_DOCUMENTS, "anomalie", "05/03/2025, 2 documents : FA-5 | FA-6"),
        # La ligne liée sans numéro ne passe pas filtre_lignes : aucun document.
        (14, CONSTAT_SANS_DOCUMENT, "anomalie", "I11 | 05/03/2025"),
    ]
    assert set(ecarts["colonnes"]) == {"i, d, l.i, l.n, e.n, e.f"}
    resume = _bilan(bilan)
    assert {cle: resume[cle] for cle in (
        "vue", "filtre", "lignes", "ecartees_doublons", "hors_champ", "non_evaluables",
        "controlees", "anomalies", "a_arbitrer", "informations",
    )} == {
        "vue": VUE_SANS_SURNOMBRE,
        "filtre": "s = R",
        "lignes": 18,
        "ecartees_doublons": 1,
        "hors_champ": 1,
        # Clé vide, date illisible, clé répétée (deux lignes), facture absente, numéro
        # de facture répété, date de facture illisible.
        "non_evaluables": 7,
        "controlees": 9,
        "anomalies": 5,
        "a_arbitrer": 0,
        "informations": 1,
    }
    # Sans filtre_lignes, l'avoir compte comme un second document, et une ligne liée
    # sans numéro rend l'intervention non évaluable, même avec un autre document.
    regle = {cle: v for cle, v in _rattachement().items() if cle != "filtre_lignes"}
    ecarts, bilan = _controler_tables(tables, NATURES_RATTACHEMENT, [regle])
    assert [(ligne, constat) for ligne, constat in _lignes(
        ecarts, "num_ligne_source", "constat") if ligne in (9, 14)] == [
        (9, CONSTAT_PLUSIEURS_DOCUMENTS)
    ]
    assert _bilan(bilan)["non_evaluables"] == 9
    assert 2 not in set(ecarts["num_ligne_source"])


def test_rattachement_bornes_du_delai_et_issue_de_la_regle():
    tables = _interventions_et_factures()
    regle = _rattachement(delai_min=-1, delai_max=31, issue="à arbitrer")
    ecarts, bilan = _controler_tables(tables, NATURES_RATTACHEMENT, [regle])
    assert _lignes(ecarts, "num_ligne_source", "issue") == [
        (6, "à arbitrer"), (7, ISSUE_INFORMATION), (8, "à arbitrer"), (14, "à arbitrer"),
    ]
    resume = _bilan(bilan)
    assert (resume["anomalies"], resume["a_arbitrer"], resume["informations"]) == (0, 3, 1)


def test_date_de_coupure_attendue():
    tables = _interventions_et_factures()
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, NATURES_RATTACHEMENT, [_rattachement()], date_coupure=None)
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R12) : la date de coupure des données est attendue (argument "
        "date_coupure, perimetre.date_coupure dans le notebook)"
    ]


def test_delai_echu_le_jour_de_la_coupure():
    tables = {
        "t": _table(i=["I1", "I2"], d=["01/03/2026", "02/03/2026"], s=["R", "R"]),
        "l": _table("l.csv", i=["I9"], n=["FA-9"]),
        "e": _table("e.csv", n=["FA-9"], f=[_date("01/03/2026")]),
    }
    ecarts, _ = _controler_tables(tables, NATURES_RATTACHEMENT, [_rattachement()])
    # Le 01/03/2026 plus 30 jours tombe le jour de la coupure : le délai est échu.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue") == [
        (2, CONSTAT_SANS_DOCUMENT, "anomalie"),
        (3, CONSTAT_DELAI_NON_ECHU, ISSUE_INFORMATION),
    ]


def test_cle_repetee_hors_du_filtre_non_evaluable():
    # I1 est répété, une fois dans le champ de la règle et une fois hors champ : les
    # lignes liées désignent la clé, sans dire laquelle des deux lignes.
    tables = {
        "t": _table(i=["I1", "I1", "I2"], d=["01/03/2025", "02/03/2025", "01/03/2025"],
                    s=["R", "A", "A"]),
        "l": _table("l.csv", i=["I9"], n=["FA-9"]),
        "e": _table("e.csv", n=["FA-9"], f=[_date("01/03/2025")]),
    }
    _, bilan = _controler_tables(tables, NATURES_RATTACHEMENT, [_rattachement()])
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"]) == (2, 1, 0)
    regle = _instance("sans_ligne_liee", ref="R16", cle=["i"], table_lignes="l",
                      filtre=[{"colonne": "s", "valeurs": ["A"]}])
    _, bilan = _controler_tables(tables, NATURES_RATTACHEMENT, [regle])
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"]) == (1, 1, 1)


def _conforme(**autres):
    return _instance(
        "reference_conforme",
        ref="R13",
        **{
            "cle": ["i"],
            "table_reference": "r",
            "attendu": [
                {"colonne": "s", "valeurs": ["Réalisée"]},
                {"colonne": "f", "motif": "O"},
            ],
            "exceptions": [{
                "libelle": "déplacement seul",
                "conditions": [
                    {"colonne": "a", "valeurs": ["DEPL"]},
                    {"colonne": "r.s", "valeurs": ["Annulée"]},
                ],
            }],
            **autres,
        },
    )


NATURES_CONFORME = {"t": {"i": "texte", "a": "texte"}, "r": {"i": "texte", "s": "texte",
                                                            "f": "texte"}}


def _lignes_et_references():
    lignes = _table(i=["R1", "R2", "R2", "R3", "R4", "R5", "R9", "", "R6"],
                    a=["MO", "DEPL", "MO", "MO", "MO", "MO", "MO", "MO", "DEPL"])
    references = _table("r.csv", i=["R1", "R2", "R3", "R4", "R5", "R5", "R6"],
                        s=["Réalisée", "Annulée", "Réalisée", " ", "Réalisée", "Annulée", "Fait"],
                        f=["O", "O", "N", "O", "O", "O", "O"])
    return {"t": lignes, "r": references}


def test_reference_conforme_et_exception():
    tables = _lignes_et_references()
    ecarts, bilan = _controler_tables(tables, NATURES_CONFORME, [_conforme()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (3, PREFIXE_PRATIQUE + "déplacement seul", ISSUE_INFORMATION, "r.s = Annulée"),
        (4, CONSTAT_NON_CONFORME, "anomalie", "r.s = Annulée"),
        (5, CONSTAT_NON_CONFORME, "anomalie", "r.f = N"),
        # L'exception demande une intervention annulée.
        (10, CONSTAT_NON_CONFORME, "anomalie", "r.s = Fait"),
    ]
    assert set(ecarts["colonnes"]) == {"i, a, r.i, r.s, r.f"}
    resume = _bilan(bilan)
    # Statut vide, référence répétée, référence absente, clé vide : non évaluables.
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"], resume["informations"]) == (0, 4, 5, 3, 1)
    ecarts, bilan = _controler_tables(tables, NATURES_CONFORME,
                                      [_conforme(cle_facultative=True, issue="à arbitrer")])
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["a_arbitrer"],
            resume["informations"]) == (1, 3, 3, 1)
    # Sans exception, la ligne de déplacement est aussi une anomalie.
    regle = {cle: v for cle, v in _conforme().items() if cle != "exceptions"}
    ecarts, _ = _controler_tables(tables, NATURES_CONFORME, [regle])
    assert set(ecarts["constat"]) == {CONSTAT_NON_CONFORME}
    assert len(ecarts) == 4


def _concordance(**autres):
    return _instance(
        "concordance_entre_references",
        ref="R13",
        **{"cle_a": ["i"], "table_a": "a", "colonne_a": "c", "cle_b": ["n"], "table_b": "b",
           "colonne_b": "c", **autres},
    )


NATURES_CONCORDANCE = {"t": {"i": "texte", "n": "texte"}, "a": {"i": "texte", "c": "texte"},
                       "b": {"n": "texte", "c": "texte"}}


def _lignes_et_deux_references():
    lignes = _table(i=["I1", "I2", "I3", "I4", "I1", "I2"], n=["N1", "N2", "N1", "N1", "N9", "N3"])
    interventions = _table("a.csv", i=["I1", "I2", "I3", "I4", "I4"],
                           c=["C1", "C2", "", "C4", "C5"])
    factures = _table("b.csv", n=["N1", "N2", "N3"], c=["C1", "c2", "C3"])
    return {"t": lignes, "a": interventions, "b": factures}


def test_concordance_entre_references():
    tables = _lignes_et_deux_references()
    ecarts, bilan = _controler_tables(tables, NATURES_CONCORDANCE, [_concordance()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (3, CONSTAT_VALEURS_DIFFERENTES, "C2 (a.c) | c2 (b.c)"),
        (7, CONSTAT_VALEURS_DIFFERENTES, "C2 (a.c) | C3 (b.c)"),
    ]
    assert set(ecarts["colonnes"]) == {"i, n, a.i, a.c, b.n, b.c"}
    resume = _bilan(bilan)
    # Valeur vide, référence répétée, référence absente : non évaluables.
    assert (resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (3, 3, 2)
    ecarts, _ = _controler_tables(tables, NATURES_CONCORDANCE,
                                  [_concordance(comparaison="après normalisation")])
    assert _lignes(ecarts, "num_ligne_source") == [(7,)]
    ecarts, _ = _controler_tables(tables, NATURES_CONCORDANCE, [_concordance()],
                                  sensibles={"b": {"c"}})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def _sans_ligne(**autres):
    return _instance(
        "sans_ligne_liee",
        ref="R16",
        **{
            "cle": ["i"],
            "table_lignes": "l",
            "filtre": [{"colonne": "s", "valeurs": ["Annulée", "Reportée"]}],
            "exceptions": [{
                "libelle": "déplacement seul",
                "conditions": [
                    {"colonne": "s", "valeurs": ["Annulée"]},
                    {"colonne": "l.a", "valeurs": ["DEPL"]},
                ],
            }],
            **autres,
        },
    )


NATURES_SANS_LIGNE = {"t": {"i": "texte", "s": "texte", "x": "texte"},
                      "l": {"i": "texte", "a": "texte", "q": "texte"}}


def test_sans_ligne_liee_et_exception_sur_toutes_les_lignes():
    tables = {
        "t": _table(i=["I1", "I2", "I3", "I4", "I5", "", "I6", "I6"],
                    s=["Annulée", "Annulée", "Annulée", "Reportée", "Réalisée", "Annulée",
                       "Annulée", "Annulée"],
                    x=["1", "2", "3", "4", "5", "6", "7", "8"]),
        "l": _table("l.csv", i=["I2", "I2", "I3", "I3", "I4", "I5", "I6"],
                    a=["DEPL", "DEPL", "DEPL", "MO", "DEPL", "MO", "MO"],
                    q=["1", "2", "1", "1", "1", "1", "1"]),
    }
    ecarts, bilan = _controler_tables(tables, NATURES_SANS_LIGNE, [_sans_ligne()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (3, PREFIXE_PRATIQUE + "déplacement seul", ISSUE_INFORMATION, "2 lignes liées dans l"),
        # Une ligne liée n'est pas un déplacement : l'exception ne s'applique pas.
        (4, CONSTAT_LIGNES_INATTENDUES, "anomalie", "2 lignes liées dans l"),
        # L'exception demande une intervention annulée.
        (5, CONSTAT_LIGNES_INATTENDUES, "anomalie", "1 ligne liée dans l"),
    ]
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"], resume["informations"]) == (1, 3, 4, 2, 1)
    # filtre_lignes restreint les lignes liées qui comptent (et que juge l'exception).
    ecarts, _ = _controler_tables(
        tables, NATURES_SANS_LIGNE,
        [_sans_ligne(filtre_lignes=[{"colonne": "a", "valeurs": ["MO"]}])],
    )
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (4, CONSTAT_LIGNES_INATTENDUES, "1 ligne liée dans l"),
    ]


def test_filtre_par_motif():
    donnees = _table(n=["FA-1", "AV-1", " ", "XFA-2", "FA-3"], km=["1,0", "1,0", "1,0", "1,0",
                                                                      "9,0"])
    filtre = [{"colonne": "n", "motif": "FA-.*"}]
    ecarts, bilan = _controler(donnees, {"n": "texte", "km": DECIMAL},
                               regles=[_instance(colonne="km", max=5, filtre=filtre)])
    assert _lignes(ecarts, "num_ligne_source") == [(6,)]
    resume = _bilan(bilan)
    # Le motif couvre la valeur entière; une cellule faite d'espaces ne le remplit pas.
    assert (resume["filtre"], resume["hors_champ"], resume["controlees"]) == (
        "n suit le motif FA-.*", 3, 2
    )


def test_structure_des_types_du_4e():
    regles = [
        _rattachement(delai_min=5, delai_max=2),
        _rattachement(delai_min=0.5),
        {cle: v for cle, v in _rattachement().items() if cle != "document"},
        _rattachement(filtre_lignes=[{"colonne": "n", "valeurs": ["A"], "motif": "A"}]),
        _rattachement(filtre=[{"colonne": "s", "motif": "("}, {"colonne": "s", "motif": 3}]),
        _conforme(exceptions=[{"libelle": "", "conditions": []}, "x",
                              {"conditions": [{"colonne": "a", "valeurs": ["D"]}], "autre": 1}]),
        _conforme(exceptions=[{"libelle": "L", "conditions": [{"colonne": "x.s",
                                                               "valeurs": ["A"]}]}]),
        _conforme(attendu=[]),
        _sans_ligne(),
        _sans_ligne(cle_lignes=["i"]),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (R12) : delai_min (5) supérieur à delai_max (2)",
        "règle n° 2 (R12) : delai_min : un nombre entier de jours est attendu",
        "règle n° 3 (R12) : paramètre manquant (document)",
        "règle n° 4 (R12), filtre_lignes : condition n° 1 : valeurs ou motif attendu, pas les "
        "deux",
        "règle n° 5 (R12), filtre, condition n° 1, motif : expression régulière invalide "
        "(missing ), unterminated subpattern at position 0)",
        "règle n° 5 (R12), filtre, condition n° 2, motif : une expression régulière est "
        "attendue (entre guillemets simples, par exemple 'FA-.*')",
        "règle n° 6 (R13), exceptions : exception n° 1, libelle : un texte non vide est "
        "attendu",
        "règle n° 6 (R13), exceptions : exception n° 1, conditions : une liste de conditions "
        "est attendue (chaque condition commence par un tiret)",
        "règle n° 6 (R13), exceptions : exception n° 2 : un dictionnaire est attendu (clés "
        "libelle et conditions)",
        "règle n° 6 (R13), exceptions : exception n° 3 : clé inconnue autre (clés possibles : "
        "libelle, conditions)",
        "règle n° 6 (R13), exceptions : exception n° 3 : clé manquante (libelle)",
        "règle n° 7 (R13), exceptions, exception n° 1, condition n° 1 : x n'est pas une table "
        "liée de la règle (tables liées : r); une colonne de la table de la règle s'écrit "
        "sans préfixe",
        "règle n° 8 (R13), attendu : une liste de conditions est attendue (chaque condition "
        "commence par un tiret)",
        # La clé des lignes reprend par défaut celle de la table.
        "règle n° 10 (R16) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 9 (R16))",
    ]


def test_tables_liees_du_4e_confrontees_aux_donnees():
    tables = _lignes_et_deux_references()
    with pytest.raises(ValueError) as erreur:
        _controler_tables(
            {"t": tables["t"], "a": tables["a"]},
            {"t": NATURES_CONCORDANCE["t"], "a": NATURES_CONCORDANCE["a"]},
            [_concordance()],
        )
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R13), table_b : table b absente des données chargées"
    ]
    tables = _lignes_et_references()
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, NATURES_CONFORME, [_conforme(
            attendu=[{"colonne": "z", "valeurs": ["O"]}],
            exceptions=[{"libelle": "L", "conditions": [{"colonne": "r.x", "valeurs": ["A"]},
                                                        {"colonne": "y", "valeurs": ["A"]}]}],
        )])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R13), attendu : colonne r.z absente des données chargées",
        "règle n° 1 (R13), exceptions : colonne r.x absente des données chargées",
        "règle n° 1 (R13), exceptions : colonne t.y absente des données chargées",
    ]


def test_masquage_selon_une_seconde_table_liee():
    tables = _interventions_et_factures()
    ecarts, _ = _controler_tables(tables, NATURES_RATTACHEMENT, [_rattachement()],
                                  sensibles={"e": {"f"}})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def test_catalogue_des_types_du_4e():
    catalogue = catalogue_types().set_index("type")
    assert catalogue.loc["rattachement_unique_dans_delai", "parametres"] == (
        "cle (liste de colonnes), date (colonne de date), table_lignes (table), cle_lignes "
        "(liste de colonnes de la table liée, facultatif), document (liste de colonnes de la "
        "table liée), filtre_lignes (liste de conditions, facultatif), table_documents "
        "(table), cle_documents (liste de colonnes de la table liée, facultatif), "
        "date_document (colonne de date de la table liée), delai_min (nombre), delai_max "
        "(nombre)"
    )
    assert catalogue.loc["reference_conforme", "parametres"] == (
        "cle (liste de colonnes), table_reference (table), cle_reference (liste de colonnes "
        "de la table liée, facultatif), attendu (liste de conditions), exceptions "
        "(exceptions, facultatif), cle_facultative (true ou false, facultatif)"
    )
    types = ["rattachement_unique_dans_delai", "reference_conforme",
             "concordance_entre_references", "sans_ligne_liee"]
    assert set(catalogue.loc[types, "vue"]) == {VUE_SANS_SURNOMBRE}
    assert set(catalogue.loc[types, "issue"]) == {"anomalie"}


def test_chargement_des_regles_du_4e(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: R12\n    libelle: Facturée\n    type: rattachement_unique_dans_delai\n"
        "    table: interventions\n    cle: [id_intervention]\n    date: date_debut\n"
        "    table_lignes: factures_lignes\n    document: [num_facture]\n"
        "    filtre_lignes:\n      - colonne: num_facture\n        motif: 'FA-.*'\n"
        "    table_documents: factures_entetes\n    date_document: date_facture\n"
        "    delai_min: 0\n    delai_max: 30\n"
        "  - ref: R16\n    libelle: Non facturée\n    type: sans_ligne_liee\n"
        "    table: interventions\n    cle: [id_intervention]\n"
        "    table_lignes: factures_lignes\n"
        "    exceptions:\n      - libelle: annulation sur place\n        conditions:\n"
        "          - colonne: factures_lignes.code_article\n            valeurs: [DEPL]\n",
        encoding="utf-8",
    )
    regles = charger_regles_gestion(chemin)
    assert regles[0]["filtre_lignes"] == [{"colonne": "num_facture", "motif": "FA-.*"}]
    assert regles[1]["exceptions"][0]["conditions"][0]["colonne"] == (
        "factures_lignes.code_article"
    )


# Morceau 4f1 : ligne liée attendue, conformité selon les horaires d'une référence,
# quantités concordantes entre deux tables liées.


def _attendue(**autres):
    return _instance(
        "ligne_liee_attendue",
        ref="R17",
        **{
            "cle": ["i"],
            "table_lignes": "l",
            "attendu": [
                {"colonne": "a", "valeurs": ["CTRL"]},
                {"colonne": "q", "motif": "[1-9][0-9]*"},
            ],
            "exceptions": [{
                "libelle": "déplacement seul",
                "conditions": [
                    {"colonne": "s", "valeurs": ["Annulée"]},
                    {"colonne": "l.a", "valeurs": ["DEPL"]},
                ],
            }],
            "filtre": [{"colonne": "s", "valeurs": ["Réalisée", "Annulée"]}],
            **autres,
        },
    )


NATURES_ATTENDUE = {"t": {"i": "texte", "s": "texte"},
                    "l": {"i": "texte", "a": "texte", "q": "texte"}}


def _interventions_et_articles():
    interventions = _table(
        i=["I1", "I2", "I3", "I4", "I5", "I6", "", "I7", "I7", "I8", "I9"],
        s=["Réalisée"] * 7 + ["Réalisée", "Reportée", "Annulée", "Annulée"],
    )
    lignes = _table(
        "l.csv",
        i=["I1", "I1", "I2", "I4", "I4", "I5", "I6", "I6", "I8", "I9", "I9"],
        a=["CTRL", "DEPL", "DEPL", " ", "DEPL", "CTRL", "CTRL", "CTRL", "DEPL", "DEPL", "MO"],
        q=["1", "1", "1", "1", "1", "0", "", "2", "1", "1", "1"],
    )
    return {"t": interventions, "l": lignes}


def test_ligne_liee_attendue_et_exception():
    tables = _interventions_et_articles()
    ecarts, bilan = _controler_tables(tables, NATURES_ATTENDUE, [_attendue()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (3, CONSTAT_AUCUNE_LIGNE_CONFORME, "anomalie", "l.a = DEPL; l.q = 1"),
        # La ligne de contrôle a une quantité nulle : aucune ligne ne remplit tout.
        (6, CONSTAT_AUCUNE_LIGNE_CONFORME, "anomalie", "l.a = CTRL; l.q = 0"),
        (11, PREFIXE_PRATIQUE + "déplacement seul", ISSUE_INFORMATION, "l.a = DEPL; l.q = 1"),
        # L'exception demande que toutes les lignes liées soient des déplacements.
        (12, CONSTAT_AUCUNE_LIGNE_CONFORME, "anomalie", "l.a = DEPL, MO; l.q = 1"),
    ]
    assert set(ecarts["colonnes"]) == {"i, s, l.i, l.a, l.q"}
    resume = _bilan(bilan)
    # Hors champ : la ligne reportée (filtre) et I3, sans ligne liée. Non évaluables :
    # I4 (article vide, aucune autre ligne conforme), clé vide, I7 répété hors du filtre.
    # I6 est conforme malgré sa ligne à quantité vide.
    assert (resume["vue"], resume["hors_champ"], resume["non_evaluables"],
            resume["controlees"], resume["anomalies"], resume["informations"]) == (
        VUE_SANS_SURNOMBRE, 2, 3, 6, 3, 1
    )
    # filtre_lignes restreint les lignes liées : I1 n'a plus que son déplacement, I5 et
    # I6 n'ont plus de ligne liée.
    regle = _attendue(filtre_lignes=[{"colonne": "a", "valeurs": ["DEPL"]}])
    ecarts, bilan = _controler_tables(tables, NATURES_ATTENDUE, [regle])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [
        (2, CONSTAT_AUCUNE_LIGNE_CONFORME),
        (3, CONSTAT_AUCUNE_LIGNE_CONFORME),
        (5, CONSTAT_AUCUNE_LIGNE_CONFORME),
        (11, PREFIXE_PRATIQUE + "déplacement seul"),
        (12, PREFIXE_PRATIQUE + "déplacement seul"),
    ]
    assert _bilan(bilan)["hors_champ"] == 4


NATURES_SELON_HORAIRES = {"t": {"i": "texte", "c": "texte"},
                          "r": {"i": "texte", "d": DATE, "h": HEURE}}


def _selon_horaires(**autres):
    return _instance(
        "conforme_selon_horaires",
        ref="R04",
        **{
            "cle": ["i"],
            "table_reference": "r",
            "date": "d",
            "heure": "h",
            "horaires": HORAIRES,
            "feries": {2025: ["2025-05-01"]},
            "dans_horaires": [{"colonne": "c", "valeurs": ["STD"]}],
            "hors_horaires": [{"colonne": "c", "valeurs": ["URG"]}],
            "filtre": [{"colonne": "c", "motif": "[A-Z]+"}],
            **autres,
        },
    )


def _lignes_et_horaires():
    lignes = _table(
        i=["R1", "R1", "R2", "R2", "R3", "R4", "R5", "R6", "R9", "", "R7", "R1"],
        c=["STD", "URG", "URG", "STD", "STD", "URG", "STD", "STD", "STD", "STD", "URG", ""],
    )
    references = _table(
        "r.csv",
        i=["R1", "R2", "R3", "R4", "R5", "R6", "R6", "R7"],
        d=["03/03/2025", "08/03/2025", "01/05/2025", "03/03/2025", "14/03/2052",
           "03/03/2025", "04/03/2025", "03/03/2025"],
        h=["10:00", "09:00", "10:00", "", "10:00", "10:00", "10:00", "18:00"],
    )
    return {"t": lignes, "r": references}


def test_conforme_selon_horaires():
    tables = _lignes_et_horaires()
    ecarts, bilan = _controler_tables(tables, NATURES_SELON_HORAIRES,
                                      [_selon_horaires(feries_minimum=2)])
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (3, CONSTAT_NON_CONFORME_DANS_HORAIRES, "c = URG | lundi 03/03/2025 10:00"),
        (5, CONSTAT_NON_CONFORME_HORS_HORAIRES, "c = STD | samedi 08/03/2025 09:00"),
        (6, CONSTAT_NON_CONFORME_HORS_HORAIRES, "c = STD | férié 01/05/2025 10:00"),
    ]
    assert set(ecarts["colonnes"]) == {"i, c, r.i, r.d, r.h"}
    resume = _bilan(bilan)
    # Non évaluables : heure vide, année sans jours fériés, référence répétée, référence
    # absente, clé vide. La fin d'un créneau est exclue (R7 à 18:00 est hors horaires).
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"]) == (1, 5, 6, 3)
    assert resume["avertissements"] == (
        "année 2025 : 1 jour férié déclaré, moins que feries_minimum (2); "
        "année 2052 absente des jours fériés déclarés : 1 ligne non évaluable"
    )
    # Sans conditions dans les horaires, une ligne dans les horaires n'a rien à remplir.
    regle = {cle: v for cle, v in _selon_horaires().items() if cle != "dans_horaires"}
    ecarts, bilan = _controler_tables(tables, NATURES_SELON_HORAIRES, [regle])
    assert _lignes(ecarts, "num_ligne_source") == [(5,), (6,)]
    assert _bilan(bilan)["controlees"] == 6
    ecarts, _ = _controler_tables(tables, NATURES_SELON_HORAIRES, [_selon_horaires()],
                                  sensibles={"r": {"h"}})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def test_conforme_selon_horaires_valeur_vide_non_evaluable():
    tables = {
        "t": _table(i=["R1", "R2", "R1"], c=["STD", " ", " "]),
        "r": _table("r.csv", i=["R1", "R2"], d=["03/03/2025", "08/03/2025"],
                    h=["10:00", "09:00"]),
    }
    regle = {cle: v for cle, v in _selon_horaires().items() if cle != "filtre"}
    regle["dans_horaires"] = [{"colonne": "c", "valeurs": ["STD"]}]
    regle["hors_horaires"] = [{"colonne": "c", "valeurs": ["URG"]}]
    regle_sans_hors = {cle: v for cle, v in regle.items() if cle != "hors_horaires"}
    _, bilan = _controler_tables(tables, NATURES_SELON_HORAIRES, [regle, regle_sans_hors])
    # Une valeur vide n'est jugée que si une condition porte sur elle.
    assert [(_bilan(bilan, rang)["non_evaluables"], _bilan(bilan, rang)["controlees"],
             _bilan(bilan, rang)["anomalies"]) for rang in (0, 1)] == [(2, 1, 0), (1, 2, 0)]


def _quantites(**autres):
    return _instance(
        "quantites_concordantes",
        ref="R18",
        **{
            "cle": ["i"],
            "table_a": "a",
            "detail_a": "p",
            "quantite_a": "q",
            "table_b": "b",
            "filtre_b": [{"colonne": "art", "valeurs": ["PIECE"]}],
            "detail_b": "p",
            "quantite_b": "q",
            "hors_champ_sans_b": True,
            "filtre": [{"colonne": "s", "valeurs": ["R"]}],
            **autres,
        },
    )


NATURES_QUANTITES = {"t": {"i": "texte", "s": "texte"},
                     "a": {"i": "texte", "p": "texte", "q": DECIMAL},
                     "b": {"i": "texte", "art": "texte", "p": "texte", "q": DECIMAL}}


def _poses_et_factures():
    interventions = _table(
        i=["I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "", "I9", "I9"],
        s=["R"] * 10 + ["X"],
    )
    poses = _table(
        "a.csv",
        i=["I1", "I1", "I2", "I2", "I3", "I6", "I7", "I7", "I9"],
        p=["P1", "P2", "P1", "P4", "P1", "P1", "P1", "P2", "P1"],
        q=["1,0", "2,0", "1,0", "2,0", "1,0", "x", "1,0", "1,0", "1,0"],
    )
    factures = _table(
        "b.csv",
        i=["I1", "I1", "I1", "I1", "I2", "I3", "I4", "I4", "I7", "I7", "I8", "I9", "I6"],
        art=["PIECE", "PIECE", "PIECE", "MO", "PIECE", "MO", "PIECE", "MO", "PIECE", "PIECE",
             "PIECE", "PIECE", "MO"],
        p=["P1", "P2", "P2", "", "P1", "", "P3", "", "P2", "P1", " ", "P1", ""],
        q=["1,0", "1,0", "1,0", "1,0", "2,0", "1,0", "1,5", "1,0", "1,0", "1,004", "1,0",
           "1,0", "1,0"],
        n=[str(rang) for rang in range(13)],
    )
    return {"t": interventions, "a": poses, "b": factures}


def test_quantites_concordantes():
    tables = _poses_et_factures()
    natures = deepcopy(NATURES_QUANTITES)
    natures["b"]["n"] = "texte"
    ecarts, bilan = _controler_tables(tables, natures, [_quantites()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (3, CONSTAT_QUANTITES_DIFFERENTES, "P1 : 1 dans a, 2 dans b; P4 : 2 dans a, 0 dans b"),
        (4, CONSTAT_QUANTITES_DIFFERENTES, "P1 : 1 dans a, 0 dans b"),
        (5, CONSTAT_QUANTITES_DIFFERENTES, "P3 : 0 dans a, 1,5 dans b"),
        (8, CONSTAT_QUANTITES_DIFFERENTES, "P1 : 1 dans a, 1,004 dans b"),
    ]
    assert set(ecarts["colonnes"]) == {"i, a.i, a.p, a.q, b.i, b.art, b.p, b.q"}
    resume = _bilan(bilan)
    # Hors champ : la ligne hors du filtre et I5, sans ligne dans b. Non évaluables :
    # quantité illisible (I6), détail vide (I8), clé vide, I9 répété hors du filtre.
    # Une ligne sans ligne dans b est hors champ avant d'être jugée (I6 le serait sans
    # sa ligne de main d'oeuvre).
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"]) == (2, 4, 5, 4)
    ecarts, bilan = _controler_tables(
        tables, natures, [_quantites(tolerance=0.005, hors_champ_sans_b=False)]
    )
    assert _lignes(ecarts, "num_ligne_source") == [(3,), (4,), (5,)]
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["controlees"]) == (1, 6)
    ecarts, _ = _controler_tables(tables, natures, [_quantites()], sensibles={"a": {"p"}})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def test_structure_des_types_du_4f1():
    sans_conditions = {cle: v for cle, v in _selon_horaires().items()
                       if cle not in ("dans_horaires", "hors_horaires")}
    regles = [
        sans_conditions,
        _selon_horaires(feries_minimum=1.5),
        _quantites(hors_champ_sans_b="oui"),
        _quantites(tolerance=-1),
        {cle: v for cle, v in _attendue().items() if cle != "attendu"},
        _attendue(exceptions=[{"libelle": "L", "conditions": [{"colonne": "x.a",
                                                               "valeurs": ["A"]}]}]),
        _quantites(),
        _quantites(cle_a=["i"], cle_b=["i"]),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (R04) : dans_horaires ou hors_horaires attendu",
        "règle n° 2 (R04) : feries_minimum : un entier positif ou nul est attendu",
        "règle n° 3 (R18), hors_champ_sans_b : true ou false est attendu",
        "règle n° 4 (R18) : tolerance : un nombre positif ou nul est attendu",
        "règle n° 5 (R17) : paramètre manquant (attendu)",
        "règle n° 6 (R17), exceptions, exception n° 1, condition n° 1 : x n'est pas une table "
        "liée de la règle (tables liées : l); une colonne de la table de la règle s'écrit "
        "sans préfixe",
        # Les clés des tables liées reprennent par défaut celle de la table.
        "règle n° 8 (R18) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 7 (R18))",
    ]


def test_tables_et_natures_du_4f1_confrontees_aux_donnees():
    tables = _lignes_et_horaires()
    natures = deepcopy(NATURES_SELON_HORAIRES)
    natures["r"]["h"] = "texte"
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, natures, [_selon_horaires(
            hors_horaires=[{"colonne": "z", "valeurs": ["URG"]}])])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R04), heure : la nature en vigueur de r.h est 'texte', une heure est "
        "attendue (à trancher dans la revue du dictionnaire, notebook 02c_dictionnaire)",
        "règle n° 1 (R04), hors_horaires : colonne t.z absente des données chargées",
    ]
    tables = _poses_et_factures()
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, NATURES_QUANTITES, [_quantites(
            filtre_a=[{"colonne": "y", "valeurs": ["A"]}])])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R18), filtre_a : colonne a.y absente des données chargées",
    ]
    tables = _interventions_et_articles()
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, NATURES_ATTENDUE, [_attendue(
            attendu=[{"colonne": "w", "valeurs": ["CTRL"]}])])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R17), attendu : colonne l.w absente des données chargées",
    ]


def test_catalogue_des_types_du_4f1():
    catalogue = catalogue_types().set_index("type")
    assert catalogue.loc["ligne_liee_attendue", "parametres"] == (
        "cle (liste de colonnes), table_lignes (table), cle_lignes (liste de colonnes de la "
        "table liée, facultatif), filtre_lignes (liste de conditions, facultatif), attendu "
        "(liste de conditions), exceptions (exceptions, facultatif)"
    )
    assert catalogue.loc["conforme_selon_horaires", "parametres"] == (
        "cle (liste de colonnes), table_reference (table), cle_reference (liste de colonnes "
        "de la table liée, facultatif), date (colonne de date de la table liée), heure "
        "(colonne d'heure de la table liée), horaires (horaires), feries (jours fériés), "
        "feries_minimum (nombre, facultatif), dans_horaires (liste de conditions, "
        "facultatif), hors_horaires (liste de conditions, facultatif)"
    )
    assert catalogue.loc["quantites_concordantes", "parametres"] == (
        "cle (liste de colonnes), table_a (table), cle_a (liste de colonnes de la table "
        "liée, facultatif), filtre_a (liste de conditions, facultatif), detail_a (colonne "
        "de la table liée), quantite_a (colonne de nombre de la table liée), table_b "
        "(table), cle_b (liste de colonnes de la table liée, facultatif), filtre_b (liste "
        "de conditions, facultatif), detail_b (colonne de la table liée), quantite_b "
        "(colonne de nombre de la table liée), tolerance (nombre, facultatif), "
        "hors_champ_sans_b (true ou false, facultatif)"
    )
    types = ["ligne_liee_attendue", "conforme_selon_horaires", "quantites_concordantes"]
    assert set(catalogue.loc[types, "vue"]) == {VUE_SANS_SURNOMBRE}
    assert set(catalogue.loc[types, "issue"]) == {"anomalie"}


def test_chargement_des_regles_du_4f1(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: R04\n    libelle: Urgence\n    type: conforme_selon_horaires\n"
        "    table: factures_lignes\n    cle: [id_intervention]\n"
        "    table_reference: interventions\n    date: date_debut\n    heure: heure_debut\n"
        "    horaires: &ouvres\n      lundi: [{debut: '07:30', fin: '18:00'}]\n"
        "    feries: {2025: [2025-05-01]}\n"
        "    hors_horaires:\n      - colonne: code_article\n        valeurs: [MO-URG]\n"
        "  - ref: R04\n    libelle: Urgence bis\n    type: conforme_selon_horaires\n"
        "    table: factures_lignes\n    cle: [id_intervention]\n"
        "    table_reference: interventions\n    date: date_debut\n    heure: heure_debut\n"
        "    horaires: *ouvres\n    feries: {2025: [2025-05-01]}\n"
        "    dans_horaires:\n      - colonne: code_article\n        valeurs: [MO-STD]\n"
        "  - ref: R18\n    libelle: Pièces\n    type: quantites_concordantes\n"
        "    table: interventions\n    cle: [id_intervention]\n"
        "    table_a: pieces_interventions\n    detail_a: ref_piece\n    quantite_a: quantite\n"
        "    table_b: factures_lignes\n    detail_b: ref_piece\n    quantite_b: quantite\n"
        "    hors_champ_sans_b: true\n",
        encoding="utf-8",
    )
    regles = charger_regles_gestion(chemin)
    assert regles[1]["horaires"] == {"lundi": [{"debut": "07:30", "fin": "18:00"}]}
    assert regles[2]["hors_champ_sans_b"] is True


# Morceau 4f2 : produit calculé, somme liée arrondie, au plus une valeur non nulle.

REMISE = {"colonne": "r", "constante": 1, "coefficient": -0.01, "vide": 0}


def _produit(**autres):
    return _instance(
        "produit_calcule", ref="calcul",
        **{"cible": "m", "facteurs": ["q", "p", REMISE], "tolerance": 0.005, **autres},
    )


def test_produit_calcule_facteurs_et_cellule_vide():
    donnees = _table(
        q=[2.0, 1.5, 1.5, 1.0, "x", None, 1.0, 0.0, 1.0],
        p=[46.8, 46.8, 46.8, 10.005, 1.0, 1.0, 1.0, 420.0, 1.0],
        r=[None, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0, None, "y"],
        m=[93.6, 63.18, 70.2, 10.01, 1.0, 1.0, "", 0.0, 1.0],
    )
    natures = {"q": NATIF, "p": NATIF, "r": NATIF, "m": NATIF}
    ecarts, bilan = _controler(donnees, natures, regles=[_produit()])
    # Une remise vide vaut 0; un écart égal à la tolérance n'en est pas un.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (4, CONSTAT_ECART_CALCUL, "anomalie", "m, q, p, r",
         "70,2 pour un calcul de 63,18 (écart 7,02)"),
    ]
    resume = _bilan(bilan)
    # Non évaluables : quantité illisible, quantité vide (sans valeur vide déclarée),
    # cible vide, remise illisible (la valeur vide ne vaut que pour une cellule vide).
    assert (resume["vue"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"]) == (VUE_TOUTES, 4, 5, 1)
    # Sans valeur vide, une remise vide rend la ligne non évaluable; sans tolérance,
    # l'écart d'arrondi en est un.
    sans_vide = {cle: v for cle, v in REMISE.items() if cle != "vide"}
    ecarts, bilan = _controler(donnees, natures,
                               regles=[_produit(facteurs=["q", "p", sans_vide], tolerance=0)])
    assert _lignes(ecarts, "num_ligne_source") == [(4,), (5,)]
    assert _bilan(bilan)["non_evaluables"] == 6
    ecarts, _ = _controler(donnees, natures, regles=[_produit()], sensibles={"t": {"r"}})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def test_produit_calcule_en_decimaux_a_virgule():
    donnees = _table(q=["12,00", "0,1", "3,00"], p=["31,20", "3,0", "7,75"],
                     m=["374,40", "0,30", "23,26"])
    ecarts, _ = _controler(
        donnees, {"q": DECIMAL, "p": DECIMAL, "m": DECIMAL},
        regles=[_produit(facteurs=["q", "p"], tolerance=0)],
    )
    # 0,1 x 3 ne fait pas un écart malgré le calcul en virgule flottante.
    assert _lignes(ecarts, "num_ligne_source", "colonnes", "valeur") == [
        (4, "m, q, p", "23,26 pour un calcul de 23,25 (écart 0,01)")
    ]


def _somme(**autres):
    return _instance(
        "somme_liee_arrondie", ref="grille",
        **{
            "cle": ["i"],
            "colonne": "d",
            "diviseur": 60,
            "pas": 0.25,
            "minimum": 0.5,
            "table_lignes": "l",
            "filtre_lignes": [
                {"colonne": "a", "motif": "MO-.*"},
                {"colonne": "n", "motif": "FA-.*"},
            ],
            "colonne_lignes": "q",
            "filtre": [{"colonne": "s", "valeurs": ["Réalisée"]}],
            **autres,
        },
    )


NATURES_SOMME = {"t": {"i": "texte", "d": ENTIER, "s": "texte"},
                 "l": {"i": "texte", "a": "texte", "n": "texte", "q": NATIF}}


def _interventions_et_main_d_oeuvre():
    interventions = _table(
        i=["I1", "I2", "I3", "I4", "I5", "I6", "I7", "", "I8", "I8", "I9"],
        d=["70", "75", "20", "61", "90", "", "60", "60", "30", "30", "45"],
        s=["Réalisée"] * 9 + ["Annulée", "Réalisée"],
    )
    lignes = _table(
        "l.csv",
        i=["I1", "I1", "I1", "I2", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I9", ""],
        a=["MO-STD", "MO-STD", "DEPL", "MO-STD", "MO-URG", "MO-STD", "MO-STD", "DEPL",
           "MO-STD", "MO-STD", "MO-STD", "MO-STD", "MO-STD", "MO-STD"],
        n=["FA-1", "FA-1", "FA-1", "FA-2", "FA-2", "FA-3", "FA-4", "FA-5", "FA-6", "FA-7",
           "FA-8", "FA-9", "AV-1", "FA-10"],
        q=[1.25, 1.25, 1.0, 1.0, 0.25, 0.5, 1.0, 1.0, 1.0, "x", 0.5, 0.75, -0.75, 1.0],
    )
    return {"t": interventions, "l": lignes}


def test_somme_liee_arrondie():
    tables = _interventions_et_main_d_oeuvre()
    ecarts, bilan = _controler_tables(tables, NATURES_SOMME, [_somme()])
    # 70 minutes donnent 1,25 h et 75 minutes aussi; 20 minutes donnent le minimum de
    # 0,5 h; 61 minutes donnent 1,25 h. La ligne de main d'oeuvre de I1 en double exact
    # n'est comptée qu'une fois, l'avoir de I9 est hors du filtre des lignes.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (5, CONSTAT_SOMME_DIFFERENTE, "anomalie", "i, d, l.i, l.a, l.n, l.q",
         "1 sur 1 ligne liée pour 1,25 attendu (d 61)"),
    ]
    resume = _bilan(bilan)
    # Hors champ : I8 annulée (filtre) et I5, sans ligne de main d'oeuvre. Non
    # évaluables : durée vide (I6), quantité illisible (I7), clé vide, I8 répété hors du
    # filtre.
    assert (resume["vue"], resume["hors_champ"], resume["non_evaluables"],
            resume["controlees"], resume["anomalies"]) == (VUE_SANS_SURNOMBRE, 2, 4, 5, 1)
    # Avec les lignes d'avoir, I9 n'a plus d'heure facturée.
    ecarts, _ = _controler_tables(tables, NATURES_SOMME, [_somme(
        filtre_lignes=[{"colonne": "a", "motif": "MO-.*"}])])
    assert _lignes(ecarts, "num_ligne_source", "valeur") == [
        (5, "1 sur 1 ligne liée pour 1,25 attendu (d 61)"),
        (12, "0 sur 2 lignes liées pour 0,75 attendu (d 45)"),
    ]
    # Arrondi au plus proche : 61 minutes donnent 1 h. Arrondi inférieur : 70 minutes
    # donnent 1 h.
    ecarts, _ = _controler_tables(tables, NATURES_SOMME, [_somme(arrondi="au plus proche")])
    assert ecarts.empty
    ecarts, _ = _controler_tables(tables, NATURES_SOMME, [_somme(arrondi="inférieur")])
    assert _lignes(ecarts, "num_ligne_source", "valeur") == [
        (2, "1,25 sur 1 ligne liée pour 1 attendu (d 70)"),
    ]
    # Sans minimum, 20 minutes donnent 0,5 h au quart d'heure supérieur, mais 0,25 h à
    # l'arrondi inférieur; un écart égal à la tolérance n'en est pas un.
    ecarts, _ = _controler_tables(tables, NATURES_SOMME, [
        {cle: v for cle, v in _somme(arrondi="inférieur").items() if cle != "minimum"}])
    assert _lignes(ecarts, "num_ligne_source") == [(2,), (4,)]
    ecarts, _ = _controler_tables(tables, NATURES_SOMME, [_somme(tolerance=0.25)])
    assert ecarts.empty



def test_somme_liee_arrondie_pas_decimal_et_valeur_a_mi_pas():
    interventions = _table(i=["I1", "I2"], d=[2.1, 1.125], s=["Réalisée", "Réalisée"])
    lignes = _table("l.csv", i=["I1", "I2"], a=["MO-STD", "MO-STD"], n=["FA-1", "FA-2"],
                    q=[2.1, 1.25])
    tables = {"t": interventions, "l": lignes}
    natures = deepcopy(NATURES_SOMME)
    natures["t"]["d"] = NATIF
    # 2,1 / 0,3 vaut 7 malgré le calcul en virgule flottante : 2,1 au multiple supérieur.
    regle = _somme(diviseur=1, pas=0.3, minimum=0, filtre=[{"colonne": "i", "valeurs": ["I1"]}])
    ecarts, bilan = _controler_tables(tables, natures, [regle])
    assert ecarts.empty and _bilan(bilan)["controlees"] == 1
    # À égale distance de deux multiples, l'arrondi au plus proche prend le supérieur.
    regle = _somme(diviseur=1, arrondi="au plus proche",
                   filtre=[{"colonne": "i", "valeurs": ["I2"]}])
    ecarts, bilan = _controler_tables(tables, natures, [regle])
    assert ecarts.empty and _bilan(bilan)["controlees"] == 1


def _non_nulle(**autres):
    return _instance("au_plus_une_non_nulle", ref="fec",
                     **{"colonnes": ["debit", "credit"], **autres})


def test_au_plus_une_non_nulle():
    donnees = _table(
        debit=["0,00", "5,00", "5,00", "0,00", "", "1 000,00", "-3,00", "0,0000000001"],
        credit=["10,00", "0,00", "5,00", "0,00", "10,00", "0,00", "0,00", "2,00"],
    )
    natures = {"debit": DECIMAL, "credit": DECIMAL}
    ecarts, bilan = _controler(donnees, natures, regles=[_non_nulle()])
    # Une valeur nulle après arrondi à 9 décimales est nulle; une valeur négative ne
    # l'est pas.
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "colonnes", "valeur") == [
        (4, CONSTAT_PLUSIEURS_NON_NULLES, "anomalie", "debit, credit", "5,00 | 5,00"),
    ]
    resume = _bilan(bilan)
    assert (resume["vue"], resume["non_evaluables"], resume["controlees"]) == (
        VUE_TOUTES, 2, 6
    )
    ecarts, _ = _controler(donnees, natures, regles=[_non_nulle(au_moins_une=True)])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [
        (4, CONSTAT_PLUSIEURS_NON_NULLES),
        (5, CONSTAT_AUCUNE_NON_NULLE),
    ]
    trois = _table(a=["1", "0", "0"], b=["0", "0", "2"], c=["0", "3", "4"])
    ecarts, _ = _controler(trois, {"a": ENTIER, "b": ENTIER, "c": ENTIER},
                           regles=[_non_nulle(colonnes=["a", "b", "c"])])
    assert _lignes(ecarts, "num_ligne_source") == [(4,)]


def test_structure_des_types_du_4f2():
    regles = [
        _produit(facteurs=[]),
        _produit(facteurs=["q", {"colonne": "r", "coef": 1}, {"constante": 1},
                           {"colonne": "r", "vide": "0"}, 3, " "]),
        _somme(arrondi="haut"),
        _somme(pas=0),
        _somme(diviseur=-60, tolerance=-1),
        _non_nulle(colonnes=["debit"]),
        _non_nulle(colonnes=["debit", "debit"]),
        _non_nulle(au_moins_une="oui"),
        _produit(),
        # Mêmes facteurs, écrits autrement et dans un autre ordre.
        _produit(facteurs=[{"colonne": "p"}, dict(REMISE), {"colonne": "q", "coefficient": 1}]),
        {cle: v for cle, v in _somme().items() if cle != "pas"},
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (calcul), facteurs : une liste non vide de facteurs est attendue "
        "(chaque facteur commence par un tiret : une colonne, ou un dictionnaire de clés "
        "colonne, coefficient, constante et vide)",
        "règle n° 2 (calcul), facteurs : facteur n° 2 : clé inconnue coef (clés possibles : "
        "colonne, coefficient, constante, vide)",
        "règle n° 2 (calcul), facteurs : facteur n° 3 : clé manquante (colonne)",
        "règle n° 2 (calcul), facteurs : facteur n° 4, vide : un nombre est attendu",
        "règle n° 2 (calcul), facteurs : facteur n° 5 : un nom de colonne ou un dictionnaire "
        "(clés colonne, coefficient, constante, vide) est attendu",
        "règle n° 2 (calcul), facteurs : facteur n° 6 : un nom de colonne est attendu",
        "règle n° 3 (grille), arrondi : arrondi inconnu 'haut' (arrondis possibles : "
        "supérieur, inférieur, au plus proche)",
        "règle n° 4 (grille) : pas : un nombre strictement positif est attendu",
        "règle n° 5 (grille) : tolerance : un nombre positif ou nul est attendu",
        "règle n° 5 (grille) : diviseur : un nombre strictement positif est attendu",
        "règle n° 6 (fec) : colonnes : au moins deux colonnes sont attendues",
        "règle n° 7 (fec), colonnes : colonne citée deux fois",
        "règle n° 8 (fec), au_moins_une : true ou false est attendu",
        "règle n° 10 (calcul) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 9 (calcul))",
        "règle n° 11 (grille) : paramètre manquant (pas)",
    ]


def test_colonnes_du_4f2_confrontees_aux_donnees():
    donnees = _table(q=[1.0], p=[1.0], r=[0.0], m=[1.0], debit=["1"], credit=["0"])
    with pytest.raises(ValueError) as erreur:
        _controler(
            donnees,
            {"q": NATIF, "p": NATIF, "r": "texte", "m": NATIF, "debit": ENTIER,
             "credit": "texte"},
            regles=[_produit(facteurs=["q", "z", REMISE]), _non_nulle()],
        )
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (calcul), facteurs : colonne t.z absente des données chargées",
        "règle n° 1 (calcul), facteurs : la nature en vigueur de t.r est 'texte', un nombre "
        "est attendu (à trancher dans la revue du dictionnaire, notebook 02c_dictionnaire)",
        "règle n° 2 (fec), colonnes : la nature en vigueur de t.credit est 'texte', un nombre "
        "est attendu (à trancher dans la revue du dictionnaire, notebook 02c_dictionnaire)",
    ]
    tables = _interventions_et_main_d_oeuvre()
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, NATURES_SOMME, [_somme(colonne_lignes="a")])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (grille), colonne_lignes : la nature en vigueur de l.a est 'texte', un "
        "nombre est attendu (à trancher dans la revue du dictionnaire, notebook "
        "02c_dictionnaire)",
    ]


def test_catalogue_des_types_du_4f2():
    catalogue = catalogue_types().set_index("type")
    assert catalogue.loc["produit_calcule", "parametres"] == (
        "cible (colonne de nombre), facteurs (facteurs), tolerance (nombre, facultatif)"
    )
    assert catalogue.loc["somme_liee_arrondie", "parametres"] == (
        "cle (liste de colonnes), colonne (colonne de nombre), diviseur (nombre, "
        "facultatif), pas (nombre), arrondi (arrondi, facultatif), minimum (nombre, "
        "facultatif), table_lignes (table), cle_lignes (liste de colonnes de la table liée, "
        "facultatif), filtre_lignes (liste de conditions, facultatif), colonne_lignes "
        "(colonne de nombre de la table liée), tolerance (nombre, facultatif)"
    )
    assert catalogue.loc["au_plus_une_non_nulle", "parametres"] == (
        "colonnes (liste de colonnes de nombre), au_moins_une (true ou false, facultatif)"
    )
    assert catalogue.loc[["produit_calcule", "au_plus_une_non_nulle"], "vue"].tolist() == [
        VUE_TOUTES, VUE_TOUTES
    ]
    assert catalogue.loc["somme_liee_arrondie", "vue"] == VUE_SANS_SURNOMBRE
    types = ["produit_calcule", "somme_liee_arrondie", "au_plus_une_non_nulle"]
    assert set(catalogue.loc[types, "issue"]) == {"anomalie"}


def test_chargement_des_regles_du_4f2(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: calcul\n    libelle: Montant\n    type: produit_calcule\n"
        "    table: factures_lignes\n    cible: montant_ht\n"
        "    facteurs:\n      - quantite\n      - pu_ht\n"
        "      - {colonne: remise_pct, constante: 1, coefficient: -0.01, vide: 0}\n"
        "    tolerance: 0.005\n"
        "  - ref: grille\n    libelle: Quart d'heure\n    type: somme_liee_arrondie\n"
        "    table: interventions\n    cle: [id_intervention]\n    colonne: duree_min\n"
        "    diviseur: 60\n    pas: 0.25\n    arrondi: supérieur\n    minimum: 0.5\n"
        "    table_lignes: factures_lignes\n    colonne_lignes: quantite\n"
        "  - ref: fec\n    libelle: Un des deux\n    type: au_plus_une_non_nulle\n"
        "    table: fec\n    colonnes: [Debit, Credit]\n    au_moins_une: true\n",
        encoding="utf-8",
    )
    regles = charger_regles_gestion(chemin)
    assert regles[0]["facteurs"][2] == {
        "colonne": "remise_pct", "constante": 1, "coefficient": -0.01, "vide": 0
    }
    assert regles[1]["arrondi"] == "supérieur"
    assert regles[2]["au_moins_une"] is True


MONTANTS = [
    {"colonne": "ttc", "conditions": [{"colonne": "c", "motif": "411.*"}],
     "termes": {"deb": 1, "cre": -1}},
    {"colonne": "ht", "conditions": [{"colonne": "c", "motif": "70.*"}],
     "termes": {"cre": 1, "deb": -1}},
]


def _concordantes(**autres):
    return _instance(
        "sommes_liees_concordantes",
        ref="R14",
        **{
            "cle": ["n"],
            "table_lignes": "l",
            "cle_lignes": ["p"],
            "filtre_lignes": [{"colonne": "j", "valeurs": ["VT"]}],
            "date": "d",
            "date_lignes": "dt",
            "groupe_lignes": ["j", "e"],
            "montants": deepcopy(MONTANTS),
            **autres,
        },
    )


NATURES_CONCORDANTES = {
    "t": {"n": "texte", "d": NATIVE, "ttc": NATIF, "ht": NATIF},
    "l": {"p": "texte", "j": "texte", "e": "texte", "dt": "date AAAAMMJJ", "c": "texte",
          "deb": DECIMAL, "cre": DECIMAL},
}


def _factures_et_ecritures():
    d = _date("01/03/2025")
    factures = _table(
        n=["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "", "F11", "F11",
           "F12", "F13", "F14", "F15"],
        d=[d, d, d, _date("04/03/2025"), d, d, d, d, d, None, d, d, d, d, d, d, d],
        ttc=[120.0, 60.0, 12.0, 12.0, 36.0, -24.0, None, 30.0, 12.0, 12.0, 12.0, 12.0, 13.0,
             0.0, 10.0, 12.0, 12.0],
        ht=[100.0, 50.0, 10.0, 10.0, 30.0, -20.0, 10.0, 25.0, 10.0, 10.0, 10.0, 10.0, 11.0,
            0.0, 10.0, 10.0, 10.0],
    )
    lignes = [
        # p, j, e, dt, c, deb, cre
        ("F1", "VT", "E1", "20250301", "411000", "120,00", "0,00"),
        ("F1", "VT", "E1", "20250301", "706100", "0,00", "100,00"),
        ("F1", "VT", "E1", "20250301", "445710", "0,00", "20,00"),
        # Doublon exact, compté une fois.
        ("F1", "VT", "E1", "20250301", "445710", "0,00", "20,00"),
        ("F2", "VT", "E2", "20250301", "411000", "60,00", "0,00"),
        ("F2", "VT", "E2", "20250301", "706100", "0,00", "40,00"),
        # Hors du filtre des lignes : F3 n'a aucune ligne liée.
        ("F3", "BQ", "B1", "20250301", "411000", "0,00", "12,00"),
        ("F4", "VT", "E4", "20250304", "706100", "0,00", "10,00"),
        ("F4", "VT", "E4", "20250305", "411000", "12,00", "0,00"),
        ("F5", "VT", "E5", "20250301", "411000", "30,00", "0,00"),
        ("F5", "VT", "E6", "20250301", "706100", "0,00", "30,00"),
        ("F6", "VT", "E7", "20250301", "411000", "0,00", "24,00"),
        ("F6", "VT", "E7", "20250301", "706100", "20,00", "0,00"),
        ("F7", "VT", "E8", "20250301", "411000", "12,00", "0,00"),
        ("F8", "VT", "E9", "20250301", "411000", "30,00", "0,00"),
        ("F8", "VT", "E9", "20250301", "", "0,00", "25,00"),
        ("F9", "VT", "E10", "20250301", "411000", "x", "0,00"),
        ("F10", "VT", "E11", "20250301", "411000", "12,00", "0,00"),
        ("F11", "VT", "E12", "20250301", "411000", "12,00", "0,00"),
        ("F12", "VT", "E13", "20250301", "411000", "0,00", "0,00"),
        ("F13", "VT", "E14", "20250301", "411000", "10,00", "0,00"),
        # Date illisible (F14) et groupe vide (F15).
        ("F14", "VT", "E15", "20250301", "411000", "12,00", "0,00"),
        ("F14", "VT", "E15", "20250231", "706100", "0,00", "10,00"),
        ("F15", "VT", "E16", "20250301", "411000", "12,00", "0,00"),
        ("F15", "VT", "", "20250301", "706100", "0,00", "10,00"),
    ]
    colonnes = dict(zip(["p", "j", "e", "dt", "c", "deb", "cre"], map(list, zip(*lignes))))
    return {"t": factures, "l": _table("l.csv", **colonnes)}


def test_sommes_liees_concordantes():
    tables = _factures_et_ecritures()
    ecarts, bilan = _controler_tables(tables, NATURES_CONCORDANTES, [_concordantes()])
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (3, CONSTAT_SOMMES_DIFFERENTES, "anomalie",
         "ht 50 pour une somme de 40 sur 1 ligne liée (écart 10)"),
        (4, CONSTAT_SANS_LIGNE, "anomalie", "F3 | 2025-03-01 00:00:00 | 12.0 | 10.0"),
        (5, CONSTAT_DATE_DIFFERENTE, "anomalie", "04/03/2025 (lignes liées : 05/03/2025)"),
        (6, CONSTAT_PLUSIEURS_GROUPES, "anomalie", "2 groupes : VT E5 | VT E6"),
        (6, CONSTAT_SOMMES_DIFFERENTES, "anomalie",
         "ttc 36 pour une somme de 30 sur 1 ligne liée (écart 6)"),
        # Un montant sans ligne retenue est comparé à une somme nulle.
        (16, CONSTAT_SOMMES_DIFFERENTES, "anomalie",
         "ht 10 pour une somme de 0 sur 0 ligne liée (écart 10)"),
    ]
    assert ecarts["colonnes"].iloc[0] == (
        "n, d, ttc, ht, l.p, l.j, l.dt, l.e, l.c, l.deb, l.cre"
    )
    resume = _bilan(bilan)
    # Non évaluables : montant vide (F7), compte vide (F8), débit illisible (F9), date
    # vide (F10), clé vide, F11 répétée, date illisible d'une ligne liée (F14), groupe
    # vide (F15).
    assert (resume["vue"], resume["lignes"], resume["hors_champ"], resume["non_evaluables"],
            resume["controlees"], resume["anomalies"]) == (VUE_SANS_SURNOMBRE, 17, 0, 9, 8, 6)
    # Une clé répétée hors du filtre rend la ligne non évaluable : seule la première
    # F11 remplit le filtre.
    _, bilan = _controler_tables(tables, NATURES_CONCORDANTES, [
        _concordantes(filtre=[{"colonne": "ttc", "valeurs": ["12.0"]}])])
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"]) == (9, 6, 2)


def test_sommes_liees_concordantes_sans_date_ni_groupe_et_tolerance():
    tables = _factures_et_ecritures()
    regle = {cle: v for cle, v in _concordantes().items()
             if cle not in ("date", "date_lignes", "groupe_lignes")}
    ecarts, bilan = _controler_tables(tables, NATURES_CONCORDANTES, [regle])
    assert _lignes(ecarts, "num_ligne_source", "constat") == [
        (3, CONSTAT_SOMMES_DIFFERENTES),
        (4, CONSTAT_SANS_LIGNE),
        (6, CONSTAT_SOMMES_DIFFERENTES),
        (11, CONSTAT_SOMMES_DIFFERENTES),
        (16, CONSTAT_SOMMES_DIFFERENTES),
    ]
    # La date vide de F10 ne compte plus : son montant HT, sans ligne 70, est en écart.
    # F14 et F15 deviennent évaluables, sans écart.
    assert _bilan(bilan)["non_evaluables"] == 6
    # Un écart égal à la tolérance n'en est pas un; une somme sur deux montants n'en
    # liste que ceux en écart.
    ecarts, _ = _controler_tables(tables, NATURES_CONCORDANTES, [_concordantes(tolerance=6)])
    assert _lignes(ecarts, "num_ligne_source", "valeur") == [
        (3, "ht 50 pour une somme de 40 sur 1 ligne liée (écart 10)"),
        (4, "F3 | 2025-03-01 00:00:00 | 12.0 | 10.0"),
        (5, "04/03/2025 (lignes liées : 05/03/2025)"),
        (6, "2 groupes : VT E5 | VT E6"),
        (16, "ht 10 pour une somme de 0 sur 0 ligne liée (écart 10)"),
    ]
    # Sans conditions, toutes les lignes liées sont retenues.
    montants = [{"colonne": "ttc", "termes": {"deb": 1, "cre": -1}}]
    regle = _concordantes(montants=montants,
                          filtre=[{"colonne": "n", "valeurs": ["F1", "F2", "F6"]}])
    ecarts, bilan = _controler_tables(tables, NATURES_CONCORDANTES, [regle])
    assert _lignes(ecarts, "num_ligne_source", "valeur") == [
        (2, "ttc 120 pour une somme de 0 sur 3 lignes liées (écart 120)"),
        (3, "ttc 60 pour une somme de 20 sur 2 lignes liées (écart 40)"),
        (7, "ttc -24 pour une somme de -4 sur 2 lignes liées (écart -20)"),
    ]
    assert _bilan(bilan)["hors_champ"] == 14


def test_sommes_liees_concordantes_masquees():
    tables = _factures_et_ecritures()
    ecarts, _ = _controler_tables(tables, NATURES_CONCORDANTES, [_concordantes()],
                                  sensibles={"l": frozenset({"c"})})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}
    assert set(ecarts["cle"]) == {None}


def test_structure_du_type_du_4g1():
    regles = [
        _concordantes(montants=[]),
        _concordantes(montants=["ttc"]),
        _concordantes(montants=[{"colonne": "ttc", "terme": {"deb": 1}}]),
        _concordantes(montants=[{"colonne": "ttc", "termes": {"deb": "1"},
                                 "conditions": [{"colonne": "c"}]}]),
        {cle: v for cle, v in _concordantes(tolerance=-1).items() if cle != "date_lignes"},
        _concordantes(),
        _concordantes(cle_lignes=["n"], groupe_lignes=["j", "e"], filtre_lignes=[
            {"colonne": "j", "valeurs": ["VT"]}]),
        _concordantes(cle_lignes=["n"]),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (R14), montants : une liste non vide de montants est attendue (chaque "
        "montant commence par un tiret, avec les clés colonne, termes et, si besoin, "
        "conditions)",
        "règle n° 2 (R14), montants : montant n° 1 : un dictionnaire est attendu (clés "
        "colonne, conditions, termes)",
        "règle n° 3 (R14), montants : montant n° 1 : clé inconnue terme (clés possibles : "
        "colonne, conditions, termes)",
        "règle n° 3 (R14), montants : montant n° 1 : clé manquante (termes)",
        "règle n° 4 (R14), montants : montant n° 1, termes : deb : un nombre est attendu "
        "comme coefficient",
        "règle n° 4 (R14), montants : montant n° 1, condition n° 1 : clé manquante (valeurs "
        "ou motif)",
        "règle n° 5 (R14) : tolerance : un nombre positif ou nul est attendu",
        "règle n° 5 (R14) : date et date_lignes : les deux sont attendues, ou aucune",
        "règle n° 8 (R14) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 7 (R14))",
    ]
    # La clé des lignes reprend par défaut celle de la règle.
    assert problemes_regles_gestion([
        _concordantes(cle_lignes=["n"]),
        {cle: v for cle, v in _concordantes().items() if cle != "cle_lignes"},
    ]) == [
        "règle n° 2 (R14) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 1 (R14))",
    ]


def test_colonnes_du_4g1_confrontees_aux_donnees():
    tables = _factures_et_ecritures()
    natures = deepcopy(NATURES_CONCORDANTES)
    natures["t"]["ht"] = "texte"
    natures["l"]["cre"] = "texte"
    montants = deepcopy(MONTANTS)
    montants[1]["conditions"] = [{"colonne": "z", "motif": "70.*"}]
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, natures, [_concordantes(montants=montants)])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R14), montants : la nature en vigueur de l.cre est 'texte', un nombre "
        "est attendu (à trancher dans la revue du dictionnaire, notebook 02c_dictionnaire)",
        "règle n° 1 (R14), montants : la nature en vigueur de t.ht est 'texte', un nombre "
        "est attendu (à trancher dans la revue du dictionnaire, notebook 02c_dictionnaire)",
        "règle n° 1 (R14), montants : colonne l.z absente des données chargées",
    ]


def test_catalogue_et_chargement_du_4g1(tmp_path):
    catalogue = catalogue_types().set_index("type")
    assert catalogue.loc["sommes_liees_concordantes", "parametres"] == (
        "cle (liste de colonnes), table_lignes (table), cle_lignes (liste de colonnes de la "
        "table liée, facultatif), filtre_lignes (liste de conditions, facultatif), date "
        "(colonne de date, facultatif), date_lignes (colonne de date de la table liée, "
        "facultatif), groupe_lignes (liste de colonnes de la table liée, facultatif), "
        "montants (montants), tolerance (nombre, facultatif)"
    )
    assert catalogue.loc["sommes_liees_concordantes", ["vue", "issue"]].tolist() == [
        VUE_SANS_SURNOMBRE, "anomalie"
    ]
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: R14\n    libelle: Facture comptabilisée\n"
        "    type: sommes_liees_concordantes\n    table: factures_entetes\n"
        "    cle: [num_facture]\n    table_lignes: fec\n    cle_lignes: [PieceRef]\n"
        "    filtre_lignes:\n      - colonne: JournalCode\n        valeurs: [VT]\n"
        "    date: date_facture\n    date_lignes: EcritureDate\n"
        "    groupe_lignes: [JournalCode, EcritureNum]\n"
        "    montants:\n"
        "      - colonne: total_ttc\n"
        "        conditions:\n          - colonne: CompteNum\n            motif: '411.*'\n"
        "        termes: {Debit: 1, Credit: -1}\n"
        "      - colonne: total_ht\n"
        "        conditions:\n          - colonne: CompteNum\n            motif: '70[678].*'\n"
        "        termes: {Credit: 1, Debit: -1}\n",
        encoding="utf-8",
    )
    regles = charger_regles_gestion(chemin)
    assert regles[0]["montants"][1] == {
        "colonne": "total_ht",
        "conditions": [{"colonne": "CompteNum", "motif": "70[678].*"}],
        "termes": {"Credit": 1, "Debit": -1},
    }


# Morceau 4g2 : totaux par période d'export, écarts sans ligne source.

def _totaux(**autres):
    return _instance(
        "totaux_par_periode",
        ref="R15",
        **{
            "termes": {"ht": 1},
            "table_lignes": "l",
            "filtre_lignes": [{"colonne": "c", "motif": "70.*"}],
            "termes_lignes": {"cre": 1, "deb": -1},
            **autres,
        },
    )


NATURES_TOTAUX = {
    "t": {"n": "texte", "ht": NATIF},
    "l": {"c": "texte", "deb": DECIMAL, "cre": DECIMAL},
}


def _factures_et_comptes():
    factures = pd.concat(
        [
            # Avoir négatif; doublon exact de F1, compté une fois.
            _table("a.csv", "2025", n=["F1", "A1", "F1"], ht=[100.0, -20.0, 100.0]),
            _table("b.csv", "2026-01", n=["F2"], ht=[30.0]),
            # Montant vide : période non évaluable.
            _table("c.csv", "2026-03", n=["F3", "F4"], ht=[10.0, None]),
            _table("d.csv", "2026-04", n=["F5"], ht=[7.0]),
        ],
        ignore_index=True,
    )
    ecritures = pd.concat(
        [
            _table("fa.txt", "2025", c=["706000", "707000", "411000", "706000"],
                   deb=["0,00", "20,00", "80,00", "0,00"],
                   cre=["100,00", "0,00", "0,00", "100,00"]),
            _table("fb.txt", "2026-01", c=["706000"], deb=["0,00"], cre=["20,00"]),
            # Période sans facture.
            _table("fc.txt", "2026-02", c=["708000"], deb=["0,00"], cre=["5,00"]),
            _table("fd.txt", "2026-03", c=["706000"], deb=["0,00"], cre=["10,00"]),
            # Débit illisible : période non évaluable.
            _table("fe.txt", "2026-04", c=["706000"], deb=["x"], cre=["7,00"]),
        ],
        ignore_index=True,
    )
    return {"t": factures, "l": ecritures}


def test_totaux_par_periode():
    tables = _factures_et_comptes()
    ecarts, bilan = _controler_tables(tables, NATURES_TOTAUX, [_totaux()])
    assert _lignes(ecarts, "fichier_source", "feuille_source", "num_ligne_source", "issue",
                   "constat", "cle", "valeur", "proposition") == [
        (None, None, None, "anomalie", gestion.CONSTAT_TOTAL_PERIODE, "2026-01",
         "t 30 sur 1 ligne pour l 20 sur 1 ligne (écart 10)", None),
        (None, None, None, "anomalie", gestion.CONSTAT_TOTAL_PERIODE, "2026-02",
         "t 0 sur 0 ligne pour l 5 sur 1 ligne (écart -5)", None),
    ]
    assert set(ecarts["colonnes"]) == {"ht, l.c, l.cre, l.deb"}
    resume = _bilan(bilan)
    assert (resume["vue"], resume["lignes"], resume["ecartees_doublons"], resume["hors_champ"],
            resume["non_evaluables"], resume["controlees"], resume["anomalies"]) == (
        VUE_SANS_SURNOMBRE, 7, 1, 0, 3, 3, 2)
    assert resume["avertissements"] == (
        "période 2026-03 : 1 montant vide ou illisible dans t; "
        "période 2026-04 : 1 montant vide ou illisible dans l"
    )
    # Un écart égal à la tolérance n'en est pas un; l'issue de la règle s'applique.
    ecarts, bilan = _controler_tables(
        tables, NATURES_TOTAUX, [_totaux(tolerance=5, issue="à arbitrer")])
    assert _lignes(ecarts, "cle", "issue") == [("2026-01", "à arbitrer")]
    assert (_bilan(bilan)["anomalies"], _bilan(bilan)["a_arbitrer"]) == (0, 1)
    # Les lignes hors du filtre de la règle ne comptent pas dans les totaux; le montant
    # vide de 2026-03, hors champ, ne bloque plus sa période.
    ecarts, bilan = _controler_tables(
        tables, NATURES_TOTAUX, [_totaux(filtre=[{"colonne": "n", "valeurs": ["F2"]}])])
    assert _lignes(ecarts, "cle", "valeur") == [
        ("2025", "t 0 sur 0 ligne pour l 80 sur 2 lignes (écart -80)"),
        ("2026-01", "t 30 sur 1 ligne pour l 20 sur 1 ligne (écart 10)"),
        ("2026-02", "t 0 sur 0 ligne pour l 5 sur 1 ligne (écart -5)"),
        ("2026-03", "t 0 sur 0 ligne pour l 10 sur 1 ligne (écart -10)"),
    ]
    resume = _bilan(bilan)
    assert (resume["hors_champ"], resume["non_evaluables"], resume["controlees"]) == (5, 0, 1)


def test_totaux_par_periode_somme_exacte():
    tables = {
        "t": _table(n=["F1", "F2", "F3"], ht=[1e16, 1.0, -1e16]),
        "l": _table("f.txt", c=["706000"], deb=["0,00"], cre=["1,00"]),
    }
    ecarts, bilan = _controler_tables(tables, NATURES_TOTAUX, [_totaux()])
    # Une somme ordinaire perdrait le 1 (1e16 + 1 vaut 1e16 en virgule flottante); la
    # fonction sum de Python ne compense les arrondis qu'à partir de la version 3.12.
    assert ecarts.empty
    assert _bilan(bilan)["controlees"] == 3


NATURES_DETAIL = {
    "t": {"k": "texte", "m": NATIF},
    "l": {"kl": "texte", "v": DECIMAL},
}


def _comptes_detailles():
    achats = pd.concat(
        [
            _table("a.xlsx", "2025", k=["A", "A", "B"], m=[10.0, 5.0, 3.0]),
            # Détail vide : la période 2026-01 n'est pas évaluable.
            _table("b.xlsx", "2026-01", k=["", "A"], m=[4.0, 1.0]),
        ],
        ignore_index=True,
    )
    ecritures = pd.concat(
        [
            _table("fa.txt", "2025", kl=["A", "B", "C"], v=["15,00", "2,00", "1,00"]),
            _table("fb.txt", "2026-01", kl=["A"], v=["1,00"]),
            _table("fc.txt", "2026-02", kl=[" "], v=["2,00"]),
        ],
        ignore_index=True,
    )
    return {"t": achats, "l": ecritures}


def _detail(**autres):
    return _instance(
        "totaux_par_periode",
        ref="R20",
        **{"termes": {"m": 1}, "detail": "k", "table_lignes": "l",
           "termes_lignes": {"v": 1}, "detail_lignes": "kl", **autres},
    )


def test_totaux_par_periode_et_par_detail():
    tables = _comptes_detailles()
    ecarts, bilan = _controler_tables(tables, NATURES_DETAIL, [_detail()])
    assert _lignes(ecarts, "num_ligne_source", "cle", "valeur") == [
        (None, "2025 | B", "t 3 sur 1 ligne pour l 2 sur 1 ligne (écart 1)"),
        (None, "2025 | C", "t 0 sur 0 ligne pour l 1 sur 1 ligne (écart -1)"),
    ]
    resume = _bilan(bilan)
    assert (resume["lignes"], resume["non_evaluables"], resume["controlees"],
            resume["anomalies"]) == (5, 2, 3, 2)
    assert resume["avertissements"] == (
        "période 2026-01 : 1 ligne au détail vide dans t (k); "
        "période 2026-02 : 1 ligne au détail vide dans l (kl)"
    )
    # Clé et valeur masquées dès qu'une colonne de la règle est sensible.
    ecarts, _ = _controler_tables(tables, NATURES_DETAIL, [_detail()],
                                  sensibles={"l": frozenset({"kl"})})
    assert _lignes(ecarts, "cle", "valeur") == [(VALEUR_MASQUEE, VALEUR_MASQUEE)] * 2


def test_totaux_par_periode_sans_periode_lisible():
    tables = _factures_et_comptes()
    tables["t"].loc[3, "periode_export"] = "2026-13"
    ecarts, bilan = _controler_tables(tables, NATURES_TOTAUX, [_totaux()])
    assert ecarts.empty
    resume = _bilan(bilan)
    assert (resume["non_evaluables"], resume["controlees"]) == (6, 0)
    assert resume["avertissements"].startswith(
        "1 ligne sans période d'export lisible dans t : aucun total évaluable; "
    )
    # Une table liée sans aucune période lisible est refusée, comme la table de la règle.
    tables = _factures_et_comptes()
    tables["l"]["periode_export"] = None
    tables["t"]["periode_export"] = "toujours"
    with pytest.raises(ValueError) as erreur:
        _controler_tables(tables, NATURES_TOTAUX, [_totaux()])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R15) : table t, la table n'est pas un export périodique (aucune "
        "période d'export lisible dans periode_export)",
        "règle n° 1 (R15), table_lignes : table l, la table n'est pas un export périodique "
        "(aucune période d'export lisible dans periode_export)",
    ]


def test_structure_du_type_du_4g2():
    regles = [
        _totaux(detail="n"),
        _totaux(tolerance=-1),
        _totaux(termes_lignes={"cre": "1"}),
        _totaux(termes_lignes={}),
        _totaux(),
        _totaux(filtre_lignes=[{"colonne": "c", "motif": "70.*"}]),
    ]
    assert problemes_regles_gestion(regles) == [
        "règle n° 1 (R15) : detail et detail_lignes : les deux sont attendues, ou aucune",
        "règle n° 2 (R15) : tolerance : un nombre positif ou nul est attendu",
        "règle n° 3 (R15), termes_lignes : cre : un nombre est attendu comme coefficient",
        "règle n° 4 (R15), termes_lignes : un dictionnaire non vide est attendu (colonne "
        "vers coefficient, par exemple {total_ht: 1, total_tva: 1})",
        "règle n° 6 (R15) : règle en double (même type, même table, mêmes paramètres et "
        "même filtre que la règle n° 5 (R15))",
    ]
    # Termes de la table liée confrontés à ses colonnes et à leur nature.
    natures = deepcopy(NATURES_TOTAUX)
    natures["l"]["cre"] = "texte"
    with pytest.raises(ValueError) as erreur:
        _controler_tables(_factures_et_comptes(), natures,
                          [_totaux(termes_lignes={"cre": 1, "z": -1})])
    assert str(erreur.value).split("\n  ")[1:] == [
        "règle n° 1 (R15), termes_lignes : la nature en vigueur de l.cre est 'texte', un "
        "nombre est attendu (à trancher dans la revue du dictionnaire, notebook "
        "02c_dictionnaire)",
        "règle n° 1 (R15), termes_lignes : colonne l.z absente des données chargées",
    ]


def _lignes_et_periodes(donnees, parametres, natures):
    constats = pd.Series(None, index=donnees.index, dtype=object)
    constats.iloc[0] = "constat de ligne"
    return Constats(
        pd.Series(True, index=donnees.index, dtype=bool),
        gestion._ecarts(constats),
        ecarts_periodes=pd.DataFrame(
            {"constat": ["constat de période"] * 2, "cle": ["2025", "2026-01"],
             "valeur": ["v1", "v2"], "issue": [ISSUE_INFORMATION, None]}
        ),
    )


def test_ecarts_sans_ligne_apres_ceux_des_lignes(monkeypatch):
    types = dict(gestion.TYPES)
    types["essai_periodes"] = TypeRegle(
        description="essai",
        parametres={"colonne": gestion.GENRE_COLONNE_DATE},
        vue=VUE_TOUTES,
        controler=_lignes_et_periodes,
    )
    monkeypatch.setattr(gestion, "TYPES", types)
    donnees = pd.concat([_table("b.csv", d=["14/03/2025"]), _table("a.csv", d=["15/03/2025"])],
                        ignore_index=True)
    regles = [_regle(type="essai_periodes"), _regle()]
    ecarts, bilan = _controler(donnees, {"d": "date JJ/MM/AAAA"}, regles=regles,
                               declarations={"t": {"cle": ["d"]}})
    assert _lignes(ecarts, "type", "fichier_source", "issue", "constat", "cle", "valeur") == [
        ("essai_periodes", "b.csv", "anomalie", "constat de ligne", "14/03/2025",
         "14/03/2025"),
        ("essai_periodes", None, ISSUE_INFORMATION, "constat de période", "2025", "v1"),
        ("essai_periodes", None, "anomalie", "constat de période", "2026-01", "v2"),
    ]
    resume = _bilan(bilan)
    assert (resume["anomalies"], resume["informations"]) == (2, 1)
    assert _bilan(bilan, 1)["anomalies"] == 0


def test_catalogue_et_chargement_du_4g2(tmp_path):
    catalogue = catalogue_types().set_index("type")
    assert catalogue.loc["totaux_par_periode", "parametres"] == (
        "termes (termes), detail (colonne, facultatif), table_lignes (table), filtre_lignes "
        "(liste de conditions, facultatif), termes_lignes (termes de la table liée), "
        "detail_lignes (colonne de la table liée, facultatif), tolerance (nombre, facultatif)"
    )
    assert catalogue.loc["totaux_par_periode", ["vue", "issue"]].tolist() == [
        VUE_SANS_SURNOMBRE, "anomalie"
    ]
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "regles:\n"
        "  - ref: R20\n    libelle: Achats égaux au solde des comptes\n"
        "    type: totaux_par_periode\n    table: achats_lignes\n"
        "    termes: {montant_ht: 1}\n    detail: compte_charge\n    table_lignes: fec\n"
        "    filtre_lignes:\n      - colonne: CompteNum\n        valeurs: ['601100', '601200']\n"
        "    detail_lignes: CompteNum\n    termes_lignes: {Debit: 1, Credit: -1}\n"
        "    filtre:\n      - colonne: compte_charge\n        valeurs: ['601100', '601200']\n",
        encoding="utf-8",
    )
    regles = charger_regles_gestion(chemin)
    assert regles[0]["filtre_lignes"] == [
        {"colonne": "CompteNum", "valeurs": ["601100", "601200"]}
    ]
    assert regles[0]["termes_lignes"] == {"Debit": 1, "Credit": -1}
