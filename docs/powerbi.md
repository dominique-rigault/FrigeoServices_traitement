# Modèle Power BI de vérification

Ce guide décrit le modèle Power BI minimal de la sous-étape 7.6 : un
classeur de **vérification**, en tableaux bruts, qui importe les vues `pbi`
et permet de comparer les indicateurs aux valeurs de référence. La mise en
page des deux tableaux de bord (direction, qualité) relève de l'étape 8.

Le livrable est un **modèle** Power BI (`.pbit`), paramétré par le serveur
et le nom de la base : le même fichier s'ouvre chez un autre client en
changeant deux paramètres. Il est rangé dans `powerbi/` (hors dépôt tant
qu'il contient un chemin de connexion ou des données ; voir plus bas).

## Prérequis

- Power BI Desktop (gratuit) installé sur le poste.
- La base construite et chargée : `python -m frigeo.base --recreer` puis la
  cellule `# BASE` du notebook 07, avec `# VERIFICATION BASE` à 0 non
  conforme (voir le mode opératoire, phase 9).
- Le pilote ODBC Driver 18 for SQL Server (déjà requis par le traitement).

## Principes repris du cahier des charges (partie 9)

- **Connexion en mode Import**, actualisée après chaque chargement : la base
  n'est réveillée qu'à l'actualisation, ce qui ménage l'offre gratuite
  d'Azure SQL.
- **Sources : les vues `pbi` uniquement**, une par table du modèle. Aucune
  autre table, aucun autre schéma.
- **Aucune règle métier dans Power BI** : une seule étape dans Power Query
  (le choix des vues dans le Navigateur), aucun filtre, aucun renommage,
  aucune colonne calculée. Les transformations vivent dans la base,
  versionnées et testées. Les mesures DAX se limitent à des sommes, des
  décomptes, des ratios et la comparaison à l'année précédente.
- **Relations en étoile, filtrage à sens unique** : chaque fait pointe vers
  ses dimensions par les clés techniques (`Clé …`).
- **Aucune donnée personnelle superflue** : les vues n'exposent déjà que ce
  qui est nécessaire (voir « Confidentialité » plus bas).

## Construire le modèle, pas à pas

1. **Nouveau fichier** dans Power BI Desktop, puis *Fichier > Options et
   paramètres > Paramètres*.
2. **Créer deux paramètres** (*Modélisation > Gérer les paramètres*, ou dans
   Power Query *Accueil > Gérer les paramètres*), de type Texte :
   - `Serveur` (par exemple `localhost`) ;
   - `Base` (par exemple `frigeo`).
3. **Obtenir les données > SQL Server**. Dans Serveur, cliquer sur le bouton
   et choisir *Paramètre > Serveur* ; faire de même pour la base de données
   avec `Base`. Mode de connectivité : **Importer**.
4. À l'invite d'authentification, choisir **Windows** (en développement) et
   valider.
5. Dans le **Navigateur**, cocher uniquement les vues du schéma `pbi`
   (elles apparaissent préfixées `pbi.`). Ne rien cocher d'autre.
6. **Charger** (pas « Transformer » : aucune transformation n'est voulue).
   Si Power Query s'ouvre, vérifier qu'il n'y a qu'une étape Source par
   requête et aucune étape ajoutée.
7. **Relations** (*Modèle*). Power BI en propose certaines ; les corriger
   pour obtenir une étoile, chaque fait relié à ses dimensions par les
   colonnes `Clé …`, **filtrage à sens unique** (du 1 vers le plusieurs) :
   - `Calendrier[Clé date]` vers les `Clé date` des faits (et les `Clé date
     d'échéance`, `Clé date de pièce` : créer une relation inactive, ou une
     copie du calendrier, selon le besoin — à l'étape 8) ;
   - `Intervenants[Clé intervenant]`, `Clients[Clé client]`,
     `Fournisseurs[Clé fournisseur]`, `Pièces[Clé pièce]`,
     `Articles facturés[Clé article]`, `Comptes[Clé compte]`,
     `Catégories d'intervention[Clé catégorie]`, `Contrôles[Clé contrôle]`
     vers les clés correspondantes des faits ;
   - `Interventions[Clé intervention]` vers les `Clé intervention` de
     Consommations de pièces et de Lignes de facture.
8. **Vérifier en tableaux bruts** : poser un visuel *Table* par vue, sans
   mise en forme, pour contrôler que les données arrivent. C'est le seul
   contenu attendu à cette étape.
9. **Enregistrer comme modèle** : *Fichier > Enregistrer sous* puis le type
   *Modèle Power BI (\*.pbit)*, dans `powerbi/`. À l'ouverture, le modèle
   redemande `Serveur` et `Base`.

## Vérifier les indicateurs

Quelques mesures DAX simples suffisent à comparer aux valeurs de référence
(aucune règle métier, seulement des agrégats) :

- CA HT retenu = `CALCULATE(SUM(Interventions[CA HT]), Interventions[Retenue pour les indicateurs] = 1)` ;
- Marge opérationnelle = somme de `Interventions[Marge opérationnelle]` ;
- Nombre d'interventions retenues = décompte des lignes où la retenue vaut 1 ;
- Taux d'anomalies par contrôle : déjà calculé dans `Bilan des contrôles`.

Comparer ces valeurs à celles attendues ; un écart se diagnostique dans la
base, pas dans Power BI.

## Confidentialité

Les vues `pbi` n'exposent aucun salaire ni donnée personnelle superflue :
pour les intervenants, seuls le matricule, le nom, le prénom, le poste, le
type de contrat et le secteur ; pour les clients et fournisseurs, le code,
le nom, la localité et le statut. En revanche, **le coût salarial et la
marge sont exposés au grain de l'intervention** : les masquer serait
illusoire (la marge et les autres composantes redonnent le coût salarial
par soustraction, et tout agrégat rapporté aux heures redonne le taux
horaire chargé). La protection repose donc sur **l'accès au rapport** : il
est réservé à la direction. Un rapport destiné à un public plus large
devrait agréger ces montants ou les retirer.

## Hors dépôt

Le fichier `.pbit` et tout `.pbix` de travail restent hors du dépôt
(`powerbi/` est ignoré, sauf ce guide) : ils peuvent contenir un chemin de
connexion propre au poste ou des données du client. Seul ce guide est
versionné.
