"""Structure des tables chargement et propre de la base (étape 7.2a).

Les tables de données de la base ne sont pas écrites à la main colonne par
colonne : leur structure est déduite du dictionnaire revu
(data/config/dictionnaire.yaml), de la classification de sensibilité
(config/sensibilite.yaml) et des règles complémentaires (config/controles.yaml).
Ce module calcule cette structure, sans se connecter à la base. La génération du
SQL et l'écriture des données viennent ensuite (7.2b et 7.2c).

Une table du dictionnaire donne une table de même nom dans chacun des deux schémas :

- chargement : les valeurs telles que livrées, toutes en texte (nvarchar(4000));
- propre : les valeurs nettoyées, typées selon la nature en vigueur de la colonne.

Nom en base. Le nom d'une table ou d'une colonne suit une règle générique
(`nom_sql`) : accents retirés, mots d'un nom en CamelCase séparés par « _ »
(JournalCode donne journal_code), tout caractère hors lettre et chiffre remplacé
par « _ », minuscules. Un nom vide, qui commence par un chiffre, trop long, égal à
un mot réservé de T-SQL ou à une colonne technique, ou que deux noms sources
donnent à la fois, est refusé : tous les problèmes sont listés en une fois.

Type en propre. La famille de la nature décide du type :

- date (date native, JJ/MM/AAAA, AAAAMMJJ, AAAA-MM-JJ) : date;
- heure (HH:MM) : time(0);
- entier (texte) : bigint, sauf pour un code (voir `est_code`), gardé en texte
  pour ne pas perdre un zéro de tête (code postal 06000);
- nombre natif, décimal virgule ou point (texte) : decimal(28, 8), sans arrondi
  silencieux;
- toute autre nature (texte, règle écartée ou à décider) : nvarchar(4000).

Colonnes techniques, communes aux deux schémas : id_ligne (identité, clé
primaire), id_chargement (qualite.journal_chargement), periode_export (vide pour
un référentiel), fichier_source, feuille_source et num_ligne_source (lignage, uniques
ensemble). Le schéma chargement garde en plus nb_champs_source et
champs_excedentaires, qui décrivent la ligne livrée.

SQL. Les tables de données ne sont pas créées par un script numéroté : `ddl_structure`
produit leurs instructions CREATE TABLE, exécutées par l'écriture (7.2c) après la
suppression de toutes les tables des deux schémas (`ddl_suppression`). Les tables
reflètent donc toujours la dernière exécution; les vues construites sur elles ne
doivent pas être créées WITH SCHEMABINDING. `lignes_correspondance` donne les lignes
de qualite.correspondance_colonne (sql/socle/002_qualite.sql).

Essai, depuis la racine du dépôt : python -m frigeo.structure_base --essai crée
toutes les tables dans une transaction annulée, pour vérifier le SQL généré.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .confidentialite import charger_sensibilite
from .controles import charger_regles_complementaires
from .dictionnaire import AUCUN_FORMAT, FORMES_FERMEES, LISTE_FERMEE, charger_dictionnaire
from .typage import NATURES_DATE, NATURES_HEURE

SCHEMA_CHARGEMENT = "chargement"
SCHEMA_PROPRE = "propre"
SCHEMAS = (SCHEMA_CHARGEMENT, SCHEMA_PROPRE)

# Longueur maximale d'un nom en base. SQL Server admet 128 caractères; la marge
# laisse la place des préfixes et suffixes des contraintes (pk_, uq_..._lignage).
LONGUEUR_MAX_NOM = 100

# Familles de types de la table propre, et type SQL de chacune.
FAMILLE_TEXTE = "texte"
FAMILLE_DATE = "date"
FAMILLE_HEURE = "heure"
FAMILLE_ENTIER = "entier"
FAMILLE_DECIMAL = "décimal"
TYPE_TEXTE = "nvarchar(4000)"
TYPES_SQL = {
    FAMILLE_TEXTE: TYPE_TEXTE,
    FAMILLE_DATE: "date",
    FAMILLE_HEURE: "time(0)",
    FAMILLE_ENTIER: "bigint",
    FAMILLE_DECIMAL: "decimal(28, 8)",
}
# Toutes les colonnes de données de chargement sont du texte, telles que livrées.
TYPE_CHARGEMENT = TYPE_TEXTE

NATURE_ENTIER_TEXTE = "entier (texte)"
NATURES_DECIMALES = ("nombre natif", "décimal virgule (texte)", "décimal point (texte)")

# Règles complémentaires (config/controles.yaml) qui font d'une colonne un code.
REGLES_CODE = ("cle_luhn", "motif")


@dataclass(frozen=True)
class ColonneTechnique:
    """Colonne ajoutée par la base à toute table de données."""

    nom: str
    type_sql: str
    obligatoire: bool
    identite: bool = False


COLONNES_TECHNIQUES = (
    ColonneTechnique("id_ligne", "bigint", True, identite=True),
    ColonneTechnique("id_chargement", "int", True),
    ColonneTechnique("periode_export", "nvarchar(20)", False),
    ColonneTechnique("fichier_source", "nvarchar(260)", True),
    ColonneTechnique("feuille_source", "nvarchar(128)", False),
    ColonneTechnique("num_ligne_source", "int", True),
)
COLONNES_TECHNIQUES_CHARGEMENT = (
    ColonneTechnique("nb_champs_source", "int", False),
    ColonneTechnique("champs_excedentaires", TYPE_TEXTE, False),
)
# Colonnes de lignage, uniques ensemble dans chaque table.
COLONNES_LIGNAGE = ("fichier_source", "feuille_source", "num_ligne_source")
NOMS_TECHNIQUES = frozenset(
    c.nom for c in (*COLONNES_TECHNIQUES, *COLONNES_TECHNIQUES_CHARGEMENT)
)

# Mots réservés de T-SQL (documentation de SQL Server, « Reserved keywords »).
MOTS_RESERVES = frozenset(
    """
    add all alter and any as asc authorization backup begin between break browse
    bulk by cascade case check checkpoint close clustered coalesce collate column
    commit compute constraint contains containstable continue convert create cross
    current current_date current_time current_timestamp current_user cursor
    database dbcc deallocate declare default delete deny desc disk distinct
    distributed double drop dump else end errlvl escape except exec execute exists
    exit external fetch file fillfactor for foreign freetext freetexttable from
    full function goto grant group having holdlock identity identity_insert
    identitycol if in index inner insert intersect into is join key kill left like
    lineno load merge national nocheck nonclustered not null nullif of off offsets
    on open opendatasource openquery openrowset openxml option or order outer over
    percent pivot plan precision primary print proc procedure public raiserror
    read readtext reconfigure references replication restore restrict return
    revert revoke right rollback rowcount rowguidcol rule save schema
    securityaudit select semantickeyphrasetable semanticsimilaritydetailstable
    semanticsimilaritytable session_user set setuser shutdown some statistics
    system_user table tablesample textsize then to top tran transaction trigger
    truncate try_convert tsequal union unique unpivot update updatetext use user
    values varying view waitfor when where while with writetext
    """.split()
)


class ErreurStructure(ValueError):
    """Structure de la base impossible à déduire du dictionnaire."""


@dataclass(frozen=True)
class ColonneBase:
    """Colonne de données d'une table, telle qu'elle sera créée en base."""

    source: str
    nom: str
    nature: str
    famille: str
    sensible: bool

    @property
    def type_propre(self) -> str:
        return TYPES_SQL[self.famille]


@dataclass(frozen=True)
class TableBase:
    """Table de données, créée sous le même nom dans chargement et dans propre."""

    source: str
    nom: str
    colonnes: tuple[ColonneBase, ...]

    def colonne(self, source: str) -> ColonneBase:
        for colonne in self.colonnes:
            if colonne.source == source:
                return colonne
        raise KeyError(f"Colonne {source} absente de la table {self.source}")


# --- Noms ------------------------------------------------------------------------

# Ligatures que la décomposition Unicode ne sépare pas.
_LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE"})


def nom_sql(nom: str) -> str:
    """Nom en base d'une table ou d'une colonne source.

    Accents retirés, mots d'un nom en CamelCase séparés (CompAuxNum donne
    comp_aux_num, HTTPServeur donne http_serveur), tout caractère hors lettre et
    chiffre remplacé par « _ », « _ » répétés réduits à un seul et retirés aux bords,
    minuscules. Le résultat peut être invalide (vide, commençant par un chiffre) :
    voir `probleme_nom`.
    """
    texte = unicodedata.normalize("NFKD", str(nom))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", texte)
    texte = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", texte)
    # Ligatures remplacées après le découpage, pour que Œuvre ne devienne pas o_euvre.
    texte = texte.translate(_LIGATURES)
    texte = re.sub(r"[^A-Za-z0-9]+", "_", texte)
    return texte.strip("_").lower()


def probleme_nom(nom: str) -> str | None:
    """Raison pour laquelle un nom en base est refusé, ou None s'il est valide."""
    if not nom:
        return "nom vide après normalisation"
    if nom[0].isdigit():
        return f"le nom en base {nom} commence par un chiffre"
    if len(nom) > LONGUEUR_MAX_NOM:
        return f"le nom en base {nom} dépasse {LONGUEUR_MAX_NOM} caractères"
    if nom in MOTS_RESERVES:
        return f"le nom en base {nom} est un mot réservé de T-SQL"
    return None


