"""Tests de la table des anomalies (frigeo.anomalies)."""

import pandas as pd
import pytest

from frigeo.anomalies import (
    COLONNES_ANOMALIES,
    COLONNES_BILAN_ANOMALIES,
    COLONNES_NON_DECLAREES,
    COLONNES_NON_QUALIFIES,
    REGLE_CLE_UNIQUE,
    REGLE_HORS_CLE,
    REGLE_LIGNES_DIFFERENTES,
    REGLE_PRESUME_UNIQUE,
    REGLE_VALEURS_UNIQUES,
    anomalies_non_masquees,
    avertissements_qualification,
    bilan_controles,
    charger_qualification,
    colonnes_non_declarees,
    problemes_qualification,
    qualifier,
    reunir_anomalies,
)
from frigeo.controles import COLONNES_BILAN, COLONNES_ECARTS, VALEUR_MASQUEE
from frigeo.doublons import COLONNES_BILAN_DOUBLONS, COLONNES_DOUBLONS, detecter_doublons
from frigeo.gestion import COLONNES_BILAN_GESTION, COLONNES_ECARTS_GESTION, controler_gestion

AUCUNE_SENSIBLE = {}
DECLARATIONS = {"t": {"cle": ["id"], "unique": [["siret"]], "presume_unique": [["nom"]]}}


def _table(fichier="t.csv", periode="2025", premiere_ligne=2, **colonnes) -> pd.DataFrame:
    """Table fictive avec son lignage et sa période d'export."""
    nombre = len(next(iter(colonnes.values())))
    donnees = pd.DataFrame(colonnes, dtype=object)
    donnees.insert(0, "periode_export", periode)
    donnees.insert(0, "num_ligne_source", range(premiere_ligne, premiere_ligne + nombre))
    donnees.insert(0, "feuille_source", None)
    donnees.insert(0, "fichier_source", fichier)
    return donnees


def _tables():
    """Table « t » sur deux exports, et un référentiel « r » sans clé déclarée."""
    t = pd.concat(
        [
            _table("t_2025.csv", "2025", id=["A1", "A2", "A3"], siret=["1", "2", "2"],
                   nom=["x", "y", "y"], d=["01/01/2025", "bad", "03/01/2025"]),
            _table("t_2026-01.csv", "2026-01", id=["B1", "B2"], siret=["3", "4"],
                   nom=["z", "w"], d=["01/01/2026", ""]),
        ],
        ignore_index=True,
    )
    r = _table("r.csv", None, code=["R1", "R2"])
    return {"t": t, "r": r}


def _frame(lignes, colonnes):
    return pd.DataFrame([dict(zip(colonnes, ligne)) for ligne in lignes], columns=list(colonnes))


def _ecart(fichier, ligne, colonne="d", regle="nature", issue="anomalie", constat="hors nature",
           valeur="bad", table="t", en_vigueur="date JJ/MM/AAAA", statut="observé"):
    return (table, fichier, None, ligne, colonne, regle, en_vigueur, statut, issue, constat, valeur)


def _ligne_bilan(table="t", colonne="d", regle="nature", en_vigueur="date JJ/MM/AAAA",
                 statut="observé", controlees=4, anomalies=1, a_arbitrer=0):
    return (table, colonne, regle, en_vigueur, statut, controlees, anomalies, a_arbitrer, 0)


def _doublon(fichier, ligne, constat="valeur en double", colonnes="siret", issue="anomalie",
             groupe=1, cle="A2", valeur="2", table="t", portee="même fichier"):
    return (table, fichier, None, ligne, constat, colonnes, issue, portee, "telle quelle",
            groupe, 2, cle, valeur)


def _ligne_bilan_doublons(constat="valeur en double", colonnes="siret", issue="anomalie",
                          comparees=5, table="t"):
    return (table, constat, colonnes, issue, comparees, 1, 2, 1, 0, 0)


def _gestion(fichier, ligne, ref="R01", libelle="Règle un", constat="écart", issue="anomalie",
             cle="A1", valeur="v", proposition=None, colonnes="d", type_regle="plage", table="t"):
    return (table, fichier, None, ligne, ref, type_regle, libelle, issue, constat, colonnes,
            cle, valeur, proposition)


def _ligne_bilan_gestion(ref="R01", libelle="Règle un", controlees=5, type_regle="plage",
                         colonnes="d", table="t"):
    return (ref, type_regle, libelle, table, colonnes, "toutes les lignes", None, 5, 0, 0,
            5 - controlees, controlees, 0, 0, 0, None)


def _sources(ecarts=(), bilan=(), doublons=(), bilan_doublons=(), gestion=(), bilan_gestion=()):
    return dict(
        ecarts=_frame(ecarts, COLONNES_ECARTS),
        doublons=_frame(doublons, COLONNES_DOUBLONS),
        ecarts_gestion=_frame(gestion, COLONNES_ECARTS_GESTION),
        bilan=_frame(bilan, COLONNES_BILAN),
        bilan_doublons=_frame(bilan_doublons, COLONNES_BILAN_DOUBLONS),
        bilan_gestion=_frame(bilan_gestion, COLONNES_BILAN_GESTION),
    )


