# Modèle Power BI de vérification

Ce guide décrit le modèle Power BI de la sous-étape 7.6 : un rapport de
**vérification**, en tableaux bruts, qui importe les vues `pbi` et permet de
comparer les indicateurs aux valeurs de référence. La mise en page des deux
tableaux de bord (direction, qualité) relève de l'étape 8.

Le livrable est un **modèle** Power BI, `powerbi/frigeo_verification.pbit`,
paramétré par le serveur et le nom de la base : le même fichier s'ouvre chez
un autre client en changeant deux paramètres. Il ne contient aucune donnée
et sert aussi de point de départ aux missions suivantes. Il est versionné
(voir « Fichiers et dépôt »).

## Prérequis

- Power BI Desktop (gratuit) installé sur le poste, en une seule version de
  préférence (celle du Microsoft Store se met à jour seule).
- La base construite et chargée : `python -m frigeo.base --recreer` puis la
  cellule `# BASE` du notebook 07, avec `# VERIFICATION BASE` à 0 non
  conforme (voir le mode opératoire, phase 9).
- Le pilote ODBC Driver 18 for SQL Server (déjà requis par le traitement).
- Aucune connexion à un compte Microsoft n'est nécessaire : elle ne sert qu'à
  publier sur le service Power BI.

## Principes repris du cahier des charges (partie 9)

- **Connexion en mode Import**, actualisée après chaque chargement : la base
  n'est réveillée qu'à l'actualisation, ce qui ménage l'offre gratuite
  d'Azure SQL.
- **Sources : les vues `pbi` uniquement**, une par table du modèle. Aucune
  autre table, aucun autre schéma.
- **Aucune règle métier dans Power BI** : chaque requête se limite aux
  étapes *Source* et *Navigation* produites par le Navigateur, sans filtre,
  sans renommage de colonne, sans colonne calculée. Les transformations
  vivent dans la base, versionnées et testées. Seul le nom des tables perd
  son préfixe `pbi ` (finition, sans effet sur les requêtes). Les mesures
  DAX se limitent à des sommes, des décomptes, des ratios et la comparaison
  à l'année précédente.
- **Relations en étoile, filtrage à sens unique** : chaque fait pointe vers
  ses dimensions par les clés techniques (`Clé …`), et aucun fait ne pointe
  vers un autre fait.
- **Aucune donnée personnelle superflue** : les vues n'exposent déjà que ce
  qui est nécessaire (voir « Confidentialité » plus bas).

## Construire le modèle, pas à pas

1. **Rapport vierge** dans Power BI Desktop, puis *Accueil > Transformer les
   données* pour ouvrir Power Query.
2. **Créer deux paramètres** (*Accueil > Gérer les paramètres > Nouveau
   paramètre*), de type Texte, requis :
   - `Serveur` (par exemple `localhost`);
   - `Base` (par exemple `frigeo`).
3. **Nouvelle source > SQL Server**. Dans Serveur, ouvrir le sélecteur à
   gauche du champ (« abc Texte ») et choisir *Paramètre > Serveur*; faire
   de même pour la base de données (sous *Options avancées*) avec `Base`.
   Mode de connectivité : **Importer**.
