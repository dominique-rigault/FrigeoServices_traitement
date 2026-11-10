import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from frigeo.ecriture_base import modules_verification
from frigeo.packs.services_intervention import (
    achats_retenus,
    chantiers_attendus,
    comparer_chantiers,
    consommations,
    couts_attendus,
    cump_attendus,
    cump_fin_de_mois,
    dates_stock_initial,
    liens,
    mois_du_calcul,
    pieces_catalogue,
    table_propre,
    verifier,
)

PARAMETRES = {
    "categorie_chantier": "Installation",
    "article_chantier": "INST-F",
    "type_piece_facture": "Facture",
    "date_stock_initial": "2025-01-01",
}


def _i(numero):
    return ("interventions.csv", None, numero)


def _e(numero):
    return ("factures.xlsx", "Entetes", numero)


def _l(numero):
    return ("factures.xlsx", "Lignes", numero)


def _jeu():
    interventions = {
        _i(2): {"categorie": "Installation", "date_debut": "2025-03-11", "heure_debut": "08:00:00"},
        _i(3): {"categorie": "Installation", "date_debut": "2025-03-10", "heure_debut": "08:00:00"},
        _i(4): {"categorie": "Installation", "date_debut": "2025-03-12", "heure_debut": "08:00:00"},
        _i(5): {"categorie": "Installation", "date_debut": "2025-04-01", "heure_debut": "09:00:00"},
        _i(6): {"categorie": "Dépannage", "date_debut": "2025-04-02", "heure_debut": "09:00:00"},
        _i(7): {"categorie": "Installation", "date_debut": "2025-05-01", "heure_debut": "09:00:00"},
        _i(8): {"categorie": "Installation", "date_debut": "2025-05-02", "heure_debut": None},
    }
    entetes = {
        _e(2): {"type_piece": "Facture"},  # chantier de trois jours
        _e(3): {"type_piece": "Facture"},  # une installation d'un jour et un dépannage
        _e(4): {"type_piece": "Avoir"},
        _e(5): {"type_piece": "Facture"},  # chantier de deux jours
    }
    lignes = {
        _l(2): {"code_article": "INST-F"}, _l(3): {"code_article": "INST-F"},
        _l(4): {"code_article": "INST-F"}, _l(5): {"code_article": "PIECE"},
        _l(6): {"code_article": "INST-F"}, _l(7): {"code_article": "INST-F"},
        _l(8): {"code_article": "INST-F"}, _l(9): {"code_article": "INST-F"},
        _l(10): {"code_article": "INST-F"}, _l(11): {"code_article": "INST-F"},
    }
    lien_entete = {
        _l(2): _e(2), _l(3): _e(2), _l(4): _e(2), _l(5): _e(2),
        _l(6): _e(3), _l(7): _e(3), _l(8): _e(4),
        _l(9): _e(5), _l(10): _e(5), _l(11): _e(5),
    }
    lien_intervention = {
        _l(2): _i(2), _l(3): _i(3), _l(4): _i(4), _l(5): _i(5),  # pièce : ne compte pas
        _l(6): _i(5), _l(7): _i(6), _l(8): _i(7),  # dépannage, avoir : ne comptent pas
        _l(9): _i(7), _l(10): _i(8), _l(11): _i(8),  # deux lignes pour un même jour
    }
    return lignes, entetes, interventions, lien_entete, lien_intervention


def test_chantiers_attendus():
    attendus = chantiers_attendus(*_jeu(), PARAMETRES)
    assert attendus == {
        _i(3): (_i(3), 1, 3), _i(2): (_i(3), 2, 3), _i(4): (_i(3), 3, 3),
        _i(7): (_i(7), 1, 2), _i(8): (_i(7), 2, 2),
    }


