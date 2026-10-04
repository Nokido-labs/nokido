# ⚡ Nokido

### Erschaffung eines künstlichen Organismus — nicht einfach ein weiterer KI-Agent

> **Ein System, das lernt, sich erinnert, sich selbst reguliert — auf deiner Maschine, mit deiner Hardware, für deine Daten.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/)
[![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/)
[![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/)
[![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![MCP](https://img.shields.io/badge/MCP-2025--03--26-9146FF?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](#-security)
[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

**MCP clients & runtimes :**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20HTTP-D97757?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](#-ecosystem-mcp--multi-llm)
[![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](#-ecosystem-mcp--multi-llm)
[![ZCode (z.ai)](https://img.shields.io/badge/ZCode%20(z.ai)-MCP%20HTTP-6E56CF?logoColor=white)](https://zcode.z.ai/en)
[![Mistral Vibe](https://img.shields.io/badge/Mistral%20Vibe-MCP%20HTTP-FA520F?logo=mistralai&logoColor=white)](https://github.com/mistralai/mistral-vibe)
[![Mammouth Code](https://img.shields.io/badge/Mammouth%20Code-MCP%20HTTP-6D4C41)](https://github.com/mammouth-ai/code)

**LLM providers (20 vendors · 39 routed slots, by use-case) :**
[![Ollama](https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white)](https://ollama.com/)
[![Groq](https://img.shields.io/badge/Groq-cloud-F55036)](https://groq.com/)
[![Cerebras](https://img.shields.io/badge/Cerebras-cloud-FF6B35)](https://www.cerebras.ai/)
[![Mistral](https://img.shields.io/badge/Mistral-cloud-FA520F)](https://mistral.ai/)
[![Cohere](https://img.shields.io/badge/Cohere-cloud-39594D)](https://cohere.com/)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-cloud-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/)
[![GitHub Models](https://img.shields.io/badge/GitHub%20Models-cloud-181717?logo=github&logoColor=white)](https://github.com/marketplace/models)
[![Cloudflare Workers AI](https://img.shields.io/badge/Cloudflare%20Workers%20AI-cloud-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-cloud-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/)
[![SambaNova](https://img.shields.io/badge/SambaNova-cloud-EE3124)](https://sambanova.ai/)
[![LM Studio](https://img.shields.io/badge/LM%20Studio-local-181717)](https://lmstudio.ai/)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-cloud-4285F4?logo=google&logoColor=white)](https://ai.google.dev/)
[![Anthropic](https://img.shields.io/badge/Anthropic-cloud-D97757?logo=anthropic&logoColor=white)](https://anthropic.com/)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-cloud-6C5CE7)](https://openrouter.ai/)
[![OpenAI](https://img.shields.io/badge/OpenAI-cloud-412991?logo=openai&logoColor=white)](https://openai.com/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-cloud-4D6BFE)](https://www.deepseek.com/)
[![Z.ai GLM](https://img.shields.io/badge/Z.ai%20GLM-cloud-6E56CF)](https://z.ai/)
[![Moonshot Kimi](https://img.shields.io/badge/Moonshot%20Kimi-cloud-1F1F1F)](https://www.moonshot.cn/)

**Languages:** [English](../../README.md) · [Français](../../docs/i18n/README.fr.md) · [Español](../../docs/i18n/README.es.md) · [简体中文](../../docs/i18n/README.zh-CN.md) · [Português](../../docs/i18n/README.pt-BR.md) · [日本語](../../docs/i18n/README.ja.md) · [Deutsch](../../docs/i18n/README.de.md) · [العربية](../../docs/i18n/README.ar.md)

---

## 🧭 In einer Minute

Nokido ist eine **Local-first-Laufzeit für einen künstlichen Organismus**: das Nervensystem und die
Physiologie, die mehrere KIs — lokale Modelle, Cloud-Anbieter, Coding-Agenten wie Claude Code,
Codex CLI, OpenCode oder Antigravity — auf Ihrem Rechner zusammenarbeiten lassen, **ohne dass sie
zu einem Haufen unabhängiger Agenten werden**.

Es geht von drei Beobachtungen aus, die im [Manifest](../../MANIFESTO.md) ausgeführt werden:

1. **Die meiste KI ist extern.** Prompts, Code und Dokumente laufen über Infrastruktur, die Ihnen nicht gehört.
2. **Die meiste KI ist gedächtnislos.** Gedächtnis ist ein Zusatz, kein Fundament.
3. **Die meiste KI hat nur ein Gehirn.** Ein einziges großes Modell beantwortet alles, während die
   Biologie Intelligenz als verteilt und spezialisiert zeigt.

Nokido fügt kein weiteres Agenten-Framework hinzu. Es fügt die **Organismus-Schicht** um die Modelle hinzu:

* **Routing** zwischen lokalen und Cloud-Modellen je nach Anwendungsfall, mit lokalem Rückfall;
* **Langzeitgedächtnis mit Herkunftsnachweis** — Volltext- und Vektorsuche über das, was das System gelernt hat;
* **Regulierung** von CPU, RAM, Warteschlangen und Anbietern — Homöostase, Reflexe, zirkadiane Zyklen;
* **deterministische Gates** um Aktionen — AST-Prüfungen, Secret-Scanning, RBAC, Egress-Kontrolle;
* **Nachrichten zwischen Agenten** (M2M, Schwärme) und **Introspektion** des eigenen Codes und Zustands;
* **ein einziger Hub**, den Clients über MCP erreichen: Der Client bleibt austauschbar, das System bleibt bestehen.

### Ein Nachweissystem, nicht nur eine Architektur

Nokido trennt drei Dinge, die die meisten Projekte vermischen: was **deklariert**, was **beobachtet**
und was **verifiziert** ist. Ein Port, der antwortet, beweist nicht, dass ein Modell geladen ist; ein
angenommener Befehl ist kein erreichter Zustand; eine Sonde, die nicht nachsehen kann, meldet
`ILLISIBLE` (unlesbar), niemals „nein“. Diese Unterscheidungen werden in Code und CI durchgesetzt —
und diese README folgt ihnen: Ihre [Statustabelle](#-projektstatus) stellt jeder Aussage ihren Nachweis
gegenüber, und eine CI-Kontrolle schlägt fehl, wenn ein pausierter Dienst als betriebsbereit angezeigt wird.

Souveränität ist eine **Architektur**, keine Garantie: Mit Nokido behalten Sie Daten, Gedächtnis und
kritische Entscheidungen auf Ihrer eigenen Infrastruktur, mit expliziter Kontrolle darüber, was sie
verlässt. Ihre eigene Compliance hängt weiterhin davon ab, wie Sie es einsetzen — und was Nokido
**nicht** behauptet, steht weiter unten.

## 🚀 Schnellstart

<!-- PIP:BEGIN nokido-agent version=0.20.8 -->
**From PyPI** — [`nokido-agent 0.20.8`](https://pypi.org/project/nokido-agent/0.20.8/), published after the
install proof on Linux, Windows and macOS:

```bash
pip install nokido-agent==0.20.8
nokido-doctor                   # what this machine has, lacks, or cannot read
```
<!-- PIP:END -->

**Aus einem Klon** — der Weg, den auch die CI nimmt ([Details](#-installation)):

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # was dieser Rechner hat, was fehlt, was unlesbar bleibt
python tools/nokido_hub.py
```

Danach sollte `curl http://localhost:8766/health` antworten. Nächste Schritte:
[Voraussetzungen und Docker-/native Wege](#-installation) ·
[Installation überprüfen](#-installation-überprüfen) ·
[Claude Code, Codex, OpenCode … anbinden](#-einen-externen-agenten-anbinden).

---

## 🧠 Warum „Nokido“?

**Nokido** schöpft seine Inspiration aus dem Japanischen:

* **脳 — Nō**: das Gehirn, Intelligenz, Kognition;
* **機動 — Kidō**: Mobilität, In-Bewegung-Setzen, die Handlungsfähigkeit.

Der Name bringt die zentrale Idee des Projekts zum Ausdruck:

> **künstliche Intelligenz mit einer Orchestrierung zusammenzuführen, die von der organischen Organisation des menschlichen Körpers inspiriert ist.**

Nokido versucht daher nicht bloß, ein besseres künstliches „Gehirn“ zu bauen.

Es strebt danach, einen **digitalen Organismus** zu erschaffen: spezialisierte Organe, persistentes Gedächtnis, ein Nervensystem zur Kommunikation, Reflexe, endokrine und homöostatische Regulation, ein Immunsystem, Ausführungsmuskeln — und letztlich ein neuronales Substrat, das in der Lage ist, sich in Richtung neuromorpher Hardware weiterzuentwickeln.

Die Biologie ist hierbei keine grafische Metapher.

**Sie dient als architektonisches Vorbild.**

Das Ziel ist das Erreichen einer **Symbiose zwischen künstlicher Kognition und organischer Orchestrierung**: verteilte Intelligenz, Anpassung, Regulation, Resilienz und situierte Handlung.

---

# 🫀 Die Idee

Die meisten KI-Systeme sind als ein **Modell umgeben von Werkzeugen** konzipiert.

Nokido ist als etwas anderes konzipiert:

> **eine Architektur eines künstlichen Organismus, deren biologische Beschränkungen im laufenden System zunehmend durchgesetzt werden.**

Der Organismus ist nicht länger bloß eine Metapher, sondern eine physische Architekturbeschränkung, die durch die CI erzwungen wird.

Das Ziel ist, einige der **architektonischen Eigenschaften eines lebenden Körpers** zu reproduzieren:

* spezialisierte Organe anstelle eines universellen Prozesses;
* persistenter interner Zustand anstelle zustandsloser Konversationen;
* schnelle Reflexe und langsamere Deliberation;
* Regulation nach Art des Nerven- und Hormonsystems;
* Immungrenzen um externe Interaktionen;
* verteilte Kognition;
* Anpassung unter Ressourcenbeschränkungen;
* mehrere Kommunikationswege;
* ein Rechensubstrat, das sich im Laufe der Zeit in Richtung neuromorpher Hardware bewegen kann.

Die biologische Sprache ist daher kein Dekor.

Sie ist eine **Design-Disziplin**.

Von einer Nokido-Komponente wird erwartet, dass sie eine klar identifizierbare Rolle im Organismus einnimmt: Was nimmt sie wahr, welchen Zustand hält sie aufrecht, was reguliert sie, was hängt von ihr ab und was geschieht, wenn sie ausfällt?

---

# 🧬 Der Organismus

```text
                              NOKIDO
                        DIGITAL ORGANISM
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
     NERVOUS                IMMUNE                 ENDOCRINE
      SYSTEM                SYSTEM                  SYSTEM
        │                      │                      │
   events / routing       firewall / RBAC       resource regulation
   M2M / protocols        membrane / trust      quotas / pressure
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                MEMORY                   MUSCLES
               RAG / FTS               workers / tools
             vector space             execution / actions
                  │                         │
                  └────────────┬────────────┘
                               │
                        CENTRAL INTEGRATION
                           Hub / MCP
                               │
                 distributed cognition layer
                  ACP / A2A / M2M / SWARM
                               │
                         neural substrate
                          SNN / edge / NPU
                               │
                      future neuromorphic
                           substrates
```

Dieses Modell spiegelt sich im gesamten Repository wider: Die Architekturdokumentation bildet das System explizit auf Gehirn, Hippocampus, Synapsen, Nervensystem, Immunsystem, Muskeln, Urteils- und Regulationsebenen ab.

---

# 🧠 Was Nokido tatsächlich ist

Nokido kombiniert mehrere Schichten, die üblicherweise getrennt voneinander entwickelt werden.

## Intelligenz

Mehrere lokale und Cloud-Modelle können je nach Aufgabe, Verfügbarkeit und Richtlinien geroutet werden.

Nokido ist um **viele spezialisierte Intelligenzen** herum konzipiert, nicht um ein einzelnes Modell, das jede Rolle ausfüllen muss.

## Persistentes Gedächtnis

Das System unterhält eine persistente hybride Retrieval-Schicht, die lexikalisches und semantisches Retrieval kombiniert.

Der primäre Embedding-Raum ist:

**BGE-M3 · 1024 Dimensionen**

Das Gedächtnis ist darauf ausgelegt, die Lebensdauer einzelner Modellsitzungen zu überdauern.

## Regulation

CPU, RAM, GPU/NPU, Speicherplatzdruck, Warteschlangendruck, Latenz und Provider-Kapazitäten können das Systemverhalten beeinflussen.

## Governance

Probabilistische Generierung wird, wo immer möglich, von deterministischen Prüfungen getrennt.

LLMs können Vorschläge machen.

Richtlinien, Tests und deterministische Gates können entscheiden, ob ein Vorschlag akzeptabel ist.

## Multi-Agenten-Kollaboration

Agenten können über persistente M2M-Mechanismen kommunizieren und über Swarm-Workflows zusammenarbeiten.

## Interoperabilität

Nokido ist darauf ausgelegt, an mehreren komplementären Agenten-/Werkzeug-Protokollen teilzunehmen:

**MCP · ACP · A2A**

## Neuronales Substrat

Eine softwarebasierte SNN-Schicht existiert bereits, mit einem längerfristigen Pfad hin zu Edge- und neuromorpher Hardware.

---

# 🌐 MCP · ACP · A2A

Nokido ist nicht an ein einziges Kommunikationsprotokoll gebunden.

### MCP — Werkzeuge und Fähigkeiten

Der zentrale Hub stellt Nokido als MCP-Server für Agenten-Clients bereit.

Dies ist die primäre Werkzeugschnittstelle für die Interaktion mit der Runtime.

### ACP — Agenten-Interoperabilität

Nokido beinhaltet beides:

* einen **ACP-Server**, der Nokido als ACP-Agenten exponiert;
* einen **ACP-Client**, der es Nokido ermöglicht, externe ACP-Agenten zu steuern.

Die aktuelle ACP-Implementierung umfasst Sitzungserstellung, Prompt-Austausch, Abbruch, Berechtigungsanfragen und Fähigkeiten-Aushandlung.

Der entfernte WebSocket-Transport ist experimentell und befindet sich weiterhin in der Entwicklung.

### A2A — Agent-to-Agent

Nokido implementiert außerdem eine **Tier-1-A2A-Oberfläche**.

Aktuelle Operationen umfassen:

```text
message/send
tasks/get
tasks/cancel
```

mit authentifizierter Aufgabenverarbeitung und Agenten-Erkennung.

Die A2A-Card wird aus dem **lebendigen Zustand des Systems** generiert, nicht als statische Marketingdatei gepflegt.

Nokido unterscheidet:

```text
DECLARED
   ↓
AVAILABLE
   ↓
VERIFIED
```

Nur Fähigkeiten, die sowohl verfügbar als auch durch Verifizierung abgesichert sind, qualifizieren sich für die öffentliche Fähigkeitenkarte.

Dies geschieht mit voller Absicht:

> **Im Repository vorhandener Code reicht nicht aus, um zu behaupten, dass eine Fähigkeit derzeit nutzbar ist.**

---

# 🐝 Swarm-Kognition

Nokido entwickelt einen **ressourcenbewussten Multi-Agenten-Schwarm**.

Das Grundmuster ist:

```text
goal
 ↓
GOAP
 ↓
DAG
 ↓
parallel workers
 ↓
validation
 ↓
reduce
 ↓
final state
```

Die Schwarm-Architektur enthält bereits die wesentlichen Bausteine:

* DAG-Scheduling;
* parallele Ausführung in Runden;
* sterile Worker-Kontexte;
* Workspace-Scoping;
* lokale Inferenz-Worker;
* Gegendruck (Backpressure);
* deterministische Validierung;
* isolierte Ausführung (Sandboxed Execution);
* Wiederholungsrichtlinien (Retry Policies);
* geteilte Overlays;
* atomare Reduktion;
* Live-Schwarm-Beobachtbarkeit.

Das Projekt bevorzugt explizit die **Wiederverwendung bestehender Orchestrierungsprimitive, anstatt eine zweite Orchestrierungs-Engine zu bauen**.

Das Ziel ist nicht, „so viele Agenten wie möglich zu starten“.

Das Ziel ist:

> **verteilte Kognition ohne unkontrollierten gemeinsamen Zustand oder unkontrollierte Nebeneffekte.**

---

# 🧠 Gedächtnis und Retrieval

Nokido behandelt das Gedächtnis als ein Subsystem des Organismus.

```text
                         QUERY
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
             FTS          BM25        VECTOR
                                      BGE-M3
              └────────────┼────────────┘
                           ▼
                        FUSION
                           ▼
                       RERANKING
                           ▼
                         CONTEXT
```

Das RAG enthält Code, Dokumentation, Projektentscheidungen, Erkenntnisse, Traces und weiteres persistentes Wissen.

Der aktuelle Vektorkontrakt ist **1024-dimensionales BGE-M3**.

Dies ist entscheidend, da ein anderes 1024-dimensionales Modell nicht automatisch mit dem bestehenden Vektorraum kompatibel ist.

---

# 🛡️ Immunsystem und Souveränität

Der Organismus besitzt eine Grenze.

Nokido behandelt Cloud-Dienste und externe Agenten daher als externe Umgebungen und nicht als vertrauenswürdiges internes Gedächtnis.

Die Sicherheitsarchitektur umfasst:

* `SemanticFirewall`;
* `SovereignMembrane`;
* Sechs-Ringe-RBAC;
* Geheimnis-Tresore;
* Scannen nach Geheimnissen (Secret Scanning);
* Shell-Guards;
* isolierte Ausführung (Sandboxed Execution);
* kontrollierten Cloud-Ausgang (Cloud Egress);
* Fähigkeiten-Gates.

Der Cloud-Ausgang ist darauf ausgelegt, Vorab- (Pre-Flight) und Nachbereitungs-Kontrollen (Post-Flight) zu durchlaufen, wobei sensible Identifikatoren durch die souveräne Membran anonymisiert werden.

Die Standardarchitektur bindet den Hub an localhost und behandelt den Cloud-Zugriff als Opt-in.

---

# 🫀 Homöostase

Ein Körper kann nicht für jede Aktivität unbegrenzt Energie aufwenden.

Nokido behandelt Rechenleistung daher als eine physiologische Ressource.

Die Regulationsschicht überwacht und reagiert auf Faktoren wie:

* RAM-Druck;
* CPU-Druck;
* GPU/NPU-Verfügbarkeit;
* thermischer Zustand;
* Warteschlangendruck;
* Dienstzustand (Service Health);
* Inferenzverfügbarkeit;
* Provider-Kontingente;
* Latenz.

Die vorgesehene Schleife ähnelt einer softwarebasierten Form der Homöostase:

```text
MONITOR
   ↓
ANALYZE
   ↓
PLAN
   ↓
ACT
   ↓
OBSERVE
   ↺
```

Das Projekt bildet dies explizit auf MAPE-K und kybernetische Regulation ab.

---

# ⚡ Reflexe

Nicht jede Reaktion sollte ein LLM erfordern.

Nokido wandelt wiederkehrende technische Fehler schrittweise in ausführbare Reflexe um:

```text
incident
   ↓
measurement
   ↓
root cause
   ↓
rule
   ↓
test
   ↓
gate
   ↓
future prevention
```

Beispiele hierfür sind:

* Verhindern pathologischer Datenbankzugriffe;
* Zurückweisen ungültiger Pläne;
* Stoppen des Abflusses von Geheimnissen;
* Steuerung des Worker-Drucks;
* Validieren von Architekturdeklarationen;
* Erkennen veralteter Zustände (Stale State);
* Verhindern unsicherer Mutationspfade.

Das Prinzip ist einfach:

> **Eine Lektion, die nur im Kontext eines Agenten existiert, ist noch nicht Teil des Organismus.**

---

# ⚡ Spiking neuronales Substrat

Nokido enthält bereits eine echte softwarebasierte SNN-Schicht.

Die aktuelle Architektur umfasst:

| Komponente          | Rolle                   |
| ------------------- | ----------------------- |
| `forge_snn_core`    | lernbares LIF-Substrat  |
| `forge_snn_monitor` | Telemetrie → Spikes     |
| `forge_snn_router`  | SNN-basiertes Routing   |

Das Repository unterscheidet diese explizit von älterem ereignisorientiertem Routing-Code, bei dem es sich nicht selbst um ein Spiking Neural Network handelt.

Die langfristige Ausrichtung lautet:

```text
software SNN
     ↓
edge acceleration
     ↓
neuromorphic hardware
     ↓
event-driven substrate
```

Mögliche zukünftige Zielplattformen umfassen Technologien wie **Loihi 2** und **Akida**.

Dies sind zukünftige Hardwareziele und keine Behauptungen aktueller Produktionsunterstützung. Die Hardware-Roadmap ordnet neuromorphe Hardware nach der aktuellen Phase konventioneller APU-/Edge-Beschleunigung ein.

---

# 🧠 Kognitive Architektur

Der Organismus wird zudem um eine Schleife im AMI-Stil herum entwickelt:

```text
perception
    ↓
world model
    ↓
cost
    ↓
actor
    ↓
planning / MPC
    ↓
action
    ↓
observation
    ↺
```

Der aktuelle Stack umfasst Komponenten für:

* Wahrnehmung (Perception);
* Weltmodelle (World Models);
* Kostenfunktionen (Cost Functions);
* Akteur/Planung (Actor/Planning);
* MPC (Model Predictive Control);
* Policy-/Value-Netzwerke;
* Aktive Inferenz (Active Inference);
* Kontinuierliches Lernen (Continual Learning).

Diese Module sollen Nokido über eine reine „Prompt → Antwort“-Architektur hinausführen.

---

# 💻 Installation

Nokido unterstützt derzeit:

**Windows · macOS · Linux**

Es gibt drei praktische Installationswege.

## Anforderungen

Minimum:

* **Python 3.12+**
* **8 GB RAM**
* ca. **2 GB freier Festplattenspeicher** für eine Minimalinstallation

Empfohlen:

* **16+ GB RAM**
* **Docker 24+**
* Ollama für einfache lokale LLM-Inferenz

Umfangreiche ML-Extras erfordern erheblich mehr Speicherplatz, da sie Pakete wie PyTorch/JAX installieren.

---

## 🐳 Option A — Docker

Empfohlen für den schnellsten isolierten Test.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

Ein lokales Modell herunterladen:

```bash
docker exec laforge-ollama \
  ollama pull qwen2.5-coder:latest
```

Den Hub überprüfen:

```bash
curl http://localhost:8766/health
```

Erwartetes Ergebnis:

```json
{"ok":true,...}
```

### Docker-Profile

| Profile | Main components                                              |
| ------- | ------------------------------------------------------------ |
| `core`  | Hub + Ollama                                                 |
| `full`  | Core + Deno web/event services + embedding worker components |
| `all`   | Full + networking/search services                            |
| `dev`   | Development database tooling                                 |

Der Docker-Installationsleitfaden führt die Profildefinitionen und Image-Varianten.

---

## 🐧 Option B — Natives Linux / macOS

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

bash install.sh
```

Für den größeren Stack:

```bash
EXTRAS=full bash install.sh
```

Für den vollständigen schweren ML-Stack:

```bash
EXTRAS=all bash install.sh
```

Das Installationsprogramm erstellt ein `.venv`, installiert die ausgewählten Extras und bereitet die Vault-Integration vor.

Aktivieren:

```bash
source .venv/bin/activate
```

---

## 🪟 Option C — Natives Windows

```powershell
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

.\install.ps1
```

Das Windows-Installationsprogramm erkennt die erwartete Python-Umgebung und konfiguriert die NSSM-gestützte Dienstarchitektur.

Für ML-/Embedding-Extras:

```powershell
.\install.ps1 -ML
```

---

# ✅ Installation überprüfen

Überprüfen Sie nach der Installation die drei grundlegenden Oberflächen.

### 1. Hub-Zustand (Health)

```bash
curl http://localhost:8766/health
```

### 2. Geheimnis-Tresor (Secrets Vault)

```bash
nokido-secrets status
```

### 3. MCP-Discovery

```bash
curl -s \
  -X POST http://localhost:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/list"
  }'
```

Die aktuelle Dokumentation setzt voraus, dass der Hub seine MCP-Werkzeugoberfläche über diesen Endpunkt bereitstellt.

---

# 🚀 Erste Schritte

Sobald der Hub läuft, kann Nokido getestet werden, ohne einen zweiten Agenten anzubinden.

Beispiel:

```python
import requests

response = requests.post(
    "http://localhost:8766/mcp",
    json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "ask",
            "arguments": {
                "provider": "auto",
                "message": "Explain how Nokido's RAG works in three lines."
            }
        }
    },
    timeout=120,
)

print(response.json())
```

Für lokale Inferenz Ollama konfigurieren und ein Modell laden:

```bash
ollama pull qwen2.5-coder:latest
```

Nokido kann dann den lokalen Stack nutzen, bevor es auf konfigurierte Cloud-Provider zurückgreift.

---

# 🔑 Provider und Geheimnisse

API-Schlüssel sollten nicht in `.env` abgelegt oder in das Repository committed werden.

Nokido verwendet einen maschinengestützten Tresor:

* **DPAPI** unter Windows;
* **Keychain** unter macOS;
* **libsecret / keyring** unter Linux.

Die Web-Administration stellt die Provider-Konfiguration bereit unter:

```text
http://127.0.0.1:8766/admin/providers
```

oder über die CLI-Vault-Werkzeuge.

Beispiel:

```bash
nokido-vault set -k GROQ_API_KEY
```

Anschließend:

```bash
nokido-secrets status
```

Konsultieren Sie die Sicherheitsdokumentation, bevor Sie netzwerkfähige Endpunkte freigeben.

---

# 🔌 Einen externen Agenten anbinden

Nokido kann mit MCP-Clients verbunden werden, wie etwa:

* Claude Desktop;
* Claude Code;
* Gemini CLI;
* Codex CLI;
* Cline;
* anderen MCP-fähigen Clients.

Die ACP-Unterstützung bietet einen zweiten Pfad für die Interoperabilität von Agenten, einschließlich der Möglichkeit, Nokido selbst als ACP-Agenten bereitzustellen.

A2A ergänzt Agent-to-Agent-Kommunikation für Systeme, die das A2A-Protokoll implementieren.

---

# 🔬 Projektstatus

Jede Zeile stellt einen **deklarierten** Reifegrad dem **Nachweis in diesem Repository**
gegenüber, der ihn trägt: ein Modul, ein Dienst, ein CI-Gate. Jeder zitierte Nachweis wird von
`tools/forge_capability_audit.py` (Kontrolle « tableau de statut ») erneut geprüft: ein ✅ ohne
Nachweis, ein Verweis, der nicht existiert, oder ein pausierter Dienst, der als betriebsbereit
angezeigt wird, lässt die CI scheitern.

Diese Tabelle sagt **nicht**, ob ein Organ *gerade jetzt* schlägt. Nokido ist ein lebender
Körper, und eine README kann ihn nur einfrieren — fragen Sie den Körper selbst, auf Ihrem Rechner:

```bash
nokido-doctor --vivant          # aus einem Klon: python tools/nokido_doctor.py --vivant
```

Es meldet jedes Organ, das einen Puls deklariert — lebendig, unsicher, schlägt nicht mehr, per
Richtlinie abgeschaltet (eine Entscheidung, keine Panne) oder unlesbar — mit dem Nachweis hinter
jedem Urteil.

```text
                                  DECLARED             EVIDENCE IN THIS REPOSITORY
ANATOMY / ORGANISM
  Strict anatomical census        ✅ achieved          `forge_module_census` --check, 0 unclassified
  CI architectural gate           ✅ achieved          `anatomie` gate, blocking since 2026-09-06
  M2M memory separation           ✅ achieved          `forge_db_path`: one switch read by every process
  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis` + `forge_homeostasis_orchestrator`
  Sleep / circadian regulation    🟡 partial           `forge_circadian` beats; 7 of 9 phase targets disabled or undeclared

COMMUNICATION
  MCP                             ✅ operational       `NokidoMCP` hub, enabled by default
  ACP                             🟡 in development    `NokidoAcpWs`, disabled by default
  A2A Tier-1                      ⏸️ paused            `NokidoA2A`, disabled by default (code present)
  M2M                             ✅ operational       `forge_m2m_protocol` validator (intents, pointers)
  Swarm                           🟡 hardening         `forge_swarm` family: NR in CI for 12 of 13 modules (not the base one)

COGNITION
  AMI                             🟡 active            `forge_world_model` + `forge_ami_strategist`
  Active Inference                🟡 active            `forge_active_inference`; homeostat coupling = prototype
  Neuro-symbolic governance       ✅ operational       `NokidoGateConsumer` + `forge_golden_rules_ast`
  Autonomous evolution            🟡 guarded           `forge_mutation_judge`: one gate (owner arming, brake, human lock) + auto-brake on capability regression

PHYSIOLOGY
  Endocrine                       ✅ operational       `NokidoHormonesListener` + `forge_endocrine`
  Nervous system                  ✅ operational       `NokidoAfferent` + `NokidoOrganPulse`
  Immune system                   🟡 partial           `forge_semantic_firewall` + `forge_sovereign_membrane`
  Cortex ↔ autonomic loop         🟡 first piece       `forge_epistemic_daemon`: epistemic drive (gap → inquiry); full coupling not built

NEURAL SUBSTRATE
  Software SNN                    ✅ experimental      `forge_snn_core` + `forge_snn_router`, on demand
  NPU / edge                      🟡 in development    `NokidoBrainWorker`, disabled by default since 2026-07-24
  Neuromorphic hardware           🔬 future            —
```

Ein Dienst, der antwortet, beweist den **Transport**, nicht die Fähigkeit: Er sagt, dass das
Organ reagiert, nicht, dass jedes Werkzeug dahinter funktioniert. Das beweisen die Tests einzeln.

### Was Nokido darüber gelernt hat, ein Organismus zu sein

Durch den Versuch, physiologische Grenzen in Software abzubilden, hat Nokido bereits Beschränkungen entdeckt, die seine kontinuierliche Entwicklung prägen:

* Ein Organ kann im Code existieren, ohne verdrahtet zu sein.
* Das Aussenden eines Signals bedeutet nicht, dass es gehört wird.
* `false` ist nicht dasselbe wie `unreadable`.
* Absichten müssen explizit deklariert werden, nicht erraten.
* Dem SNN mangelte es mehr an geeigneten biologischen Sensoren als an algorithmischer Raffinesse.
* Die zentralisierte Architektur muss schrittweise einige Reflexpfade direkt an die Edge abgeben.

Das Projekt unterscheidet explizit deklarierte, verfügbare und verifizierte Fähigkeiten, anstatt jeglichen Quellcode als produktionsreife Funktionalität zu behandeln.

---

# ⚠️ Was Nokido nicht beansprucht

Nokido beansprucht derzeit **nicht**:

* AGI;
* garantierte Selbstheilung;
* perfekte Autonomie;
* perfektes Selbstbewusstsein;
* universelle Protokollkompatibilität;
* produktionsreife Stabilität für jedes Subsystem;
* produktionsreife Unterstützung neuromorpher Hardware.

Nokido ist ein **Forschungs- und Ingenieurprojekt im Alpha-Stadium**.

Die Architektur ist real.

Einige Subsysteme sind ausgereift.

Einige werden aktiv gehärtet.

Einige sind Forschungsprototypen.

Einige sind zukünftige Richtungen.

Das Repository, seine Tests und seine Live-Fähigkeitsprüfungen sind die maßgebliche Quelle für den aktuellen Stand.

---

# 🔐 Sicherheit

Bitte lesen Sie [`SECURITY.md`](../../SECURITY.md), bevor Sie Nokido über localhost hinaus bereitstellen.

Sicherheitsrelevante Bereiche umfassen:

* Cloud-Ausgang (Cloud Egress);
* Firewall- und Membranlogik;
* RBAC;
* Tresore;
* Sandboxing;
* Netzwerkfreigabe;
* ACP/A2A-Endpunkte.

Sicherheitslücken sollten **zunächst vertraulich gemeldet werden** und nicht öffentlich in einem Issue oder einer Diskussion gepostet werden.

---

# 🤝 Mitwirken

Nokido ist offen für Beiträge, architektonische Änderungen unterliegen jedoch strengen Projektregeln.

Vor einem Beitrag bitte lesen:

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](../../docs/CLA.md)

Der Entwicklungszweig ist derzeit:

```text
alpha
```

Typischer Workflow für Beitragende:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

git checkout -b feat/my-change alpha

bash install.sh
source .venv/bin/activate

pip install -e ".[dev,security]"

ruff check app/ tools/
pytest -m unit
```

Das Projekt verlangt Tests für neue Funktionalitäten, rät von der Duplizierung bestehender Primitive ab und verwendet Sicherheits-Gates für Geheimnisse, Cloud-Ausgang und privilegierte Ausführung.

---

# 📜 Lizenzierung

Nokido verwendet ein **Duales-Lizenzmodell**.

## AGPLv3-or-later

Die standardmäßige Open-Source-Lizenz ist:

**GNU Affero General Public License v3 or later**

Siehe [`LICENSE`](../../LICENSE).

Sie dürfen Nokido unter den Bedingungen der AGPL ausführen, studieren, modifizieren und weiterverbreiten.

Die Bestimmungen zum Netzwerk-Copyleft sind insbesondere dann relevant, wenn ein modifiziertes Nokido-System Nutzern als Netzwerkdienst angeboten wird.

## Kommerzielle Lizenz

Eine separate kommerzielle Lizenz ist für Anwendungsfälle verfügbar, die nicht mit der AGPL vereinbar sind, einschließlich bestimmter:

* proprietärer Produkte;
* Closed-Source-SaaS;
* OEM-Integrationen;
* White-Label-Distributionen;
* proprietärer eingebetteter Implementierungen.

Siehe [`COMMERCIAL.md`](../../COMMERCIAL.md).

Sie benötigen **keine** kommerzielle Lizenz, nur um Nokido privat oder intern unter der AGPL zu nutzen.

## Software und Modelle von Drittanbietern

Die Lizenz von Nokido setzt die Lizenzen von Abhängigkeiten Dritter, Modellen oder externen Providern nicht außer Kraft.

Prüfen Sie vor einer Weiterverbreitung stets die geltenden Upstream-Bedingungen:

* Modellgewichte;
* Provider-SDKs;
* Docker-Images;
* Datensätze;
* externe Dienste.

---

# 📝 Contributor License Agreement

Beiträge erfordern die Annahme des Nokido-CLA, da das Projekt ein duales Lizenzmodell pflegt.

Das CLA:

* überträgt **nicht** Ihr Urheberrecht;
* gewährt dem Maintainer umfassende Rechte an Ihrem Beitrag;
* gestattet eine zukünftige kommerzielle Neulizenzierung;
* beinhaltet eine Patentlizenz;
* ist versioniert.

Das aktuelle individuelle CLA ist in [`docs/CLA.md`](../../docs/CLA.md) dokumentiert.

Unternehmensbeiträge erfordern die dort beschriebene gesonderte Unternehmensvereinbarung.

---

# 🧭 Ingenieursprinzipien

## Messen vor dem Durchsetzen

Ein Detektor verdient sich das Recht, ein Gate zu werden, indem er nachweist, dass er misst, was er vorgibt.

## Evidenz vor Annahme

Unbekannt ist nicht null.

Nicht verfügbar ist nicht tot.

Implementiert ist nicht verifiziert.

## Ursachen beheben, nicht Symptome

Ein deaktivierter Dienst mag das System schützen.

Das bedeutet nicht, dass das zugrunde liegende Problem gelöst ist.

## Geteilten Zustand kohärent halten

Verteilter Zustand erfordert eine explizite Source of Truth und einen kontrollierten Migrationspfad.

## Lektionen in Reflexe verwandeln

Wiederholte Fehler sollten letztlich zu Tests, Gates oder Laufzeit-Schutzmechanismen werden.

## Dem Silizium folgen

Nokido ist so konzipiert, dass sich die kognitive Architektur weiterentwickeln kann, während sich das physische Rechensubstrat verändert.

---

# 🗺️ Roadmap

### Kurzfristig

**Den Organismus kohärenter machen.**

* M2M-Trennung abschließen;
* verifizierte A2A-Fähigkeiten erweitern;
* ACP stabilisieren;
* Schwarm-Ausführung härten;
* Routing der Embedding-Kapazitäten verbessern;
* unnötige Datenbankarbeit reduzieren;
* Homöostase stärken.

### Mittelfristig

**Verteilte Kognition autonomer machen.**

* stärkere Schwarm-Koordination;
* reichhaltigere Peer-Erkennung;
* stärkere autonome Entwicklungsschleifen;
* tiefergehendes ressourcenbewusstes Routing;
* größere Held-Out-Validierungsabdeckung.

### Langfristig

**Das Substrat verändern.**

```text
APU / iGPU
    ↓
edge NPU
    ↓
neuromorphic
    ↓
compute-in-memory
    ↓
continuous neural substrate
```

Die Hardware-Roadmap folgt explizit diesem Fortschritt.

---

# 📚 Dokumentation

### Hier beginnen

* [`docs/wiki/01-Installation.md`](../../docs/wiki/01-Installation.md) — Installation
* [`docs/wiki/02-Quick-Start.md`](../../docs/wiki/02-Quick-Start.md) — Die ersten 30 Minuten
* [`docs/wiki/03-Architecture.md`](../../docs/wiki/03-Architecture.md) — Systemüberblick

### Tiefgehende Architektur

* [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](../../MANIFESTO.md)

### Agenten-Protokolle

* [`docs/ACP_INGRESS.md`](../../docs/ACP_INGRESS.md)
* A2A-Implementierung — `tools/forge_a2a_server.py`, `tools/forge_a2a_card.py`
* Schwarm-Architektur — [`docs/roadmap_forge_swarm.md`](../../docs/roadmap_forge_swarm.md)

### Neuronale / Hardware-Richtung

* [`docs/wiki/13-Hardware-Roadmap.md`](../../docs/wiki/13-Hardware-Roadmap.md)

### Community

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`SECURITY.md`](../../SECURITY.md)
* [`docs/CLA.md`](../../docs/CLA.md)
* [`COMMERCIAL.md`](../../COMMERCIAL.md)

---

# 🌱 Das langfristige Ziel

Nokido versucht nicht, ein weiterer Chatbot zu werden.

Das langfristige Ziel ist der Bau:

> **eines persönlichen künstlichen Organismus, dessen Kognition über spezialisierte Agenten und Substrate verteilt ist, dessen Gedächtnis fortbesteht, dessen Ressourcen reguliert werden, dessen Grenzen geschützt sind, dessen Fehler zu gelernten Beschränkungen werden und dessen Rechensubstrat im Laufe der Zeit von konventionellem Silizium zu neuromorphen Systemen übergehen kann.**

Dieser Organismus existiert noch nicht vollständig. Doch mehrere Organe sind bereits real, funktionsfähig und interagieren aktiv. Die Architektur, um darauf hinzuarbeiten, ist vorhanden.

**Nokido ist der Versuch, ihn Wirklichkeit werden zu lassen.**

---

## Lizenz

**AGPLv3-or-later** · Kommerzielle Lizenzierung verfügbar

Siehe [`LICENSE`](../../LICENSE) und [`COMMERCIAL.md`](../../COMMERCIAL.md).
