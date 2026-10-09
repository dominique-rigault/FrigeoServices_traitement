"""Tests des contrôles de format et de complétude (frigeo.controles)."""

from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from frigeo.controles import (
    COLONNES_BILAN,
    COLONNES_ECARTS,
    COLONNES_SANS_CONTROLE,
    VALEUR_MASQUEE,
    charger_dictionnaire_enregistre,
    charger_regles_complementaires,
    controler,
    problemes_regles_complementaires,
    regles_sans_controle,
)
from frigeo.dictionnaire import ecrire_dictionnaire

AUCUNE_SENSIBLE = {}


def _regle(regle, statut="observé", proposition=None, motif="motif fictif"):
    return {
        "regle": regle,
        "proposition": regle if proposition is None else proposition,
        "statut": statut,
        "motif": motif,
        "a_arbitrer": {},
        "commentaire": "" if statut != "invalide" else "écartée",
        "revu_le": None if statut == "observé" else "2026-10-08",
    }


def _valeur(valeur, origine="liste proposée", statut="observé", effectif=1, remplacement=None):
    return {
        "valeur": valeur,
        "origine": origine,
        "effectif": effectif,
        "statut": statut,
        "commentaire": "",
        "revu_le": None if statut == "observé" else "2026-10-08",
        "remplacement": remplacement,
    }


def _forme(forme, origine="liste proposée", statut="observé", effectif=1):
    element = _valeur(forme, origine, statut, effectif)
    del element["valeur"], element["remplacement"]
    return {"forme": forme, **element}


def _colonne(obligatoire="facultatif", nature="texte", valeurs=None, formes=None, **regles):
    """Règles d'une colonne : sans contrôle par défaut, sauf ce qui est demandé.

    `valeurs` et `formes` donnent une liste fermée ou des formes fermées au statut
    « observé ». Une règle complète peut être passée par son nom.
    """
    if isinstance(valeurs, dict):
        regle_valeurs = valeurs
    else:
        regle_valeurs = _regle("liste fermée" if valeurs else "aucune")
        regle_valeurs["liste"] = list(valeurs or [])
    regle_format = _regle("formes fermées" if formes else "aucune")
    regle_format["liste"] = list(formes or [])
    colonne = {
        "obligatoire": obligatoire if isinstance(obligatoire, dict) else _regle(obligatoire),
        "nature": nature if isinstance(nature, dict) else _regle(nature),
        "valeurs": regle_valeurs,
        "format": regle_format,
    }
    colonne.update(regles)
    return colonne


def _table(fichier="t.csv", premiere_ligne=2, **colonnes) -> pd.DataFrame:
    """Table fictive avec son lignage, la première ligne de données étant la ligne 2."""
    nombre = len(next(iter(colonnes.values())))
    donnees = pd.DataFrame(colonnes, dtype=object)
    donnees.insert(0, "num_ligne_source", range(premiere_ligne, premiere_ligne + nombre))
    donnees.insert(0, "feuille_source", None)
    donnees.insert(0, "fichier_source", fichier)
    return donnees


def _controler(donnees, colonnes, sensibles=AUCUNE_SENSIBLE, complementaires=None):
    """Contrôle d'une table « t », sans règle complémentaire sauf celles de la table."""
    return controler(
        {"t": donnees},
        {"t": colonnes},
        sensibles,
        {"t": complementaires} if complementaires else {},
    )


def _lignes(ecarts, *colonnes):
    """Écarts réduits à quelques colonnes, sous forme de liste de tuples."""
    return [
        tuple(None if pd.isna(valeur) else valeur for valeur in ligne)
        for ligne in ecarts[list(colonnes)].itertuples(index=False)
    ]