def _reunir(sources, tables=None, declarations=DECLARATIONS, sensibles=AUCUNE_SENSIBLE):
    return reunir_anomalies(
        _tables() if tables is None else tables,
        declarations=declarations,
        sensibles=sensibles,
        **sources,
    )


def _bilan(sources, anomalies, declarations=DECLARATIONS):
    return bilan_controles(
        sources["bilan"], sources["bilan_doublons"], sources["bilan_gestion"], anomalies,
        declarations,
    )


def _lignes(table, *colonnes):
    return [
        tuple(None if pd.isna(v) else v for v in ligne)
        for ligne in table[list(colonnes)].itertuples(index=False)
    ]


def _exemple():
    return _sources(
        ecarts=[
            _ecart("t_2025.csv", 3),
            _ecart("t_2026-01.csv", 3, regle="obligatoire", en_vigueur="obligatoire",
                   constat="vide", valeur=None, statut="valide"),
            _ecart("r.csv", 2, table="r", colonne="code", regle="decimales", en_vigueur="2",
                   constat="trop de décimales", valeur="R1", statut="documenté"),
        ],
        bilan=[
            _ligne_bilan(),
            _ligne_bilan(regle="obligatoire", en_vigueur="obligatoire", statut="valide"),
            _ligne_bilan(table="r", colonne="code", regle="decimales", en_vigueur="2",
                         statut="documenté", controlees=2),
        ],
        doublons=[
            _doublon("t_2025.csv", 3),
            _doublon("t_2025.csv", 4, cle="A3"),
            _doublon("t_2025.csv", 3, constat="valeur en double", colonnes="nom",
                     issue="à arbitrer", valeur="y"),
            _doublon("t_2025.csv", 4, constat="valeur en double", colonnes="nom",
                     issue="à arbitrer", cle="A3", valeur="y"),
        ],
        bilan_doublons=[
            _ligne_bilan_doublons(constat="doublon exact", colonnes="toutes"),
            _ligne_bilan_doublons(colonnes="id"),
            _ligne_bilan_doublons(),
            _ligne_bilan_doublons(colonnes="nom", issue="à arbitrer"),
            _ligne_bilan_doublons(constat="identique hors clé", colonnes="toutes sauf id",
                                  issue="à arbitrer"),
        ],
        gestion=[
            _gestion("t_2025.csv", 2, proposition="2025-01-02"),
            _gestion("t_2025.csv", 2, constat="autre écart", issue="information"),
            _gestion(None, None, ref="R15", libelle="Totaux", constat="total différent",
                     cle="2025", type_regle="totaux_par_periode"),
            _gestion(None, None, ref="R15", libelle="Totaux", constat="total différent",
                     cle="2026-01", type_regle="totaux_par_periode"),
        ],
        bilan_gestion=[
            _ligne_bilan_gestion(ref="R15", libelle="Totaux", type_regle="totaux_par_periode"),
            _ligne_bilan_gestion(),
            _ligne_bilan_gestion(ref="R02", libelle="Sans écart"),
        ],
    )


def test_reunion_des_trois_sources():
    anomalies = _reunir(_exemple())
    assert list(anomalies.columns) == list(COLONNES_ANOMALIES)
    assert anomalies["etape"].value_counts().to_dict() == {
        "format": 3, "doublons": 4, "gestion": 4,
    }
    # Format : clé retrouvée par le lignage, période de la ligne, règle en clair.
    assert _lignes(
        anomalies[anomalies["etape"] == "format"],
        "controle", "num_ligne_source", "periode_export", "cle", "champ", "regle",
        "statut_regle",
    ) == [
        ("t.d nature", 3, "2025", "A2", "d", "nature = date JJ/MM/AAAA", "observé"),
        ("t.d obligatoire", 3, "2026-01", "B2", "d", "obligatoire = obligatoire", "valide"),
        ("r.code decimales", 2, None, None, "code", "decimales = 2", "documenté"),
    ]
    # Doublons : règle tirée de la déclaration, détail du groupe.
    doublons = anomalies[anomalies["etape"] == "doublons"]
    assert _lignes(doublons, "controle", "regle", "cle", "periode_export")[0] == (
        "t valeur en double (siret)", REGLE_VALEURS_UNIQUES, "A2", "2025",
    )
    assert doublons["detail"].iloc[0] == "même fichier, telle quelle, groupe 1 de 2 lignes"
    assert set(doublons["regle"]) == {REGLE_VALEURS_UNIQUES, REGLE_PRESUME_UNIQUE}
    # Gestion : proposition reprise, écarts de période sans lignage ni période.
    gestion = anomalies[anomalies["etape"] == "gestion"]
    assert _lignes(gestion, "controle", "num_ligne_source", "periode_export", "cle",
                   "proposition", "regle") == [
        ("R15 Totaux", None, None, "2025", None, "totaux_par_periode"),
        ("R15 Totaux", None, None, "2026-01", None, "totaux_par_periode"),
        ("R01 Règle un", 2, "2025", "A1", "2025-01-02", "plage"),
        ("R01 Règle un", 2, "2025", "A1", None, "plage"),
    ]
    assert anomalies["gravite"].isna().all() and anomalies["indicateurs"].isna().all()


