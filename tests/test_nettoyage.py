"""Tests des règles de nettoyage (frigeo.nettoyage)."""

from collections import Counter
from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from frigeo.controles import _REPERTOIRE, VALEUR_MASQUEE, constats_encodage, controler
from frigeo.dictionnaire import MOTIF_SENSIBLE
from frigeo.nettoyage import (
    COLONNES_BILAN_NETTOYAGE,
    COLONNES_CATALOGUE_NETTOYAGE,
    COLONNES_JOURNAL,
    MAX_PASSES,
    RAISON_DESACCORD,
    RAISON_PASSES,
    RAISON_REMPLACEMENT,
    Reparation,
    catalogue_nettoyage,
    nettoyer,
    reparer_encodage,
)

AUCUNE_SENSIBLE = {}
AUCUNE_DECLARATION = {}
INSECABLE = chr(160)
REMPLACEMENT = chr(0xFFFD)
TOUS = ("cp1252", "iso8859_15", "latin_1")


def _mal(texte, encodage="cp1252", fois=1):
    """Texte écrit en UTF-8 puis relu dans l'encodage, `fois` fois de suite."""
    for _ in range(fois):
        texte = texte.encode("utf-8").decode(encodage)
    return texte


def _regle(regle, motif="motif fictif"):
    return {
        "regle": regle,
        "proposition": regle,
        "statut": "observé",
        "motif": motif,
        "a_arbitrer": {},
        "commentaire": "",
        "revu_le": None,
    }


def _colonne(nature="texte", motif_valeurs="motif fictif"):
    """Règles d'une colonne, sans contrôle; `motif_valeurs` permet de marquer la
    colonne sensible dans le dictionnaire."""
    valeurs = _regle("aucune", motif_valeurs)
    valeurs["liste"] = []
    format_ = _regle("aucune")
    format_["liste"] = []
    return {
        "obligatoire": _regle("facultatif"),
        "nature": _regle(nature),
        "valeurs": valeurs,
        "format": format_,
    }


def _table(fichier="t.csv", premiere_ligne=2, periode=None, **colonnes) -> pd.DataFrame:
    """Table fictive avec son lignage (première ligne de données en ligne 2) et, si
    demandé, sa période d'export."""
    nombre = len(next(iter(colonnes.values())))
    donnees = pd.DataFrame(colonnes, dtype=object)
    donnees.insert(0, "num_ligne_source", range(premiere_ligne, premiere_ligne + nombre))
    donnees.insert(0, "feuille_source", None)
    donnees.insert(0, "fichier_source", fichier)
    if periode is not None:
        donnees["periode_export"] = periode
    return donnees


def _dictionnaire(tables, **particulieres):
    """Dictionnaire qui décrit exactement les tables; `particulieres` remplace les
    règles d'une colonne (« table.colonne »)."""
    lignage = {"fichier_source", "feuille_source", "num_ligne_source", "periode_export"}
    return {
        table: {
            colonne: particulieres.get(f"{table}.{colonne}", _colonne())
            for colonne in donnees.columns
            if colonne not in lignage
        }
        for table, donnees in tables.items()
    }


def _lignes(tableau, *colonnes):
    return [tuple(ligne) for ligne in tableau[list(colonnes)].itertuples(index=False)]


# --- reparer_encodage ---------------------------------------------------------


def test_reparer_encodage_une_passe():
    assert reparer_encodage(_mal("Café du Port")) == Reparation("Café du Port", None, 1, TOUS)
    # L'apostrophe typographique n'est repérée qu'en Windows-1252.
    assert reparer_encodage(_mal("l’atelier")) == Reparation("l’atelier", None, 1, ("cp1252",))
    assert reparer_encodage(_mal("Crêperie", "latin_1")) == Reparation(
        "Crêperie", None, 1, TOUS
    )