def test_champ_obligatoire_vide_sous_ses_trois_formes():
    donnees = _table(code=["A", None, "", "  ", "B"])
    ecarts, bilan = _controler(donnees, {"code": _colonne(obligatoire="obligatoire")})
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (3, "vide", "anomalie", None),
        (4, "vide", "anomalie", ""),
        (5, "vide", "anomalie", "  "),
    ]
    assert list(ecarts.columns) == list(COLONNES_ECARTS)
    assert list(bilan.columns) == list(COLONNES_BILAN)
    assert bilan.to_dict("records") == [
        {
            "table": "t",
            "colonne": "code",
            "regle": "obligatoire",
            "regle_en_vigueur": "obligatoire",
            "statut_regle": "observé",
            "controlees": 5,
            "anomalies": 3,
            "a_arbitrer": 0,
            "non_revues": 0,
        }
    ]


def test_colonne_toujours_vide_renseignee():
    donnees = _table(devise=[None, "EUR", ""])
    ecarts, bilan = _controler(donnees, {"devise": _colonne(obligatoire="toujours vide")})
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (3, "renseignée", "EUR")
    ]
    assert bilan.loc[0, "controlees"] == 3 and bilan.loc[0, "anomalies"] == 1


def test_regles_sans_controle():
    donnees = _table(a=[None, "x"], b=[None, "12"], c=[None, "x"], d=["1", "x"])
    colonnes = {
        "a": _colonne(obligatoire="facultatif"),
        "b": _colonne(obligatoire="presque toujours vide", nature="à décider"),
        "c": _colonne(obligatoire="à décider"),
        "d": _colonne(
            obligatoire="obligatoire", nature=_regle("aucune", "invalide", "entier (texte)")
        ),
    }
    ecarts, bilan = _controler(donnees, colonnes)
    assert ecarts.empty and list(ecarts.columns) == list(COLONNES_ECARTS)
    assert _lignes(bilan, "colonne", "regle") == [("d", "obligatoire")]

    sans = regles_sans_controle({"t": colonnes})
    assert list(sans.columns) == list(COLONNES_SANS_CONTROLE)
    assert len(sans) + len(bilan) == 4 * len(colonnes)
    a_decider = sans[sans["regle_en_vigueur"] == "à décider"]
    assert _lignes(a_decider, "colonne", "regle") == [("b", "nature"), ("c", "obligatoire")]
    assert ("d", "nature", "aucune", "invalide") in _lignes(
        sans, "colonne", "regle", "regle_en_vigueur", "statut_regle"
    )


def test_nature_date_en_texte():
    donnees = _table(jour=["14/03/2025", "31/02/2025", "2025-03-14", None, "  "])
    ecarts, bilan = _controler(donnees, {"jour": _colonne(nature="date JJ/MM/AAAA")})
    assert _lignes(ecarts, "num_ligne_source", "regle", "constat", "valeur") == [
        (3, "nature", "hors nature", "31/02/2025"),
        (4, "nature", "hors nature", "2025-03-14"),
    ]
    # Les cellules vides ne sont jugées que par la règle obligatoire.
    assert bilan.loc[0, "controlees"] == 3 and bilan.loc[0, "anomalies"] == 2


def test_natures_natives_d_un_fichier_excel():
    donnees = _table(
        montant=[12.5, "12,50", 3, None],
        emis_le=[datetime(2025, 3, 14), "14/03/2025", datetime(2025, 3, 15), None],
    )
    ecarts, _ = _controler(
        donnees,
        {
            "montant": _colonne(nature="nombre natif"),
            "emis_le": _colonne(nature="date native"),
        },
    )
    assert _lignes(ecarts, "num_ligne_source", "colonne", "valeur") == [
        (3, "montant", "12,50"),
        (3, "emis_le", "14/03/2025"),
    ]


def test_nature_decimale_n_admet_pas_un_entier():
    donnees = _table(debit=["12,00", "12", "0,5"])
    ecarts, _ = _controler(donnees, {"debit": _colonne(nature="décimal virgule (texte)")})
    assert _lignes(ecarts, "num_ligne_source", "valeur") == [(3, "12")]


