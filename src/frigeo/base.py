"""Construction de la base de données à partir des scripts SQL numérotés.

Usage, depuis la racine du dépôt :

    python -m frigeo.base              applique les scripts pas encore appliqués
    python -m frigeo.base --recreer    supprime et recrée la base (serveur local
                                       seulement), puis applique tous les scripts
    python -m frigeo.base --reconstruire
                                       relance seule la reconstruction de dw
                                       (procédure dw.reconstruire d'un pack) sur
                                       la dernière exécution réussie

Ordre d'application : les scripts de sql/socle/ par ordre de nom, puis ceux de
chaque pack listé dans config/base.yaml (sql/packs/<pack>/), dans l'ordre de la
liste. Chaque script est appliqué une seule fois, dans sa propre transaction,
et inscrit dans qualite.script_applique avec son empreinte SHA-256, calculée
après normalisation des fins de ligne. Un script déjà appliqué ne doit plus
changer : s'il a été modifié ou s'il a disparu, rien n'est appliqué et la liste
des scripts en cause est affichée. Pour faire évoluer la base, on écrit un
nouveau script.

Dans un script, les lots sont séparés par une ligne qui ne contient que GO
(casse indifférente, espaces admis). « GO 5 » ou « GO -- commentaire » ne sont
pas reconnus comme séparateurs.

Le module fournit aussi la connexion à la base (creer_moteur) et l'appel de la
reconstruction de dw (reconstruire_dw), réutilisés par l'écriture depuis Python.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pyodbc
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import DBAPIError

RACINE = Path(__file__).resolve().parents[2]
DOSSIER_SQL = RACINE / "sql"
CONFIG_BASE = RACINE / "config" / "base.yaml"
FICHIER_ENV = RACINE / ".env"

SERVEURS_LOCAUX = {"localhost", ".", "(local)", "127.0.0.1"}
BASES_SYSTEME = {"master", "model", "msdb", "tempdb"}
CLASSEMENT_DEFAUT = "French_100_CI_AS"
NOM_SUR = re.compile(r"^[A-Za-z0-9_]+$")
SEPARATEUR_GO = re.compile(r"^[ \t]*GO[ \t]*$", re.IGNORECASE | re.MULTILINE)
BOM_UTF8 = b"\xef\xbb\xbf"

# Reconstruction de dw : procédure déclarée par un pack, et son journal.
PROCEDURE_RECONSTRUCTION = "dw.reconstruire"
# Statuts d'une exécution (contrainte ck_execution_statut de qualite.execution).
STATUT_EN_COURS = "en cours"
STATUT_REUSSIE = "réussie"


class ErreurBase(Exception):
    """Erreur de construction de la base, affichée sans trace Python."""


@dataclass(frozen=True)
class Script:
    """Script SQL à appliquer."""

    nom: str  # chemin relatif à la racine du dépôt, séparateur « / »
    chemin: Path


# Fonctions sans base de données (testées dans tests/test_base.py)


def normaliser(contenu: bytes) -> bytes:
    """Retire une éventuelle marque d'ordre UTF-8 et ramène les fins de ligne à LF."""
    if contenu.startswith(BOM_UTF8):
        contenu = contenu[len(BOM_UTF8):]
    return contenu.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def empreinte(contenu: bytes) -> str:
    """Empreinte SHA-256 (64 caractères hexadécimaux) du contenu normalisé."""
    return hashlib.sha256(normaliser(contenu)).hexdigest()


def decouper_lots(texte: str) -> list[str]:
    """Découpe un script en lots sur les lignes GO; les lots vides sont ignorés."""
    texte = texte.replace("\r\n", "\n").replace("\r", "\n")
    return [lot.strip() for lot in SEPARATEUR_GO.split(texte) if lot.strip()]


def lire_packs(chemin_config: Path = CONFIG_BASE) -> list[str]:
    """Liste des packs déclarés dans config/base.yaml (clé packs)."""
    if not chemin_config.is_file():
        raise ErreurBase(f"Fichier de configuration introuvable : {chemin_config}")
    config = yaml.safe_load(chemin_config.read_text(encoding="utf-8")) or {}
    packs = config.get("packs") or []
    if not isinstance(packs, list) or not all(
        isinstance(p, str) and NOM_SUR.match(p) for p in packs
    ):
        raise ErreurBase(
            f"{chemin_config.name} : la clé packs doit être une liste de noms "
            "(lettres, chiffres et _ seulement)."
        )
    doublons = sorted({p for p in packs if packs.count(p) > 1})
    if doublons:
        raise ErreurBase(f"{chemin_config.name} : pack listé plusieurs fois : {', '.join(doublons)}")
    return packs


