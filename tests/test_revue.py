"""Tests de l'export et de l'import du classeur de revue (frigeo.revue)."""

import pytest
from openpyxl import load_workbook

from frigeo.revue import (
    COLONNES_REGLES,
    COLONNES_VALEURS,
    LIGNES_AJOUT,
    exporter_revue,
    importer_revue,
    lignes_regles,
    lignes_valeurs,
)

PIEGES = ["076", "27", "2026-03-01", "=1+1", "Non", "Gisors  ", "a b"]


def _regle(regle, a_arbitrer, statut="observé"):
    return {
        "regle": regle,
        "proposition": regle,
        "statut": statut,
        "motif": "motif fictif",
        "a_arbitrer": a_arbitrer,
        "commentaire": "",
        "revu_le": None,
    }


def _valeur(valeur, origine, effectif):
    return {
        "valeur": valeur,
        "origine": origine,
        "effectif": effectif,
        "statut": "observé",
        "commentaire": "",
        "revu_le": None,
        "remplacement": None,
    }


def _colonne(valeurs=None, a_arbitrer=None, vides=0, hors_nature=0):
    """Colonne avec une liste fermée si `valeurs` est donnée (effectif 10 par valeur)."""
    a_arbitrer = a_arbitrer or {}
    liste = _regle(
        "liste fermée" if valeurs else "aucune",
        {"valeurs": len(a_arbitrer)} if valeurs else {},
    )
    liste["liste"] = [_valeur(v, "liste proposée", 10) for v in valeurs or []] + [
        _valeur(v, "à arbitrer", n) for v, n in a_arbitrer.items()
    ]
    return {
        "obligatoire": _regle("obligatoire", {"vides": vides}),
        "nature": _regle("texte", {"hors_nature": hors_nature}),
        "valeurs": liste,
    }


def _dictionnaire():
    duree = _colonne()
    duree["obligatoire"] = _regle("à décider", {"vides": 1})
    duree["nature"] = _regle(
        "à décider", {"nature_dominante": "entier (texte)", "hors_nature": 40}
    )
    return {
        "clients": {
            "statut": _colonne(["Actif", "Inactif"], {"actif": 3}, vides=5),
            "code": _colonne(PIEGES),
            "type_commerce": _colonne(),
        },
        "interventions": {"duree": duree},
    }


def _lire(feuille):
    lignes = list(feuille.iter_rows(values_only=True))
    return [dict(zip(lignes[0], ligne)) for ligne in lignes[1:] if any(v is not None for v in ligne)]


def test_lignes_regles():
    lignes = lignes_regles(_dictionnaire())
    cles = [(l["table"], l["colonne"], l["regle"]) for l in lignes]
    # Deux lignes par colonne, plus une ligne « valeurs » par liste proposée.
    assert len(lignes) == 4 * 2 + 2
    assert ("clients", "statut", "valeurs") in cles
    assert ("clients", "type_commerce", "valeurs") not in cles
    par_cle = dict(zip(cles, lignes))
    assert par_cle[("clients", "statut", "obligatoire")]["nb_a_arbitrer"] == 5
    assert par_cle[("clients", "statut", "valeurs")]["proposition"] == "liste de 2 valeurs"
    assert par_cle[("clients", "statut", "valeurs")]["nb_a_arbitrer"] == 1
    # Le nom de la nature dominante n'est pas compté comme un écart.
    assert par_cle[("interventions", "duree", "nature")]["nb_a_arbitrer"] == 40


def test_lignes_valeurs():
    lignes = lignes_valeurs(_dictionnaire())
    assert len(lignes) == 3 + len(PIEGES)
    assert {l["colonne"] for l in lignes} == {"statut", "code"}
    # L'effectif et l'origine viennent du dictionnaire.
    assert [l["effectif"] for l in lignes[:3]] == [10, 10, 3]
    assert [l["origine"] for l in lignes[:3]] == ["liste proposée", "liste proposée", "à arbitrer"]
    remarques = {l["valeur"]: l["remarque"] for l in lignes}
    assert remarques["Gisors  "] == "espaces en bord"
    assert remarques["a\u00a0b"] == "espace insécable"
    assert remarques["Actif"] == ""