def test_liste_fermee_et_ses_trois_issues():
    liste = [
        _valeur("Rouen", statut="valide"),
        _valeur("Dieppe"),
        _valeur("Evreux", origine="ajoutée", statut="documenté"),
        _valeur("rouen", origine="à arbitrer", statut="invalide", remplacement="Rouen"),
        _valeur("Elbeuf", origine="à arbitrer"),
    ]
    donnees = _table(
        ville=["Rouen", "Dieppe", "Evreux", "rouen", "Elbeuf", "Paris", "Rouen ", None]
    )
    ecarts, bilan = _controler(donnees, {"ville": _colonne(valeurs=liste)})
    assert _lignes(ecarts, "num_ligne_source", "constat", "issue", "valeur") == [
        (5, "valeur invalide", "anomalie", "rouen"),
        (6, "valeur à arbitrer", "à arbitrer", "Elbeuf"),
        (7, "valeur hors liste", "anomalie", "Paris"),
        # Les valeurs sont comparées telles quelles, espaces compris.
        (8, "valeur hors liste", "anomalie", "Rouen "),
    ]
    ligne = bilan.iloc[0]
    assert (ligne["controlees"], ligne["anomalies"], ligne["a_arbitrer"]) == (7, 3, 1)
    # « Dieppe », d'origine « liste proposée » et pas encore revue, est admise.
    assert ligne["non_revues"] == 1


def test_valeurs_d_une_colonne_candidate_declaree_par_le_metier():
    liste = [
        _valeur("CDI", origine="observée", statut="valide"),
        _valeur("Stage", origine="observée"),
    ]
    regle = _regle("liste fermée", "documenté", proposition="aucune")
    regle["liste"] = liste
    donnees = _table(contrat=["CDI", "Stage"])
    ecarts, _ = _controler(donnees, {"contrat": _colonne(valeurs=regle)})
    assert _lignes(ecarts, "num_ligne_source", "issue", "statut_regle") == [
        (3, "à arbitrer", "documenté")
    ]


def test_valeur_native_comparee_par_son_texte():
    donnees = _table(secteur=[27, "76", 14])
    liste = [_valeur("27", statut="valide"), _valeur("76", statut="valide")]
    ecarts, _ = _controler(donnees, {"secteur": _colonne(valeurs=liste)})
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (4, "valeur hors liste", "14")
    ]


def test_formes_fermees_et_leurs_trois_issues():
    formes = [
        _forme("AAA-99999"),
        _forme("AAA99999", origine="à arbitrer", statut="invalide"),
        _forme("AAA-9999", origine="à arbitrer"),
    ]
    donnees = _table(code=["CLI-00412", "CLI00412", "CLI-0041", "cli-00412", "CLI-00413", ""])
    ecarts, bilan = _controler(donnees, {"code": _colonne(formes=formes)})
    assert _lignes(ecarts, "num_ligne_source", "regle", "constat", "issue", "valeur") == [
        (3, "format", "forme invalide", "anomalie", "CLI00412"),
        (4, "format", "forme à arbitrer", "à arbitrer", "CLI-0041"),
        (5, "format", "forme hors liste", "anomalie", "cli-00412"),
    ]
    ligne = bilan.iloc[0]
    assert (ligne["controlees"], ligne["anomalies"], ligne["a_arbitrer"]) == (5, 2, 1)
    assert ligne["non_revues"] == 2


def test_la_regle_en_vigueur_fait_foi_pas_la_proposition():
    ecartee = _regle("aucune", "invalide", proposition="liste fermée")
    ecartee["liste"] = [_valeur("FRN-001"), _valeur("FRN-002", origine="à arbitrer")]
    declaree = _regle("formes fermées", "documenté", proposition="aucune")
    declaree["liste"] = [_forme("AAA-999", origine="observée", statut="valide")]
    donnees = _table(fournisseur=["FRN-001", "FRN-009", "FRN9"])
    ecarts, bilan = _controler(
        donnees, {"fournisseur": _colonne(valeurs=ecartee, format=declaree)}
    )
    # La liste écartée ne contrôle rien, le format déclaré par le métier contrôle.
    assert _lignes(bilan, "regle", "regle_en_vigueur", "statut_regle") == [
        ("format", "formes fermées", "documenté")
    ]
    assert _lignes(ecarts, "num_ligne_source", "constat") == [(4, "forme hors liste")]


