"""Tests du module frigeo.rattachement (étape 7.3d)."""

import pandas as pd
import pytest

from frigeo.rattachement import (
    COLONNES_BILAN_RATTACHEMENT,
    COLONNES_RATTACHEMENT,
    RegleRattachement,
    rattacher,
    regles_rattachement,
)


def _table(fichier="t.csv", premiere_ligne=2, feuille=None, numeros=None, **colonnes):
    """Table fictive avec son lignage."""
    nombre = len(next(iter(colonnes.values())))
    donnees = pd.DataFrame(colonnes, dtype=object)
    donnees.insert(0, "num_ligne_source",
                   numeros or list(range(premiere_ligne, premiere_ligne + nombre)))
    donnees.insert(0, "feuille_source", feuille)
    donnees.insert(0, "fichier_source", fichier)
    return donnees


def _existence(table="f", cle=("code",), reference="r", ref="existence", **autres):
    return {"ref": ref, "libelle": "l", "type": "existence_dans_reference", "table": table,
            "cle": list(cle), "table_reference": reference, **autres}


def _periode(table="f", cle=("code",), reference="r", ref="R11", **autres):
    return {"ref": ref, "libelle": "l", "type": "date_dans_periode_reference",
            "table": table, "cle": list(cle), "date": "jour", "table_reference": reference,
            "debut": "debut", "fin": "fin", **autres}


DICTIONNAIRE = {
    "f": {"code": {"nature": {"regle": "texte"}}, "jour": {"nature": {"regle": "date JJ/MM/AAAA"}}},
    "r": {"code": {"nature": {"regle": "texte"}}, "debut": {"nature": {"regle": "date JJ/MM/AAAA"}},
          "fin": {"nature": {"regle": "date JJ/MM/AAAA"}}},
}


def _choix(resultat, regle=1):
    """(numéro de la ligne source, numéro de la ligne du référentiel, candidates, par date)."""
    lignes = resultat.lignes[resultat.lignes["regle"] == regle]
    return [
        (int(l.num_ligne_source), int(l.num_ligne_reference), int(l.candidates),
         bool(l.choix_par_date))
        for l in lignes.itertuples(index=False)
    ]


# --- Règles reprises --------------------------------------------------------------


def test_regles_reprises_et_cle_du_referentiel_par_defaut():
    regles = [
        {"ref": "R02", "libelle": "l", "type": "plage", "table": "f", "colonne": "x"},
        _existence(),
        _existence(table="g", cle=("c1", "c2"), cle_reference=["a", "b"],
                   comparaison="après normalisation"),
    ]
    assert regles_rattachement(regles) == [
        RegleRattachement("f", ("code",), "r", ("code",), refs=("existence",)),
        RegleRattachement("g", ("c1", "c2"), "r", ("a", "b"), "après normalisation",
                          refs=("existence",)),
    ]


def test_regles_dedoublonnees_variante_avec_date_gardee():
    regles = [
        _existence(ref="existence", cle_facultative=True),
        _periode(ref="avoir", fin=None),
        _existence(comparaison="après normalisation"),
        _periode(ref="R11"),
    ]
    regles[1].pop("fin")
    resultat = regles_rattachement(regles)
    assert resultat == [
        RegleRattachement("f", ("code",), "r", ("code",), date="jour", debut="debut",
                          refs=("existence", "avoir", "R11")),
        RegleRattachement("f", ("code",), "r", ("code",), "après normalisation",
                          refs=("existence",)),
    ]
    assert resultat[0].avec_date and not resultat[1].avec_date


# --- Comparaisons -----------------------------------------------------------------


def test_telle_quelle_cle_vide_et_absente_sans_ligne():
    faits = _table(code=["A1", "a1", "", None, "B2", " "])
    reference = _table("r.csv", code=["A1", "B2"])
    resultat = rattacher({"f": faits, "r": reference}, DICTIONNAIRE, [_existence()])
    assert list(resultat.lignes.columns) == list(COLONNES_RATTACHEMENT)
    assert _choix(resultat) == [(2, 2, 1, False), (6, 3, 1, False)]
    assert resultat.lignes.iloc[0]["fichier_source"] == "t.csv"
    assert resultat.lignes.iloc[0]["fichier_reference"] == "r.csv"
    bilan = resultat.bilan.iloc[0]
    assert list(resultat.bilan.columns) == list(COLONNES_BILAN_RATTACHEMENT)
    assert (bilan["lignes"], bilan["cles_vides"], bilan["introuvables"], bilan["rattachees"]) == (
        6, 3, 1, 2,
    )


def test_apres_normalisation():
    faits = _table(code=["dupont  sa", "Éclair"])
    reference = _table("r.csv", code=["DUPONT SA", "ECLAIR"])
    regle = _existence(comparaison="après normalisation")
    resultat = rattacher({"f": faits, "r": reference}, DICTIONNAIRE, [regle])
    assert _choix(resultat) == [(2, 2, 1, False), (3, 3, 1, False)]


def test_mots_dans_le_desordre_sur_plusieurs_colonnes():
    faits = _table(intervenant=["Mathieu LEROUX", "LEROUX Mathieu", "LEROUX"])
    reference = _table("intervenants.xlsx", feuille="Intervenants",
                       nom=["MARTIN", "LEROUX"], prenom=["Julie", "Mathieu"])
    regle = _existence(cle=("intervenant",), cle_reference=["nom", "prenom"],
                       comparaison="mots dans le désordre")
    resultat = rattacher({"f": faits, "r": reference}, {}, [regle])
    assert _choix(resultat) == [(2, 3, 1, False), (3, 3, 1, False)]
    assert resultat.lignes.iloc[0]["feuille_reference"] == "Intervenants"
    assert resultat.lignes.iloc[0]["feuille_source"] is None


