"""Tests du formulaire des règles de gestion (frigeo.formulaire_gestion)."""

import datetime as dt

import pandas as pd
import pytest
from openpyxl import load_workbook

from frigeo.formulaire_gestion import (
    COLONNES_AUTRES,
    COLONNES_FERIES,
    COLONNES_NOUVELLES,
    COLONNES_PERIODES,
    COLONNES_REFERENCES,
    COLONNES_RENSEIGNEMENT,
    FEUILLE_AUTRES,
    FEUILLE_FERIES,
    FEUILLE_MODE_EMPLOI,
    FEUILLE_NOUVELLES,
    FEUILLE_PERIODES,
    FEUILLE_REFERENCES,
    FEUILLE_RENSEIGNEMENT,
    REPERE_EMPREINTE,
    _seuil_atteint,
    annees_des_exports,
    cibles_references,
    empreinte_gestion,
    exporter_formulaire_gestion,
    feries_france,
    lignes_autres,
    lignes_feries,
    lignes_minimales,
    lignes_nouvelles,
    lignes_periodes,
    lignes_references,
    lignes_renseignement,
    problemes_contenu_formulaire,
    proposer_renseignement,
    texte_parametres,
)
from frigeo.gestion import lire_fichier_gestion

J = dt.date


def _export(periodes, **colonnes):
    return pd.DataFrame({"periode_export": periodes, **colonnes}, dtype=object)


def _tables():
    """Un export « t » (six dates par colonne) et un référentiel « r »."""
    return {
        "t": _export(
            ["2025"] * 5 + ["2026-01"],
            d=["01/02/2025"] * 5 + ["05/01/2026"],
            e=["01/02/2025"] * 5 + ["05/01/2026"],
            f=["01/02/2025"] * 4 + ["01/02/2052", "05/01/2026"],
            g=["01/02/2025"] * 6,
            h=["01/02/2025", "", "x", None, "01/03/2025", "05/01/2026"],
            n=["1"] * 6,
        ),
        "r": pd.DataFrame({"code": ["A"], "debut": ["01/01/2020"]}, dtype=object),
    }


def _dictionnaire():
    date = {"nature": {"regle": "date JJ/MM/AAAA"}}
    return {
        "r": {"code": {"nature": {"regle": "texte"}}, "debut": date},
        "t": {c: date for c in "defgh"} | {"n": {"nature": {"regle": "entier (texte)"}}},
    }


def _periode(colonne, ref="decoupage", **autres):
    return {"ref": ref, "libelle": f"{colonne} dans la période", "type":
            "date_dans_periode_export", "table": "t", "colonne": colonne, **autres}


def _contenu():
    return {
        "jours_feries": {2025: ["2025-01-01", "2025-12-26"]},
        "regles": [
            _periode("d", issue="anomalie", commentaire="Vu avec le métier"),
            {"ref": "R22", "libelle": "Distance", "type": "plage", "table": "t",
             "colonne": "n", "min": 2, "max": 120},
            _periode("d", ref="autre", filtre=[{"colonne": "n", "valeurs": ["1", "2"]}]),
            _periode("e", filtre=[{"colonne": "n", "motif": "1.*"}]),
            _periode("d", filtre=[{"colonne": "n", "valeurs": ["1"]},
                                  {"colonne": "e", "valeurs": ["x"]}]),
        ],
        "retirees": [_periode("h", libelle="Date h retirée")],
        "ecartees": {
            "periodes_export": [{"table": "t", "colonne": "g"}],
            "jours_feries": {2025: ["2025-05-08"]},
        },
        "demandes": [{"regle": "Un avoir suit sa facture", "tables": "factures",
                      "issue": "à arbitrer"}],
    }


def test_feries_france():
    assert list(feries_france(2025)) == [
        J(2025, 1, 1), J(2025, 4, 21), J(2025, 5, 1), J(2025, 5, 8), J(2025, 5, 29),
        J(2025, 6, 9), J(2025, 7, 14), J(2025, 8, 15), J(2025, 11, 1), J(2025, 11, 11),
        J(2025, 12, 25),
    ]
    assert feries_france(2027)[J(2027, 5, 6)] == "Ascension"
    assert list(feries_france(2027))[3:5] == [J(2027, 5, 6), J(2027, 5, 8)]
    # Pâques aux dates extrêmes du calendrier grégorien (22 mars et 25 avril).
    assert feries_france(2285)[J(2285, 3, 23)] == "Lundi de Pâques"
    assert feries_france(2038)[J(2038, 4, 26)] == "Lundi de Pâques"
    assert feries_france(2024)[J(2024, 5, 20)] == "Lundi de Pentecôte"
    # Années où la règle corrige le 26 ou le 25 avril (Pâques le 19 ou le 18 avril).
    assert feries_france(2049)[J(2049, 4, 19)] == "Lundi de Pâques"
    assert feries_france(2076)[J(2076, 4, 20)] == "Lundi de Pâques"
    assert len(feries_france(2026)) == 11


def _reduites(lignes, *colonnes):
    return [tuple(ligne.get(c) for c in colonnes) for ligne in lignes]