def test_regle_donnee_par_le_metier_a_la_place_de_la_proposition():
    colonnes = {
        "duree": _colonne(
            obligatoire=_regle("obligatoire", "documenté", proposition="facultatif"),
            nature=_regle("entier (texte)", "documenté", proposition="à décider"),
        )
    }
    ecarts, _ = _controler(_table(duree=["95", None, "1h30"]), colonnes)
    assert _lignes(ecarts, "num_ligne_source", "regle", "regle_en_vigueur", "statut_regle") == [
        (3, "obligatoire", "obligatoire", "documenté"),
        (4, "nature", "entier (texte)", "documenté"),
    ]


def test_colonne_sensible_valeur_masquee():
    donnees = _table(
        salaire=["2460,00", "abc", None], motif=["Retraite", "Licenciement", "Retraite"]
    )
    regle = _regle("liste fermée", "documenté", proposition="aucune", motif="colonne sensible")
    regle["liste"] = [_valeur("Retraite", origine="ajoutée", statut="documenté", effectif=None)]
    regle_format = _regle("aucune", motif="colonne sensible")
    regle_format["liste"] = []
    colonnes = {
        "salaire": _colonne(obligatoire="obligatoire", nature="décimal virgule (texte)"),
        "motif": _colonne(valeurs=regle, format=regle_format),
    }
    ecarts, bilan = _controler(donnees, colonnes, {"t": frozenset({"salaire", "motif"})})
    assert _lignes(ecarts, "num_ligne_source", "colonne", "constat", "valeur") == [
        (3, "salaire", "hors nature", VALEUR_MASQUEE),
        (3, "motif", "valeur hors liste", VALEUR_MASQUEE),
        (4, "salaire", "vide", VALEUR_MASQUEE),
    ]
    assert bilan["anomalies"].sum() == 3
    # Aucune valeur de ces colonnes ne figure dans la table des écarts.
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}

    # Une colonne que seul le dictionnaire marque comme sensible est masquée aussi.
    ecarts, _ = _controler(donnees, colonnes, {"t": frozenset({"salaire"})})
    assert set(ecarts["valeur"]) == {VALEUR_MASQUEE}


def test_les_lignes_d_une_meme_cellule_se_suivent():
    liste = [_valeur("1", statut="valide")]
    formes = [_forme("9", statut="valide")]
    colonnes = {
        "x": _colonne(obligatoire="obligatoire", nature="entier (texte)"),
        "y": _colonne(nature="entier (texte)", valeurs=liste, formes=formes),
    }
    donnees = pd.concat(
        [
            _table("b.csv", x=["1", "k"], y=["1", "zz"]),
            _table("a.csv", x=["", "2"], y=["zz", "1"]),
        ],
        ignore_index=True,
    )
    ecarts, _ = _controler(donnees, colonnes)
    # Tri par fichier, puis ligne, puis colonne dans l'ordre de la table, puis règle
    # dans l'ordre obligatoire, nature, valeurs, format.
    assert _lignes(ecarts, "fichier_source", "num_ligne_source", "colonne", "regle") == [
        ("a.csv", 2, "x", "obligatoire"),
        ("a.csv", 2, "y", "nature"),
        ("a.csv", 2, "y", "valeurs"),
        ("a.csv", 2, "y", "format"),
        ("b.csv", 3, "x", "nature"),
        ("b.csv", 3, "y", "nature"),
        ("b.csv", 3, "y", "valeurs"),
        ("b.csv", 3, "y", "format"),
    ]
    cellules = list(zip(ecarts["fichier_source"], ecarts["num_ligne_source"], ecarts["colonne"]))
    groupes = [c for rang, c in enumerate(cellules) if rang == 0 or c != cellules[rang - 1]]
    assert len(groupes) == len(set(cellules))