def test_statut_propre_a_chaque_valeur():
    dictionnaire = _dictionnaire()
    liste = dictionnaire["clients"]["statut"]["valeurs"]["liste"]
    liste[2].update(statut="invalide", revu_le="2026-10-08")
    lignes = lignes_valeurs(dictionnaire)
    assert [l["statut"] for l in lignes[:3]] == ["observé", "observé", "invalide"]


def test_classeur_ecrit_et_relu(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue" / "revue.xlsx")
    classeur = load_workbook(chemin)
    assert classeur.sheetnames == ["mode_emploi", "regles", "valeurs"]
    regles, valeurs = classeur["regles"], classeur["valeurs"]
    assert tuple(c.value for c in regles[1]) == COLONNES_REGLES
    assert tuple(c.value for c in valeurs[1]) == COLONNES_VALEURS
    assert len(_lire(regles)) == 10
    assert {l["statut"] for l in _lire(regles)} == {"observé"}
    notice = " ".join(str(c.value) for c in classeur["mode_emploi"]["A"] if c.value)
    assert "2026-03" in notice
    assert "10 lignes" in notice
    assert "réimporté" in notice


def test_valeurs_conservees_comme_texte(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    lues = [l for l in _lire(load_workbook(chemin)["valeurs"]) if l["colonne"] == "code"]
    assert [l["valeur"] for l in lues] == PIEGES
    assert all(isinstance(l["valeur"], str) for l in lues)


def test_protection_et_menus(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    classeur = load_workbook(chemin)
    regles, valeurs = classeur["regles"], classeur["valeurs"]
    assert regles.protection.sheet and valeurs.protection.sheet
    assert classeur["mode_emploi"].protection.sheet
    # Feuille des règles : seules statut, regle_retenue et commentaire sont libres.
    libres = {c.value for c, d in zip(regles[1], regles[2]) if not d.protection.locked}
    assert libres == {"statut", "regle_retenue", "commentaire"}
    # Sur une ligne « valeurs », regle_retenue reste verrouillée.
    ligne = next(l for l in regles.iter_rows(min_row=2) if l[2].value == "valeurs")
    assert ligne[COLONNES_REGLES.index("regle_retenue")].protection.locked
    libres = {c.value for c, d in zip(valeurs[1], valeurs[2]) if not d.protection.locked}
    assert libres == {"statut", "commentaire"}
    # Lignes d'ajout en bas de la feuille des valeurs.
    ajout = valeurs[3 + len(PIEGES) + 2]
    libres = {c.value for c, d in zip(valeurs[1], ajout) if not d.protection.locked}
    assert libres == {"table", "colonne", "valeur", "statut", "commentaire"}
    assert valeurs.max_row == 1 + 3 + len(PIEGES) + LIGNES_AJOUT
    menus = [m.formula1 for m in regles.data_validations.dataValidation]
    assert '"observé,valide,invalide,documenté"' in menus
    assert '"obligatoire,facultatif,toujours vide"' in menus
    assert all(len(m) <= 255 for m in menus)
    assert len(valeurs.data_validations.dataValidation) == 1


def test_colonne_sans_liste_absente_de_la_feuille_des_valeurs(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    colonnes = {l["colonne"] for l in _lire(load_workbook(chemin)["valeurs"])}
    assert "type_commerce" not in colonnes


def test_export_refuse_d_ecraser_un_classeur_existant(tmp_path):
    chemin = exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")
    with pytest.raises(FileExistsError, match="existe déjà"):
        exporter_revue(_dictionnaire(), "2026-03", chemin)
    exporter_revue(_dictionnaire(), "2026-03", chemin, ecraser=True)


def _exporter(tmp_path):
    return exporter_revue(_dictionnaire(), "2026-03", tmp_path / "revue.xlsx")


def _ligne(feuille, **cles):
    """Numéro de la ligne Excel dont les cellules nommées ont les valeurs données."""
    entete = [c.value for c in feuille[1]]
    for ligne in feuille.iter_rows(min_row=2):
        if all(ligne[entete.index(nom)].value == valeur for nom, valeur in cles.items()):
            return ligne[0].row
    raise KeyError(cles)


def _modifier(chemin, nom_feuille, ligne, **valeurs):
    classeur = load_workbook(chemin)
    feuille = classeur[nom_feuille]
    entete = [c.value for c in feuille[1]]
    numero = ligne if isinstance(ligne, int) else _ligne(feuille, **ligne)
    for nom, valeur in valeurs.items():
        feuille.cell(row=numero, column=entete.index(nom) + 1).value = valeur
    classeur.save(chemin)


def _erreur_import(chemin):
    with pytest.raises(ValueError) as erreur:
        importer_revue(chemin, _dictionnaire())
    return str(erreur.value)


def test_import_sans_modification(tmp_path):
    revue = importer_revue(_exporter(tmp_path), _dictionnaire())
    assert len(revue.regles) == 10
    assert len(revue.valeurs) == 3 + len(PIEGES)
    assert set(revue.regles["statut"]) == set(revue.valeurs["statut"]) == {"observé"}
    assert list(revue.valeurs.loc[revue.valeurs["colonne"] == "code", "valeur"]) == PIEGES
    assert revue.avertissements == []


def test_import_des_decisions_du_metier(tmp_path):
    chemin = _exporter(tmp_path)
    regle = dict(table="clients", colonne="statut")
    _modifier(chemin, "regles", dict(regle, regle="obligatoire"), statut="valide")
    # Statut saisi en forme décomposée, avec une espace en trop : il est normalisé.
    _modifier(chemin, "regles", dict(regle, regle="nature"), statut=" documenté",
              regle_retenue="entier (texte)")
    _modifier(chemin, "regles", dict(regle, regle="valeurs"), statut="invalide",
              commentaire="clé vers un référentiel")
    _modifier(chemin, "valeurs", dict(regle, valeur="actif"), statut="invalide")
    # Ajouts : dans une colonne avec liste et dans une colonne sans liste.
    fin = 1 + 3 + len(PIEGES)
    _modifier(chemin, "valeurs", fin + 1, table="clients", colonne="statut",
              valeur="En sommeil", statut="documenté")
    _modifier(chemin, "valeurs", fin + 5, table="clients", colonne="type_commerce",
              valeur="Boulangerie", statut="documenté", commentaire="chapitre 4")

    revue = importer_revue(chemin, _dictionnaire())
    regles = revue.regles.set_index(["colonne", "regle"])
    assert regles.loc[("statut", "obligatoire"), "statut"] == "valide"
    assert regles.loc[("statut", "nature"), "statut"] == "documenté"
    assert regles.loc[("statut", "nature"), "regle_retenue"] == "entier (texte)"
    ajouts = revue.valeurs[revue.valeurs["origine"] == "ajoutée"]
    assert list(ajouts["valeur"]) == ["En sommeil", "Boulangerie"]
    assert list(ajouts["ligne_excel"]) == [fin + 1, fin + 5]
    assert revue.avertissements == [
        "clients.statut : liste écartée, mais 1 valeurs revues "
        "(statuts conservés, sans effet tant que la liste est écartée)"
    ]


def test_problemes_de_la_feuille_regles_listes_en_une_fois(tmp_path):
    chemin = _exporter(tmp_path)
    statut = dict(table="clients", colonne="statut")
    duree = dict(table="interventions", colonne="duree")
    _modifier(chemin, "regles", dict(statut, regle="obligatoire"), statut=None)
    _modifier(chemin, "regles", dict(statut, regle="nature"), statut="ok")
    _modifier(chemin, "regles", dict(duree, regle="obligatoire"), statut="valide")
    _modifier(chemin, "regles", dict(duree, regle="nature"), statut="documenté")
    _modifier(chemin, "regles", dict(table="clients", colonne="code", regle="obligatoire"),
              statut="documenté", regle_retenue="presque toujours vide")
    _modifier(chemin, "regles", dict(table="clients", colonne="code", regle="nature"),
              statut="valide", regle_retenue="texte")
    _modifier(chemin, "regles", dict(statut, regle="valeurs"), statut="invalide")
    _modifier(chemin, "regles", dict(table="clients", colonne="code", regle="valeurs"),
              statut="documenté")
    classeur = load_workbook(chemin)
    feuille = classeur["regles"]
    feuille.delete_rows(_ligne(feuille, table="clients", colonne="type_commerce", regle="nature"))
    classeur.save(chemin)

    message = _erreur_import(chemin)
    assert "9 problèmes" in message
    for attendu in (
        "statut vide",
        "statut inconnu 'ok'",
        "ne peut pas être validée",
        "regle_retenue obligatoire avec le statut documenté",
        "'presque toujours vide' hors du menu",
        "regle_retenue réservée au statut documenté",
        "commentaire obligatoire avec le statut invalide",
        "statut documenté impossible sur une liste",
        "('clients', 'type_commerce', 'nature') absente du classeur",
    ):
        assert attendu in message
    assert "regles, ligne " in message


def test_classeur_perime_refuse(tmp_path):
    chemin = _exporter(tmp_path)
    dictionnaire = _dictionnaire()
    dictionnaire["clients"]["statut"]["obligatoire"]["proposition"] = "facultatif"
    dictionnaire["clients"]["statut"]["valeurs"]["liste"].append(
        _valeur("Radié", "à arbitrer", 1)
    )
    with pytest.raises(ValueError) as erreur:
        importer_revue(chemin, dictionnaire)
    message = str(erreur.value)
    assert "classeur périmé, à réexporter" in message
    assert "('clients', 'statut', 'Radié') absente du classeur" in message


def test_problemes_de_la_feuille_valeurs(tmp_path):
    chemin = _exporter(tmp_path)
    fin = 1 + 3 + len(PIEGES)
    _modifier(chemin, "valeurs", dict(table="clients", colonne="statut", valeur="Actif"),
              statut="documenté")
    _modifier(chemin, "valeurs", fin + 1, table="clients", colonne="statut",
              valeur="Archivé", statut="valide")
    _modifier(chemin, "valeurs", fin + 2, table="clients", colonne="inconnue",
              valeur="X", statut="documenté")
    _modifier(chemin, "valeurs", fin + 3, table="clients", colonne="statut",
              valeur="Inactif", statut="documenté")
    _modifier(chemin, "valeurs", fin + 4, table="clients", colonne="code",
              valeur=27, statut="documenté")
    _modifier(chemin, "valeurs", fin + 5, table="clients", colonne="statut",
              statut="documenté")
    message = _erreur_import(chemin)
    assert "6 problèmes" in message
    for attendu in (
        "statut 'documenté' impossible sur une valeur observée",
        "une valeur ajoutée doit porter le statut documenté",
        "colonne clients.inconnue absente du dictionnaire",
        "valeur 'Inactif' déjà présente pour clients.statut",
        "valeur 27 lue comme int",
        "valeur vide",
    ):
        assert attendu in message


@pytest.mark.parametrize("cas", ["feuille", "entete"])
def test_structure_modifiee_refusee(tmp_path, cas):
    chemin = _exporter(tmp_path)
    classeur = load_workbook(chemin)
    if cas == "feuille":
        classeur["valeurs"].title = "Valeurs"
        attendu = "feuille « valeurs » absente"
    else:
        classeur["regles"]["D1"] = "proposée"
        attendu = "en-tête modifié"
    classeur.save(chemin)
    assert attendu in _erreur_import(chemin)
