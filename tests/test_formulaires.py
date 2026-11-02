"""Tests du dossier commun des formulaires et de l'archivage (frigeo.formulaires)."""

from datetime import datetime

import pytest

import frigeo.dictionnaire as module_dictionnaire
from frigeo.decisions import chemin_arbitrage
from frigeo.formulaire_controles import chemin_formulaire
from frigeo.formulaires import (
    archiver_formulaire,
    dossier_archives,
    dossier_formulaires,
    ecrire_et_archiver,
    exiger_variables,
    nombres_a_la_francaise,
    separer_milliers,
    texte_entier,
)
from frigeo.revue import chemin_revue


def _horloge(monkeypatch, *instant):
    monkeypatch.setattr(module_dictionnaire, "_maintenant", lambda: datetime(*instant))


def test_classeurs_du_metier_dans_un_seul_dossier():
    dossier = dossier_formulaires()
    assert dossier.parts[-2:] == ("data", "formulaires")
    assert chemin_revue("2026-03") == dossier / "dictionnaire_revue_2026-03.xlsx"
    assert chemin_formulaire("2026-03") == dossier / "controles_2026-03.xlsx"
    assert chemin_arbitrage("2026-03") == dossier / "arbitrage_2026-03.xlsx"
    assert dossier_archives() == dossier / "appliques"


def test_archivage_d_un_formulaire(tmp_path, monkeypatch):
    _horloge(monkeypatch, 2026, 10, 22, 18, 4, 5)
    chemin = tmp_path / "formulaires" / "controles_2026-03.xlsx"
    chemin.parent.mkdir()
    chemin.write_bytes(b"classeur")
    archive = archiver_formulaire(chemin)
    assert archive == tmp_path / "formulaires" / "appliques" / (
        "controles_2026-03_2026-10-22_180405.xlsx"
    )
    assert archive.read_bytes() == b"classeur" and not chemin.exists()
    assert dossier_archives(chemin) == archive.parent
    # Une archive du même nom n'est jamais remplacée.
    chemin.write_bytes(b"autre")
    with pytest.raises(FileExistsError, match="rien n'a été modifié"):
        archiver_formulaire(chemin)
    assert chemin.read_bytes() == b"autre" and archive.read_bytes() == b"classeur"


def test_classeur_ouvert_non_archive(tmp_path, monkeypatch):
    from pathlib import Path

    chemin = tmp_path / "controles_2026-03.xlsx"
    chemin.write_bytes(b"classeur")

    def refuser(self, cible):
        raise PermissionError("ouvert")

    monkeypatch.setattr(Path, "rename", refuser)
    with pytest.raises(PermissionError, match="fermer le classeur dans Excel"):
        archiver_formulaire(chemin, tmp_path / "a")
    assert chemin.exists()


def test_ecriture_puis_archivage(tmp_path, monkeypatch):
    _horloge(monkeypatch, 2026, 10, 23, 14, 0, 0)
    chemin = tmp_path / "arbitrage_2026-03.xlsx"
    chemin.write_bytes(b"classeur")
    vus = []

    def ecrire():
        # Le classeur est déjà archivé quand l'écriture commence.
        vus.append(chemin.exists())
        return "écrit"

    resultat, archive = ecrire_et_archiver(chemin, ecrire)
    assert resultat == "écrit" and vus == [False]
    assert archive == tmp_path / "appliques" / "arbitrage_2026-03_2026-10-23_140000.xlsx"
    assert archive.read_bytes() == b"classeur"


def test_ecriture_echouee_classeur_remis_en_place(tmp_path, monkeypatch):
    _horloge(monkeypatch, 2026, 10, 23, 14, 0, 0)
    chemin = tmp_path / "dictionnaire_revue_2026-03.xlsx"
    chemin.write_bytes(b"classeur")

    def echouer():
        raise ValueError("écriture refusée")

    with pytest.raises(ValueError, match="écriture refusée"):
        ecrire_et_archiver(chemin, echouer)
    assert chemin.read_bytes() == b"classeur"
    assert not list((tmp_path / "appliques").iterdir())


def test_nombres_avec_separateur_des_milliers():
    milliers = chr(160)
    assert texte_entier(999) == "999"
    assert texte_entier(10191) == f"10{milliers}191"
    assert texte_entier(-1234567) == f"-1{milliers}234{milliers}567"
    # La partie décimale n'est pas groupée, un nombre de moins de quatre chiffres non plus.
    assert separer_milliers("7531 lignes, 0,12345 et 120") == (
        f"7{milliers}531 lignes, 0,12345 et 120"
    )
    assert separer_milliers("-12345,5 à 76999") == f"-12{milliers}345,5 à 76{milliers}999"
    assert nombres_a_la_francaise("12345 valeurs, 98.50 % des valeurs") == (
        f"12{milliers}345 valeurs, 98,50 % des valeurs"
    )
    # Un texte à plusieurs points n'est pas un nombre décimal.
    assert nombres_a_la_francaise("version 1.2.3") == "version 1.2.3"


def test_cellule_de_notebook_lancee_sans_les_precedentes():
    espace = {"PERIODE_FIN": "2026-03", "tables": {}}
    exiger_variables(espace, ["PERIODE_FIN", "tables"], "# CHARGEMENT")
    with pytest.raises(RuntimeError, match=r"^Exécuter d'abord la cellule des paramètres, "
                       r"puis # CHARGEMENT \(dictionnaire non défini\)\.$"):
        exiger_variables(espace, ["PERIODE_FIN", "dictionnaire"],
                         "la cellule des paramètres, puis # CHARGEMENT")
    with pytest.raises(RuntimeError, match=r"\(PERIODE_FIN, tables non définis\)"):
        exiger_variables({}, ["PERIODE_FIN", "tables"], "la cellule des paramètres")