def test_tables_dans_l_ordre_du_dictionnaire_et_feuille_source():
    premiere = _table("classeur.xlsx", code=[None])
    premiere["feuille_source"] = "Lignes"
    seconde = _table("autre.csv", code=[None])
    colonnes = {"code": _colonne(obligatoire="obligatoire")}
    ecarts, _ = controler(
        {"zebre": premiere, "abeille": seconde},
        {"zebre": colonnes, "abeille": deepcopy(colonnes)},
        AUCUNE_SENSIBLE,
        {},
    )
    assert _lignes(ecarts, "table", "fichier_source", "feuille_source") == [
        ("zebre", "classeur.xlsx", "Lignes"),
        ("abeille", "autre.csv", None),
    ]


def test_table_sans_lignage_et_index_quelconque():
    donnees = pd.DataFrame({"code": ["A", None, None]}, dtype=object, index=[7, 7, 3])
    ecarts, bilan = _controler(donnees, {"code": _colonne(obligatoire="obligatoire")})
    assert len(ecarts) == 2 and bilan.loc[0, "controlees"] == 3
    assert ecarts["fichier_source"].isna().all() and ecarts["num_ligne_source"].isna().all()


def test_les_arguments_ne_sont_pas_modifies():
    donnees = _table(ville=["Rouen", "Paris", None])
    colonnes = {"ville": _colonne(obligatoire="obligatoire", valeurs=[_valeur("Rouen")])}
    tables, dictionnaire = {"t": donnees}, {"t": colonnes}
    avant_tables, avant_dictionnaire = donnees.copy(deep=True), deepcopy(dictionnaire)
    complementaires = {"t": {"ville": {"motif": "[A-Z].*"}}}
    avant_complementaires = deepcopy(complementaires)
    controler(tables, dictionnaire, AUCUNE_SENSIBLE, complementaires)
    assert complementaires == avant_complementaires
    pd.testing.assert_frame_equal(tables["t"], avant_tables)
    assert dictionnaire == avant_dictionnaire


def test_dictionnaire_qui_ne_decrit_pas_les_donnees():
    tables = {"t": _table(a=["x"], nouvelle=["y"]), "inconnue": _table(a=["x"])}
    dictionnaire = {
        "t": {"a": _colonne(), "disparue": _colonne()},
        "absente": {"a": _colonne()},
    }
    with pytest.raises(ValueError) as erreur:
        controler(tables, dictionnaire, AUCUNE_SENSIBLE, {})
    message = str(erreur.value)
    assert "02c_dictionnaire" in message
    for attendu in (
        "table inconnue absente du dictionnaire",
        "table absente absente des données chargées",
        "colonne t.nouvelle absente du dictionnaire",
        "colonne t.disparue absente des données chargées",
    ):
        assert attendu in message


def test_regle_inconnue_et_dictionnaire_invalide():
    donnees = _table(a=["x"])
    with pytest.raises(ValueError, match="inconnue des contrôles"):
        _controler(donnees, {"a": _colonne(nature="date fantaisiste")})
    with pytest.raises(ValueError, match="Dictionnaire invalide"):
        _controler(donnees, {"a": _colonne(obligatoire=_regle("obligatoire", "approuvé"))})


def test_classification_de_sensibilite_incoherente():
    with pytest.raises(RuntimeError, match="sensibilité incohérente"):
        _controler(_table(a=["x"]), {"a": _colonne()}, {"t": frozenset({"salaire"})})


def test_dictionnaire_absent_renvoie_au_notebook(tmp_path):
    with pytest.raises(FileNotFoundError, match="02c_dictionnaire"):
        charger_dictionnaire_enregistre(tmp_path / "dictionnaire.yaml")


