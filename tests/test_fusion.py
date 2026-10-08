"""Tests de la fusion d'une régénération avec le dictionnaire en place (frigeo.fusion)."""

from copy import deepcopy

import pytest

from frigeo.dictionnaire import (
    charger_dictionnaire,
    charger_meta,
    dossier_sauvegardes,
    ecrire_dictionnaire,
)
from frigeo.fusion import fusionner

DATE = "2026-10-08"


def _regle(proposition, a_arbitrer=None, motif="motif fictif"):
    return {
        "regle": proposition,
        "proposition": proposition,
        "statut": "observé",
        "motif": motif,
        "a_arbitrer": a_arbitrer or {},
        "commentaire": "",
        "revu_le": None,
    }


def _valeur(valeur, origine="liste proposée", effectif=10):
    return {
        "valeur": valeur,
        "origine": origine,
        "effectif": effectif,
        "statut": "observé",
        "commentaire": "",
        "revu_le": None,
        "remplacement": None,
    }


def _colonne(obligatoire="obligatoire", liste=None):
    """Colonne générée, avec une liste fermée si `liste` est donnée."""
    liste = liste or []
    rares = sum(v["origine"] == "à arbitrer" for v in liste)
    valeurs = _regle("liste fermée" if liste else "aucune", {"valeurs": rares} if liste else {})
    valeurs["liste"] = liste
    return {
        "obligatoire": _regle(obligatoire, {"vides": 0}),
        "nature": _regle("texte", {"hors_nature": 0}),
        "valeurs": valeurs,
    }


def _genere():
    return {
        "clients": {
            "statut": _colonne(
                liste=[
                    _valeur("Actif", effectif=700),
                    _valeur("Inactif", effectif=290),
                    _valeur("actif", "à arbitrer", 6),
                    _valeur("Actf", "à arbitrer", 4),
                ]
            ),
            "ville": _colonne(),
        }
    }


def _decider(element, statut, **champs):
    element.update(statut=statut, revu_le=DATE, **champs)


def _valeurs(dictionnaire, colonne="statut"):
    return {v["valeur"]: v for v in dictionnaire["clients"][colonne]["valeurs"]["liste"]}


def _evenements(rapport):
    return [
        (ligne.colonne, ligne.regle, ligne.valeur, ligne.evenement, ligne.niveau)
        for ligne in rapport.itertuples()
    ]


def test_sans_decision_et_sans_changement_la_fusion_rend_la_regeneration():
    fusion, rapport = fusionner(_genere(), _genere())
    assert fusion == _genere()
    assert rapport.empty
    assert list(rapport.columns) == ["table", "colonne", "regle", "valeur", "evenement", "niveau"]


def test_les_dictionnaires_fournis_ne_sont_pas_modifies():
    existant, regenere = _genere(), _genere()
    _decider(existant["clients"]["statut"]["obligatoire"], "valide")
    regenere["clients"]["statut"]["valeurs"]["liste"].pop()
    copies = deepcopy(existant), deepcopy(regenere)
    fusion, _ = fusionner(existant, regenere)
    assert (existant, regenere) == copies
    # Le résultat ne partage aucun objet avec les entrées.
    fusion["clients"]["statut"]["obligatoire"]["a_arbitrer"]["vides"] = 99
    fusion["clients"]["ville"]["nature"]["motif"] = "modifié"
    assert (existant, regenere) == copies


def test_regle_non_revue_remplacee_par_la_nouvelle_proposition():
    regenere = _genere()
    regenere["clients"]["ville"]["obligatoire"] = _regle("facultatif", motif="3.00 % de vides")
    fusion, rapport = fusionner(_genere(), regenere)
    regle = fusion["clients"]["ville"]["obligatoire"]
    assert (regle["regle"], regle["proposition"]) == ("facultatif", "facultatif")
    assert regle["motif"] == "3.00 % de vides"
    assert _evenements(rapport) == [
        ("ville", "obligatoire", "", "proposition changée", "information")
    ]