# --- Types -----------------------------------------------------------------------


def est_code(regles: dict, complementaires: dict | None = None) -> bool:
    """Vrai si l'écriture de la colonne est contrainte, ce qui en fait un code.

    Une colonne est un code si sa règle `format` en vigueur est « formes fermées »,
    si sa règle `valeurs` en vigueur est « liste fermée », ou si les règles
    complémentaires lui donnent une clé de Luhn ou un motif. `regles` sont les
    règles de la colonne dans le dictionnaire, `complementaires` celles de
    config/controles.yaml pour la même colonne.
    """
    if regles.get("format", {}).get("regle", AUCUN_FORMAT) == FORMES_FERMEES:
        return True
    if regles.get("valeurs", {}).get("regle") == LISTE_FERMEE:
        return True
    complementaires = complementaires or {}
    return any(complementaires.get(regle) for regle in REGLES_CODE)


def famille_propre(nature: str, code: bool = False) -> str:
    """Famille de type de la colonne dans la table propre, selon sa nature."""
    if nature in NATURES_DATE:
        return FAMILLE_DATE
    if nature in NATURES_HEURE:
        return FAMILLE_HEURE
    if nature == NATURE_ENTIER_TEXTE:
        return FAMILLE_TEXTE if code else FAMILLE_ENTIER
    if nature in NATURES_DECIMALES:
        return FAMILLE_DECIMAL
    return FAMILLE_TEXTE