def test_reparer_encodage_reunit_les_encodages():
    # `Ã©` est repéré par les trois encodages, `â€™` par Windows-1252 seul : les
    # réparations ne se contredisent pas, elles sont réunies en une passe.
    texte = _mal("Café l’atelier")
    assert reparer_encodage(texte) == Reparation("Café l’atelier", None, 1, TOUS)
    # Le reste du texte est gardé tel quel, même un caractère correct que
    # l'encodage ne connaît pas.
    # (`Ã‰` n'est repéré qu'en Windows-1252, où 0x89 est le signe pour mille.)
    assert reparer_encodage("→ " + _mal("Élise") + " ’") == Reparation(
        "→ Élise ’", None, 1, ("cp1252",)
    )


def test_reparer_encodage_plusieurs_passes():
    # Au plus 5 passes, valeur validée par Dominique le 19/10/2026.
    assert MAX_PASSES == 5
    for fois in range(2, 6):
        assert reparer_encodage(_mal("Crêperie Élise", fois=fois)) == Reparation(
            "Crêperie Élise", None, fois, TOUS
        )
    assert reparer_encodage(_mal("é", fois=6)) == Reparation(None, RAISON_PASSES, 5, TOUS)
    assert RAISON_PASSES == "séquence toujours présente après 5 passes"


def test_reparer_encodage_refus():
    # `Ã€` donne `À` en Windows-1252 et `ä` en ISO-8859-15.
    assert reparer_encodage("Ã€") == Reparation(
        None, RAISON_DESACCORD, 1, ("cp1252", "iso8859_15")
    )
    assert reparer_encodage("Caf" + _mal("é") + " Ã€") == Reparation(
        None, RAISON_DESACCORD, 1, ("cp1252", "iso8859_15", "latin_1")
    )
    # Une cellule qui contient le caractère de remplacement n'est pas touchée, même
    # si elle porte aussi une séquence réparable.
    assert reparer_encodage("perdu " + REMPLACEMENT) == Reparation(
        None, RAISON_REMPLACEMENT, 0, ()
    )
    assert reparer_encodage(_mal("Café ") + REMPLACEMENT) == Reparation(
        None, RAISON_REMPLACEMENT, 0, ()
    )


def test_reparer_encodage_textes_corrects_inchanges():
    for texte in ("Café", "CHÂTEAU", "SÃO PAULO", "café" + INSECABLE + "»", "abc", ""):
        assert reparer_encodage(texte) == Reparation(texte, None, 0, ()), texte


def test_aucune_reparation_fausse():
    # Chaque caractère du répertoire, écrit en UTF-8 puis relu dans chacun des trois
    # encodages, est soit rendu à l'identique, soit refusé pour désaccord : jamais
    # remplacé par un autre caractère.
    issues = Counter()
    for caractere in sorted(_REPERTOIRE):
        for encodage in TOUS:
            try:
                relu = _mal(caractere, encodage)
            except UnicodeDecodeError:
                continue
            reparation = reparer_encodage("a" + relu + "b")
            if reparation.texte is None:
                assert reparation.raison == RAISON_DESACCORD, (caractere, encodage)
                issues[(encodage, "refus")] += 1
            else:
                assert reparation.texte == "a" + caractere + "b", (caractere, encodage)
                assert constats_encodage(reparation.texte) == ()
                issues[(encodage, "réparé")] += 1
    assert issues == {
        ("cp1252", "réparé"): 109,
        ("cp1252", "refus"): 8,
        ("iso8859_15", "réparé"): 115,
        ("iso8859_15", "refus"): 8,
        ("latin_1", "réparé"): 123,
    }


# --- nettoyer -----------------------------------------------------------------


def _exemple():
    clients = _table(
        "clients.csv",
        code=["C1", "C2", "C3", "C4", "C5", "C6", "C7"],
        nom=[
            "Café",
            _mal("Café"),
            None,
            "  ",
            "perdu " + REMPLACEMENT,
            "Ã€",
            _mal("Crêperie", fois=2),
        ],
        ville=["Rouen", "Évreux", _mal("Évreux"), "Rouen", 12, datetime(2025, 3, 14), "Rouen"],
    )
    clients.index = range(10, 17)
    factures = _table("factures_2025.xlsx", periode="2025", num=["F1", "F2"],
                      libelle=[_mal("Forfait déplacement"), "Main d'oeuvre"],
                      montant=[31.85, 46.8])
    return {"clients": clients, "factures": factures}