def test_ordre_des_bilans_puis_des_sources():
    sources = _exemple()
    sources["bilan"] = sources["bilan"].iloc[[2, 1, 0]]
    anomalies = _reunir(sources)
    assert list(anomalies["controle"]) == [
        "r.code decimales", "t.d obligatoire", "t.d nature",
        "t valeur en double (siret)", "t valeur en double (siret)",
        "t valeur en double (nom)", "t valeur en double (nom)",
        "R15 Totaux", "R15 Totaux", "R01 Règle un", "R01 Règle un",
    ]
    # Dans un contrôle, l'ordre de la table source est gardé (groupes de doublons à la suite).
    assert list(anomalies["num_ligne_source"].iloc[3:7]) == [3, 4, 3, 4]


def test_regles_des_doublons():
    sources = _sources(
        doublons=[
            _doublon("t_2025.csv", 3, constat="doublon exact", colonnes="toutes", valeur=None),
            _doublon("t_2025.csv", 4, constat="valeur en double", colonnes="id"),
            _doublon("t_2025.csv", 2, constat="identique hors clé", colonnes="toutes sauf id",
                     issue="à arbitrer", valeur=None),
        ],
        bilan_doublons=[
            _ligne_bilan_doublons(constat="doublon exact", colonnes="toutes"),
            _ligne_bilan_doublons(colonnes="id"),
            _ligne_bilan_doublons(constat="identique hors clé", colonnes="toutes sauf id",
                                  issue="à arbitrer"),
        ],
    )
    assert list(_reunir(sources)["regle"]) == [
        REGLE_LIGNES_DIFFERENTES, REGLE_CLE_UNIQUE, REGLE_HORS_CLE,
    ]


def test_cle_masquee_ou_absente():
    sources = _sources(
        ecarts=[_ecart("t_2025.csv", 2), _ecart("r.csv", 2, table="r", colonne="code")],
        bilan=[_ligne_bilan(), _ligne_bilan(table="r", colonne="code")],
    )
    anomalies = _reunir(sources, sensibles={"t": frozenset({"id"})})
    assert _lignes(anomalies, "cle") == [(VALEUR_MASQUEE,), (None,)]
    # Clé en plusieurs colonnes, reliées comme pour les doublons.
    anomalies = _reunir(sources, declarations={"t": {"cle": ["id", "nom"]}})
    assert _lignes(anomalies, "cle") == [("A1 | x",), (None,)]
    # Ligne introuvable (lignage inconnu) : ni clé ni période, sans erreur.
    sources["ecarts"].loc[0, "num_ligne_source"] = 99
    anomalies = _reunir(sources)
    assert _lignes(anomalies, "cle", "periode_export")[0] == (None, None)


def test_identifiant_stable_et_unique():
    sources = _exemple()
    premier = _reunir(sources)
    assert premier["id_anomalie"].str.fullmatch(r"[0-9a-f]{12}").all()
    assert premier["id_anomalie"].is_unique
    assert list(_reunir(sources)["id_anomalie"]) == list(premier["id_anomalie"])
    # Un écart de plus ne change pas les identifiants des autres.
    sources["ecarts"] = pd.concat(
        [_frame([_ecart("t_2025.csv", 2)], COLONNES_ECARTS), sources["ecarts"]],
        ignore_index=True,
    )
    second = _reunir(sources)
    assert set(premier["id_anomalie"]) < set(second["id_anomalie"])
    # La valeur constatée n'entre pas dans l'identifiant, le constat et le contrôle si.
    sources = _exemple()
    sources["ecarts"].loc[0, "valeur"] = "autre"
    assert list(_reunir(sources)["id_anomalie"]) == list(premier["id_anomalie"])
    sources["ecarts"].loc[0, "constat"] = "autre constat"
    assert _reunir(sources)["id_anomalie"].iloc[0] != premier["id_anomalie"].iloc[0]


def test_identifiants_en_double_refuses():
    sources = _sources(
        ecarts=[_ecart("t_2025.csv", 2), _ecart("t_2025.csv", 2, valeur="autre")],
        bilan=[_ligne_bilan()],
    )
    with pytest.raises(ValueError, match="2 lignes partagent leur identifiant"):
        _reunir(sources)


def test_controles_inconnus_ou_en_double_refuses():
    sources = _exemple()
    sources["bilan_gestion"] = sources["bilan_gestion"].iloc[1:]
    with pytest.raises(ValueError, match="absent de son bilan(.|\n)*gestion.. R15 Totaux"):
        _reunir(sources)
    sources = _exemple()
    sources["bilan_gestion"].loc[2, "ref"] = "R01"
    sources["bilan_gestion"].loc[2, "libelle"] = "Règle un"
    with pytest.raises(ValueError, match="Contrôles de même nom(.|\n)*R01 Règle un"):
        _reunir(sources)
    with pytest.raises(ValueError, match="Contrôles de même nom"):
        _bilan(sources, pd.DataFrame(columns=list(COLONNES_ANOMALIES)))


def test_colonnes_des_sources_verifiees():
    sources = _exemple()
    sources["doublons"] = sources["doublons"].drop(columns=["groupe", "cle"])
    with pytest.raises(ValueError, match="table des doublons.. colonnes absentes groupe, cle"):
        _reunir(sources)