def lister_scripts(dossier_sql: Path, packs: list[str]) -> list[Script]:
    """Scripts dans l'ordre d'application : socle par ordre de nom, puis chaque pack."""
    dossiers = [dossier_sql / "socle"] + [dossier_sql / "packs" / p for p in packs]
    scripts = []
    for dossier in dossiers:
        if not dossier.is_dir():
            raise ErreurBase(f"Dossier de scripts introuvable : {dossier}")
        for chemin in sorted(dossier.glob("*.sql"), key=lambda c: c.name):
            nom = chemin.relative_to(dossier_sql.parent).as_posix()
            scripts.append(Script(nom, chemin))
    return scripts


def controler_appliques(appliques: dict[str, str], disponibles: dict[str, str]) -> list[tuple[str, str]]:
    """Scripts déjà appliqués qui ont été modifiés ou qui ont disparu.

    appliques et disponibles associent un nom de script à son empreinte.
    Renvoie des couples (nom, motif), motif valant « modifié » ou « disparu ».
    """
    problemes = []
    for nom, emp in sorted(appliques.items()):
        if nom not in disponibles:
            problemes.append((nom, "disparu"))
        elif disponibles[nom] != emp:
            problemes.append((nom, "modifié"))
    return problemes


def scripts_a_appliquer(scripts: list[Script], appliques: dict[str, str]) -> list[Script]:
    """Scripts pas encore appliqués, dans l'ordre d'application."""
    return [s for s in scripts if s.nom not in appliques]


def execution_a_reconstruire(executions: list[tuple[int, str]]) -> int:
    """Exécution dont les tables sont dans propre : la dernière réussie.

    executions donne (id_execution, statut) de qualite.execution. Refusé s'il n'y a
    aucune exécution réussie, ou si la dernière exécution inscrite est encore en
    cours (son écriture n'est pas finie, ou a été interrompue).
    """
    if not executions:
        raise ErreurBase(
            "aucune exécution dans qualite.execution : exécuter d'abord la cellule # BASE "
            "du notebook 07."
        )
    derniere, statut = max(executions)
    if statut == STATUT_EN_COURS:
        raise ErreurBase(
            f"l'exécution {derniere} est en cours : attendre sa fin, ou relancer la "
            "cellule # BASE si elle a été interrompue."
        )
    reussies = [identifiant for identifiant, statut in executions if statut == STATUT_REUSSIE]
    if not reussies:
        raise ErreurBase(
            "aucune exécution réussie dans qualite.execution : exécuter d'abord la "
            "cellule # BASE du notebook 07."
        )
    return max(reussies)


def est_serveur_local(serveur: str) -> bool:
    """Vrai pour localhost, ., (local) ou 127.0.0.1, avec ou sans instance ni port."""
    hote = re.split(r"[\\,]", serveur.strip(), maxsplit=1)[0].strip().lower()
    return hote in SERVEURS_LOCAUX


def composer_version(description: str, statut: str) -> str | None:
    """Version du code à partir de git describe et de git status --porcelain.

    « -dirty » est ajouté dès que le dossier de travail diffère du commit :
    fichier suivi modifié ou fichier nouveau non suivi. Les fichiers ignorés
    par .gitignore (data/, .env) ne comptent pas.
    """
    description = description.strip()
    if not description:
        return None
    return f"{description}-dirty" if statut.strip() else description


def version_traitement() -> str | None:
    """Version du code (git describe --tags --always, plus « -dirty »), None si Git est absent."""
    try:
        description = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=RACINE, capture_output=True, text=True, check=True,
        ).stdout
        statut = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=RACINE, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return composer_version(description, statut)


# Connexion


def lire_parametres() -> dict[str, str | None]:
    """Paramètres de connexion lus dans le fichier .env de la racine du dépôt.

    Obligatoires : BASE_SERVEUR, BASE_NOM, BASE_PILOTE. Facultatifs :
    BASE_CONFIANCE_CERTIFICAT (yes ou no), BASE_CLASSEMENT (French_100_CI_AS
    par défaut, utilisé par --recreer).
    """
    load_dotenv(FICHIER_ENV)
    manquants = [v for v in ("BASE_SERVEUR", "BASE_NOM", "BASE_PILOTE") if not os.getenv(v)]
    if manquants:
        raise ErreurBase(f"Variables absentes de {FICHIER_ENV} : {', '.join(manquants)}")
    return {
        "serveur": os.environ["BASE_SERVEUR"],
        "nom": os.environ["BASE_NOM"],
        "pilote": os.environ["BASE_PILOTE"],
        "confiance": os.getenv("BASE_CONFIANCE_CERTIFICAT"),
        "classement": os.getenv("BASE_CLASSEMENT") or CLASSEMENT_DEFAUT,
    }


