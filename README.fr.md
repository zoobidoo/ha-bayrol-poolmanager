# PoolManager pour Home Assistant (intégration Bayrol non officielle)

*[English version](README.md)*

Intégration Home Assistant pour le régulateur de piscine **Bayrol PoolManager 5**. Elle lit les
mesures et l'état de la pompe de filtration, et permet de **modifier le programmateur et le mode de
la pompe**, soit directement sur le réseau local, soit via le portail Bayrol (bayrol-poolaccess.de).

> [!WARNING]
> **Projet non officiel, sans lien avec Bayrol.** « Bayrol » et « PoolManager » sont des marques de
> leur propriétaire, citées uniquement pour indiquer la compatibilité.
> Le PoolManager rappelle lui-même que l'accès à distance n'est permis que si la sécurité des
> personnes, des animaux et des biens est garantie en permanence. Arrêter la pompe de filtration
> arrête aussi la circulation et le dosage. Vous restez seul responsable de votre installation.
> L'intégration n'expose volontairement **ni** le dosage, **ni** l'étalonnage, **ni** les réglages
> de sécurité.

## Fonctions

| Entité | Rôle |
|---|---|
| `sensor.*_ph`, `*_redox`, `*_temperature_de_l_eau` | Mesures |
| Consignes pH / redox | Lecture seule |
| État de la pompe de filtration | En marche / arrêtée / avertissement / erreur |
| `binary_sensor` pompe, alarme générale, absence de débit | |
| Filtration programmée aujourd'hui | Heures programmées (attribut `per_day` par jour) |
| Mode pompe de filtration | Auto (programmateur) / marche forcée / arrêt |
| Plages 1 à 6 | Résumé, début, fin, mode, jours (modifiables) |

L'action `bayrol_poolmanager.set_timer_interval` modifie une plage en un seul appel (début, fin,
mode, jours quelconques). Les diagnostics se téléchargent depuis la page de l'appareil, avec les
identifiants masqués.

> [!CAUTION]
> **Mode de la pompe de filtration.** *Arrêt* coupe la pompe jusqu'à ce que vous la remettiez en
> marche : plus de circulation, et le PoolManager arrête le dosage sans débit. *Marche forcée* la fait
> tourner en continu. Les deux court-circuitent le programmateur. Si vous automatisez cette entité,
> prévoyez toujours le retour en *Auto (programmateur)*, par exemple une automatisation qui y revient
> au bout de quelques heures.

**Compatibilité :** testé sur un PoolManager 5 « Chlorine (Cl) », firmware v221216-M1 (7.8.3). Les
autres variantes (Oxygène, Brome…) devraient fonctionner en lecture, mais leurs identifiants internes
peuvent différer. Ouvrez une *issue* avec le fichier de diagnostics si quelque chose manque.

## Installation

- **HACS** : HACS → ⋮ → *Dépôts personnalisés* → `https://github.com/zoobidoo/ha-bayrol-poolmanager`,
  catégorie *Intégration* → installer → redémarrer Home Assistant.
- **Manuel** : copier `custom_components/bayrol_poolmanager` dans `config/custom_components/`, puis
  redémarrer.

## Configuration

**Paramètres → Appareils et services → Ajouter une intégration → « PoolManager (Bayrol, unofficial) »**.

### A. Réseau local (recommandé)

1. **Trouver l'adresse IP du PoolManager** :
   - soit dans la liste des appareils connectés de votre box ou routeur (appareil nommé Bayrol ou
     PoolManager) ;
   - soit sur l'écran tactile du PoolManager : **Menu → Communication & Interfaces → Network (IP)
     Configuration**.

   Conseil : réservez-lui une IP fixe (bail DHCP statique) dans votre routeur.
2. **Vérifier qu'il répond** : ouvrez `http://<IP>/cgi-bin/webgui.fcgi?xmlitem=34.4001` dans un
   navigateur. Vous devez obtenir un petit XML contenant votre pH.
3. Saisissez l'IP dans l'intégration. Le code d'accès *Customer* est facultatif.

À ce stade l'intégration est en **lecture seule**. Pour autoriser les modifications, ouvrez les
**options** de l'intégration (roue dentée) et renseignez **l'un** des deux couples :

- **Utilisateur distant + mot de passe (écritures en local)** : un « individual user » avec accès
  distant, défini sur le PoolManager dans **Menu → User management → Individual users (menu & remote
  access)**. Si les modifications sont toujours refusées, vérifiez les droits dans **User management
  → Enable remote access for add-on functions** (la pompe de filtration est une « add-on function »).
- **E-mail + mot de passe du portail Bayrol (écritures via le portail)** : la lecture reste locale,
  les modifications passent par bayrol-poolaccess.de. C'est la solution si vous ne connaissez pas le
  mot de passe de l'utilisateur distant : le portail le connecte automatiquement.

### B. Portail Bayrol

Saisissez l'e-mail et le mot de passe de **bayrol-poolaccess.de**. Lecture et écriture passent par le
portail.

**N° d'appareil :** laissez le champ vide, il est détecté automatiquement (premier appareil du
compte). Pour le connaître : connectez-vous sur bayrol-poolaccess.de, cliquez sur **Accès direct** à
côté de votre appareil, et relevez le nombre après `c=` dans la barre d'adresse :

```
https://www.bayrol-poolaccess.de/webview/p/device.php?c=12345
                                                        ^^^^^ n° d'appareil
```