def test_regle_revue_conservee_et_divergence_signalee():
    existant, regenere = _genere(), _genere()
    _decider(existant["clients"]["ville"]["obligatoire"], "valide", commentaire="vu avec la direction")
    regenere["clients"]["ville"]["obligatoire"] = _regle(
        "facultatif", {"vides": 30}, motif="3.00 % de vides"
    )
    fusion, rapport = fusionner(existant, regenere)
    regle = fusion["clients"]["ville"]["obligatoire"]
    # La décision reste, l'observation est mise à jour.
    assert regle == {
        "regle": "obligatoire",
        "proposition": "facultatif",
        "statut": "valide",
        "motif": "3.00 % de vides",
        "a_arbitrer": {"vides": 30},
        "commentaire": "vu avec la direction",
        "revu_le": DATE,
    }
    assert _evenements(rapport) == [
        ("ville", "obligatoire", "",
         "nouvelle proposition différente de la règle en vigueur", "à regarder")
    ]
    # Au mois suivant, la même proposition n'est pas signalée une seconde fois.
    fusion, rapport = fusionner(fusion, regenere)
    assert fusion["clients"]["ville"]["obligatoire"] == regle
    assert rapport.empty


def test_regle_documentee_que_la_proposition_rejoint():
    existant, regenere = _genere(), _genere()
    existant["clients"]["ville"]["obligatoire"] = _regle("à décider")
    _decider(existant["clients"]["ville"]["obligatoire"], "documenté", regle="obligatoire")
    fusion, rapport = fusionner(existant, regenere)
    assert fusion["clients"]["ville"]["obligatoire"]["statut"] == "documenté"
    assert _evenements(rapport) == [
        ("ville", "obligatoire", "", "proposition changée", "information")
    ]


def test_valeurs_nouvelle_supprimee_et_effectifs_mis_a_jour():
    existant, regenere = _genere(), _genere()
    liste = regenere["clients"]["statut"]["valeurs"]["liste"]
    liste[0]["effectif"] = 800
    del liste[3]  # « Actf » n'est plus observée et n'a pas été revue.
    liste.append(_valeur("Radié", "à arbitrer", 2))
    fusion, rapport = fusionner(existant, regenere)
    assert fusion == regenere
    assert _evenements(rapport) == [
        ("statut", "valeurs", "Radié", "valeur nouvelle", "information"),
        ("statut", "valeurs", "Actf", "valeur non revue supprimée", "information"),
    ]


def test_valeur_revue_conservee_meme_si_elle_n_est_plus_observee():
    existant, regenere = _genere(), _genere()
    anciennes = _valeurs(existant)
    _decider(anciennes["Actif"], "valide")
    _decider(anciennes["Actf"], "invalide", remplacement="Actif", commentaire="faute de frappe")
    del regenere["clients"]["statut"]["valeurs"]["liste"][3]
    fusion, rapport = fusionner(existant, regenere)
    liste = fusion["clients"]["statut"]["valeurs"]["liste"]
    # L'ordre de la génération, puis la valeur conservée.
    assert [v["valeur"] for v in liste] == ["Actif", "Inactif", "actif", "Actf"]
    assert liste[3] == {
        "valeur": "Actf",
        "origine": "à arbitrer",
        "effectif": 0,
        "statut": "invalide",
        "commentaire": "faute de frappe",
        "revu_le": DATE,
        "remplacement": "Actif",
    }
    assert _evenements(rapport) == [
        ("statut", "valeurs", "Actf", "valeur revue qui n'est plus observée", "à regarder")
    ]
    # Déjà à zéro au mois suivant : plus de signalement.
    assert fusionner(fusion, regenere)[1].empty


