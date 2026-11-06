"""Tests sans base de données du module frigeo.base."""

from pathlib import Path

import pytest

from frigeo.base import (
    ErreurBase,
    Script,
    composer_version,
    controler_appliques,
    decouper_lots,
    empreinte,
    est_serveur_local,
    lire_packs,
    lister_scripts,
    scripts_a_appliquer,
)


def creer(chemin: Path, contenu: str = "SELECT 1;\n") -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


def test_decoupage_sur_go():
    texte = "CREATE SCHEMA a;\nGO\n  go  \nCREATE TABLE a.t (x int);\r\nGo\r\nSELECT 1;\n"
    assert decouper_lots(texte) == ["CREATE SCHEMA a;", "CREATE TABLE a.t (x int);", "SELECT 1;"]


def test_go_dans_une_ligne_ne_coupe_pas():
    texte = "SELECT 1 AS go_un;\nPRINT 'GO';\nSELECT 'x' -- GO"
    assert decouper_lots(texte) == [texte]


def test_empreinte_independante_des_fins_de_ligne():
    lf = b"CREATE SCHEMA a;\nGO\n"
    attendu = empreinte(lf)
    assert empreinte(lf.replace(b"\n", b"\r\n")) == attendu
    assert empreinte(lf.replace(b"\n", b"\r")) == attendu
    assert empreinte(b"\xef\xbb\xbf" + lf) == attendu


def test_empreinte_change_avec_le_contenu():
    assert empreinte(b"a\n") != empreinte(b"b\n")
    assert len(empreinte(b"")) == 64


def test_ordre_socle_puis_packs(tmp_path):
    sql = tmp_path / "sql"
    for nom in ("002_qualite.sql", "001_schemas.sql", "010_vues.sql", "notes.txt"):
        creer(sql / "socle" / nom)
    creer(sql / "packs" / "pack_b" / "001_b.sql")
    creer(sql / "packs" / "pack_a" / "001_a.sql")
    noms = [s.nom for s in lister_scripts(sql, ["pack_b", "pack_a"])]
    assert noms == [
        "sql/socle/001_schemas.sql",
        "sql/socle/002_qualite.sql",
        "sql/socle/010_vues.sql",
        "sql/packs/pack_b/001_b.sql",
        "sql/packs/pack_a/001_a.sql",
    ]


def test_pack_sans_script_accepte(tmp_path):
    sql = tmp_path / "sql"
    creer(sql / "socle" / "001_schemas.sql")
    creer(sql / "packs" / "vide" / ".gitkeep", "")
    assert [s.nom for s in lister_scripts(sql, ["vide"])] == ["sql/socle/001_schemas.sql"]


def test_dossier_de_pack_absent(tmp_path):
    creer(tmp_path / "sql" / "socle" / "001_schemas.sql")
    with pytest.raises(ErreurBase):
        lister_scripts(tmp_path / "sql", ["inconnu"])


def test_lecture_des_packs(tmp_path):
    config = tmp_path / "base.yaml"
    creer(config, "packs:\n  - services_intervention\n")
    assert lire_packs(config) == ["services_intervention"]
    creer(config, "packs: []\n")
    assert lire_packs(config) == []


def test_pack_liste_deux_fois_refuse(tmp_path):
    config = tmp_path / "base.yaml"
    creer(config, "packs: [a, a]\n")
    with pytest.raises(ErreurBase):
        lire_packs(config)


def test_scripts_modifies_ou_disparus():
    appliques = {"sql/socle/001.sql": "a" * 64, "sql/socle/002.sql": "b" * 64, "sql/socle/003.sql": "c" * 64}
    disponibles = {"sql/socle/001.sql": "a" * 64, "sql/socle/002.sql": "x" * 64, "sql/socle/004.sql": "d" * 64}
    assert controler_appliques(appliques, disponibles) == [
        ("sql/socle/002.sql", "modifié"),
        ("sql/socle/003.sql", "disparu"),
    ]


def test_scripts_nouveaux_seulement():
    appliques = {"sql/socle/001.sql": "a" * 64}
    disponibles = {"sql/socle/001.sql": "a" * 64, "sql/socle/002.sql": "b" * 64}
    assert controler_appliques(appliques, disponibles) == []
    scripts = [Script("sql/socle/001.sql", Path("x")), Script("sql/socle/002.sql", Path("y"))]
    assert [s.nom for s in scripts_a_appliquer(scripts, appliques)] == ["sql/socle/002.sql"]


def test_serveur_local():
    for serveur in ("localhost", "LOCALHOST\\SQLEXPRESS", ".", ".\\SQLEXPRESS", "(local)", "127.0.0.1,1433"):
        assert est_serveur_local(serveur), serveur
    for serveur in ("frigeo.database.windows.net", "192.168.1.10", ""):
        assert not est_serveur_local(serveur), serveur

def test_version_propre_ou_modifiee():
    assert composer_version("v1-3-gabc1234\n", "") == "v1-3-gabc1234"
    assert composer_version("v1-3-gabc1234\n", "?? src/frigeo/base.py\n") == "v1-3-gabc1234-dirty"
    assert composer_version("v1-3-gabc1234\n", " M README.md\n") == "v1-3-gabc1234-dirty"
    assert composer_version("", "") is None