def test_lignes_periodes():
    lignes = lignes_periodes(_tables(), _dictionnaire(), _contenu())
    assert _reduites(lignes, "colonne", "origine", "statut", "ref", "issue",
                     "filtre_colonne", "filtre_valeurs", "rang") == [
        ("d", "en vigueur", "documenté", "decoupage", "anomalie", None, None, 0),
        ("d", "en vigueur", "documenté", "autre", "à arbitrer", "n", "1, 2", 2),
        # e a une règle à filtre par motif (feuille des autres règles) : pas de
        # proposition.
        ("f", "proposée", "observé", "decoupage", "à arbitrer", None, None, None),
        ("h", "retirée", "invalide", "decoupage", "à arbitrer", None, None, 0),
        ("g", "écartée", "invalide", "decoupage", "à arbitrer", None, None, None),
    ]
    # Six dates ne suffisent pas à une proposition (seuil compté avec une date de plus).
    assert _reduites(lignes, "colonne", "nature", "dates", "observé", "proposition") == [
        ("d", "date JJ/MM/AAAA", 6, "6 sur 6 dans la période de l'export (100 %)", "aucune"),
        ("d", "date JJ/MM/AAAA", 6, "6 sur 6 dans la période de l'export (100 %)", "aucune"),
        ("f", "date JJ/MM/AAAA", 6, "5 sur 6 dans la période de l'export (83,3 %)",
         "aucune"),
        # Cellules vides ou illisibles non comptées.
        ("h", "date JJ/MM/AAAA", 3, "3 sur 3 dans la période de l'export (100 %)",
         "aucune"),
        ("g", "date JJ/MM/AAAA", 6, "5 sur 6 dans la période de l'export (83,3 %)",
         "aucune"),
    ]
    assert lignes[0]["libellé"] == "d dans la période"
    assert lignes[0]["commentaire"] == "Vu avec le métier"
    assert lignes[2]["libellé"] == "f dans la période de l'export"
    assert all(set(ligne) <= set(COLONNES_PERIODES) for ligne in lignes)
    # Seuil de proposition : 95 % des dates avec une date hors période de plus, sans
    # compter les lignes sans période.
    # La fin de la période est exclue : le 1er janvier 2026 est hors de l'export 2025.
    tables = {"t": _export(["2025", "2025"], d=["31/12/2025", "01/01/2026"])}
    assert lignes_periodes(tables, _dictionnaire(), {})[0]["observé"] == (
        "1 sur 2 dans la période de l'export (50 %)"
    )
    tables = _tables()
    tables["t"]["periode_export"] = ["2025"] * 5 + ["inconnue"]
    lignes = lignes_periodes(tables, _dictionnaire(), {})
    assert _reduites(lignes, "colonne", "dates") == [
        ("d", 5), ("e", 5), ("f", 5), ("g", 5), ("h", 2),
    ]
    for dates, attendu in ((19, "oui"), (18, "aucune")):
        tables = {"t": _export(["2025"] * dates + ["inconnue"], d=["01/02/2025"] * (dates + 1))}
        ligne = lignes_periodes(tables, _dictionnaire(), {})[0]
        assert (ligne["colonne"], ligne["dates"], ligne["proposition"]) == ("d", dates, attendu)
    tables = {"t": _export(["2025"] * 39, d=["01/02/2025"] * 38 + ["01/02/2026"])}
    assert lignes_periodes(tables, _dictionnaire(), {})[0]["proposition"] == "oui"


def test_regle_sur_une_colonne_hors_des_exports():
    contenu = {"regles": [_periode("debut") | {"table": "r"}, _periode("zz")]}
    lignes = lignes_periodes({"r": _tables()["r"]}, _dictionnaire(), contenu)
    assert _reduites(lignes, "table", "colonne", "dates", "observé", "statut") == [
        ("r", "debut", None, None, "documenté"),
        ("t", "zz", None, None, "documenté"),
    ]


def test_annees_et_lignes_feries():
    tables = _tables()
    assert annees_des_exports(tables) == [2025, 2026]
    lignes = lignes_feries(tables, _contenu())
    de_2025 = [ligne for ligne in lignes if ligne["année"] == 2025]
    assert len(de_2025) == 12
    assert _reduites(de_2025[:4], "date", "jour", "fête", "origine", "statut") == [
        (J(2025, 1, 1), "mercredi", "Jour de l'an", "en vigueur", "documenté"),
        (J(2025, 4, 21), "lundi", "Lundi de Pâques", "proposée", "observé"),
        (J(2025, 5, 1), "jeudi", "Fête du travail", "proposée", "observé"),
        (J(2025, 5, 8), "jeudi", "Victoire 1945", "écartée", "invalide"),
    ]
    assert _reduites(de_2025[-2:], "date", "fête", "origine", "statut") == [
        (J(2025, 12, 25), "Noël", "proposée", "observé"),
        (J(2025, 12, 26), None, "en vigueur", "documenté"),
    ]
    de_2026 = [ligne for ligne in lignes if ligne["année"] == 2026]
    assert {ligne["statut"] for ligne in de_2026} == {"observé"}
    assert len(de_2026) == 11
    assert all(set(ligne) == set(COLONNES_FERIES) for ligne in lignes)
    # Une année déclarée ou écartée hors des exports est montrée.
    lignes = lignes_feries(
        {}, {"jours_feries": {2030: []}, "ecartees": {"jours_feries": {2031: ["2031-01-01"]}}}
    )
    assert {ligne["année"] for ligne in lignes} == {2030, 2031}