4. À l'invite d'authentification, choisir **Windows** (informations
   d'identification actuelles). Si Power BI signale qu'il ne peut pas
   chiffrer la connexion, accepter seulement pour un serveur local
   (`localhost`) : sur un serveur distant, refuser et faire installer un
   certificat (Azure SQL chiffre toujours).
5. Dans le **Navigateur**, filtrer sur `pbi.` et cocher uniquement les
   **19 vues** du schéma `pbi` :
   - dimensions : Calendrier, Catégories d'intervention, Articles facturés,
     Pièces, Comptes, Intervenants, Clients, Fournisseurs;
   - faits et calculs : Interventions, Consommations de pièces, Lignes de
     facture, Achats, Écritures comptables, Stock mensuel des pièces,
     Chantiers;
   - tableau qualité : Contrôles, Anomalies, Bilan des contrôles,
     Chargements.
6. **OK**, puis vérifier sur une requête que les étapes appliquées sont
   seulement *Source* et *Navigation*. *Accueil > Fermer et appliquer*.
7. **Relations** (*Vue Modèle*, puis *Accueil > Gérer les relations*). La
   détection automatique en trace la plupart; corriger pour obtenir les
   **22 relations actives** suivantes, toutes « plusieurs à un », filtrage
   croisé **unique** :

   | Dimension (côté 1) | Faits (côté plusieurs) |
   |---|---|
   | Calendrier[Clé date] | Interventions, Consommations de pièces, Lignes de facture, Achats, Écritures comptables (Clé date); Chantiers (Clé date de début) |
   | Catégories d'intervention[Clé catégorie] | Interventions |
   | Articles facturés[Clé article] | Lignes de facture |
   | Pièces[Clé pièce] | Consommations de pièces, Lignes de facture, Achats, Stock mensuel des pièces |
   | Comptes[Clé compte] | Achats, Écritures comptables |
   | Intervenants[Clé intervenant] | Interventions, Chantiers |
   | Clients[Clé client] | Interventions, Lignes de facture, Chantiers |
   | Fournisseurs[Clé fournisseur] | Achats |
   | Contrôles[Clé contrôle] | Anomalies, Bilan des contrôles |

   Supprimer les relations que Power BI crée entre faits (Interventions vers
   Consommations de pièces, Lignes de facture ou Chantiers) : elles ouvrent
   des chemins en double, qu'il résout en désactivant une relation au hasard.
   Chaque fait porte déjà ses propres clés de dimension, et la marge par
   intervention est calculée dans la base. Les autres dates (échéance, date
   de pièce, date de fin) attendent l'étape 8. `Chargements` reste isolée, et
   `Anomalies[Clé de la ligne]`, clé générique, n'a pas de dimension.
8. **Clés non résumées** : dans la Vue Modèle, sélectionner toutes les
   colonnes `Clé …` marquées Σ (Ctrl pour la sélection multiple), puis
   *Propriétés > Avancé > Résumer par : Aucun*. Un visuel *Table* affiche
   alors une ligne par ligne de la vue, et sa ligne Total donne les totaux.
9. **Vérifier en tableaux bruts** : un visuel *Table* par vue, avec toutes
   ses colonnes, sur trois pages (`Dimensions`, `Faits`, `Qualité`). Pour
   les vues larges, allonger la page (*Format de la page > Paramètres du
   canevas > Type : Personnalisé*).
10. **Mesures de contrôle** sur une page `Indicateurs` (voir « Vérifier les
    indicateurs »), chacune dans une carte.
11. **Finitions** :
    - masquer les colonnes `Clé …` (*Propriétés > Masqué*); les relations
      et les visuels existants n'en sont pas affectés;
    - retirer le préfixe `pbi ` du nom des 19 tables (double-clic dans le
      volet Données); les mesures et les visuels suivent;
    - *Fichier > Options et paramètres > Options > Fichier actuel >
      Chargement des données* : décocher les trois cases de la section
      Relations (le modèle ne doit pas changer à l'actualisation) et
      *Date/heure automatique* (le Calendrier de la base en tient lieu).
12. **Enregistrer** : le fichier de travail par *Fichier > Enregistrer sous*
    (`powerbi/frigeo_verification.pbix`), puis le modèle par *Fichier >
    Exporter > Modèle Power BI* (`powerbi/frigeo_verification.pbit`), avec
    une description courte. À l'ouverture, le modèle demande `Serveur` et
    `Base`, vides : les valeurs des paramètres ne sont pas conservées à
    l'export.

### Table de dates

Le Calendrier n'est pas marqué comme table de dates : Power BI l'exige sans
valeur vide, alors que ses membres -1 (date absente) et -2 (date hors
calendrier) n'ont pas de date. Le modèle de vérification n'en a pas besoin.
Le choix est à faire à l'étape 8, avec les comparaisons temporelles : soit
retirer ces deux membres de la vue `pbi.Calendrier` (les faits concernés
tombant dans la ligne « (Vide) » de Power BI), soit écrire des mesures qui
lèvent elles-mêmes le filtre du calendrier (`REMOVEFILTERS`).

## Vérifier les indicateurs

Des mesures DAX simples suffisent à comparer aux valeurs de référence (aucune
règle métier, seulement des agrégats). `Retenue pour les indicateurs` vient
d'une colonne `bit` et s'importe en Vrai/faux, d'où `TRUE()` :

```
CA HT total = SUM('Interventions'[CA HT])
CA HT retenu = CALCULATE([CA HT total], 'Interventions'[Retenue pour les indicateurs] = TRUE())
Marge opérationnelle totale = SUM('Interventions'[Marge opérationnelle])
Interventions avec marge = COUNT('Interventions'[Marge opérationnelle])
Interventions retenues = CALCULATE(COUNTROWS('Interventions'), 'Interventions'[Retenue pour les indicateurs] = TRUE())
```

Une mesure ne peut pas porter le nom d'une colonne, d'où « Marge
opérationnelle totale ». Le taux d'anomalies par contrôle est déjà calculé
dans `Bilan des contrôles`.

Le format se règle sur la mesure (*Outils de mesure* : Devise en euros à
deux décimales pour les montants, Nombre entier pour les décomptes,
séparateur des milliers), afin de s'appliquer dans tous les visuels. La
carte abrège en plus les grands nombres (K, M) : choisir la mesure dans
*Format du visuel > Objet visuel > Légende > Appliquer les paramètres à*
(et non « Tout »), puis *Valeur > Unités d'affichage : Aucune*.

Un écart se diagnostique dans la base, pas dans Power BI.

### Valeurs de contrôle du jeu Frigéo (période de fin 2026-03)

- Dimensions, membres -1 et -2 compris en plus : Calendrier 1 095 jours
  (2025 à 2027), 5 catégories, 8 articles, 254 pièces, 46 comptes,
  17 intervenants, 850 clients, 25 fournisseurs (7 codes clients et
  1 code fournisseur rattachés à un code principal par le métier).
- Faits : Interventions 10 180, Consommations de pièces 6 509, Lignes de
  facture 22 626, Achats 3 495, Écritures comptables 54 161, Stock mensuel
  des pièces 3 810 (254 pièces sur 15 mois), Chantiers 10 171 (7 chantiers
  sur plusieurs jours regroupent 16 interventions).
- Qualité : Bilan des contrôles a une ligne par contrôle et par état
  (619 en brut, 607 en nettoyé). Anomalies ne contient que l'état nettoyé :
  ses 810 lignes égalent, en nettoyé, la somme des colonnes Anomalies (713),
  À arbitrer (14) et Informations (83). Chargements a une ligne par feuille
  chargée (34).
- Mesures : CA HT total 1 648 205,53 €, CA HT retenu 1 645 025,58 €, marge
  opérationnelle totale 723 029,79 €, 10 131 interventions avec marge,
  10 150 interventions retenues.
## Confidentialité

Les vues `pbi` n'exposent aucun salaire ni donnée personnelle superflue :
pour les intervenants, seuls le matricule, le nom, le prénom, le poste, le
type de contrat et le secteur; pour les clients et fournisseurs, le code,
le nom, la localité et le statut. En revanche, **le coût salarial et la
marge sont exposés au grain de l'intervention** : les masquer serait
illusoire (la marge et les autres composantes redonnent le coût salarial
par soustraction, et tout agrégat rapporté aux heures redonne le taux
horaire chargé). La protection repose donc sur **l'accès au rapport** : il
est réservé à la direction. Un rapport destiné à un public plus large
devrait agréger ces montants ou les retirer.

## Fichiers et dépôt

Le modèle `powerbi/frigeo_verification.pbit` est versionné : il ne contient
ni donnée, ni chemin propre au poste, ni valeur de paramètre, seulement la
structure du modèle, les requêtes, les mesures et les pages. Le fichier de
travail `.pbix`, qui contient les données, reste hors du dépôt.