def test_bilan_par_controle():
    sources = _exemple()
    sources["ecarts"] = pd.concat(
        [sources["ecarts"], _frame([_ecart("t_2025.csv", 3, regle="obligatoire",
                                           en_vigueur="obligatoire", statut="valide")],
                                   COLONNES_ECARTS)],
        ignore_index=True,
    )
    anomalies = _reunir(sources)
    bilan = _bilan(sources, anomalies)
    assert list(bilan.columns) == list(COLONNES_BILAN_ANOMALIES)
    assert len(bilan) == 3 + 5 + 3
    lignes = {
        ligne.controle: (ligne.controlees, ligne.anomalies, ligne.a_arbitrer, ligne.informations,
                         ligne.taux, ligne.lignes_distinctes)
        for ligne in bilan.itertuples(index=False)
    }
    assert lignes["t.d nature"] == (4, 1, 0, 0, 0.25, 1)
    assert lignes["t.d obligatoire"] == (4, 2, 0, 0, 0.5, 2)
    assert lignes["r.code decimales"] == (2, 1, 0, 0, 0.5, 1)
    assert lignes["t valeur en double (siret)"] == (5, 2, 0, 0, 0.4, 2)
    # Écarts à arbitrer : aucune ligne en anomalie.
    assert lignes["t valeur en double (nom)"] == (5, 0, 2, 0, 0.0, 0)
    assert lignes["t doublon exact (toutes)"] == (5, 0, 0, 0, 0.0, 0)
    # Deux écarts de la même ligne : une seule ligne distincte; information non comptée.
    assert lignes["R01 Règle un"] == (5, 1, 0, 1, 0.2, 1)
    # Total par période : taux vide, aucune ligne distincte.
    assert lignes["R15 Totaux"][:4] == (5, 2, 0, 0)
    assert lignes["R15 Totaux"][4] is None and lignes["R15 Totaux"][5] == 0
    assert lignes["R02 Sans écart"] == (5, 0, 0, 0, 0.0, 0)
    assert bilan["gravite"].isna().all()
    assert list(bilan["regle"].iloc[:3]) == [
        "nature = date JJ/MM/AAAA", "obligatoire = obligatoire", "decimales = 2",
    ]
    # Rien de contrôlé : taux vide.
    sources["bilan_gestion"].loc[2, "controlees"] = 0
    bilan = _bilan(sources, anomalies)
    assert bilan[bilan["controle"] == "R02 Sans écart"]["taux"].iloc[0] is None


def test_comptes_du_bilan_egaux_aux_bilans_sources():
    """Les anomalies et écarts à arbitrer recomptés égalent ceux des contrôles."""
    tables = _tables()
    declarations = DECLARATIONS
    doublons, bilan_doublons = detecter_doublons(tables, declarations, AUCUNE_SENSIBLE)
    regles = [
        {"ref": "decoupage", "libelle": "Date dans la période", "type": "date_dans_periode_export",
         "table": "t", "colonne": "d"},
    ]
    tables["t"].loc[2, "d"] = "03/01/2027"
    ecarts_gestion, bilan_gestion = controler_gestion(
        tables, {"t": {c: {"nature": {"regle": "date JJ/MM/AAAA"}} for c in ["d"]}},
        regles, declarations, doublons, AUCUNE_SENSIBLE,
    )
    sources = _sources()
    sources.update(doublons=doublons, bilan_doublons=bilan_doublons,
                   ecarts_gestion=ecarts_gestion, bilan_gestion=bilan_gestion)
    anomalies = _reunir(sources, tables=tables)
    bilan = _bilan(sources, anomalies)
    gestion = bilan[bilan["etape"] == "gestion"]
    assert list(gestion["anomalies"]) == list(bilan_gestion["anomalies"])
    assert list(gestion["a_arbitrer"]) == list(bilan_gestion["a_arbitrer"]) == [1]
    assert anomalies[anomalies["etape"] == "gestion"]["proposition"].iloc[0] == "03/01/2025"
    par_issue = bilan[bilan["etape"] == "doublons"][["anomalies", "a_arbitrer"]].sum(axis=1)
    assert list(par_issue) == list(bilan_doublons["lignes"])
    assert set(anomalies[anomalies["etape"] == "doublons"]["regle"]) == {
        REGLE_VALEURS_UNIQUES, REGLE_PRESUME_UNIQUE,
    }


def test_controle_du_masquage():
    sources = _exemple()
    sensibles = {"t": frozenset({"d", "id"}), "r": frozenset({"code"})}
    anomalies = _reunir(sources)
    fautives = anomalies_non_masquees(anomalies, sensibles, DECLARATIONS)
    # Toutes visibles : valeur de t.d et de r.code, clé de t (id), écarts de période sur t.d.
    assert len(fautives) == len(anomalies)
    assert anomalies_non_masquees(anomalies, {"r": frozenset({"code"})}, DECLARATIONS)[
        "controle"
    ].tolist() == ["r.code decimales"]
    masquees = anomalies.copy()
    for colonne in ("valeur", "cle", "proposition"):
        masquees[colonne] = masquees[colonne].map(lambda v: None if pd.isna(v) else VALEUR_MASQUEE)
    assert anomalies_non_masquees(masquees, sensibles, DECLARATIONS).empty
    # Colonne d'une table liée, écrite « table.colonne ».
    masquees.loc[masquees["controle"] == "R01 Règle un", "champ"] = "id, r.code"
    masquees.loc[masquees["controle"] == "R01 Règle un", "valeur"] = "visible"
    assert len(anomalies_non_masquees(masquees, {"r": frozenset({"code"})}, DECLARATIONS)) == 2
    assert anomalies_non_masquees(anomalies, AUCUNE_SENSIBLE, DECLARATIONS).empty