def test_origine_suit_la_generation_sauf_pour_une_valeur_ajoutee():
    existant, regenere = _genere(), _genere()
    anciennes = _valeurs(existant)
    _decider(anciennes["actif"], "invalide")
    ajout = _valeur("En sommeil", "ajoutée", 0)
    _decider(ajout, "documenté")
    existant["clients"]["statut"]["valeurs"]["liste"].append(ajout)
    nouvelles = _valeurs(regenere)
    nouvelles["actif"].update(origine="liste proposée", effectif=60)
    regenere["clients"]["statut"]["valeurs"]["liste"].append(_valeur("En sommeil", "à arbitrer", 3))
    fusion, rapport = fusionner(existant, regenere)
    valeurs = _valeurs(fusion)
    assert (valeurs["actif"]["origine"], valeurs["actif"]["statut"]) == ("liste proposée", "invalide")
    assert valeurs["actif"]["effectif"] == 60
    assert valeurs["En sommeil"]["origine"] == "ajoutée"
    assert valeurs["En sommeil"]["statut"] == "documenté"
    assert valeurs["En sommeil"]["effectif"] == 3
    assert _evenements(rapport) == [
        ("statut", "valeurs", "actif", "origine changée", "information")
    ]


def test_valeur_ajoutee_non_observee_reste_a_zero_sans_signalement():
    existant = _genere()
    ajout = _valeur("En sommeil", "ajoutée", 0)
    _decider(ajout, "documenté")
    existant["clients"]["statut"]["valeurs"]["liste"].append(ajout)
    fusion, rapport = fusionner(existant, _genere())
    assert _valeurs(fusion)["En sommeil"] == ajout
    assert rapport.empty


def test_liste_qui_n_est_plus_proposee():
    existant, regenere = _genere(), _genere()
    _decider(_valeurs(existant)["Actif"], "valide")
    regenere["clients"]["statut"] = _colonne()
    fusion, rapport = fusionner(existant, regenere)
    valeurs = fusion["clients"]["statut"]["valeurs"]
    assert (valeurs["regle"], valeurs["proposition"]) == ("aucune", "aucune")
    # Seule la valeur revue reste, avec son dernier effectif connu.
    assert [(v["valeur"], v["effectif"]) for v in valeurs["liste"]] == [("Actif", 700)]
    assert _evenements(rapport) == [
        ("statut", "valeurs", "", "proposition changée", "information"),
        ("statut", "valeurs", "Inactif", "valeur non revue supprimée", "information"),
        ("statut", "valeurs", "actif", "valeur non revue supprimée", "information"),
        ("statut", "valeurs", "Actf", "valeur non revue supprimée", "information"),
        ("statut", "valeurs", "",
         "liste qui n'est plus proposée : 1 valeurs conservées, effectif non mis à jour",
         "information"),
    ]


def test_liste_validee_qui_n_est_plus_proposee_garde_toutes_ses_valeurs():
    existant, regenere = _genere(), _genere()
    _decider(existant["clients"]["statut"]["valeurs"], "valide")
    regenere["clients"]["statut"] = _colonne()
    fusion, rapport = fusionner(existant, regenere)
    valeurs = fusion["clients"]["statut"]["valeurs"]
    assert (valeurs["regle"], valeurs["proposition"]) == ("liste fermée", "aucune")
    assert valeurs["liste"] == existant["clients"]["statut"]["valeurs"]["liste"]
    assert _evenements(rapport) == [
        ("statut", "valeurs", "",
         "nouvelle proposition différente de la règle en vigueur", "à regarder"),
        ("statut", "valeurs", "",
         "liste qui n'est plus proposée : 4 valeurs conservées, effectif non mis à jour",
         "information"),
    ]


def test_liste_nouvellement_proposee_sans_un_evenement_par_valeur():
    existant = _genere()
    ajout = _valeur("Lyon", "ajoutée", 0)
    _decider(ajout, "documenté")
    existant["clients"]["ville"]["valeurs"]["liste"].append(ajout)
    regenere = _genere()
    regenere["clients"]["ville"] = _colonne(liste=[_valeur("Gisors"), _valeur("Evreux")])
    fusion, rapport = fusionner(existant, regenere)
    assert [v["valeur"] for v in _valeurs(fusion, "ville").values()] == ["Gisors", "Evreux", "Lyon"]
    assert _evenements(rapport) == [
        ("ville", "valeurs", "", "proposition changée", "information")
    ]