def test_lignes_autres_et_parametres_en_clair():
    lignes = lignes_autres(_contenu())
    assert _reduites(lignes, "ref", "type", "paramètres", "filtre", "issue", "origine",
                     "statut", "rang") == [
        ("R22", "plage", "colonne = n; min = 2; max = 120", None, "anomalie", "en vigueur",
         "documenté", 1),
        ("decoupage", "date_dans_periode_export", "colonne = e", "n suit le motif 1.*",
         "à arbitrer", "en vigueur", "documenté", 3),
        ("decoupage", "date_dans_periode_export", "colonne = d", "n = 1 et e = x",
         "à arbitrer", "en vigueur", "documenté", 4),
    ]
    assert all(set(ligne) <= set(COLONNES_AUTRES) for ligne in lignes)
    regle = {
        "ref": "x", "libelle": "x", "type": "sans_ligne_liee", "table": "t", "cle": ["a", "b"],
        "table_lignes": "l",
        "filtre_lignes": [{"colonne": "c", "valeurs": ["V"]}, {"colonne": "d", "motif": "M.*"}],
        "exceptions": [{"libelle": "cas normal",
                        "conditions": [{"colonne": "s", "valeurs": ["A", "B"]}]}],
        "issue": "information", "commentaire": "c",
    }
    assert texte_parametres(regle) == (
        "cle = a, b; table_lignes = l; filtre_lignes = c = V et d suit le motif M.*; "
        "exceptions = « cas normal » si s = A ou B"
    )
    regle = {
        "ref": "x", "libelle": "x", "type": "produit_calcule", "table": "t", "cible": "m",
        "facteurs": ["q", {"colonne": "r", "constante": 1, "coefficient": -0.01, "vide": 0}],
        "tolerance": 0.005,
    }
    assert texte_parametres(regle) == (
        "cible = m; facteurs = [q, {colonne: r, constante: 1, coefficient: -0.01, vide: 0}]; "
        "tolerance = 0.005"
    )
    regle = {
        "ref": "x", "libelle": "x", "type": "solde_jamais_negatif", "table": "t",
        "date_initial": dt.date(2025, 1, 1), "hors": True,
    }
    assert texte_parametres(regle) == "date_initial = 2025-01-01; hors = true"


def test_lignes_nouvelles():
    assert lignes_nouvelles(_contenu()) == [
        {"règle": "Un avoir suit sa facture", "tables": "factures", "colonnes": None,
         "tolérance_ou_délai": None, "issue_souhaitée": "à arbitrer", "commentaire": None}
    ]
    assert set(lignes_nouvelles(_contenu())[0]) == set(COLONNES_NOUVELLES)
    assert lignes_nouvelles({}) == []