def test_nettoyer_ne_modifie_pas_les_tables_recues():
    tables = _exemple()
    avant = deepcopy(tables)
    resultat = nettoyer(tables, _dictionnaire(tables), AUCUNE_SENSIBLE, AUCUNE_DECLARATION)
    for table, donnees in tables.items():
        pd.testing.assert_frame_equal(donnees, avant[table])
        nettoyee = resultat.tables[table]
        assert nettoyee is not donnees
        assert list(nettoyee.columns) == list(donnees.columns)
        assert list(nettoyee.index) == list(donnees.index)
        assert list(nettoyee.dtypes) == list(donnees.dtypes)
    clients = resultat.tables["clients"]
    # Seules les cellules corrigées changent.
    def pareilles(a, b):
        return a is b or a == b or (pd.isna(a) and pd.isna(b))

    differentes = [
        (index, colonne)
        for colonne in clients.columns
        for index in clients.index
        if not pareilles(clients.at[index, colonne], avant["clients"].at[index, colonne])
    ]
    assert differentes == [(11, "nom"), (16, "nom"), (12, "ville")]
    assert clients.at[11, "nom"] == "Café"
    assert clients.at[16, "nom"] == "Crêperie"
    assert clients.at[12, "ville"] == "Évreux"
    assert clients.at[14, "ville"] == 12
    assert clients.at[15, "ville"] == datetime(2025, 3, 14)
    assert resultat.tables["factures"].at[0, "libelle"] == "Forfait déplacement"
    assert resultat.tables["factures"].at[0, "montant"] == 31.85


def test_nettoyer_journal_et_bilan():
    tables = _exemple()
    declarations = {"clients": {"cle": ["code"]}, "factures": {"cle": ["num"]}}
    resultat = nettoyer(tables, _dictionnaire(tables), AUCUNE_SENSIBLE, declarations)
    journal, bilan = resultat.journal, resultat.bilan
    assert list(journal.columns) == list(COLONNES_JOURNAL)
    assert list(bilan.columns) == list(COLONNES_BILAN_NETTOYAGE)
    # Ordre : tables, puis lignes, puis colonnes.
    assert _lignes(
        journal, "regle_nettoyage", "table", "fichier_source", "feuille_source",
        "num_ligne_source", "periode_export", "cle", "colonne", "action", "source",
    ) == [
        ("encodage", "clients", "clients.csv", None, 3, None, "C2", "nom",
         "valeur modifiée", "règle générique"),
        ("encodage", "clients", "clients.csv", None, 4, None, "C3", "ville",
         "valeur modifiée", "règle générique"),
        ("encodage", "clients", "clients.csv", None, 8, None, "C7", "nom",
         "valeur modifiée", "règle générique"),
        ("encodage", "factures", "factures_2025.xlsx", None, 2, "2025", "F1", "libelle",
         "valeur modifiée", "règle générique"),
    ]
    assert _lignes(journal, "valeur_avant", "valeur_apres", "detail") == [
        (_mal("Café"), "Café", "repéré en cp1252, iso8859_15, latin_1; 1 passe"),
        (_mal("Évreux"), "Évreux", "repéré en cp1252; 1 passe"),
        (_mal("Crêperie", fois=2), "Crêperie",
         "repéré en cp1252, iso8859_15, latin_1; 2 passes"),
        (_mal("Forfait déplacement"), "Forfait déplacement",
         "repéré en cp1252, iso8859_15, latin_1; 1 passe"),
    ]
    # Une ligne par colonne qui a au moins une cellule visée : les cellules que la
    # règle encodage de l'étape 3 signale, caractère de remplacement compris.
    assert _lignes(bilan, *COLONNES_BILAN_NETTOYAGE) == [
        ("encodage", "clients", "nom", 4, 2, 2,
         "caractère de remplacement 1; encodages en désaccord 1"),
        ("encodage", "clients", "ville", 1, 1, 0, None),
        ("encodage", "factures", "libelle", 1, 1, 0, None),
    ]