def test_chantiers_premier_en_tete_et_ordre_des_jours():
    lignes, entetes, interventions, lien_entete, lien_intervention = _jeu()
    # L'intervention 4 apparaît aussi sur un autre en-tête, plus loin dans le lignage :
    # elle reste au chantier du premier.
    entetes[_e(9)] = {"type_piece": "Facture"}
    lignes[_l(20)] = {"code_article": "INST-F"}
    lien_entete[_l(20)] = _e(9)
    lien_intervention[_l(20)] = _i(4)
    # Même jour : une heure vide passe d'abord, puis, à même heure, le lignage départage.
    for numero in (2, 3, 4):
        interventions[_i(numero)]["date_debut"] = "2025-03-10"
    interventions[_i(4)]["heure_debut"] = None
    attendus = chantiers_attendus(lignes, entetes, interventions, lien_entete,
                                  lien_intervention, PARAMETRES)
    assert attendus[_i(4)] == (_i(4), 1, 3)
    assert attendus[_i(2)] == (_i(4), 2, 3)
    assert attendus[_i(3)] == (_i(4), 3, 3)


def test_chantiers_lien_ou_ligne_absents():
    lignes, entetes, interventions, lien_entete, lien_intervention = _jeu()
    del lien_intervention[_l(2)]  # ligne sans intervention rattachée
    del entetes[_e(5)]  # en-tête absent de propre
    attendus = chantiers_attendus(lignes, entetes, interventions, lien_entete,
                                  lien_intervention, PARAMETRES)
    assert attendus == {_i(3): (_i(3), 1, 2), _i(4): (_i(3), 2, 2)}


def test_comparer_chantiers():
    attendus = {_i(3): (_i(3), 1, 2), _i(4): (_i(3), 2, 2)}
    toutes = [_i(2), _i(3), _i(4)]
    obtenus = {_i(2): (_i(2), 1, 1), _i(3): (_i(3), 1, 2), _i(4): (_i(3), 2, 2)}
    assert comparer_chantiers(attendus, toutes, obtenus) == (0, "1 / 2", "1 / 2")
    obtenus[_i(4)] = (_i(4), 1, 1)
    obtenus[_i(9)] = (_i(9), 1, 1)  # absente de propre
    assert comparer_chantiers(attendus, toutes, obtenus) == (2, "1 / 2", "1 / 1")


def test_dates_stock_initial():
    regles = [
        {"type": "solde_jamais_negatif", "date_initial": dt.date(2025, 1, 1)},
        {"type": "solde_jamais_negatif", "date_initial": "2025-01-01"},
        {"type": "plage", "date_initial": dt.date(2020, 1, 1)},
        {"type": "solde_jamais_negatif"},
    ]
    assert dates_stock_initial(regles) == ["2025-01-01"]
    assert dates_stock_initial([]) == []


def _rattachements():
    regles = [
        SimpleNamespace(table="factures_lignes", cle=("num_facture",),
                        table_reference="factures_entetes"),
        SimpleNamespace(table="factures_lignes", cle=("num_facture",),
                        table_reference="factures_entetes"),
        SimpleNamespace(table="factures_lignes", cle=("id_intervention",),
                        table_reference="interventions"),
    ]
    lignes = pd.DataFrame([
        {"regle": 1, "fichier_source": "factures.xlsx", "feuille_source": "Lignes",
         "num_ligne_source": 2, "fichier_reference": "factures.xlsx",
         "feuille_reference": "Entetes", "num_ligne_reference": 2},
        {"regle": 2, "fichier_source": "factures.xlsx", "feuille_source": "Lignes",
         "num_ligne_source": 3, "fichier_reference": "factures.xlsx",
         "feuille_reference": "Entetes", "num_ligne_reference": 3},
        {"regle": 3, "fichier_source": "factures.xlsx", "feuille_source": "Lignes",
         "num_ligne_source": 2, "fichier_reference": "interventions.csv",
         "feuille_reference": float("nan"), "num_ligne_reference": 2},
    ])
    return SimpleNamespace(regles=regles, lignes=lignes)


def test_liens_par_le_premier_rattachement():
    rattachements = _rattachements()
    assert liens(rattachements, "factures_lignes", "num_facture", "factures_entetes") == {
        _l(2): _e(2)
    }
    assert liens(rattachements, "factures_lignes", "id_intervention", "interventions") == {
        _l(2): _i(2)
    }
    assert liens(rattachements, "factures_lignes", "ref_piece", "catalogue_pieces") == {}