def creer_moteur(base: str | None = None, autocommit: bool = False) -> Engine:
    """Moteur SQLAlchemy (authentification Windows) vers la base du .env ou vers base."""
    p = lire_parametres()
    requete = {"driver": p["pilote"], "Trusted_Connection": "yes"}
    if p["confiance"]:
        requete["TrustServerCertificate"] = p["confiance"]
    url = URL.create("mssql+pyodbc", host=p["serveur"], database=base or p["nom"], query=requete)
    options = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    # fast_executemany : insertion groupée pour l'écriture depuis Python (7.2).
    return create_engine(url, fast_executemany=True, **options)


def executer_lot(curseur, lot: str, *parametres) -> None:
    """Exécute un lot tel quel et parcourt tous ses résultats.

    Le pilote ne remonte l'erreur d'une instruction qu'au moment où l'on atteint
    son résultat : sans ce parcours, l'échec d'une instruction placée après la
    première d'un lot passerait inaperçu.
    """
    curseur.execute(lot, *parametres)
    while curseur.nextset():
        pass


# Opérations sur la base


def procedure_reconstruction_presente(curseur) -> bool:
    """Vrai si un pack appliqué déclare la procédure dw.reconstruire."""
    curseur.execute(f"SELECT OBJECT_ID(N'{PROCEDURE_RECONSTRUCTION}', N'P')")
    return curseur.fetchone()[0] is not None


def reconstruire_dw(curseur, id_execution: int) -> list[tuple[int, str, int]] | None:
    """Reconstruit dw pour une exécution, dans la transaction ouverte sur curseur.

    Renvoie le journal de la reconstruction (ordre, étape, lignes), ou None si
    aucun pack ne déclare la procédure dw.reconstruire. Une erreur de la
    procédure (contrat d'entrée non respecté par exemple) remonte telle quelle :
    à l'appelant d'annuler la transaction.
    """
    if not procedure_reconstruction_presente(curseur):
        return None
    executer_lot(curseur, f"EXEC {PROCEDURE_RECONSTRUCTION} @id_execution = ?", id_execution)
    curseur.execute(
        "SELECT ordre, etape, lignes FROM dw.journal_reconstruction ORDER BY ordre"
    )
    return [(int(ordre), etape, int(lignes)) for ordre, etape, lignes in curseur.fetchall()]


def reconstruire() -> None:
    """Relance seule la reconstruction de dw sur la dernière exécution réussie, dans
    sa propre transaction : en cas d'erreur, dw reste tel qu'il était."""
    moteur = creer_moteur()
    try:
        with moteur.begin() as conn:
            curseur = conn.connection.cursor()
            try:
                try:
                    curseur.execute("SELECT id_execution, statut FROM qualite.execution")
                    executions = [(int(i), statut) for i, statut in curseur.fetchall()]
                except pyodbc.Error as erreur:
                    raise ErreurBase(
                        f"Lecture de qualite.execution impossible (base à construire : "
                        f"python -m frigeo.base) : {erreur}"
                    ) from erreur
                id_execution = execution_a_reconstruire(executions)
                try:
                    journal = reconstruire_dw(curseur, id_execution)
                except pyodbc.Error as erreur:
                    raise ErreurBase(
                        f"reconstruction de dw échouée (exécution {id_execution}), dw est "
                        f"inchangé : {erreur}"
                    ) from erreur
                if journal is None:
                    raise ErreurBase(
                        f"aucune procédure {PROCEDURE_RECONSTRUCTION} : aucun pack de "
                        "config/base.yaml ne construit dw, ou ses scripts ne sont pas "
                        "appliqués (python -m frigeo.base)."
                    )
            finally:
                curseur.close()
    except DBAPIError as erreur:
        raise ErreurBase(f"Reconstruction de dw impossible : {erreur}") from erreur
    finally:
        moteur.dispose()
    print(f"dw reconstruit pour l'exécution {id_execution} :")
    for ordre, etape, lignes in journal:
        print(f"  {ordre}. {etape} : {lignes} ligne(s)")


