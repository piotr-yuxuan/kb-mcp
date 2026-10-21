---
title: "Traiter une demande de remboursement (marchands français)"
lang: fr
---

- **Responsable :** Inès Moreau, responsable de l'équipe support France
- **Dernière relecture :** 8 septembre 2026
- **Pour qui :** les conseillers T1 et les spécialistes T2 de la file `fr-marchands`

Les marchands français nous écrivent souvent au sujet des remboursements, surtout après les soldes et en fin d'année. Dans la grande majorité des cas, ils ne nous demandent pas de rembourser à leur place : ils veulent savoir comment faire, comprendre pourquoi leur client n'a encore rien vu sur son compte, ou obtenir la validation d'un remboursement important. Cette page décrit la manière dont l'équipe de Paris traite ces demandes. Les marchands anglophones sont suivis par Londres selon [la page anglaise sur les remboursements](refunds.md) ; les règles sont les mêmes des deux côtés de la Manche.

## Ce qu'il faut retenir

- **Le délai.** Un paiement peut être remboursé dans les 180 jours qui suivent la date du paiement. Passé ce délai, Quillmoor ne peut plus le rembourser, quelle que soit la raison.
- **La validation.** Au-delà de 10 000 €, le remboursement doit recevoir la validation par le niveau T2 avant de partir.
- **Le partiel.** Un remboursement peut être partiel, et un même paiement peut recevoir plusieurs remboursements partiels, tant que leur total ne dépasse pas le montant encaissé.
- **L'initiative.** C'est le marchand qui rembourse, depuis Merchant Hub ou par la Merchant API. Le support ne le fait à sa place que dans deux cas précis.
- **La destination.** Le remboursement repart toujours vers la carte utilisée pour payer, dans la devise du paiement d'origine.

## Qui fait quoi