def _table(source, colonnes, lignes, schema="propre"):
    techniques = ["periode_export", "fichier_source", "feuille_source", "num_ligne_source",
                  "retenue"]
    return SimpleNamespace(schema=schema, table=SimpleNamespace(source=source),
                           colonnes=techniques + colonnes, lignes=lignes)


def _preparation():
    colonnes = ["categorie", "date_debut", "heure_debut"]
    return SimpleNamespace(tables=[
        _table("interventions", colonnes, [], schema="chargement"),
        _table("interventions", colonnes,
               [["2025", "interventions.csv", None, 2, 1, "Installation", "2025-03-11",
                 "08:00:00"]]),
        _table("factures_lignes", [], []),
        _table("factures_entetes", [], []),
        _table("catalogue_pieces", ["ref_piece", "stock_initial", "cump_initial"],
               [[None, "catalogue.xlsx", None, 2, 1, "PCE-1", "2", "10.5"]]),
        _table("achats_lignes", [], []),
        _table("achats_entetes", [], []),
        _table("pieces_interventions", [], []),
    ])


def test_table_propre():
    table = table_propre(_preparation(), "interventions")
    assert list(table) == [_i(2)]
    assert table[_i(2)]["categorie"] == "Installation"


class _Curseur:
    """Faux curseur : rend, pour chaque requête, les lignes de la première table citée."""

    def __init__(self, parametres, chantiers, cump=(), couts=(), periode="2025-02"):
        self.resultats = {
            "dw.parametre_calcul": parametres, "dw.cump_mensuel": list(cump),
            "dw.fait_consommation": list(couts), "dw.fait_intervention": chantiers,
            "qualite.execution": [(periode,)],
        }
        self.courant = None

    def execute(self, requete, *parametres):
        self.courant = next(v for k, v in self.resultats.items() if k in requete)

    def fetchall(self):
        return self.courant


def test_verifier():
    cump = [("PCE-1", dt.date(2025, mois, 1), Decimal(2), Decimal("10.5"), Decimal(0),
             Decimal(0), Decimal(0), Decimal(2), Decimal("10.5")) for mois in (1, 2)]
    curseur = _Curseur(
        list(PARAMETRES.items()),
        [("interventions.csv", None, 2, "interventions.csv", None, 2, 1, 1)],
        cump,
    )
    controles = []
    ecriture = SimpleNamespace(preparation=_preparation(), id_execution=1)
    sorties = SimpleNamespace(rattachements=SimpleNamespace(regles=[], lignes=pd.DataFrame()))
    regles = [{"type": "solde_jamais_negatif", "date_initial": dt.date(2025, 1, 1)}]
    verifier(curseur, ecriture, sorties, lambda *c: controles.append(c), regles)
    assert [c[1:] for c in controles] == [
        ("2025-01-01", "2025-01-01"), (0, 0), ("0 / 0", "0 / 0"),
        (2, 2), (0, 0), (0, 0), ("aucun", "aucun"), (Decimal(0), Decimal(0)),
    ]
    # Un CUMP qui diffère d'un mois sort en écart.
    cump[1] = cump[1][:-1] + (Decimal("10.4"),)
    controles.clear()
    verifier(_Curseur(list(PARAMETRES.items()), [], cump), ecriture, sorties,
             lambda *c: controles.append(c), regles)
    assert controles[4][1:] == (0, 1)


def test_verifier_sans_rattachements():
    curseur = _Curseur(list(PARAMETRES.items()), [])
    controles = []
    ecriture = SimpleNamespace(preparation=_preparation(), id_execution=1)
    verifier(curseur, ecriture, None, lambda *c: controles.append(c), [])
    assert controles[0][1:] == (None, "2025-01-01")
    assert controles[1][1:] == ("rattachements absents", None)
    assert len(controles) == 2


# --- CUMP et coût des pièces -----------------------------------------------------


def _c(numero):
    return ("catalogue.xlsx", None, numero)