def recreer_base(p: dict[str, str | None]) -> None:
    """Supprime puis recrée la base, sur un serveur local seulement."""
    if not est_serveur_local(p["serveur"]):
        raise ErreurBase(
            "--recreer est réservé à un serveur local (localhost, ., (local) ou "
            f"127.0.0.1), or BASE_SERVEUR vaut {p['serveur']}."
        )
    nom, classement = p["nom"], p["classement"]
    for valeur, variable in ((nom, "BASE_NOM"), (classement, "BASE_CLASSEMENT")):
        if not NOM_SUR.match(valeur):
            raise ErreurBase(f"{variable} contient des caractères non admis : {valeur}")
    if nom.lower() in BASES_SYSTEME:
        raise ErreurBase(f"Suppression d'une base système refusée : {nom}")
    moteur = creer_moteur(base="master", autocommit=True)
    try:
        with moteur.connect() as conn:
            curseur = conn.connection.cursor()
            executer_lot(
                curseur,
                f"IF DB_ID(N'{nom}') IS NOT NULL BEGIN "
                f"ALTER DATABASE [{nom}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE [{nom}]; END",
            )
            executer_lot(curseur, f"CREATE DATABASE [{nom}] COLLATE {classement}")
            curseur.close()
    except (DBAPIError, pyodbc.Error) as erreur:
        raise ErreurBase(f"Recréation de la base {nom} impossible : {erreur}") from erreur
    finally:
        moteur.dispose()


def lire_appliques(moteur: Engine) -> dict[str, str]:
    """Scripts inscrits dans qualite.script_applique (vide si la table n'existe pas encore)."""
    try:
        with moteur.connect() as conn:
            existe = conn.execute(text("SELECT OBJECT_ID(N'qualite.script_applique', N'U')")).scalar()
            if existe is None:
                return {}
            lignes = conn.execute(
                text("SELECT nom_script, empreinte_sha256 FROM qualite.script_applique")
            ).all()
    except DBAPIError as erreur:
        raise ErreurBase(
            f"Lecture de la base impossible (base absente : python -m frigeo.base --recreer) : {erreur}"
        ) from erreur
    return {nom: emp.strip().lower() for nom, emp in lignes}


def appliquer_script(moteur: Engine, script: Script, version: str | None) -> None:
    """Applique un script et l'inscrit dans qualite.script_applique, en une transaction."""
    contenu = script.chemin.read_bytes()
    try:
        texte = normaliser(contenu).decode("utf-8")
    except UnicodeDecodeError as erreur:
        raise ErreurBase(f"Script illisible en UTF-8 : {script.nom}") from erreur
    lots = decouper_lots(texte)
    with moteur.begin() as conn:
        curseur = conn.connection.cursor()
        try:
            for numero, lot in enumerate(lots, start=1):
                try:
                    executer_lot(curseur, lot)
                except pyodbc.Error as erreur:
                    raise ErreurBase(f"{script.nom}, lot {numero} : {erreur}") from erreur
            try:
                executer_lot(
                    curseur,
                    "INSERT INTO qualite.script_applique "
                    "(nom_script, empreinte_sha256, version_traitement) VALUES (?, ?, ?)",
                    script.nom, empreinte(contenu), version,
                )
            except pyodbc.Error as erreur:
                raise ErreurBase(
                    f"{script.nom} : inscription dans qualite.script_applique impossible : {erreur}"
                ) from erreur
        finally:
            curseur.close()


def construire(recreer: bool) -> None:
    """Contrôle les scripts déjà appliqués, puis applique les nouveaux dans l'ordre."""
    p = lire_parametres()
    scripts = lister_scripts(DOSSIER_SQL, lire_packs())
    disponibles = {s.nom: empreinte(s.chemin.read_bytes()) for s in scripts}
    if recreer:
        recreer_base(p)
        print(f"Base {p['nom']} supprimée et recréée (classement {p['classement']}).")
    moteur = creer_moteur()
    try:
        appliques = lire_appliques(moteur)
        problemes = controler_appliques(appliques, disponibles)
        if problemes:
            detail = "\n".join(f"  {nom} : {motif}" for nom, motif in problemes)
            raise ErreurBase(
                "aucun script appliqué, car des scripts déjà appliqués ont changé :\n"
                f"{detail}\nÉcrire un nouveau script plutôt que modifier un script appliqué; tant "
                "qu'aucune base n'est à conserver (avant le premier déploiement), on peut aussi "
                "recréer la base par --recreer."
            )
        a_faire = scripts_a_appliquer(scripts, appliques)
        if not a_faire:
            print("Base à jour : aucun script à appliquer.")
            return
        version = version_traitement()
        for script in a_faire:
            appliquer_script(moteur, script, version)
            print(f"Appliqué : {script.nom}")
        print(f"{len(a_faire)} script(s) appliqué(s), version {version or 'inconnue'}.")
    finally:
        moteur.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m frigeo.base",
        description="Applique les scripts SQL du socle et des packs à la base du fichier .env.",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--recreer", action="store_true",
        help="supprime et recrée la base avant d'appliquer les scripts (serveur local seulement)",
    )
    action.add_argument(
        "--reconstruire", action="store_true",
        help="relance seule la reconstruction de dw sur la dernière exécution réussie",
    )
    args = parser.parse_args(argv)
    try:
        if args.reconstruire:
            reconstruire()
        else:
            construire(args.recreer)
    except ErreurBase as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())