def test_dictionnaire_enregistre_relu(tmp_path):
    dictionnaire = {"t": {"a": _colonne(obligatoire="obligatoire")}}
    chemin = ecrire_dictionnaire(dictionnaire, "2026-03", tmp_path / "dictionnaire.yaml")
    assert charger_dictionnaire_enregistre(chemin) == dictionnaire


def test_decimales_sur_des_textes_et_des_nombres_natifs():
    donnees = _table(
        montant=["12,50", "12,505", "12.5", "12", "12,500", "abc", None],
        natif=[12.5, 12.505, 181.45000000000002, 3, "12,505", "abc", None],
    )
    ecarts, bilan = _controler(
        donnees,
        {"montant": _colonne(), "natif": _colonne()},
        complementaires={"montant": {"decimales": 2}, "natif": {"decimales": 2}},
    )
    assert _lignes(ecarts, "num_ligne_source", "colonne", "regle", "constat", "valeur") == [
        (3, "montant", "decimales", "trop de décimales", "12,505"),
        (3, "natif", "decimales", "trop de décimales", "12.505"),
        (6, "natif", "decimales", "trop de décimales", "12,505"),
    ]
    # Une valeur qui n'est pas un nombre n'est pas évaluable : la règle nature la signale.
    assert _lignes(bilan, "colonne", "regle_en_vigueur", "statut_regle", "controlees") == [
        ("montant", "2", "documenté", 5),
        ("natif", "2", "documenté", 5),
    ]
    assert list(bilan["anomalies"]) == [1, 2] and bilan["non_revues"].sum() == 0


def test_bornes_incluses_et_borne_unique():
    donnees = _table(remise=[0, 15, 15.5, -1, "7,5", "16", "x"], quantite=[0, 1, -2, 3, 4, 5, 6])
    ecarts, bilan = _controler(
        donnees,
        {"remise": _colonne(), "quantite": _colonne()},
        complementaires={
            "remise": {"bornes": {"min": 0, "max": 15}},
            "quantite": {"bornes": {"min": 0}},
        },
    )
    assert _lignes(ecarts, "num_ligne_source", "colonne", "constat", "valeur") == [
        (4, "remise", "hors bornes", "15.5"),
        (4, "quantite", "hors bornes", "-2"),
        (5, "remise", "hors bornes", "-1"),
        (7, "remise", "hors bornes", "16"),
    ]
    assert _lignes(bilan, "colonne", "regle_en_vigueur", "controlees") == [
        ("remise", "0 à 15", 6),
        ("quantite", "min 0", 7),
    ]


def test_motif_sur_la_valeur_entiere():
    donnees = _table(nom=["LEROUX", "Leroux", "D'ARC", "DE LA TOUR", "", None])
    ecarts, bilan = _controler(
        donnees, {"nom": _colonne()}, complementaires={"nom": {"motif": "[^a-zà-ÿ]+"}}
    )
    assert _lignes(ecarts, "num_ligne_source", "regle", "constat", "valeur") == [
        (3, "motif", "hors motif", "Leroux")
    ]
    assert bilan.loc[0, "controlees"] == 4 and bilan.loc[0, "regle_en_vigueur"] == "[^a-zà-ÿ]+"


def test_cle_de_luhn_sur_toute_valeur_faite_de_chiffres():
    donnees = _table(
        siret=["73282932000074", "73282932000075", "7328293200007", "732 829", 79927398713]
    )
    ecarts, bilan = _controler(
        donnees, {"siret": _colonne()}, complementaires={"siret": {"cle_luhn": True}}
    )
    # La valeur à espaces n'est pas évaluable : c'est la règle format qui la juge.
    assert _lignes(ecarts, "num_ligne_source", "constat", "valeur") == [
        (3, "clé invalide", "73282932000075"),
        (4, "clé invalide", "7328293200007"),
    ]
    assert bilan.loc[0, "controlees"] == 4 and bilan.loc[0, "regle_en_vigueur"] == "oui"