def _a(numero):
    return ("achats.xlsx", "Lignes", numero)


def _ea(numero):
    return ("achats.xlsx", "Entetes", numero)


def _p(numero):
    return ("pieces.csv", None, numero)


def test_mois_du_calcul():
    mois = mois_du_calcul("2025-11-01", "2026-02")
    assert mois == ["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01"]
    assert mois_du_calcul("2025-01-01", "2025-01") == ["2025-01-01"]
    assert mois_du_calcul("2025-03-01", "2025-02") == []


def test_pieces_catalogue():
    catalogue = {
        _c(3): {"ref_piece": "PCE-1", "stock_initial": "9", "cump_initial": "1"},
        _c(2): {"ref_piece": "PCE-1", "stock_initial": "2", "cump_initial": "30.85005"},
        _c(4): {"ref_piece": "PCE-2", "stock_initial": None, "cump_initial": None},
        _c(5): {"ref_piece": None, "stock_initial": "1", "cump_initial": "1"},
    }
    assert pieces_catalogue(catalogue) == {
        "PCE-1": (Decimal(2), Decimal("30.8501")),  # première ligne, moitié vers le haut
        "PCE-2": (Decimal(0), None),
    }


def test_cump_fin_de_mois():
    d = Decimal
    # (2 × 10 + 3 × 12) / 5
    assert cump_fin_de_mois(d(2), d("10.0000"), d(3), d(36)) == d("11.2000")
    # Sans achat, ou avoir qui rend le dénominateur nul : CUMP de début gardé.
    assert cump_fin_de_mois(d(2), d("10.0000"), d(0), d(0)) == d("10.0000")
    assert cump_fin_de_mois(d(1), d("10.0000"), d(-1), d(-12)) == d("10.0000")
    # Stock négatif, ou sans CUMP connu : il pèse zéro.
    assert cump_fin_de_mois(d(-3), d("10.0000"), d(2), d(25)) == d("12.5000")
    assert cump_fin_de_mois(d(4), None, d(2), d(25)) == d("12.5000")
    assert cump_fin_de_mois(d(0), None, d(0), d(0)) is None
    # Arrondi à 4 décimales, la moitié s'éloignant de zéro.
    assert cump_fin_de_mois(d(1), d("1.0000"), d(1), d("1.0001")) == d("1.0001")
    # Opérandes ramenés à 6 décimales.
    assert cump_fin_de_mois(d("0.0000004"), d("1.0000"), d(1), d(3)) == d(3)


def test_achats_retenus():
    lignes = {
        _a(2): {"retenue": 1, "ref_piece": "PCE-1", "quantite": "3", "montant_ht": "36"},
        _a(3): {"retenue": 1, "ref_piece": "PCE-1", "quantite": "-1", "montant_ht": "-12"},
        _a(4): {"retenue": 0, "ref_piece": "PCE-1", "quantite": "1", "montant_ht": "1"},
        _a(5): {"retenue": 1, "ref_piece": "PCE-1", "quantite": "1", "montant_ht": "1"},
        _a(6): {"retenue": 1, "ref_piece": None, "quantite": "1", "montant_ht": "1"},
        _a(7): {"retenue": 1, "ref_piece": "PCE-1", "quantite": None, "montant_ht": "1"},
        _a(8): {"retenue": 1, "ref_piece": "PCE-1", "quantite": "1", "montant_ht": "1"},
    }
    entetes = {
        _ea(2): {"retenue": 1, "date_facture": "2025-01-15"},
        _ea(3): {"retenue": 1, "date_facture": "2025-02-01"},
        _ea(4): {"retenue": 0, "date_facture": "2025-01-15"},
    }
    lien_entete = {_a(2): _ea(2), _a(3): _ea(3), _a(4): _ea(2), _a(5): _ea(4),
                   _a(6): _ea(2), _a(7): _ea(2)}  # 8 : sans en-tête
    lien_piece = {_a(n): _c(2) for n in (2, 3, 4, 5, 7, 8)}
    catalogue = {_c(2): {"ref_piece": "PCE-1"}}
    assert achats_retenus(lignes, entetes, lien_entete, lien_piece, catalogue) == [
        ("PCE-1", "2025-01-01", Decimal(3), Decimal(36)),
        ("PCE-1", "2025-02-01", Decimal(-1), Decimal(-12)),
    ]