| Acteur | Rôle |
|---|---|
| Le marchand | Déclenche le remboursement, choisit le montant, répond à son client |
| Conseiller T1 | Répond aux questions, vérifie le paiement, envoie les modèles de réponse, transmet au T2 si nécessaire |
| Spécialiste T2 (trois à Paris, dont Maëlle Garnier) | Valide les remboursements au-delà de 10 000 €, enquête sur les remboursements échoués ou introuvables, traite les cas sensibles |
| Équipes d'ingénierie (T3) | N'interviennent qu'en cas d'anomalie dans nos systèmes, selon [le guide d'escalade du support](escalation.md) |

## Premier réflexe : retrouver le paiement

Avant de répondre, ouvrez le paiement dans l'outil interne. Le marchand nous donne souvent son propre numéro de commande, que nous ne connaissons pas : demandez-lui la référence Quillmoor du paiement ou, à défaut, la date, le montant et les quatre derniers chiffres de la carte.

Regardez ensuite quatre choses :

1. **La date du paiement.** Comptez 180 jours à partir de la date affichée dans Merchant Hub. C'est cette date qui compte, et non celle de la commande chez le marchand ou celle de la livraison.
2. **Le statut.** Un paiement seulement autorisé, jamais encaissé, ne se rembourse pas : on l'annule, et la banque de l'acheteur libère la somme bloquée. Aucun argent ne circule.
3. **Un litige en cours ?** Si l'acheteur a contesté le paiement auprès de sa banque, aucun remboursement n'est possible sur ce paiement (voir « Cas particuliers »).
4. **Le montant restant.** C'est le montant encaissé, moins les remboursements déjà effectués.

Ces vérifications prennent une minute et évitent la plupart des allers-retours avec le marchand.

## Le marchand demande comment rembourser

C'est la question la plus fréquente. Dans Merchant Hub, un utilisateur qui a le rôle Paiements ouvre l'onglet **Paiements**, sélectionne le paiement, clique sur **Rembourser**, saisit le montant et le motif, puis confirme. Merchant Hub s'affiche en français lorsque l'utilisateur a choisi cette langue dans son profil ; les libellés cités sur cette page sont ceux de l'interface française.

Les marchands qui veulent automatiser leurs remboursements peuvent passer par l'API de remboursement en libre-service, disponible depuis la fin du projet ENG-6 en août 2026. Leurs développeurs trouveront la documentation sur `docs.quillmoor.example`. Les règles ne changent pas selon le canal : le délai et la validation s'appliquent de la même façon.

Modèle à adapter : `fr-remboursement-procedure` (voir « Modèles de réponse »).

## Les remboursements partiels

Un remboursement partiel rend une partie du paiement : un article manquant, des frais de livraison, un geste commercial. Prenons une commande de 320 €, composée de deux articles à 275 € et 45 €. Le marchand rembourse d'abord 45 € pour l'article en rupture de stock, puis 275 € lorsque le client renvoie le second. Le paiement est alors entièrement remboursé, et le bouton **Rembourser** disparaît.

Trois points reviennent souvent :

- Chaque remboursement partiel a sa propre référence et apparaît séparément dans le relevé des versements, à la date à laquelle il a été traité.
- Le délai de 180 jours court toujours à partir du paiement d'origine. Un premier remboursement partiel ne le prolonge pas.
- Lorsque plusieurs remboursements partiels sur un même paiement dépassent ensemble 10 000 € en moins de 24 heures, Harbour le signale. On les traite alors comme un seul remboursement : ils passent par la validation T2, même si chacun reste sous le seuil.

## Au-delà de 10 000 € : la validation par le niveau T2

Tout remboursement au-delà de 10 000 € attend la validation par le niveau T2 avant d'être envoyé. Peu importe qu'il soit total ou partiel, et qu'il vienne de Merchant Hub, de l'API ou du support. Dans Merchant Hub, le remboursement affiche le statut « En attente de validation » ; dans Harbour, il crée un ticket dans la file `refund-approvals`, que l'équipe de Paris suit dans la vue « France ».

Un remboursement de 10 000 € tout juste part sans validation : la règle vise les montants au-delà de ce seuil.

### Ce que vérifie le spécialiste T2

- Le paiement existe, a bien été encaissé et date de moins de 180 jours.
- Le montant ne dépasse pas ce qui reste à rembourser.
- Aucun litige n'est ouvert sur ce paiement.
- La demande vient d'un utilisateur actif du compte, qui a le rôle Paiements, par le canal habituel du marchand : sa session Merchant Hub ou ses identifiants d'API, et non une nouvelle adresse email.
- Le solde du marchand couvre le remboursement.
- Rien ne paraît inhabituel. Par exemple, un utilisateur ajouté au compte quelques jours plus tôt qui demande plusieurs gros remboursements d'affilée. En cas de doute, le spécialiste suspend sa décision et prévient l'équipe Risk Operations par la file `fraud-reports` (voir [la page sur les signalements de fraude](merchant-fraud-reports.md)).

### Délai et horaires

L'objectif est une décision dans les 4 heures ouvrées qui suivent l'arrivée du remboursement dans la file. Les heures ouvrées de la file `fr-marchands` vont de 9 h à 18 h, heure de Paris, du lundi au vendredi, hors jours fériés français. Il n'y a pas de validation la nuit ni le week-end : un remboursement de 15 000 € demandé le vendredi à 19 h sera examiné le lundi matin. Le modèle `fr-remboursement-validation-t2` le dit clairement au marchand.

Celui qui prépare un remboursement pour le compte d'un marchand ne le valide jamais lui-même : un second spécialiste T2 s'en charge.

## Plus de 180 jours : que répondre ?

Il n'y a pas d'exception, pas même pour un marchand stratégique. La limite tient à la façon dont les remboursements circulent dans les schémas de cartes, et non à une simple règle interne. Le marchand peut en revanche rembourser son client par un autre moyen, par exemple un virement bancaire qu'il organise lui-même.

Restez factuel : expliquez la limite, rappelez la date du paiement et proposez l'alternative. Inutile de transmettre au T2, sauf si le marchand conteste la date du paiement. Modèle : `fr-remboursement-hors-delai`.

## Quand le support rembourse à la place du marchand

Seulement dans deux cas :

1. Merchant Hub et l'API sont tous deux indisponibles pour ce marchand, lors d'un incident par exemple, et le remboursement ne peut pas attendre.
2. Tous les administrateurs du compte sont bloqués, et le remboursement est urgent pour le marchand.

Dans les deux cas, il faut une demande écrite d'un administrateur du compte, sur le ticket, qui précise la référence du paiement et le montant. Le T1 prépare le remboursement dans l'outil interne, le T2 l'envoie.

Nous ne remboursons jamais à la demande d'un porteur de carte. Celui qui nous écrit directement est réorienté vers le vendeur, avec le modèle `fr-remboursement-porteur`.

## Cas particuliers

| Situation | Ce qu'il se passe | Que faire |
|---|---|---|
| Statut « Réussi », mais le client ne voit rien | Le remboursement est parti ; la banque émettrice le crédite en général sous 5 à 10 jours ouvrés | Donner la référence de l'acquéreur, que le client peut citer à sa banque ; modèle `fr-remboursement-en-cours` |
| Solde insuffisant | Le remboursement reste « En attente de fonds » jusqu'à ce que de nouveaux paiements le couvrent | S'il n'est pas couvert au bout de 5 jours ouvrés, il échoue et le marchand reçoit un email |
| Carte expirée ou remplacée | La banque émettrice crédite généralement le compte du client quand même | Si le remboursement revient, il passe « Échoué », la somme retourne au solde, et le marchand rembourse autrement |
| Remboursement envoyé deux fois par erreur | Un remboursement parti ne peut pas être rappelé | Le marchand demande au client de lui restituer la différence ; seuls les remboursements « En attente de validation » ou « En attente de fonds » peuvent être annulés |
| Paiement contesté par l'acheteur | Le remboursement est bloqué, sinon le client serait crédité deux fois | Le marchand peut accepter le litige ; la procédure est décrite sur [la page anglaise sur les litiges](chargebacks.md), et un spécialiste francophone suit la file `disputes` |
| Paiement encaissé dans une autre devise | Le remboursement se fait dans la devise du paiement ; le solde est débité au taux du jour du remboursement | Prévenir le marchand que le montant débité peut différer de celui encaissé à l'origine |
| Vers une autre carte ou un compte bancaire | Impossible | Le remboursement repart toujours vers la carte qui a payé |

## Modèles de réponse

Adaptez toujours le modèle au ticket : le prénom, le montant, la date. La liste complète des modèles se trouve sur [la page des macros](macros.md).

`fr-remboursement-procedure` :

> Bonjour {{merchant.first_name}},
>
> Pour rembourser ce paiement, ouvrez-le dans Merchant Hub, onglet **Paiements**, puis cliquez sur **Rembourser**. Indiquez le montant, total ou partiel, et un motif, puis confirmez. La banque de votre client affiche généralement le remboursement sous 5 à 10 jours ouvrés.
>
> Bien cordialement,

`fr-remboursement-hors-delai` :

> Bonjour {{merchant.first_name}},
>
> Ce paiement date du {{payment.date}}. Or un paiement par carte ne peut être remboursé par Quillmoor que dans les 180 jours qui suivent le paiement. Si vous souhaitez dédommager votre client, il vous faudra le faire directement, par exemple par virement bancaire.
>
> Bien cordialement,

`fr-remboursement-validation-t2` :

> Bonjour {{merchant.first_name}},
>
> Votre remboursement de {{refund.amount}} est en attente d'une seconde validation, que nous appliquons à tout remboursement au-delà de 10 000 € afin de protéger votre compte. Nos spécialistes l'examinent pendant nos heures d'ouverture, du lundi au vendredi de 9 h à 18 h, en général sous 4 heures ouvrées. Le statut changera dans Merchant Hub dès la validation.
>
> Bien cordialement,

`fr-remboursement-porteur` :

> Bonjour,
>
> Quillmoor traite les paiements par carte pour le compte du vendeur auprès duquel vous avez effectué votre achat, mais nous ne pouvons pas décider d'un remboursement à sa place. Nous vous invitons à contacter directement le vendeur, dont le nom figure sur votre relevé de carte. Si vous n'obtenez pas de réponse, votre banque pourra vous conseiller.
>
> Bien cordialement,

## Questions fréquentes

**« Mon client dit que sa banque n'a rien reçu. »** Vérifiez le statut. S'il est « Réussi », donnez la référence de l'acquéreur et le délai habituel de 5 à 10 jours ouvrés. Au-delà, transmettez au T2.

**« Puis-je annuler un remboursement ? »** Oui, depuis Merchant Hub, tant qu'il est « En attente de validation » ou « En attente de fonds ». Ensuite, non.

**« Pourquoi mon remboursement de 12 000 € n'est-il pas parti ? »** Parce qu'il dépasse 10 000 € et attend la validation par le niveau T2. Vérifiez qu'il figure bien dans la file `refund-approvals` et indiquez au marchand le délai.

**« Un marchand stratégique peut-il obtenir une exception au délai de 180 jours ? »** Non. Le statut de marchand stratégique change la personne qui répond, pas les règles.

**« Le ticket est arrivé en anglais, mais le marchand est français. »** Répondez dans la langue du ticket et proposez de poursuivre en français. Les usages de l'équipe sont décrits sur [la page consacrée aux marchands francophones](french-speaking-merchants.md).