def colonnes_techniques(schema: str) -> tuple[ColonneTechnique, ...]:
    """Colonnes techniques d'une table de données du schéma, dans l'ordre de création."""
    if schema == SCHEMA_CHARGEMENT:
        return (*COLONNES_TECHNIQUES, *COLONNES_TECHNIQUES_CHARGEMENT)
    if schema == SCHEMA_PROPRE:
        return COLONNES_TECHNIQUES
    raise ValueError(f"Schéma {schema!r} inconnu : {' ou '.join(SCHEMAS)} attendu")


# --- Structure -------------------------------------------------------------------


def _table(
    nom_table: str,
    colonnes: dict,
    sensibles: frozenset[str],
    complementaires: dict,
    problemes: list[str],
) -> TableBase:
    resultat, origines = [], {}
    for source, regles in colonnes.items():
        nom = nom_sql(source)
        raison = probleme_nom(nom)
        if raison:
            problemes.append(f"Colonne {nom_table}.{source} : {raison}")
        elif nom in NOMS_TECHNIQUES:
            problemes.append(
                f"Colonne {nom_table}.{source} : le nom en base {nom} est celui d'une "
                f"colonne technique"
            )
        elif nom in origines:
            problemes.append(
                f"Colonnes {nom_table}.{origines[nom]} et {nom_table}.{source} : même "
                f"nom en base {nom}"
            )
        origines.setdefault(nom, source)
        nature = regles.get("nature", {}).get("regle", "")
        code = est_code(regles, complementaires.get(source))
        resultat.append(
            ColonneBase(
                source=source,
                nom=nom,
                nature=nature,
                famille=famille_propre(nature, code),
                sensible=source in sensibles,
            )
        )
    for source in sorted(sensibles - set(colonnes)):
        problemes.append(
            f"Colonne {nom_table}.{source} classée sensible mais absente du dictionnaire"
        )
    return TableBase(source=nom_table, nom=nom_sql(nom_table), colonnes=tuple(resultat))