def test_contenu_lu_et_problemes(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    chemin.write_text(
        "jours_feries: {2025: ['2025-01-01']}\nregles: []\nretirees: []\n"
        "ecartees: {periodes_export: [{table: t, colonne: d}]}\n"
        "demandes: [{regle: Une règle}]\n",
        encoding="utf-8",
    )
    contenu = lire_fichier_gestion(chemin)
    assert problemes_contenu_formulaire(contenu) == []
    contenu = {
        "jours_feries": {2025: ["2026-01-01"]},
        "regles": [_periode("d"), {"ref": "x"}],
        "retirees": [_periode("d", issue="grave")],
        "ecartees": {
            "periodes_export": [{"table": "t"}],
            "jours_feries": {"an": []},
            "autre": [],
        },
        "demandes": [{"regle": " "}, "texte", {"regle": "r", "delai": "3 j", "tables": 2}],
    }
    horaires = {"ref": "R04", "libelle": "h", "type": "hors_horaires_selon_valeur",
                "table": "t", "date": "d", "heure": "h", "colonne": "c", "valeurs": [],
                "horaires": {"lundi": [{"debut": "08:00", "fin": "18:00"}]}}
    contenu["regles"].append(horaires)
    assert problemes_contenu_formulaire(contenu) == [
        "jours_feries : année 2025 : 2026-01-01 n'est pas de cette année",
        "regles, règle n° 2 (x) : clé manquante (libelle, type, table)",
        "regles, règle n° 3 (R04) : paramètre manquant (feries) (les jours fériés peuvent "
        "aussi se déclarer une fois pour le fichier, sous la clé jours_feries)",
        "retirees, règle n° 1 (decoupage), issue : issue inconnue 'grave' "
        "(issues possibles : anomalie, à arbitrer, information)",
        "ecartees, periodes_export : une liste de {table, colonne} (textes) est attendue",
        "ecartees, jours_feries : année 'an' : une année AAAA est attendue",
        "ecartees : famille inconnue 'autre' (familles possibles : references, "
        "renseignement, periodes_export, jours_feries)",
        "demandes, demande n° 1, regle : un texte non vide est attendu",
        "demandes, demande n° 2 : un dictionnaire de clés est attendu",
        "demandes, demande n° 3 : clé inconnue delai (clés possibles : regle, tables, "
        "colonnes, tolerance, issue, commentaire)",
        "demandes, demande n° 3 : des textes sont attendus",
    ]
    contenu = {"ecartees": {
        "references": [{"table": "t", "colonne": "a", "table_reference": "r",
                        "colonne_reference": "b"}],
        "renseignement": [{"table": "t", "colonne": "a", "selon": "b"}],
    }}
    assert problemes_contenu_formulaire(contenu) == []
    contenu = {"ecartees": {
        "references": [{"table": "t", "colonne": "a", "table_reference": "r"}],
        "renseignement": [{"table": "t", "colonne": "a", "selon": ""}],
    }}
    assert problemes_contenu_formulaire(contenu) == [
        "ecartees, references : une liste de {table, colonne, table_reference, "
        "colonne_reference} (textes) est attendue",
        "ecartees, renseignement : une liste de {table, colonne, selon} (textes) est attendue",
    ]
    assert problemes_contenu_formulaire({"ecartees": [], "demandes": {}}) == [
        "ecartees : un dictionnaire par famille est attendu",
        "demandes : une liste est attendue",
    ]


def test_empreinte_gestion(tmp_path):
    chemin = tmp_path / "gestion.yaml"
    assert empreinte_gestion(chemin) == "absent"
    chemin.write_bytes(b"regles:\n  - ref: x\n")
    lf = empreinte_gestion(chemin)
    chemin.write_bytes(b"regles:\r\n  - ref: x\r\n")
    assert empreinte_gestion(chemin) == lf
    chemin.write_bytes(b"regles:\n  - ref: y\n")
    assert empreinte_gestion(chemin) != lf


def _verrouillee(feuille, ligne, nom, colonnes):
    return feuille.cell(row=ligne, column=colonnes.index(nom) + 1).protection.locked


def test_export_du_classeur(tmp_path):
    chemin = tmp_path / "formulaires" / "gestion_2026-03.xlsx"
    assert exporter_formulaire_gestion(
        _tables(), _dictionnaire(), _contenu(), {}, {}, "2026-03", chemin, empreinte="abc123"
    ) == chemin
    classeur = load_workbook(chemin)
    assert classeur.sheetnames == [
        FEUILLE_MODE_EMPLOI, FEUILLE_REFERENCES, FEUILLE_RENSEIGNEMENT, FEUILLE_PERIODES,
        FEUILLE_FERIES, FEUILLE_AUTRES, FEUILLE_NOUVELLES, "listes",
    ]
    assert classeur["listes"].sheet_state == "hidden"
    notice = classeur[FEUILLE_MODE_EMPLOI]
    textes = [ligne[0] for ligne in notice.iter_rows(values_only=True)]
    rang = textes.index(REPERE_EMPREINTE) + 1
    assert notice.cell(row=rang, column=2).value == "abc123"
    assert any(
        texte and texte.startswith("Feuille « références » : 0 lignes à « observé » sur 0")
        and "Feuille « périodes_export » : 1 sur 5." in texte
        for texte in textes
    )
    assert any(texte and "moins de 19 lignes" in texte for texte in textes)

    feuille = classeur[FEUILLE_PERIODES]
    assert [c.value for c in feuille[1]] == list(COLONNES_PERIODES)
    assert feuille.column_dimensions["O"].hidden
    assert feuille.cell(row=2, column=15).value == 0
    assert _verrouillee(feuille, 2, "table", COLONNES_PERIODES)
    assert _verrouillee(feuille, 2, "filtre_colonne", COLONNES_PERIODES)
    assert not _verrouillee(feuille, 2, "statut", COLONNES_PERIODES)
    assert not _verrouillee(feuille, 2, "libellé", COLONNES_PERIODES)
    # Lignes d'ajout : table, colonne et filtre se saisissent.
    assert not _verrouillee(feuille, 8, "table", COLONNES_PERIODES)
    assert not _verrouillee(feuille, 8, "filtre_colonne", COLONNES_PERIODES)
    assert _verrouillee(feuille, 8, "observé", COLONNES_PERIODES)
    plages = {str(menu.sqref): menu.formula1 for menu in feuille.data_validations.dataValidation}
    assert plages["H2:H56"] == '"observé,valide,invalide,documenté"'
    assert plages["K2:K56"] == '"anomalie,à arbitrer,information"'
    assert "A7:A56" in plages and "B7:B56" in plages

    feuille = classeur[FEUILLE_FERIES]
    assert feuille.cell(row=2, column=2).value == dt.datetime(2025, 1, 1)
    assert feuille.cell(row=2, column=2).number_format == "DD/MM/YYYY"
    # 12 dates en 2025, 11 en 2026, puis les lignes d'ajout.
    assert feuille.max_row == 1 + 23 + 50
    assert not _verrouillee(feuille, 25, "date", COLONNES_FERIES)
    assert feuille.cell(row=25, column=2).number_format == "DD/MM/YYYY"
    assert _verrouillee(feuille, 2, "date", COLONNES_FERIES)

    feuille = classeur[FEUILLE_AUTRES]
    assert feuille.max_row == 4
    assert not _verrouillee(feuille, 2, "issue", COLONNES_AUTRES)
    assert _verrouillee(feuille, 2, "paramètres", COLONNES_AUTRES)
    feuille = classeur[FEUILLE_NOUVELLES]
    assert feuille.cell(row=2, column=1).value == "Un avoir suit sa facture"
    assert not _verrouillee(feuille, 30, "règle", COLONNES_NOUVELLES)

    # Un formulaire existant n'est pas remplacé; un contenu mal formé est refusé.
    with pytest.raises(FileExistsError, match="export refusé"):
        exporter_formulaire_gestion(
            _tables(), _dictionnaire(), _contenu(), {}, {}, "2026-03", chemin, empreinte="x"
        )
    with pytest.raises(ValueError, match="demandes : une liste est attendue"):
        exporter_formulaire_gestion(
            _tables(), _dictionnaire(), {"demandes": {}}, {}, {}, "2026-03", chemin,
            empreinte="x", ecraser=True,
        )
    exporter_formulaire_gestion(
        _tables(), _dictionnaire(), {}, None, None, "2026-03", chemin, empreinte="absent",
        ecraser=True,
    )
    assert load_workbook(chemin)[FEUILLE_AUTRES].max_row == 1


# --- Seuil, références et renseignement (morceau b2) ------------------------------


def test_seuil_robuste():
    # Une ligne contraire de plus : 19 sur 19 atteint 95 %, 18 sur 18 non.
    assert _seuil_atteint(19, 19) and not _seuil_atteint(18, 18)
    assert _seuil_atteint(38, 39) and not _seuil_atteint(37, 38)
    assert not _seuil_atteint(0, 0) and not _seuil_atteint(1, 1)
    assert lignes_minimales() == 19


def _texte(nature):
    return {"nature": {"regle": nature}, "valeurs": {"regle": "aucune"}}


def _liste(*valeurs, invalides=()):
    return {
        "nature": {"regle": "texte"},
        "valeurs": {"regle": "liste fermée", "liste": [
            {"valeur": v, "statut": "invalide" if v in invalides else "valide"}
            for v in (*valeurs, *invalides)
        ]},
    }


def _tables_references():
    """Clients « c » (30) et factures « f » (25) qui citent leur client et leur
    facture précédente."""
    codes = [f"C{i:02d}" for i in range(1, 31)]
    nums = [f"F{i:02d}" for i in range(1, 26)]
    return {
        "c": pd.DataFrame({
            "code": codes,
            "siret": [str(i) for i in range(1, 31)],
            "ville": ["X"] * 30,
        }, dtype=object),
        "f": pd.DataFrame({
            "num": nums,
            # 24 clients connus et une cellule vide : clé facultative proposée.
            "client": codes[:24] + [None],
            "client2": codes[:25],
            "client3": codes[:25],
            # Un seul client distinct : pas de proposition.
            "agence": ["C01"] * 25,
            # La facture précédente, dans la même table (20 renseignées).
            "precedente": nums[:20] + [None] * 5,
            # Des numéros trouvés dans le siret, mais de nature texte : pas de proposition.
            "qte": [str(i) for i in range(1, 26)],
            # Des numéros de nature entier (texte), trouvés dans le siret : proposés.
            "rang": [str(i) for i in range(1, 26)],
            "n": ["1"] * 20 + ["2"] * 5,
        }, dtype=object),
    }


def _dictionnaire_references():
    return {
        "c": {"code": _texte("texte"), "siret": _texte("entier (texte)"),
              "ville": _texte("texte")},
        "f": {"num": _texte("texte"), "client": _texte("texte"), "client2": _texte("texte"),
              "client3": _texte("texte"), "agence": _texte("texte"),
              "precedente": _texte("texte"), "qte": _texte("texte"),
              "rang": _texte("entier (texte)"), "n": _texte("entier (texte)")},
    }


DECLARATIONS = {
    "c": {"cle": ["code"], "unique": [["siret"], ["code", "ville"]],
          "presume_unique": [["ville"]]},
    "f": {"cle": ["num"]},
}


def _existence(colonnes, reference, colonnes_ref=None, **autres):
    regle = {"ref": "existence", "libelle": f"{colonnes} connu", "type":
             "existence_dans_reference", "table": "f", "cle": colonnes,
             "table_reference": reference, **autres}
    if colonnes_ref is not None:
        regle["cle_reference"] = colonnes_ref
    return regle


def _contenu_references():
    return {
        "regles": [
            _existence(["client"], "c", ["code"], cle_facultative=True,
                       comparaison="après normalisation", commentaire="Vu",
                       filtre=[{"colonne": "n", "valeurs": ["1"]}]),
            _existence(["client", "agence"], "c", ["code", "ville"], issue="à arbitrer"),
            # Filtre de deux conditions : feuille des autres règles, mais pas de
            # proposition de client3 vers c.code.
            _existence(["client3"], "c", ["code"], filtre=[
                {"colonne": "n", "valeurs": ["1"]}, {"colonne": "qte", "valeurs": ["1"]}]),
        ],
        "retirees": [_existence(["agence"], "c", ["code"])],
        "ecartees": {"references": [{"table": "f", "colonne": "client2",
                                     "table_reference": "c", "colonne_reference": "code"}]},
    }


def test_cibles_references():
    assert cibles_references(_dictionnaire_references(), DECLARATIONS) == [
        ("c", "code"), ("c", "siret"), ("f", "num"),
    ]
    # Une clé de nature nombre natif, ou une colonne hors du dictionnaire, n'est pas une
    # cible; sans déclarations, aucune cible.
    dictionnaire = _dictionnaire_references()
    dictionnaire["f"]["num"] = _texte("nombre natif")
    declarations = {**DECLARATIONS, "c": {"cle": ["zz"]}}
    assert cibles_references(dictionnaire, declarations) == []
    assert cibles_references(dictionnaire, None) == []
    # Une colonne unique avec d'autres n'est pas une cible.
    declarations = {"c": {"unique": [["ville", "code"]]}}
    assert cibles_references(_dictionnaire_references(), declarations) == []


def test_lignes_references():
    lignes = lignes_references(
        _tables_references(), _dictionnaire_references(), _contenu_references(), DECLARATIONS
    )
    assert _reduites(lignes, "table", "colonne", "table_reference", "colonne_reference",
                     "origine", "statut", "ref", "issue", "clé_facultative", "comparaison",
                     "filtre_colonne", "filtre_valeurs", "rang") == [
        ("f", "client", "c", "code", "en vigueur", "documenté", "existence", "anomalie",
         "oui", "après normalisation", "n", "1", 0),
        ("f", "client, agence", "c", "code, ville", "en vigueur", "documenté", "existence",
         "à arbitrer", "non", "telle quelle", None, None, 1),
        # Propositions dans l'ordre des colonnes de f : la facture précédente (même
        # table), puis le rang, de même nature que le siret.
        ("f", "precedente", "f", "num", "proposée", "observé", "existence", "anomalie",
         "oui", "telle quelle", None, None, None),
        ("f", "rang", "c", "siret", "proposée", "observé", "existence", "anomalie",
         "non", "telle quelle", None, None, None),
        # Deux valeurs distinctes suffisent (n vaut 1 ou 2).
        ("f", "n", "c", "siret", "proposée", "observé", "existence", "anomalie",
         "non", "telle quelle", None, None, None),
        ("f", "agence", "c", "code", "retirée", "invalide", "existence", "anomalie", "non",
         "telle quelle", None, None, 0),
        ("f", "client2", "c", "code", "écartée", "invalide", "existence", "anomalie",
         "non", "telle quelle", None, None, None),
    ]
    assert _reduites(lignes, "observé", "proposition", "proposition_clé_facultative") == [
        # Filtre appliqué : les 20 lignes où n vaut 1.
        ("20 lignes renseignées, 20 trouvées (100 %)", "oui", "non"),
        ("24 lignes renseignées, 0 trouvées (0 %), 1 vides", "aucune", "oui"),
        ("20 lignes renseignées, 20 trouvées (100 %), 5 vides", "oui", "oui"),
        ("25 lignes renseignées, 25 trouvées (100 %)", "oui", "non"),
        ("25 lignes renseignées, 25 trouvées (100 %)", "oui", "non"),
        # Un seul client distinct trouvé : pas de proposition.
        ("25 lignes renseignées, 25 trouvées (100 %)", "aucune", "non"),
        ("25 lignes renseignées, 25 trouvées (100 %)", "oui", "non"),
    ]
    assert lignes[0]["libellé"] == "['client'] connu"
    assert lignes[0]["commentaire"] == "Vu"
    assert lignes[2]["libellé"] == "f.precedente connue de f.num"
    assert all(set(ligne) <= set(COLONNES_REFERENCES) for ligne in lignes)
    # Sans règle : le client est proposé (24 sur 25, clé facultative), pas client3
    # (trouvé à 100 %) s'il est écarté.
    contenu = {"ecartees": {"references": [{"table": "f", "colonne": "client3",
                                            "table_reference": "c",
                                            "colonne_reference": "code"}]}}
    lignes = lignes_references(
        _tables_references(), _dictionnaire_references(), contenu, DECLARATIONS
    )
    assert _reduites(lignes, "colonne", "colonne_reference", "origine",
                     "clé_facultative") == [
        ("client", "code", "proposée", "oui"),
        ("client2", "code", "proposée", "non"),
        ("precedente", "num", "proposée", "oui"),
        ("rang", "siret", "proposée", "non"),
        ("n", "siret", "proposée", "non"),
        ("client3", "code", "écartée", "non"),
    ]
    # 18 lignes trouvées sur 18 ne suffisent pas; 19 sur 19 suffisent.
    for lignes_f, attendu in ((18, 0), (19, 1)):
        tables = _tables_references()
        tables["f"] = tables["f"].iloc[:lignes_f][["num", "client2"]]
        dictionnaire = _dictionnaire_references()
        dictionnaire["f"] = {c: dictionnaire["f"][c] for c in ("num", "client2")}
        lignes = lignes_references(tables, dictionnaire, {}, DECLARATIONS)
        assert len(lignes) == attendu
    # Une règle sur une table ou une colonne absente des données est montrée sans
    # observation. Les lignes suivent l'ordre des tables du dictionnaire.
    contenu = {"regles": [
        _existence(["zz"], "c", ["code"]), _existence(["client"], "zz"),
        _existence(["ville"], "f", ["num"]) | {"table": "c"},
    ]}
    lignes = lignes_references(_tables_references(), _dictionnaire_references(), contenu, {})
    assert _reduites(lignes, "table", "colonne", "table_reference", "observé",
                     "proposition") == [
        ("c", "ville", "f", "30 lignes renseignées, 0 trouvées (0 %)", "aucune"),
        ("f", "zz", "c", None, "aucune"),
        ("f", "client", "zz", None, "aucune"),
    ]


def test_proposer_renseignement():
    def observation(**effectifs):
        from collections import Counter
        return {
            "lignes": Counter({v: n for v, (n, _) in effectifs.items()}),
            "renseignees": Counter({v: r for v, (_, r) in effectifs.items()}),
            "selon_vide": 0,
        }
    liste = ["A", "B", "C"]
    # Retenue avec une ligne contraire de plus; vide_sinon de même.
    assert proposer_renseignement(observation(B=(19, 19), A=(19, 0)), liste) == (["B"], True)
    assert proposer_renseignement(observation(B=(19, 19), A=(18, 0)), liste) == (["B"], False)
    assert proposer_renseignement(observation(B=(18, 18), A=(30, 0)), liste) is None
    # Valeurs retenues dans l'ordre de la liste.
    assert proposer_renseignement(
        observation(C=(20, 20), A=(20, 20), B=(40, 0)), liste
    ) == (["A", "C"], True)
    # Toutes les valeurs atteignent le seuil simple (B, 11 sur 11, trop peu pour être
    # retenue) : la colonne est toujours renseignée, pas de proposition.
    assert proposer_renseignement(observation(A=(100, 100), B=(11, 11)), liste) is None
    assert proposer_renseignement(observation(A=(100, 100), B=(20, 19)), liste) is None
    # Une valeur hors liste ne compte pas, ni pour retenir ni pour vide_sinon.
    assert proposer_renseignement(
        observation(A=(20, 20), B=(20, 0), Z=(5, 5)), liste
    ) == (["A"], True)
    assert proposer_renseignement(observation(Z=(50, 50), A=(30, 0)), liste) is None


def _tables_renseignement():
    """40 clients : 20 inactifs (date de fin renseignée), 20 actifs, 3 prospects, 2
    statuts hors liste et 1 statut vide."""
    statut = ["inactif"] * 20 + ["actif"] * 20 + ["prospect"] * 3 + ["Inactif"] * 2 + [None]
    inactif = [s in ("inactif", "Inactif") for s in statut]
    return {"c": pd.DataFrame({
        "statut": statut,
        "fin": ["01/01/2025" if i else None for i in inactif],
        # Toujours renseigné, sauf pour un actif : pas de proposition.
        "tel": ["0102"] * 21 + [None] + ["0102"] * 24,
        # Renseignée pour les inactifs et la moitié des actifs : pas de vide_sinon.
        "note": ["x" if i or k % 2 else " " for k, i in enumerate(inactif)],
        "categorie": ["A" if i else "B" for i in inactif],
        "region": ["r1" if i else "r2" for i in inactif],
    }, dtype=object)}


def _dictionnaire_renseignement():
    return {"c": {
        "statut": _liste("actif", "inactif", "prospect", invalides=("Inactif",)),
        "fin": _texte("date JJ/MM/AAAA"),
        "tel": _texte("texte"),
        "note": _texte("texte"),
        "categorie": _liste("A", "B"),
        "region": _liste(*(f"r{i}" for i in range(1, 14))),
    }}


def _renseignee(colonne, selon, valeurs, **autres):
    return {"ref": "renseignement", "libelle": f"{colonne} selon {selon}", "type":
            "renseignee_selon_valeur", "table": "c", "colonne": colonne, "selon": selon,
            "valeurs": valeurs, **autres}


def test_lignes_renseignement():
    tables, dictionnaire = _tables_renseignement(), _dictionnaire_renseignement()
    contenu = {
        "regles": [_renseignee("note", "statut", ["inactif"], vide_sinon=True,
                               filtre=[{"colonne": "categorie", "valeurs": ["A"]}])],
        "retirees": [_renseignee("fin", "categorie", ["A"])],
        "ecartees": {"renseignement": [{"table": "c", "colonne": "tel", "selon": "statut"}]},
    }
    lignes = lignes_renseignement(tables, dictionnaire, contenu)
    assert _reduites(lignes, "colonne", "selon", "origine", "statut", "valeurs",
                     "vide_sinon", "filtre_colonne", "filtre_valeurs", "rang") == [
        ("note", "statut", "en vigueur", "documenté", "inactif", "oui", "categorie", "A", 0),
        # Propositions dans l'ordre des colonnes, puis des colonnes selon; aucune selon
        # region (13 valeurs dans sa liste), ni pour tel (toujours renseigné ou presque).
        ("fin", "statut", "proposée", "observé", "inactif", "oui", None, None, None),
        ("note", "categorie", "proposée", "observé", "A", "non", None, None, None),
        ("fin", "categorie", "retirée", "invalide", "A", "non", None, None, 0),
        ("tel", "statut", "écartée", "invalide", None, None, None, None, None),
    ]
    assert _reduites(lignes, "observé", "proposition", "proposition_valeurs",
                     "proposition_vide_sinon") == [
        # Filtre appliqué (categorie A) : statut inactif ou hors liste.
        ("inactif 20 sur 20 renseignées; autres valeurs 2 sur 2 renseignées", "aucune",
         None, None),
        # Les statuts hors liste, renseignés, ne comptent pas pour vide_sinon.
        ("inactif 20 sur 20 renseignées; autres valeurs 2 sur 25 renseignées; selon vide "
         "sur 1 lignes", "inactif; vide sinon", "inactif", "oui"),
        ("A 22 sur 22 renseignées; autres valeurs 12 sur 24 renseignées", "A", "A", "non"),
        ("A 22 sur 22 renseignées; autres valeurs 0 sur 24 renseignées", "A; vide sinon", "A",
         "oui"),
        ("autres valeurs 44 sur 45 renseignées; selon vide sur 1 lignes", "aucune", None,
         None),
    ]
    assert _reduites(lignes, "ref", "libellé", "issue") == [
        ("renseignement", "note selon statut", "anomalie"),
        ("renseignement", "fin renseignée si statut vaut inactif, vide sinon", "anomalie"),
        ("renseignement", "note renseignée si categorie vaut A", "anomalie"),
        ("renseignement", "fin selon categorie", "anomalie"),
        ("renseignement", "tel renseignée selon statut", "anomalie"),
    ]
    assert all(set(ligne) <= set(COLONNES_RENSEIGNEMENT) for ligne in lignes)
    # Une colonne selon sensible ne sert à aucune proposition : ses valeurs entreraient
    # dans config/gestion.yaml.
    lignes = lignes_renseignement(tables, dictionnaire, contenu, {"c": frozenset({"categorie"})})
    assert _reduites(lignes, "colonne", "selon", "origine", "proposition") == [
        ("note", "statut", "en vigueur", "aucune"),
        ("fin", "statut", "proposée", "inactif; vide sinon"),
        ("fin", "categorie", "retirée", "aucune"),
        ("tel", "statut", "écartée", "aucune"),
    ]
    # Une règle à filtre de deux conditions (feuille des autres règles) empêche aussi la
    # proposition.
    complexe = _renseignee("fin", "statut", ["inactif"], filtre=[
        {"colonne": "categorie", "valeurs": ["A"]}, {"colonne": "region", "valeurs": ["r1"]}])
    lignes = lignes_renseignement(tables, dictionnaire, {"regles": [complexe]})
    assert ("fin", "statut") not in _reduites(lignes, "colonne", "selon")
    assert ("note", "statut") in _reduites(lignes, "colonne", "selon")
    # Sans liste fermée en vigueur sur statut, pas de proposition selon statut.
    dictionnaire["c"]["statut"] = _texte("texte")
    lignes = lignes_renseignement(tables, dictionnaire, {})
    assert _reduites(lignes, "colonne", "selon") == [("fin", "categorie"), ("note", "categorie")]
    # Une règle sur une colonne absente des données est montrée sans observation.
    lignes = lignes_renseignement(tables, dictionnaire, {"regles": [_renseignee("zz", "s", ["V"])]})
    assert _reduites(lignes[:1], "colonne", "observé", "proposition", "valeurs") == [
        ("zz", None, "aucune", "V"),
    ]


def test_export_references_et_renseignement(tmp_path):
    tables = {**_tables_references(), "k": _tables_renseignement()["c"]}
    dictionnaire = {**_dictionnaire_references(), "k": _dictionnaire_renseignement()["c"]}
    chemin = tmp_path / "gestion_2026-03.xlsx"
    exporter_formulaire_gestion(
        tables, dictionnaire, _contenu_references(), DECLARATIONS, {}, "2026-03", chemin,
        empreinte="abc",
    )
    classeur = load_workbook(chemin)
    textes = [ligne[0] for ligne in classeur[FEUILLE_MODE_EMPLOI].iter_rows(values_only=True)]
    assert any(
        texte and texte.startswith(
            "Feuille « références » : 3 lignes à « observé » sur 7. Feuille "
            "« renseignement » : 4 sur 4."
        )
        for texte in textes
    )

    feuille = classeur[FEUILLE_REFERENCES]
    colonnes = list(COLONNES_REFERENCES)
    assert [c.value for c in feuille[1]] == colonnes
    lettre = {nom: chr(ord("A") + rang) for rang, nom in enumerate(colonnes)}
    assert feuille.column_dimensions[lettre["rang"]].hidden
    assert feuille.column_dimensions[lettre["proposition_clé_facultative"]].hidden
    assert not feuille.column_dimensions[lettre["clé_facultative"]].hidden
    assert feuille.cell(row=2, column=colonnes.index("colonne") + 1).value == "client"
    assert feuille.cell(row=3, column=colonnes.index("colonne") + 1).value == "client, agence"
    assert not _verrouillee(feuille, 2, "clé_facultative", colonnes)
    assert not _verrouillee(feuille, 2, "comparaison", colonnes)
    assert _verrouillee(feuille, 2, "table_reference", colonnes)
    assert not _verrouillee(feuille, 9, "table_reference", colonnes)
    assert not _verrouillee(feuille, 9, "colonne_reference", colonnes)
    assert _verrouillee(feuille, 9, "observé", colonnes)
    menus = {str(menu.sqref): menu for menu in feuille.data_validations.dataValidation}
    assert menus[f"{lettre['clé_facultative']}2:{lettre['clé_facultative']}58"].formula1 == (
        '"oui,non"'
    )
    assert menus[f"{lettre['comparaison']}2:{lettre['comparaison']}58"].formula1 == (
        '"telle quelle,après normalisation,mots dans le désordre"'
    )
    # Lignes d'ajout : menus des tables, et des colonnes, qui admettent « a, b ».
    for nom in ("table", "table_reference"):
        assert menus[f"{lettre[nom]}9:{lettre[nom]}58"].errorStyle in (None, "stop")
    for nom in ("colonne", "colonne_reference"):
        assert menus[f"{lettre[nom]}9:{lettre[nom]}58"].errorStyle == "warning"

    feuille = classeur[FEUILLE_RENSEIGNEMENT]
    colonnes = list(COLONNES_RENSEIGNEMENT)
    assert [c.value for c in feuille[1]] == colonnes
    lettre = {nom: chr(ord("A") + rang) for rang, nom in enumerate(colonnes)}
    for nom in ("rang", "proposition_valeurs", "proposition_vide_sinon"):
        assert feuille.column_dimensions[lettre[nom]].hidden
    assert _reduites(
        [dict(zip(colonnes, ligne)) for ligne in feuille.iter_rows(min_row=2, max_row=5,
                                                                    values_only=True)],
        "table", "colonne", "selon", "valeurs", "vide_sinon", "statut",
    ) == [
        ("k", "fin", "statut", "inactif", "oui", "observé"),
        ("k", "fin", "categorie", "A", "oui", "observé"),
        ("k", "note", "statut", "inactif", "non", "observé"),
        ("k", "note", "categorie", "A", "non", "observé"),
    ]
    assert not _verrouillee(feuille, 2, "valeurs", colonnes)
    assert not _verrouillee(feuille, 2, "vide_sinon", colonnes)
    assert _verrouillee(feuille, 2, "selon", colonnes)
    assert not _verrouillee(feuille, 6, "selon", colonnes)
    menus = {str(menu.sqref): menu for menu in feuille.data_validations.dataValidation}
    assert menus[f"{lettre['vide_sinon']}2:{lettre['vide_sinon']}55"].formula1 == '"oui,non"'
    for nom in ("table", "colonne", "selon"):
        assert menus[f"{lettre[nom]}6:{lettre[nom]}55"].errorStyle in (None, "stop")
    # Les règles des familles ne vont pas dans la feuille des autres règles, sauf celle
    # dont le filtre a deux conditions.
    feuille = classeur[FEUILLE_AUTRES]
    assert feuille.max_row == 2
    assert feuille.cell(row=2, column=COLONNES_AUTRES.index("paramètres") + 1).value == (
        "cle = client3; table_reference = c; cle_reference = code"
    )
