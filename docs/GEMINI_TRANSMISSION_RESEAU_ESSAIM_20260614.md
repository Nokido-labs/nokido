# [ARCH] Topologie Réseau Essaim : Transport Hybride TCP/UDP (Multicast + Jumbo Frames)
*Auteur : Gemini & user — 2026-06-14*

## 1. Contexte & Limites du Modèle Classique (Unicast)
Dans une architecture d'agents distribués (Grid/Neural comme Nokido), la transmission classique des vecteurs d'état (ex: 4096d en FP16, soit ~8 Ko) sature la bande passante locale et le CPU si le Hub doit dupliquer (Unicast) le message pour chaque nœud (ex: 5 mini-PCs).

## 2. Le Paradigne Hybride (NATS + Raw UDP Multicast)
Pour marier durabilité et "flux de conscience" temps-réel, nous adoptons une topologie de transport hybride :

* **Transactionnel / État (TCP Unicast)** : Géré par **NATS JetStream**. Dédié aux commandes GOAP, à l'écriture sérialisée dans le Blackboard (SQLite WAL), et à la validation des états.
* **Télémétrie / Pensées (UDP Multicast)** : Géré par des **Raw Sockets / ZeroMQ**. Dédié à la diffusion continue des vecteurs d'états (WorldModel) à l'ensemble du cluster pour une mise à jour synchrone et non-bloquante des index USearch locaux. Le switch réseau clone le paquet matériellement, libérant le CPU hôte.

## 3. Alignement Physique & Compatibilité
L'ennemi du Multicast est la fragmentation IP (MTU standard à 1500). Un vecteur de 8 Ko sera fragmenté en 6 paquets. Si un paquet est perdu (UDP), le vecteur entier est jeté, créant un pic d'interruptions CPU.

**Solution : Activer les Jumbo Frames (MTU 9000)**
En forçant un MTU à 9000, le vecteur 4096d tient dans un seul paquet physique. 

> **Observation Locale :**
> Le système de l'hôte principal (Windows) a été vérifié : **l'interface principale `Ethernet 2` est DÉJÀ configurée avec un MTU de 9000.** L'OS est donc prêt à expédier ces paquets sans fragmentation.

**Pré-requis sur le Switch Local :**
1. Autoriser les Jumbo Frames (MTU 9000).
2. Activer `IGMP Snooping v3` pour empêcher l'inondation de tout le réseau domestique (évite le Déni de Service interne).

## 4. Implémentation de Référence (Python)
L'émission des vecteurs perceptifs vers le cluster s'effectuera via une configuration multicast standard (Time-To-Live = 1 pour cantonner au LAN) :

```python
import socket

def create_multicast_sender():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    return sock

# Émission du vecteur 4096D FP16 (non fragmenté grâce au MTU 9000)
# Les nodes écoutent le groupe IGMP (ex: 239.255.0.1)
multicast_group = ('239.255.0.1', 9999)
sender_sock.sendto(wm_vector.tobytes(), multicast_group)
```

## 5. Frontière LAN/WAN : L'Illusion du MTU 9000 sur Internet
**Avertissement critique :** L'optimisation Jumbo Frames (MTU 9000) est strictement réservée à l'intra-essaim sur le réseau local (LAN).

Il est illusoire de penser que l'infrastructure cœur de Free (4rd) conservera ce MTU sur le transit Internet mondial. Si l'Ingress Adapter force un MTU de 9000 vers l'API d'Anthropic ou Google, le paquet sera :
- Soit rejeté par le premier routeur de transit (Erreur ICMP Type 3 Code 4 : *Destination Unreachable, Fragmentation Required*) si le flag DF est actif.
- Soit fragmenté par l'OS hôte en paquets de 1500 octets, réduisant à néant l'optimisation.

**Règle d'implémentation (Path MTU) :**
- **Flux de Conscience / Inter-processus Local (UDP) :** Socket lié à l'interface LAN (Port SFP+ / Switch) opérant à **MTU 9000**.
- **Requêtes Cloud / Ingress Adapter (TCP/REST) :** Le Hub s'assure que les clients HTTP (`httpx`) empruntent l'interface WAN (ou que la couche TCP négocie le MSS correctement) avec un **MTU effectif de 1500**. L'adaptation TCP doit être transparente pour les API distantes.

## 6. L'Atomicité Sémantique : Le Réseau comme Bus Système (PCIe Distribué)
Le ratio de 1 à 6 offert par le MTU 9000 change radicalement la nature du flux dans l'essaim, transformant le réseau LAN en un véritable "bus système distribué" :

* **Atomicité de la Pensée :** Un vecteur 4096d FP16 pèse exactement 8192 octets. En MTU 9000, il tient dans UNE seule trame physique UDP. La donnée n'est plus fragmentée. Si un paquet est perdu, l'essaim perd une mise à jour isolée et atomique, et non un fragment corrompant l'ensemble de la matrice.
* **Effondrement de la "Taxe CPU" :** En divisant par 6 le nombre d'interruptions matérielles (softIRQs) sur les cartes réseau, les processeurs (ex: APU Ryzen 8700G) récupèrent des cycles massifs. Ce temps CPU est réalloué aux calculs de similarité (SimSIMD) et aux boucles de décision GOAP.
* **Espace de Métadonnées Gratuit :** 8192 octets (vecteur) + 42 octets (headers UDP/IP/Ethernet) = 8234 octets. Il reste mathématiquement **~766 octets libres** dans la trame pour injecter des métadonnées applicatives riches (worker_id, timestamps, contextes intentionnels, hash AST) sans surcoût réseau, garantissant un contexte toujours synchrone avec le vecteur.