def construire_structure(
    dictionnaire: dict,
    sensibles: dict[str, frozenset[str]],
    complementaires: dict | None = None,
) -> dict[str, TableBase]:
    """Structure des tables de données, par nom de table source, dans l'ordre du
    dictionnaire.

    `dictionnaire` est le contenu de la clé `tables` du dictionnaire revu,
    `sensibles` la classification de sensibilité, `complementaires` les règles de
    config/controles.yaml par table puis colonne. Tous les problèmes sont listés
    dans une seule `ErreurStructure`.
    """
    complementaires = complementaires or {}
    problemes: list[str] = []
    for table in sorted(set(sensibles) - set(dictionnaire)):
        problemes.append(f"Table {table} classée sensible mais absente du dictionnaire")
    structure, origines = {}, {}
    for nom_table, colonnes in dictionnaire.items():
        table = _table(
            nom_table,
            colonnes or {},
            sensibles.get(nom_table, frozenset()),
            complementaires.get(nom_table) or {},
            problemes,
        )
        raison = probleme_nom(table.nom)
        if raison:
            problemes.append(f"Table {nom_table} : {raison}")
        elif table.nom in origines:
            problemes.append(
                f"Tables {origines[table.nom]} et {nom_table} : même nom en base {table.nom}"
            )
        origines.setdefault(table.nom, nom_table)
        structure[nom_table] = table
    if problemes:
        raise ErreurStructure(
            "Structure de la base impossible à déduire du dictionnaire\n  "
            + "\n  ".join(problemes)
        )
    return structure


def charger_structure(
    chemin_dictionnaire: str | Path | None = None,
    chemin_sensibilite: str | Path | None = None,
    chemin_controles: str | Path | None = None,
) -> dict[str, TableBase]:
    """Structure déduite des fichiers du projet (emplacements par défaut)."""
    return construire_structure(
        charger_dictionnaire(chemin_dictionnaire),
        charger_sensibilite(Path(chemin_sensibilite) if chemin_sensibilite else None),
        charger_regles_complementaires(chemin_controles),
    )


COLONNES_RESUME = [
    "table",
    "colonne",
    "table_base",
    "colonne_base",
    "nature",
    "famille",
    "type_propre",
    "sensible",
]


def resumer_structure(structure: dict[str, TableBase]) -> pd.DataFrame:
    """Une ligne par colonne de données : noms source et en base, nature, type."""
    lignes = [
        {
            "table": table.source,
            "colonne": colonne.source,
            "table_base": table.nom,
            "colonne_base": colonne.nom,
            "nature": colonne.nature,
            "famille": colonne.famille,
            "type_propre": colonne.type_propre,
            "sensible": colonne.sensible,
        }
        for table in structure.values()
        for colonne in table.colonnes
    ]
    return pd.DataFrame(lignes, columns=COLONNES_RESUME)


# --- SQL des tables de données ------------------------------------------------------

# Tables présentes en base dans les deux schémas de données, à supprimer avant la
# recréation (lues au moment de l'écriture).
REQUETE_TABLES_EXISTANTES = (
    "SELECT s.name, t.name FROM sys.tables AS t "
    "JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
    f"WHERE s.name IN (N'{SCHEMA_CHARGEMENT}', N'{SCHEMA_PROPRE}') "
    "ORDER BY s.name, t.name"
)


def _definition(nom: str, type_sql: str, obligatoire: bool, identite: bool = False) -> str:
    return (
        f"{nom} {type_sql}"
        + (" IDENTITY(1, 1)" if identite else "")
        + (" NOT NULL" if obligatoire else " NULL")
    )


def ddl_table(table: TableBase, schema: str) -> str:
    """Instruction CREATE TABLE d'une table de données dans le schéma.

    Colonnes techniques d'abord, puis colonnes de données dans l'ordre du
    dictionnaire, toutes facultatives : en texte dans chargement, au type de leur
    famille dans propre. Contraintes : clé primaire sur id_ligne, unicité du lignage,
    clé étrangère vers qualite.journal_chargement. Les noms de contraintes sont les
    mêmes dans les deux schémas, SQL Server les rattachant au schéma de la table.
    """
    definitions = [
        _definition(c.nom, c.type_sql, c.obligatoire, c.identite)
        for c in colonnes_techniques(schema)
    ]
    definitions += [
        _definition(
            c.nom, TYPE_CHARGEMENT if schema == SCHEMA_CHARGEMENT else c.type_propre, False
        )
        for c in table.colonnes
    ]
    definitions += [
        f"CONSTRAINT pk_{table.nom} PRIMARY KEY (id_ligne)",
        f"CONSTRAINT uq_{table.nom}_lignage UNIQUE ({', '.join(COLONNES_LIGNAGE)})",
        f"CONSTRAINT fk_{table.nom}_chargement FOREIGN KEY (id_chargement) "
        "REFERENCES qualite.journal_chargement (id_chargement)",
    ]
    return f"CREATE TABLE {schema}.{table.nom} (\n    " + ",\n    ".join(definitions) + "\n);"