def test_consommations_et_motifs():
    mois = ["2025-01-01", "2025-02-01"]
    lignes = {
        _p(2): {"retenue": 1, "ref_piece": "PCE-1", "quantite": "2", "date_sortie": "2025-01-20"},
        _p(3): {"retenue": 0, "ref_piece": "PCE-1", "quantite": "1", "date_sortie": "2025-02-03"},
        _p(4): {"retenue": 1, "ref_piece": "PCE-1", "quantite": None, "date_sortie": None},
        _p(5): {"retenue": 1, "ref_piece": None, "quantite": "1", "date_sortie": "2025-01-20"},
        _p(6): {"retenue": 1, "ref_piece": "PCE-9", "quantite": "1", "date_sortie": "2025-01-20"},
        _p(7): {"retenue": 1, "ref_piece": "PCE-1", "quantite": "1", "date_sortie": None},
        _p(8): {"retenue": 1, "ref_piece": "PCE-1", "quantite": "1", "date_sortie": "2024-12-31"},
    }
    lien_piece = {_p(n): _c(2) for n in (2, 3, 4, 7, 8)}
    catalogue = {_c(2): {"ref_piece": "PCE-1"}}
    consommees = consommations(lignes, lien_piece, catalogue, mois)
    assert {cle: v[4] for cle, v in consommees.items()} == {
        _p(2): None, _p(3): None, _p(4): "quantité vide", _p(5): "pièce non renseignée",
        _p(6): "pièce introuvable", _p(7): "date vide", _p(8): "date hors des mois du calcul",
    }
    assert consommees[_p(3)] == ("PCE-1", "2025-02-01", Decimal(1), False, None)


def test_cump_attendus_et_couts():
    mois = ["2025-01-01", "2025-02-01"]
    pieces = {"PCE-1": (Decimal(2), Decimal("10.0000")), "PCE-2": (Decimal(0), None)}
    achats = [("PCE-1", "2025-01-01", Decimal(3), Decimal(36)),
              ("PCE-1", "2024-12-01", Decimal(5), Decimal(5))]  # hors des mois du calcul
    consommees = {
        _p(2): ("PCE-1", "2025-01-01", Decimal(2), True, None),
        _p(3): ("PCE-1", "2025-02-01", Decimal("1.5"), True, None),
        _p(4): ("PCE-1", "2025-02-01", Decimal(1), False, None),  # non retenue : hors stock
        _p(5): ("PCE-2", "2025-01-01", Decimal(1), True, None),
        _p(6): (None, None, None, True, "quantité vide"),
    }
    cump = cump_attendus(pieces, achats, consommees, mois)
    d = Decimal
    assert cump[("PCE-1", "2025-01-01")] == (d(2), d("10.0000"), d(3), d(36), d(2), d(3),
                                            d("11.2000"))
    assert cump[("PCE-1", "2025-02-01")] == (d(3), d("11.2000"), d(0), d(0), d("1.5"),
                                            d("1.5"), d("11.2000"))
    assert cump[("PCE-2", "2025-01-01")][5:] == (d(-1), None)
    assert len(cump) == 4
    couts = couts_attendus(consommees, cump)
    assert couts == {
        _p(2): (d("10.0000"), d("20.00"), None),  # CUMP de début du mois
        _p(3): (d("11.2000"), d("16.80"), None),
        _p(4): (d("11.2000"), d("11.20"), None),  # coût calculé, même non retenue
        _p(5): (None, None, "CUMP inconnu"),
        _p(6): (None, None, "quantité vide"),
    }


def test_modules_verification():
    modules = modules_verification(["services_intervention", "pack_sans_module"])
    assert [nom for nom, _ in modules] == ["services_intervention"]
    assert hasattr(modules[0][1], "verifier")