def test_sources_vides():
    sources = _sources(bilan=[_ligne_bilan()])
    anomalies = _reunir(sources)
    assert anomalies.empty and list(anomalies.columns) == list(COLONNES_ANOMALIES)
    bilan = _bilan(sources, anomalies)
    assert _lignes(bilan, "controle", "anomalies", "taux") == [("t.d nature", 0, 0.0)]


def test_lignage_complet_et_numero_entier():
    # Une table faite de deux feuilles d'un même fichier : la feuille distingue les lignes.
    t = pd.concat(
        [
            _table("c.xlsx", "2025", id=["F1"], siret=["1"], nom=["x"], d=["a"]).assign(
                feuille_source="Feuille1"
            ),
            _table("c.xlsx", "2026-01", id=["G1"], siret=["2"], nom=["y"], d=["b"]).assign(
                feuille_source="Feuille2"
            ),
        ],
        ignore_index=True,
    )
    # Deux lignes de même lignage dans une table : repère ambigu, ni clé ni période.
    r = pd.concat([_table("r.csv", None, code=["R1"])] * 2, ignore_index=True)
    ecarts = _frame([_ecart("c.xlsx", 2), _ecart("c.xlsx", 2), _ecart("r.csv", 2, table="r",
                                                                      colonne="code")],
                    COLONNES_ECARTS)
    ecarts["feuille_source"] = ["Feuille2", "Feuille1", None]
    ecarts.loc[1, "regle"] = "obligatoire"
    sources = _sources(bilan=[_ligne_bilan(), _ligne_bilan(regle="obligatoire"),
                              _ligne_bilan(table="r", colonne="code")])
    sources["ecarts"] = ecarts
    anomalies = _reunir(sources, tables={"t": t, "r": r},
                        declarations={**DECLARATIONS, "r": {"cle": ["code"]}})
    assert _lignes(anomalies, "feuille_source", "cle", "periode_export") == [
        ("Feuille2", "G1", "2026-01"), ("Feuille1", "F1", "2025"), (None, None, None),
    ]
    # Numéro de ligne entier, même quand la source le donne en flottant (lignes sans lignage).
    anomalies = _reunir(_exemple())
    assert str(anomalies["num_ligne_source"].dtype) == "Int64"
    assert [str(n) for n in anomalies["num_ligne_source"].iloc[:2]] == ["3", "3"]


def test_lignes_distinctes_d_un_controle():
    sources = _sources(
        gestion=[
            _gestion("t_2025.csv", 2, constat="premier"),
            _gestion("t_2025.csv", 2, constat="second"),
            _gestion("t_2025.csv", 3, constat="premier"),
        ],
        bilan_gestion=[_ligne_bilan_gestion()],
    )
    sources["ecarts_gestion"]["num_ligne_source"] = [2.0, 2.0, 3.0]
    anomalies = _reunir(sources)
    bilan = _bilan(sources, anomalies)
    assert _lignes(bilan, "anomalies", "lignes_distinctes") == [(3, 2)]
    assert list(anomalies["periode_export"]) == ["2025", "2025", "2025"]


# Gravité et indicateurs affectés (5c)

QUALIFICATION = {
    "indicateurs": {
        "CA": {},
        "heures": None,
        "coût": {},
        "marge": {"depend_de": ["CA", "coût"]},
        "taux de marge": {"depend_de": ["marge"]},
    },
    "colonnes": {
        "t": {"id": [], "siret": ["CA"], "nom": [], "d": ["heures", "coût"]},
        "r": {"code": []},
    },
}
TOUT_T = "CA, heures, coût, marge, taux de marge"
DE_D = "heures, coût, marge, taux de marge"


def _exemple_5c():
    """Exemple du 5a, avec une règle de gestion sur une table liée et une sans indicateur."""
    sources = _exemple()
    sources["bilan_gestion"] = _frame(
        [
            _ligne_bilan_gestion(ref="R15", libelle="Totaux", type_regle="totaux_par_periode"),
            _ligne_bilan_gestion(),
            _ligne_bilan_gestion(ref="R02", libelle="Sans écart", colonnes="siret, r.code"),
            _ligne_bilan_gestion(ref="R03", libelle="Identifiant", colonnes="id"),
        ],
        COLONNES_BILAN_GESTION,
    )
    return sources


def _qualifier(qualification=QUALIFICATION, sources=None, tables=None):
    sources = _exemple_5c() if sources is None else sources
    anomalies = _reunir(sources)
    bilan = _bilan(sources, anomalies)
    return qualifier(anomalies, bilan, qualification, _tables() if tables is None else tables)


def _par_controle(bilan):
    return {
        controle: (gravite, indicateurs)
        for controle, gravite, indicateurs in _lignes(bilan, "controle", "gravite", "indicateurs")
    }


def _avec(**blocs):
    return {**QUALIFICATION, **blocs}