Le lien *Données de l'appareil* (`plant_settings.php?c=12345`) affiche le même numéro.

> [!TIP]
> Les navigateurs préremplissent parfois les champs e-mail / mot de passe avec vos identifiants
> **Home Assistant**. Vérifiez qu'il s'agit bien de ceux du **portail Bayrol** avant de valider.

### Modifier les réglages ensuite

- **Nouvelle adresse IP, nouveau mot de passe du portail :** page de l'intégration → ⋮ →
  **Reconfigurer**. L'entrée, ses entités et leur historique sont conservés.
- **Mot de passe du portail refusé :** Home Assistant affiche une notification de
  *réauthentification* (Paramètres → Appareils et services) ; saisissez-y le nouveau mot de passe.

## Exemples

```yaml
action: bayrol_poolmanager.set_timer_interval
data:
  # device_id : obligatoire seulement si vous avez plusieurs PoolManager
  interval: 1
  start: "10:00:00"
  end: "18:00:00"
  days: [mon, tue, wed, thu, fri, sat, sun]
  mode: normal
```

Avant tout envoi :

- une plage **active** ne peut pas commencer et finir à la même heure (0 h ou 24 h ?). Les plages
  inutilisées sont stockées par l'appareil avec début = fin et aucun jour : c'est accepté ;
- une plage peut passer minuit (22:00–02:00). Les chevauchements sont acceptés : la pompe tourne dès
  qu'une plage est active.

Le dossier [`examples/`](examples/) contient trois fichiers :

- une automatisation qui ajuste la durée de filtration selon la température de l'eau (règle
  empirique « température ÷ 2 », pas une consigne Bayrol) ;
- une carte de tableau de bord ;
- une alternative en lecture seule fondée sur l'interface XML locale documentée par Bayrol.

## Fonctionnement

L'écran **Accès direct** du portail et l'interface web locale dialoguent avec le PoolManager par une
petite API JSON (`POST /cgi-bin/webgui.fcgi?sid=…` avec `{"get": [...], "set": {...}}`).

- Chaque nouvelle session commence par un écran **« User Login (remote access) »**. Tant qu'il n'est
  pas validé, la lecture fonctionne mais **toute écriture est refusée (statut 113)**. Le portail
  préremplit cet écran avec l'utilisateur distant du compte ; en local il est vide, d'où les options
  ci-dessus.
- Dans une session, l'appareil ne renvoie que les valeurs qui ont **changé** depuis la requête
  précédente. L'intégration garde donc un cache et rouvre une session toutes les 30 minutes.
- Interrogation toutes les 60 s par défaut (réglable, minimum 30 s).
- Une modification part en **une seule** requête (début et fin d'une plage ensemble), puis est
  relue : si l'appareil a gardé une autre valeur, Home Assistant affiche une erreur. Les écritures
  sont de simples affectations : la nouvelle tentative automatique après un délai dépassé est sans
  risque.

Le tableau complet des identifiants figure dans le [README anglais](README.md#how-it-works).

## Sécurité

- **Le mode local passe par `http://` non chiffré** (le PoolManager n'a pas de HTTPS) : sur votre
  réseau, les mesures et les identifiants de l'utilisateur distant circulent en clair. Gardez
  l'appareil sur un réseau de confiance (ou un VLAN dédié) et ne l'exposez jamais sur Internet.
- **Les identifiants** (portail, utilisateur distant) sont stockés par Home Assistant dans
  `.storage/core.config_entries`, comme pour toute intégration. Ils sont masqués dans les diagnostics.
- **Test d'écriture :** quand vous saisissez un utilisateur distant dans les options, l'intégration
  réécrit sur l'appareil l'heure de début actuelle de la plage 6 (même valeur, rien ne change) pour
  vérifier que les écritures sont acceptées.

## Dépannage

| Symptôme | Cause / solution |
|---|---|
| « Le PoolManager a refusé la modification (113) » | Aucun utilisateur distant connecté. En local, renseignez l'utilisateur distant ou les identifiants du portail dans les options. |
| « PoolManager injoignable » à la configuration du portail | Vérifiez e-mail et mot de passe (préremplissage du navigateur !) ainsi que le n° d'appareil. La cause exacte est dans le journal (`custom_components.bayrol_poolmanager`). |
| « Plusieurs PoolManager sont configurés » | Ajoutez `device_id` à l'action `set_timer_interval`. |
| « La plage N commencerait et finirait à la même heure » | Modifiez le début ou la fin, ou désactivez la plage (jours : aucun, ou mode : pompe arrêtée). |
| « Le PoolManager a accepté la modification sans l'appliquer » | L'appareil a gardé sa valeur (réglage verrouillé sur l'appareil ?). Vérifiez sur l'écran tactile. |
| La pompe reste « arrêtée » pendant une plage active | Une plage modifiée en cours de route ne s'applique parfois qu'au prochain démarrage. |

## Soutenir le projet

Voir la section [Support the project](README.md#support-the-project) : GitHub Sponsors,
[Buy Me a Coffee](https://buymeacoffee.com/zoobidoo), ou crypto (réseaux EVM : ETH, USDC… sur Ethereum, Base,
Arbitrum, Optimism…) à l'adresse `0x3D7FC7EEb2375b71C3156De836A0866059C65697`. Les signalements de bugs et les contributions comptent tout autant.

## Licence

[MIT](LICENSE), fourni « en l'état », sans aucune garantie.