def test_nettoyer_cellules_visees_identiques():
    # Une même valeur répétée est réparée une fois par cellule, chacune au journal.
    tables = {"t": _table(nom=[_mal("Café"), "x", _mal("Café")], code=["a", "b", "c"])}
    resultat = nettoyer(tables, _dictionnaire(tables), AUCUNE_SENSIBLE, {"t": {"cle": ["code"]}})
    assert list(resultat.tables["t"]["nom"]) == ["Café", "x", "Café"]
    assert _lignes(resultat.journal, "num_ligne_source", "cle") == [(2, "a"), (4, "c")]
    assert _lignes(resultat.bilan, "visees", "corrigees") == [(2, 2)]


def test_nettoyer_colonnes_sensibles_masquees():
    tables = {
        "t": _table(
            code=["a", "b"],
            nom=[_mal("Café"), "x"],
            adresse=[_mal("rue Élise"), "y"],
            ville=[_mal("Évreux"), "z"],
        )
    }
    dictionnaire = _dictionnaire(tables, **{"t.adresse": _colonne(motif_valeurs=MOTIF_SENSIBLE)})
    sensibles = {"t": frozenset({"nom"})}
    resultat = nettoyer(tables, dictionnaire, sensibles, {"t": {"cle": ["code"]}})
    # Les cellules sensibles sont corrigées comme les autres, mais leurs valeurs sont
    # masquées au journal (classification ou dictionnaire).
    assert list(resultat.tables["t"].loc[0, ["nom", "adresse", "ville"]]) == [
        "Café", "rue Élise", "Évreux"
    ]
    assert _lignes(resultat.journal, "colonne", "cle", "valeur_avant", "valeur_apres") == [
        ("nom", "a", VALEUR_MASQUEE, VALEUR_MASQUEE),
        ("adresse", "a", VALEUR_MASQUEE, VALEUR_MASQUEE),
        ("ville", "a", _mal("Évreux"), "Évreux"),
    ]
    # Une clé dont une colonne est sensible est masquée.
    resultat = nettoyer(tables, dictionnaire, {"t": frozenset({"code"})}, {"t": {"cle": ["code"]}})
    assert set(resultat.journal["cle"]) == {VALEUR_MASQUEE}
    assert _lignes(resultat.journal, "colonne", "valeur_apres") == [
        ("nom", "Café"), ("adresse", VALEUR_MASQUEE), ("ville", "Évreux"),
    ]


def test_nettoyer_cle_composee_ou_absente():
    tables = {"t": _table(a=["1", "1"], b=["x", "y"], nom=["n", _mal("é")])}
    resultat = nettoyer(tables, _dictionnaire(tables), AUCUNE_SENSIBLE, {"t": {"cle": ["a", "b"]}})
    assert _lignes(resultat.journal, "cle", "periode_export") == [("1 | y", None)]
    resultat = nettoyer(tables, _dictionnaire(tables), AUCUNE_SENSIBLE, AUCUNE_DECLARATION)
    assert _lignes(resultat.journal, "cle") == [(None,)]


def test_nettoyer_sans_cellule_visee():
    tables = {"t": _table(nom=["Café", "CHÂTEAU", None], n=[1, 2, 3])}
    resultat = nettoyer(tables, _dictionnaire(tables), AUCUNE_SENSIBLE, AUCUNE_DECLARATION)
    assert resultat.journal.empty and list(resultat.journal.columns) == list(COLONNES_JOURNAL)
    assert resultat.bilan.empty
    assert list(resultat.bilan.columns) == list(COLONNES_BILAN_NETTOYAGE)
    pd.testing.assert_frame_equal(resultat.tables["t"], tables["t"])