def test_charger_qualification(tmp_path):
    assert charger_qualification(tmp_path / "absent.yaml") == {}
    vide = tmp_path / "vide.yaml"
    vide.write_text("", encoding="utf-8")
    assert charger_qualification(vide) == {}
    fichier = tmp_path / "anomalies.yaml"
    fichier.write_text(
        "indicateurs:\n  CA: {}\n  marge: {depend_de: [CA]}\n"
        "colonnes:\n  t:\n    d: [CA]\n    nom: []\n"
        "exceptions:\n  - motif: '.* encodage'\n    gravite: mineure\n",
        encoding="utf-8",
    )
    lu = charger_qualification(fichier)
    assert lu["colonnes"] == {"t": {"d": ["CA"], "nom": []}}
    assert lu["exceptions"] == [{"motif": ".* encodage", "gravite": "mineure"}]
    liste = tmp_path / "liste.yaml"
    liste.write_text("- CA\n", encoding="utf-8")
    with pytest.raises(ValueError, match="seules clés"):
        charger_qualification(liste)
    mal_forme = tmp_path / "mal.yaml"
    mal_forme.write_text("indicateur:\n  CA: {}\ncolonnes:\n  t:\n    d: [CB]\n", encoding="utf-8")
    with pytest.raises(ValueError) as erreur:
        charger_qualification(mal_forme)
    assert "clé inconnue indicateur" in str(erreur.value)
    assert "indicateur inconnu CB" in str(erreur.value)


def test_problemes_qualification_tous_listes():
    problemes = problemes_qualification(
        {
            "indicateurs": {
                "CA": {"depend": ["x"]},
                "a": {"depend_de": ["b"]},
                "b": {"depend_de": ["a"]},
                "c": {"depend_de": ["c", "c"]},
                "d": [],
            },
            "colonnes": {"t": {"d": None, "nom": "CA", "id": ["CA", "CB", "CA"]}, "r": ["code"]},
            "exceptions": [
                {"gravite": "majeure"},
                {"controle": "x", "motif": "y", "gravite": "majeure"},
                {"motif": "(", "gravite": "majeure"},
                {"controle": "x", "etape": "cellule", "gravite": "grave"},
                {"controle": "x"},
                {"controle": "x", "indicateur": ["CA"]},
                {"controle": "x", "indicateurs": "CA"},
                "x",
            ],
            "regles": {},
        }
    )
    attendus = [
        "clé inconnue regles",
        "indicateurs, CA : clé inconnue depend",
        "indicateurs, c, depend_de : indicateur répété c",
        "indicateurs, d : un dictionnaire est attendu",
        "dépendance circulaire (a, b, c)",
        "colonnes, t.d : une liste d'indicateurs est attendue",
        "colonnes, t.nom : une liste d'indicateurs est attendue",
        "colonnes, t.id : indicateur inconnu CB",
        "colonnes, t.id : indicateur répété CA",
        "colonnes, r : un dictionnaire colonne vers indicateurs est attendu",
        "exception n° 1 : une clé controle ou une clé motif est attendue",
        "exception n° 2 : une clé controle ou une clé motif est attendue",
        "exception n° 3 : expression régulière invalide",
        "exception n° 4 : étape inconnue 'cellule'",
        "exception n° 4 : gravité inconnue 'grave'",
        "exception n° 5 : une gravite ou des indicateurs sont attendus",
        "exception n° 6 : clé inconnue indicateur",
        "exception n° 7 : une liste d'indicateurs est attendue",
        "exception n° 8 : un dictionnaire est attendu",
    ]
    texte = "\n".join(problemes)
    for attendu in attendus:
        assert attendu in texte, attendu
    assert problemes_qualification(QUALIFICATION) == []
    assert problemes_qualification({}) == []
    assert problemes_qualification({"indicateurs": None, "colonnes": None}) == []


def test_tables_et_colonnes_confrontees_aux_donnees():
    qualification = _avec(
        colonnes={"t": {"d": [], "inconnue": [], "periode_export": []}, "absente": {"x": []}}
    )
    texte = "\n".join(problemes_qualification(qualification, _tables()))
    assert "colonnes : colonne t.inconnue absente des données chargées" in texte
    assert "colonnes : colonne t.periode_export absente des données chargées" in texte
    assert "colonnes : table absente absente des données chargées" in texte
    assert "t.d" not in texte
    with pytest.raises(ValueError, match="t.inconnue"):
        _qualifier(qualification)


def test_indicateurs_et_gravite_par_defaut():
    anomalies, bilan, non_qualifies = _qualifier()
    assert non_qualifies.empty
    assert list(non_qualifies.columns) == list(COLONNES_NON_QUALIFIES)
    assert list(bilan.columns) == list(COLONNES_BILAN_ANOMALIES)
    assert list(anomalies.columns) == list(COLONNES_ANOMALIES)
    assert _par_controle(bilan) == {
        "t.d nature": ("majeure", DE_D),
        "t.d obligatoire": ("majeure", DE_D),
        "r.code decimales": ("mineure", None),
        # Un doublon affecte toute sa table, quelles que soient les colonnes comparées.
        "t doublon exact (toutes)": ("majeure", TOUT_T),
        "t valeur en double (id)": ("majeure", TOUT_T),
        "t valeur en double (siret)": ("majeure", TOUT_T),
        "t valeur en double (nom)": ("majeure", TOUT_T),
        "t identique hors clé (toutes sauf id)": ("majeure", TOUT_T),
        "R15 Totaux": ("majeure", DE_D),
        "R01 Règle un": ("majeure", DE_D),
        # Colonne d'une table liée : « r.code » désigne la colonne code de r.
        "R02 Sans écart": ("majeure", "CA, marge, taux de marge"),
        "R03 Identifiant": ("mineure", None),
    }


