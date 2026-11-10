"""Vérification des calculs des packs métier (étape 7.4).

Un pack métier (sql/packs/<pack>/) construit le schéma dw et y fait des calculs
propres à l'activité du client (chantiers, coûts, marge). Pour qu'un calcul reste
vérifiable ligne par ligne, le pack peut avoir ici un module de même nom
(frigeo.packs.<pack>), qui refait les calculs en Python à partir de ce que le
traitement a écrit dans propre et des rattachements, sans relire dw, puis compare
son résultat à dw : la règle est ainsi écrite deux fois, par deux chemins, et un
désaccord sort en non conforme. Le socle (frigeo.ecriture_base) reste générique : il
appelle seulement, pour chaque pack de config/base.yaml qui en a un, la fonction

    verifier(curseur, ecriture, sorties, ajouter)

où `curseur` est un curseur ouvert sur la base (lecture seule), `ecriture` le
résultat de l'écriture (`ecriture_base.Ecriture`, dont la préparation donne les
valeurs de propre), `sorties` les sorties de la qualité (`ecriture_base.SortiesQualite`,
dont les rattachements), et `ajouter(controle, attendu, obtenu, masque=False)` inscrit
un contrôle de la famille « calculs » de la vérification. Un contrôle impossible
s'inscrit avec la raison comme valeur attendue et None comme valeur obtenue.
"""