def test_nettoyer_verifie_sensibilite_et_dictionnaire():
    tables = {"t": _table(nom=[_mal("Café")])}
    with pytest.raises(RuntimeError, match="sensibilité incohérente"):
        nettoyer(tables, _dictionnaire(tables), {"t": frozenset({"absente"})}, {})
    dictionnaire = _dictionnaire(tables)
    del dictionnaire["t"]["nom"]
    with pytest.raises(ValueError, match="à régénérer"):
        nettoyer(tables, dictionnaire, AUCUNE_SENSIBLE, {})
    dictionnaire = _dictionnaire(tables)
    del dictionnaire["t"]["nom"]["format"]
    with pytest.raises(ValueError, match="Dictionnaire invalide"):
        nettoyer(tables, dictionnaire, AUCUNE_SENSIBLE, {})


def test_catalogue_nettoyage():
    catalogue = catalogue_nettoyage()
    assert list(catalogue.columns) == list(COLONNES_CATALOGUE_NETTOYAGE)
    assert _lignes(catalogue, "rang", "regle_nettoyage", "source") == [
        (1, "encodage", "règle générique"),
        (2, "remplacement", "dictionnaire"),
    ]
    assert "caractère de remplacement" in catalogue.at[0, "ne_corrige_jamais"]
    assert "hors liste" in catalogue.at[1, "ne_corrige_jamais"]


# --- remplacement -------------------------------------------------------------


def _valeur(valeur, statut="valide", origine="liste proposée", effectif=1, remplacement=None,
            revu_le="2026-10-08 13:05:11"):
    return {
        "valeur": valeur,
        "origine": origine,
        "effectif": effectif,
        "statut": statut,
        "commentaire": "",
        "revu_le": None if statut == "observé" else revu_le,
        "remplacement": remplacement,
    }


def _liste(*elements, regle="liste fermée", motif="motif fictif"):
    """Colonne dont la règle `valeurs` porte la liste donnée, revue par le métier."""
    colonne = _colonne()
    colonne["valeurs"] = {
        **_regle(regle, motif),
        "statut": "valide",
        "revu_le": "2026-10-08 13:05:11",
        "liste": list(elements),
    }
    return colonne


LISTE_CATEGORIES = (
    _valeur("Dépannage"),
    _valeur("Maintenance"),
    _valeur("depannage", "invalide", remplacement="Dépannage"),
    _valeur("Dépanage", "invalide", remplacement="Dépannage", revu_le="2026-10-09 18:50:53"),
    _valeur("DEP", "invalide"),
    _valeur("12", "invalide", remplacement="Maintenance"),
    _valeur("Maint", "observé", origine="à arbitrer"),
)


def test_remplacement_des_valeurs_invalidees():
    tables = {
        "t": _table(
            code=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
            categorie=["Dépannage", "depannage", "DEP", "Autre", "Maint", None, "  ", 12,
                       "Dépanage", "depannage"],
        )
    }
    dictionnaire = _dictionnaire(tables, **{"t.categorie": _liste(*LISTE_CATEGORIES)})
    resultat = nettoyer(tables, dictionnaire, AUCUNE_SENSIBLE, {"t": {"cle": ["code"]}})
    assert list(resultat.tables["t"]["categorie"]) == [
        "Dépannage", "Dépannage", "DEP", "Autre", "Maint", None, "  ", 12, "Dépannage",
        "Dépannage",
    ]
    assert list(tables["t"]["categorie"])[1] == "depannage"
    assert _lignes(
        resultat.journal, "regle_nettoyage", "num_ligne_source", "cle", "colonne", "action",
        "source", "valeur_avant", "valeur_apres", "detail",
    ) == [
        ("remplacement", 3, "b", "categorie", "valeur modifiée", "dictionnaire", "depannage",
         "Dépannage", "valeur invalidée le 2026-10-08"),
        ("remplacement", 10, "i", "categorie", "valeur modifiée", "dictionnaire", "Dépanage",
         "Dépannage", "valeur invalidée le 2026-10-09"),
        ("remplacement", 11, "j", "categorie", "valeur modifiée", "dictionnaire", "depannage",
         "Dépannage", "valeur invalidée le 2026-10-08"),
    ]
    # Valeurs visées : invalides ou hors liste; « Maint », à arbitrer, ne l'est pas,
    # ni les cellules vides. La cellule 12 (nombre) n'est pas remplacée par un texte.
    assert _lignes(resultat.bilan, *COLONNES_BILAN_NETTOYAGE) == [
        ("remplacement", "t", "categorie", 6, 3, 3,
         "valeur invalidée sans remplacement 1; valeur hors liste 1; valeur non textuelle 1"),
    ]
    # Mêmes cellules que les anomalies de la règle valeurs à l'étape 3.
    ecarts, _ = controler(tables, dictionnaire, AUCUNE_SENSIBLE, {})
    visees = ecarts[(ecarts["regle"] == "valeurs") & (ecarts["issue"] == "anomalie")]
    assert len(visees) == 6
    # Après nettoyage, il ne reste que les trois non corrigées.
    ecarts, _ = controler(resultat.tables, dictionnaire, AUCUNE_SENSIBLE, {})
    restantes = ecarts[(ecarts["regle"] == "valeurs") & (ecarts["issue"] == "anomalie")]
    assert list(restantes["num_ligne_source"]) == [4, 5, 9]