def test_doublons_d_une_table_sans_indicateur():
    qualification = _avec(colonnes={"t": {"id": [], "siret": [], "nom": [], "d": []},
                                     "r": {"code": ["heures"]}})
    _, bilan, _ = _qualifier(qualification)
    gravites = _par_controle(bilan)
    assert gravites["t valeur en double (siret)"] == ("mineure", None)
    assert gravites["r.code decimales"] == ("majeure", "heures")
    assert gravites["R02 Sans écart"] == ("majeure", "heures")


def test_lignes_des_anomalies_et_issues():
    anomalies, _, _ = _qualifier()
    lignes = _lignes(anomalies, "controle", "issue", "gravite", "indicateurs")
    assert ("t.d nature", "anomalie", "majeure", DE_D) in lignes
    assert ("r.code decimales", "anomalie", "mineure", None) in lignes
    # Un écart à arbitrer reçoit la gravité qu'il aurait s'il était confirmé.
    assert ("t valeur en double (nom)", "à arbitrer", "majeure", TOUT_T) in lignes
    # Une information n'est pas une anomalie : ni gravité ni indicateurs.
    assert ("R01 Règle un", "information", None, None) in lignes
    assert ("R01 Règle un", "anomalie", "majeure", DE_D) in lignes
    assert [ligne for ligne in lignes if ligne[0] == "R15 Totaux"] == [
        ("R15 Totaux", "anomalie", "majeure", DE_D)
    ] * 2


def test_exceptions():
    qualification = _avec(
        exceptions=[
            {"controle": "t.d nature", "gravite": "bloquante"},
            # Les indicateurs d'une exception remplacent ceux des colonnes, et la
            # gravité par défaut suit les nouveaux indicateurs.
            {"motif": "t valeur en double .*", "indicateurs": []},
            {"motif": "R0[12] .*", "indicateurs": ["CA"]},
            # Restreinte à une étape : ne touche pas « t.d obligatoire ».
            {"motif": ".* obligatoire", "etape": "gestion", "gravite": "mineure"},
            # Le motif doit couvrir tout le nom du contrôle.
            {"motif": "r.code", "gravite": "bloquante"},
            {"motif": "R03 .*", "indicateurs": ["coût"], "gravite": "mineure"},
        ]
    )
    anomalies, bilan, _ = _qualifier(qualification)
    gravites = _par_controle(bilan)
    assert gravites["t.d nature"] == ("bloquante", DE_D)
    assert gravites["t.d obligatoire"] == ("majeure", DE_D)
    assert gravites["t valeur en double (siret)"] == ("mineure", None)
    assert gravites["t doublon exact (toutes)"] == ("majeure", TOUT_T)
    assert gravites["R01 Règle un"] == ("majeure", "CA, marge, taux de marge")
    assert gravites["R02 Sans écart"] == ("majeure", "CA, marge, taux de marge")
    assert gravites["r.code decimales"] == ("mineure", None)
    assert gravites["R03 Identifiant"] == ("mineure", "coût, marge, taux de marge")
    assert ("t.d nature", "bloquante") in _lignes(anomalies, "controle", "gravite")


def test_exceptions_contradictoires_refusees():
    contradictoires = _avec(
        exceptions=[
            {"motif": "t.d .*", "gravite": "bloquante", "indicateurs": ["marge"]},
            {"controle": "t.d nature", "gravite": "bloquante", "indicateurs": ["coût"]},
        ]
    )
    # Mêmes indicateurs une fois complétés de leurs dépendances : pas de contradiction.
    _, bilan, _ = _qualifier(_avec(exceptions=[
        {"motif": "t.d .*", "indicateurs": ["coût", "marge"]},
        {"controle": "t.d nature", "indicateurs": ["coût"]},
    ]))
    assert _par_controle(bilan)["t.d nature"] == ("majeure", "coût, marge, taux de marge")
    with pytest.raises(ValueError) as erreur:
        _qualifier(contradictoires)
    texte = str(erreur.value)
    assert "format : t.d nature, indicateurs différents" in texte
    assert "gravités différentes" not in texte
    with pytest.raises(ValueError, match="gravités différentes"):
        _qualifier(_avec(exceptions=[
            {"motif": "R.*", "gravite": "bloquante"},
            {"controle": "R15 Totaux", "gravite": "mineure"},
        ]))