# --- Plusieurs lignes du référentiel ----------------------------------------------


def test_choix_par_la_date():
    # Deux périodes d'emploi pour le même code, la seconde ouverte.
    reference = _table("r.csv", code=["A", "A", "B"], debut=["01/01/2020", "01/03/2025", "01/01/2020"],
                       fin=["31/12/2024", None, None])
    faits = _table(code=["A", "A", "A", "A", "B"],
                   jour=["15/06/2023", "10/04/2026", "15/01/2025", None, "15/01/2025"])
    resultat = rattacher({"f": faits, "r": reference}, DICTIONNAIRE, [_periode()])
    assert _choix(resultat) == [
        (2, 2, 2, True),    # dans la première période
        (3, 3, 2, True),    # dans la période ouverte
        (4, 2, 2, False),   # hors des deux périodes : première dans l'ordre du lignage
        (5, 2, 2, False),   # date vide : idem
        (6, 4, 1, False),   # une seule ligne : sans recours à la date
    ]
    bilan = resultat.bilan.iloc[0]
    assert (bilan["plusieurs_candidates"], bilan["choisies_par_date"], bilan["date"]) == (
        4, 2, "jour",
    )


def test_periodes_qui_se_chevauchent_ou_inutilisables():
    reference = _table("r.csv", code=["A", "A", "C", "C"],
                       debut=["01/01/2020", "01/01/2021", None, "01/01/2022"],
                       fin=[None, None, None, "pas une date"])
    faits = _table(code=["A", "C"], jour=["01/06/2021", "01/06/2023"])
    resultat = rattacher({"f": faits, "r": reference}, DICTIONNAIRE, [_periode()])
    # A : deux périodes contiennent la date; C : début vide et fin illisible.
    assert _choix(resultat) == [(2, 2, 2, False), (3, 4, 2, False)]


def test_bornes_incluses_et_sans_colonne_de_fin():
    reference = _table("r.csv", code=["A", "A"], debut=["01/01/2020", "01/02/2020"])
    faits = _table(code=["A", "A"], jour=["31/01/2020", "01/02/2020"])
    regle = _periode()
    regle.pop("fin")
    dictionnaire = {"f": DICTIONNAIRE["f"], "r": {"debut": DICTIONNAIRE["r"]["debut"]}}
    resultat = rattacher({"f": faits, "r": reference}, dictionnaire, [regle])
    # Sans fin, les deux périodes sont ouvertes : le 01/02/2020 est dans les deux.
    assert _choix(resultat) == [(2, 2, 2, True), (3, 2, 2, False)]


def test_premiere_dans_l_ordre_du_lignage():
    # Lignes du référentiel livrées dans le désordre : fichier, puis feuille, puis numéro.
    reference = pd.concat([
        _table("r_2026-01.xlsx", feuille="Entetes", numeros=[2], code=["A"]),
        _table("r_2025.xlsx", feuille="Entetes", numeros=[9], code=["A"]),
        _table("r_2025.xlsx", feuille="Entetes", numeros=[4], code=["A"]),
    ], ignore_index=True)
    faits = _table(code=["A"])
    resultat = rattacher({"f": faits, "r": reference}, DICTIONNAIRE, [_existence()])
    ligne = resultat.lignes.iloc[0]
    assert (ligne["fichier_reference"], ligne["num_ligne_reference"], ligne["candidates"]) == (
        "r_2025.xlsx", 4, 3,
    )


def test_table_qui_se_prend_pour_reference():
    # La facture d'origine d'un avoir est cherchée dans la même table.
    factures = _table(num=["FA-1", "AV-1", "FA-2"], origine=[None, "FA-1", None])
    regle = _existence(table="e", cle=("origine",), reference="e", cle_reference=["num"],
                       cle_facultative=True)
    resultat = rattacher({"e": factures}, {}, [regle])
    assert _choix(resultat) == [(3, 2, 1, False)]


# --- Résultat ---------------------------------------------------------------------


def test_plusieurs_regles_numerotees_et_decomptes():
    faits = _table(code=["A", "B"])
    reference = _table("r.csv", code=["A"])
    regles = [_existence(), _existence(comparaison="après normalisation")]
    resultat = rattacher({"f": faits, "r": reference}, DICTIONNAIRE, regles)
    assert list(resultat.lignes["regle"]) == [1, 2]
    assert resultat.lignes_par_regle() == {1: 1, 2: 1}
    assert list(resultat.bilan["regle"]) == [1, 2]
    vide = rattacher({"f": faits, "r": reference}, DICTIONNAIRE, [])
    assert vide.lignes.empty and vide.bilan.empty and vide.lignes_par_regle() == {}


def test_problemes_tous_listes_sans_valeur():
    faits = _table(code=["SECRET-1"])
    regles = [_existence(reference="absente"), _periode(cle=("autre",))]
    with pytest.raises(ValueError) as erreur:
        rattacher({"f": faits, "r": _table("r.csv", code=["SECRET-1"])}, {}, regles)
    message = str(erreur.value)
    assert "table absente absente" in message
    assert "colonnes absentes de f autre, jour" in message
    assert "colonnes absentes de r autre, debut, fin" in message
    assert "colonnes de f absentes du dictionnaire jour" in message
    assert "SECRET" not in message


def test_arguments_non_modifies():
    faits = _table(code=["A", "A"], jour=["01/01/2021", None])
    reference = _table("r.csv", code=["A"], debut=["01/01/2020"], fin=[None])
    copies = (faits.copy(), reference.copy())
    regles = [_periode()]
    rattacher({"f": faits, "r": reference}, DICTIONNAIRE, regles)
    pd.testing.assert_frame_equal(faits, copies[0])
    pd.testing.assert_frame_equal(reference, copies[1])
    assert regles == [_periode()]