def ddl_structure(structure: dict[str, TableBase]) -> list[str]:
    """Instructions de création de toutes les tables de données : celles de
    chargement, puis celles de propre, dans l'ordre du dictionnaire."""
    return [ddl_table(table, schema) for schema in SCHEMAS for table in structure.values()]


def _entre_crochets(nom: str) -> str:
    return "[" + nom.replace("]", "]]") + "]"


def ddl_suppression(existantes) -> list[str]:
    """Instructions DROP TABLE des tables (schéma, nom) présentes en base.

    Toutes les tables des schémas chargement et propre sont supprimées, y compris
    une table qui n'est plus dans le dictionnaire. Une table d'un autre schéma est
    refusée, par sécurité. Les noms sont mis entre crochets, une table créée à la
    main pouvant porter un nom quelconque.
    """
    instructions = []
    for schema, nom in existantes:
        if schema not in SCHEMAS:
            raise ValueError(
                f"Suppression refusée : la table {schema}.{nom} n'est pas dans "
                f"{' ou '.join(SCHEMAS)}"
            )
        instructions.append(f"DROP TABLE {_entre_crochets(schema)}.{_entre_crochets(nom)};")
    return instructions


COLONNES_CORRESPONDANCE = (
    "table_source",
    "colonne_source",
    "table_base",
    "colonne_base",
    "ordre",
    "nature",
    "famille",
    "type_propre",
    "sensible",
)


def lignes_correspondance(structure: dict[str, TableBase]) -> list[dict]:
    """Lignes de qualite.correspondance_colonne, sans id_execution.

    `ordre` est la position de la colonne dans sa table, à partir de 1.
    """
    return [
        {
            "table_source": table.source,
            "colonne_source": colonne.source,
            "table_base": table.nom,
            "colonne_base": colonne.nom,
            "ordre": ordre,
            "nature": colonne.nature or None,
            "famille": colonne.famille,
            "type_propre": colonne.type_propre,
            "sensible": colonne.sensible,
        }
        for table in structure.values()
        for ordre, colonne in enumerate(table.colonnes, start=1)
    ]


# --- Essai contre la base -----------------------------------------------------------


def essayer(moteur) -> dict[str, tuple[int, int]]:
    """Crée toutes les tables de données dans une transaction, puis l'annule.

    Vérifie que le SQL généré est accepté par le serveur, sans rien laisser en
    base. Rend, par schéma, le nombre de tables et de colonnes créées.
    """
    from sqlalchemy import text

    from .base import executer_lot

    structure = charger_structure()
    comptes = {}
    with moteur.connect() as conn:
        transaction = conn.begin()
        try:
            existantes = conn.execute(text(REQUETE_TABLES_EXISTANTES)).all()
            curseur = conn.connection.cursor()
            try:
                for instruction in ddl_suppression(existantes) + ddl_structure(structure):
                    executer_lot(curseur, instruction)
            finally:
                curseur.close()
            for schema, tables, colonnes in conn.execute(
                text(
                    "SELECT s.name, COUNT(DISTINCT t.object_id), COUNT(*) "
                    "FROM sys.tables AS t "
                    "JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
                    "JOIN sys.columns AS c ON c.object_id = t.object_id "
                    f"WHERE s.name IN (N'{SCHEMA_CHARGEMENT}', N'{SCHEMA_PROPRE}') "
                    "GROUP BY s.name"
                )
            ).all():
                comptes[schema] = (tables, colonnes)
        finally:
            transaction.rollback()
    return comptes


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from .base import ErreurBase, creer_moteur

    parser = argparse.ArgumentParser(
        prog="python -m frigeo.structure_base",
        description="Structure des tables de données déduite du dictionnaire.",
    )
    parser.add_argument(
        "--essai", action="store_true",
        help="crée les tables dans une transaction annulée, pour vérifier le SQL généré",
    )
    args = parser.parse_args(argv)
    try:
        structure = charger_structure()
        resume = resumer_structure(structure)
        print(f"{len(structure)} tables, {len(resume)} colonnes de données.")
        print(resume["type_propre"].value_counts().to_string())
        if args.essai:
            moteur = creer_moteur()
            try:
                comptes = essayer(moteur)
            finally:
                moteur.dispose()
            for schema in SCHEMAS:
                tables, colonnes = comptes.get(schema, (0, 0))
                print(f"Essai {schema} : {tables} tables, {colonnes} colonnes (annulé).")
    except (ErreurStructure, ErreurBase, ValueError, RuntimeError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    except Exception as erreur:  # erreur du serveur, rendue sans trace Python
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