def test_controles_non_qualifies():
    qualification = _avec(
        colonnes={"t": {"siret": ["CA"], "d": ["heures"]}},
        exceptions=[
            {"controle": "R03 Identifiant", "indicateurs": []},
            {"controle": "r.code decimales", "gravite": "bloquante"},
        ],
    )
    anomalies, bilan, non_qualifies = _qualifier(qualification)
    gravites = _par_controle(bilan)
    assert gravites["t.d nature"] == ("majeure", "heures")
    assert gravites["R03 Identifiant"] == ("mineure", None)
    # Une gravité seule ne qualifie pas : les indicateurs restent inconnus.
    assert gravites["r.code decimales"] == (None, None)
    assert gravites["t doublon exact (toutes)"] == (None, None)
    assert _lignes(non_qualifies, "controle", "colonnes_non_declarees") == [
        ("r.code decimales", "r.code"),
        ("t doublon exact (toutes)", "t.id, t.nom"),
        ("t valeur en double (id)", "t.id, t.nom"),
        ("t valeur en double (siret)", "t.id, t.nom"),
        ("t valeur en double (nom)", "t.id, t.nom"),
        ("t identique hors clé (toutes sauf id)", "t.id, t.nom"),
        ("R02 Sans écart", "r.code"),
    ]
    assert ("r.code decimales", None, None) in _lignes(
        anomalies, "controle", "gravite", "indicateurs"
    )
    _, bilan, non_qualifies = _qualifier({})
    assert bilan["gravite"].isna().all() and bilan["indicateurs"].isna().all()
    assert len(non_qualifies) == len(bilan)
    tables = _tables()
    del tables["r"]
    sources = _exemple_5c()
    sources["bilan_doublons"] = _frame(
        [_ligne_bilan_doublons(table="r", constat="doublon exact", colonnes="toutes")],
        COLONNES_BILAN_DOUBLONS,
    )
    sources["doublons"] = _frame([], COLONNES_DOUBLONS)
    sources["ecarts"] = sources["ecarts"][sources["ecarts"]["table"] == "t"]
    sources["bilan"] = sources["bilan"][sources["bilan"]["table"] == "t"]
    qualification = _avec(colonnes={"t": QUALIFICATION["colonnes"]["t"]})
    anomalies = _reunir(sources, tables=tables)
    _, _, non_qualifies = qualifier(
        anomalies, _bilan(sources, anomalies), qualification, tables
    )
    assert ("r doublon exact (toutes)", "table r absente des données") in _lignes(
        non_qualifies, "controle", "colonnes_non_declarees"
    )


def test_arguments_non_modifies_et_controle_inconnu():
    sources = _exemple_5c()
    anomalies = _reunir(sources)
    bilan = _bilan(sources, anomalies)
    copie_anomalies, copie_bilan = anomalies.copy(), bilan.copy()
    qualification = _avec(exceptions=[{"controle": "t.d nature", "gravite": "bloquante"}])
    qualifier(anomalies, bilan, qualification, _tables())
    pd.testing.assert_frame_equal(anomalies, copie_anomalies)
    pd.testing.assert_frame_equal(bilan, copie_bilan)
    assert qualification["exceptions"] == [{"controle": "t.d nature", "gravite": "bloquante"}]
    with pytest.raises(ValueError, match="R01 Règle un"):
        qualifier(anomalies, bilan[bilan["controle"] != "R01 Règle un"], QUALIFICATION, _tables())
    with pytest.raises(ValueError, match="colonnes absentes gravite"):
        qualifier(anomalies, bilan.drop(columns="gravite"), QUALIFICATION, _tables())


def test_colonnes_non_declarees_et_avertissements():
    qualification = _avec(
        indicateurs={
            **QUALIFICATION["indicateurs"], "délai": {}, "dérivé": {"depend_de": ["délai"]}
        },
        colonnes={"t": {"siret": ["CA"], "d": ["heures"]}},
        exceptions=[
            {"motif": "x.*", "gravite": "mineure"},
            {"controle": "t.d nature", "etape": "gestion", "gravite": "mineure"},
            {"controle": "t.d nature", "indicateurs": ["coût"]},
        ],
    )
    assert _lignes(colonnes_non_declarees(_tables(), qualification), "table", "colonne") == [
        ("t", "id"),
        ("t", "nom"),
        ("r", "code"),
    ]
    assert list(colonnes_non_declarees(_tables(), {}).columns) == list(COLONNES_NON_DECLAREES)
    assert len(colonnes_non_declarees(_tables(), {})) == 5
    _, bilan, _ = _qualifier(qualification)
    messages = avertissements_qualification(bilan, qualification)
    assert messages == [
        "exception n° 1 (x.*) : aucun contrôle désigné",
        "exception n° 2 (t.d nature) : aucun contrôle désigné",
        "indicateur délai : affecté par aucune colonne ni exception",
        "indicateur dérivé : affecté par aucune colonne ni exception",
    ]
    assert avertissements_qualification(bilan, QUALIFICATION) == []


def test_dependances_declarees_avant_leurs_sources():
    qualification = {
        "indicateurs": {
            "taux": {"depend_de": ["marge"]},
            "marge": {"depend_de": ["coût"]},
            "coût": {},
            "CA": {},
        },
        "colonnes": {
            "t": {"id": [], "siret": [], "nom": [], "d": ["coût"]},
            "r": {"code": ["CA"]},
        },
    }
    _, bilan, _ = _qualifier(qualification)
    gravites = _par_controle(bilan)
    # Ordre du catalogue, quel que soit l'ordre des dépendances.
    assert gravites["t.d nature"] == ("majeure", "taux, marge, coût")
    assert gravites["r.code decimales"] == ("majeure", "CA")