def test_regles_complementaires_apres_celles_du_dictionnaire_et_masquage():
    donnees = _table(salaire=["2460,005", None, "abc"])
    colonnes = {"salaire": _colonne(obligatoire="obligatoire", nature="décimal virgule (texte)")}
    ecarts, bilan = _controler(
        donnees,
        colonnes,
        {"t": frozenset({"salaire"})},
        {"salaire": {"cle_luhn": True, "bornes": {"max": 2000}, "decimales": 2}},
    )
    assert _lignes(ecarts, "num_ligne_source", "regle", "valeur") == [
        (2, "decimales", VALEUR_MASQUEE),
        (2, "bornes", VALEUR_MASQUEE),
        (3, "obligatoire", VALEUR_MASQUEE),
        (4, "nature", VALEUR_MASQUEE),
    ]
    # Ordre du bilan : règles du dictionnaire, puis décimales, bornes, motif, clé de Luhn.
    assert list(bilan["regle"]) == ["obligatoire", "nature", "decimales", "bornes", "cle_luhn"]
    assert list(bilan["controlees"]) == [3, 2, 1, 1, 0]


def test_regles_complementaires_sur_une_table_ou_une_colonne_inconnue():
    with pytest.raises(ValueError) as erreur:
        controler(
            {"t": _table(a=["x"])},
            {"t": {"a": _colonne()}},
            AUCUNE_SENSIBLE,
            {"t": {"b": {"decimales": 2}}, "u": {"a": {"decimales": 2}}},
        )
    message = str(erreur.value)
    assert "colonne t.b absente des données chargées" in message
    assert "table u absente des données chargées" in message


def test_problemes_des_regles_complementaires_listes_en_une_fois():
    regles = {
        "t": {
            "a": {"decimales": -1, "arrondi": 2},
            "b": {"bornes": {"min": 5, "max": 1}},
            "c": {"bornes": {"entre": 1}},
            "d": {"motif": "[a-"},
            "e": {"cle_luhn": False},
            "f": {"decimales": True},
            "g": {},
        },
        "u": [],
    }
    problemes = problemes_regles_complementaires(regles)
    assert len(problemes) == 9
    texte = "\n".join(problemes)
    for attendu in (
        "t.a, règle decimales",
        "règle inconnue 'arrondi'",
        "le minimum dépasse le maximum",
        "t.c, règle bornes",
        "expression régulière invalide",
        "retirer la ligne",
        "t.f, règle decimales",
        "t.g : au moins une règle",
        "u : un dictionnaire de colonnes",
    ):
        assert attendu in texte
    with pytest.raises(ValueError, match="Règles complémentaires invalides"):
        _controler(_table(a=["x"]), {"a": _colonne()}, complementaires={"a": {"arrondi": 2}})


def test_lecture_des_regles_complementaires(tmp_path):
    chemin = tmp_path / "controles.yaml"
    assert charger_regles_complementaires(chemin) == {}
    chemin.write_text(
        "regles:\n"
        "  clients:\n"
        "    siret: {cle_luhn: true}\n"
        "  factures_lignes:\n"
        "    remise_pct:\n"
        "      bornes: {min: 0, max: 15}\n"
        "    montant_ht:\n"
        "      decimales: 2\n",
        encoding="utf-8",
    )
    assert charger_regles_complementaires(chemin) == {
        "clients": {"siret": {"cle_luhn": True}},
        "factures_lignes": {
            "remise_pct": {"bornes": {"min": 0, "max": 15}},
            "montant_ht": {"decimales": 2},
        },
    }
    chemin.write_text("regles:\n", encoding="utf-8")
    assert charger_regles_complementaires(chemin) == {}
    chemin.write_text("controles: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="seule clé attendue"):
        charger_regles_complementaires(chemin)
    chemin.write_text("regles:\n  clients:\n    siret: {luhn: true}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="règle inconnue 'luhn'"):
        charger_regles_complementaires(chemin)