def test_colonnes_nouvelle_absente_conservee_et_absente_supprimee():
    existant, regenere = _genere(), _genere()
    existant["clients"]["ancienne"] = _colonne()
    existant["archives"] = {"code": _colonne(), "libelle": _colonne()}
    _decider(existant["archives"]["code"]["nature"], "valide")
    del regenere["clients"]["ville"]
    _decider(existant["clients"]["ville"]["valeurs"], "invalide", commentaire="texte libre")
    regenere["clients"]["pays"] = _colonne()
    regenere["contrats"] = {"numero": _colonne()}
    fusion, rapport = fusionner(existant, regenere)
    assert {table: list(colonnes) for table, colonnes in fusion.items()} == {
        "clients": ["statut", "pays", "ville"],
        "contrats": ["numero"],
        "archives": ["code"],
    }
    assert fusion["clients"]["ville"] == existant["clients"]["ville"]
    conservee = "colonne absente de la régénération, conservée avec ses décisions"
    assert [(l.table, l.colonne, l.evenement, l.niveau) for l in rapport.itertuples()] == [
        ("clients", "ville", conservee, "à regarder"),
        ("archives", "code", conservee, "à regarder"),
        ("clients", "pays", "colonne nouvelle", "information"),
        ("contrats", "numero", "colonne nouvelle", "information"),
        ("clients", "ancienne", "colonne absente de la régénération, supprimée", "information"),
        ("archives", "libelle", "colonne absente de la régénération, supprimée", "information"),
    ]


def test_le_dictionnaire_fusionne_passe_les_controles_du_fichier(tmp_path):
    existant, regenere = _genere(), _genere()
    anciennes = _valeurs(existant)
    _decider(anciennes["Actif"], "valide")
    _decider(anciennes["Actf"], "invalide", remplacement="Actif")
    _decider(existant["clients"]["statut"]["valeurs"], "valide")
    _decider(existant["clients"]["ville"]["obligatoire"], "valide")
    del regenere["clients"]["statut"]["valeurs"]["liste"][3]
    regenere["clients"]["ville"]["obligatoire"] = _regle("facultatif")
    fusion, _ = fusionner(existant, regenere)
    chemin = ecrire_dictionnaire(fusion, "2026-04", tmp_path / "dictionnaire.yaml")
    assert charger_dictionnaire(chemin) == fusion


def test_la_fusion_remplace_le_dictionnaire_revu_la_regeneration_seule_non(tmp_path):
    chemin = tmp_path / "dictionnaire.yaml"
    existant, regenere = _genere(), _genere()
    _decider(_valeurs(existant)["Actif"], "valide")
    _decider(existant["clients"]["ville"]["obligatoire"], "valide", commentaire="confirmé")
    ecrire_dictionnaire(existant, "2026-03", chemin)
    avant = chemin.read_bytes()
    # Mois suivant : la proposition change et une valeur n'est plus observée.
    del regenere["clients"]["statut"]["valeurs"]["liste"][0]
    regenere["clients"]["ville"]["obligatoire"] = _regle("facultatif")

    with pytest.raises(ValueError, match="écriture refusée, 2 décisions") as erreur:
        ecrire_dictionnaire(regenere, "2026-04", chemin)
    assert str(erreur.value).splitlines()[1:] == [
        "  clients.statut, valeur 'Actif' : décision (valide) absente",
        (
            "  clients.ville, règle obligatoire : statut 'valide' devenu 'observé', regle "
            "'obligatoire' devenu 'facultatif', commentaire 'confirmé' devenu '', revu_le "
            "'2026-10-08' devenu None"
        ),
    ]
    assert chemin.read_bytes() == avant
    assert not dossier_sauvegardes(chemin).exists()

    fusion, _ = fusionner(existant, regenere)
    ecrire_dictionnaire(fusion, "2026-04", chemin)
    assert charger_dictionnaire(chemin) == fusion
    assert charger_meta(chemin)["periode_fin"] == "2026-04"
    copies = list(dossier_sauvegardes(chemin).iterdir())
    assert len(copies) == 1 and copies[0].name.startswith("dictionnaire_2026-03_")
    assert copies[0].read_bytes() == avant
