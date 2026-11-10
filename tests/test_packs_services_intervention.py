import datetime as dt
from types import SimpleNamespace

import pandas as pd

from frigeo.ecriture_base import modules_verification
from frigeo.packs.services_intervention import (
    chantiers_attendus,
    comparer_chantiers,
    dates_stock_initial,
    liens,
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


def _preparation():
    colonnes = ["periode_export", "fichier_source", "feuille_source", "num_ligne_source",
                "retenue", "categorie", "date_debut", "heure_debut"]
    interventions = SimpleNamespace(
        schema="propre", table=SimpleNamespace(source="interventions"), colonnes=colonnes,
        lignes=[["2025", "interventions.csv", None, 2, 1, "Installation", "2025-03-11",
                 "08:00:00"]],
    )
    chargement = SimpleNamespace(
        schema="chargement", table=SimpleNamespace(source="interventions"),
        colonnes=colonnes, lignes=[],
    )
    vides = [
        SimpleNamespace(schema="propre", table=SimpleNamespace(source=nom),
                        colonnes=colonnes[:5], lignes=[])
        for nom in ("factures_lignes", "factures_entetes")
    ]
    return SimpleNamespace(tables=[chargement, interventions, *vides])


def test_table_propre():
    table = table_propre(_preparation(), "interventions")
    assert list(table) == [_i(2)]
    assert table[_i(2)]["categorie"] == "Installation"


class _Curseur:
    def __init__(self, parametres, chantiers):
        self.resultats = {"parametre_calcul": parametres, "fait_intervention": chantiers}
        self.courant = None

    def execute(self, requete, *parametres):
        self.courant = next(v for k, v in self.resultats.items() if f"dw.{k}" in requete)

    def fetchall(self):
        return self.courant


def test_verifier():
    curseur = _Curseur(
        list(PARAMETRES.items()),
        [("interventions.csv", None, 2, "interventions.csv", None, 2, 1, 1)],
    )
    controles = []
    ecriture = SimpleNamespace(preparation=_preparation())
    sorties = SimpleNamespace(rattachements=SimpleNamespace(regles=[], lignes=pd.DataFrame()))
    regles = [{"type": "solde_jamais_negatif", "date_initial": dt.date(2025, 1, 1)}]
    verifier(curseur, ecriture, sorties, lambda *c: controles.append(c), regles)
    assert [c[1:] for c in controles] == [("2025-01-01", "2025-01-01"), (0, 0), ("0 / 0", "0 / 0")]


def test_verifier_sans_rattachements():
    curseur = _Curseur(list(PARAMETRES.items()), [])
    controles = []
    ecriture = SimpleNamespace(preparation=_preparation())
    verifier(curseur, ecriture, None, lambda *c: controles.append(c), [])
    assert controles[0][1:] == (None, "2025-01-01")
    assert controles[1][1:] == ("rattachements absents", None)


def test_modules_verification():
    modules = modules_verification(["services_intervention", "pack_sans_module"])
    assert [nom for nom, _ in modules] == ["services_intervention"]
    assert hasattr(modules[0][1], "verifier")