def test_remplacement_seulement_pour_une_liste_fermee():
    # Une liste écartée (règle « aucune ») ne donne ni contrôle ni remplacement, même
    # si elle garde des valeurs invalidées avec leur remplacement.
    tables = {"t": _table(categorie=["depannage", "Autre"])}
    colonne = _liste(*LISTE_CATEGORIES, regle="aucune")
    colonne["valeurs"]["statut"] = "observé"
    colonne["valeurs"]["revu_le"] = None
    dictionnaire = _dictionnaire(tables, **{"t.categorie": colonne})
    resultat = nettoyer(tables, dictionnaire, AUCUNE_SENSIBLE, AUCUNE_DECLARATION)
    assert resultat.journal.empty and resultat.bilan.empty
    assert list(resultat.tables["t"]["categorie"]) == ["depannage", "Autre"]


def test_remplacement_apres_reparation_de_l_encodage():
    # La règle remplacement s'applique à la valeur laissée par la règle encodage.
    # Le journal suit l'ordre des règles, puis des lignes.
    tables = {"t": _table(categorie=["depannage", _mal("Dépanage"), "Dépannage"])}
    dictionnaire = _dictionnaire(tables, **{"t.categorie": _liste(*LISTE_CATEGORIES)})
    resultat = nettoyer(tables, dictionnaire, AUCUNE_SENSIBLE, AUCUNE_DECLARATION)
    assert list(resultat.tables["t"]["categorie"]) == ["Dépannage"] * 3
    assert _lignes(
        resultat.journal, "regle_nettoyage", "num_ligne_source", "source", "valeur_avant",
        "valeur_apres",
    ) == [
        ("encodage", 3, "règle générique", _mal("Dépanage"), "Dépanage"),
        ("remplacement", 2, "dictionnaire", "depannage", "Dépannage"),
        ("remplacement", 3, "dictionnaire", "Dépanage", "Dépannage"),
    ]
    assert _lignes(resultat.bilan, "regle_nettoyage", "visees", "corrigees") == [
        ("encodage", 1, 1),
        ("remplacement", 2, 2),
    ]


def test_remplacement_sur_colonne_sensible_masque():
    sensibles_liste = [
        _valeur("Démission", "documenté", effectif=None, origine="ajoutée"),
        _valeur("demission", "invalide", effectif=None, origine="observée",
                remplacement="Démission"),
    ]
    tables = {"t": _table(code=["a", "b"], motif=["demission", "Démission"])}
    colonne = _liste(*sensibles_liste, motif=MOTIF_SENSIBLE)
    dictionnaire = _dictionnaire(tables, **{"t.motif": colonne})
    resultat = nettoyer(tables, dictionnaire, AUCUNE_SENSIBLE, {"t": {"cle": ["code"]}})
    assert list(resultat.tables["t"]["motif"]) == ["Démission", "Démission"]
    assert _lignes(resultat.journal, "cle", "valeur_avant", "valeur_apres", "detail") == [
        ("a", VALEUR_MASQUEE, VALEUR_MASQUEE, "valeur invalidée le 2026-10-08"),
    ]
