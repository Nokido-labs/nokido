# ⚡ Nokido

### Construyendo un organismo artificial — no solo otro agente de IA

> **Un sistema que aprende, recuerda, se autorregula — en tu máquina, con tu hardware, para tus datos.**

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

## 🧭 En un minuto

Nokido es un **runtime local-first para un organismo artificial**: el sistema nervioso y la
fisiología que permiten que varias IA — modelos locales, proveedores en la nube, agentes de código
como Claude Code, Codex CLI, OpenCode o Antigravity — trabajen juntas en su máquina **sin convertirse
en un montón de agentes independientes**.

Parte de tres constataciones, desarrolladas en el [Manifiesto](../../MANIFESTO.md):

1. **La mayoría de la IA es externa.** Prompts, código y documentos viajan a una infraestructura que no es suya.
2. **La mayoría de la IA es amnésica.** La memoria es un añadido, no un fundamento.
3. **La mayoría de la IA tiene un solo cerebro.** Un único gran modelo responde a todo, cuando la
   biología muestra una inteligencia distribuida y especializada.

Nokido no añade un framework de agentes más. Añade la **capa de organismo** alrededor de los modelos:

* **enrutamiento** entre modelos locales y en la nube según el uso, con respaldo local;
* **memoria a largo plazo con procedencia** — búsqueda de texto completo y vectorial sobre lo que el sistema aprendió;
* **regulación** de CPU, RAM, colas y proveedores — homeostasis, reflejos, ciclos circadianos;
* **gates deterministas** alrededor de las acciones — comprobaciones AST, detección de secretos, RBAC, control del egress;
* **mensajería entre agentes** (M2M, enjambres) e **introspección** de su propio código y estado;
* **un único hub** al que los clientes llegan por MCP: el cliente es desechable, el sistema persiste.

### Un sistema de prueba, no solo una arquitectura

Nokido separa tres cosas que la mayoría de los proyectos confunden: lo **declarado**, lo **observado**
y lo **verificado**. Un puerto que responde no prueba que un modelo esté cargado; un comando aceptado
no es un estado alcanzado; una sonda que no puede mirar responde `ILLISIBLE` (ilegible), nunca «no».
Estas distinciones se aplican en el código y en la CI — y este README las sigue: su
[tabla de estado](#-estado-del-proyecto) empareja cada afirmación con su evidencia, y un control de CI
falla cuando un servicio en pausa se muestra como operativo.

La soberanía es una **arquitectura**, no una garantía: Nokido le permite conservar datos, memoria y
decisiones críticas en su propia infraestructura, con control explícito de lo que sale de ella. Su
propio cumplimiento normativo sigue dependiendo de cómo lo despliegue — y lo que Nokido **no**
afirma está escrito más abajo.

## 🚀 Inicio rápido

<!-- PIP:BEGIN nokido-agent version=0.20.8 -->
**From PyPI** — [`nokido-agent 0.20.8`](https://pypi.org/project/nokido-agent/0.20.8/), published after the
install proof on Linux, Windows and macOS:

```bash
pip install nokido-agent==0.20.8
nokido-doctor                   # what this machine has, lacks, or cannot read
```
<!-- PIP:END -->

**Desde un clon** — el camino que usa la propia CI ([detalles](#-instalación)):

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # lo que esta máquina tiene, le falta o no puede leer
python tools/nokido_hub.py
```

Después, `curl http://localhost:8766/health` debería responder. Siguientes pasos:
[requisitos y rutas Docker / nativas](#-instalación) ·
[verificar la instalación](#-verificar-la-instalación) ·
[conectar Claude Code, Codex, OpenCode…](#-conectar-un-agente-externo).

---

## 🧠 ¿Por qué “Nokido”?

**Nokido** se inspira en el japonés:

* **脳 — Nō**: el cerebro, la inteligencia, la cognición;
* **機動 — Kidō**: la movilidad, la puesta en movimiento, la capacidad de acción.

El nombre expresa la idea central del proyecto:

> **hacer converger la inteligencia artificial con una orquestación inspirada en la organización orgánica del cuerpo humano.**

Por lo tanto, Nokido no intenta simplemente construir un mejor "cerebro" artificial.

Busca construir un **organismo digital**: órganos especializados, memoria persistente, un sistema nervioso para la comunicación, reflejos, regulación endocrina y homeostática, un sistema inmunitario, músculos de ejecución—y, en última instancia, un sustrato neuronal capaz de evolucionar hacia hardware neuromórfico.

La biología no es aquí una metáfora gráfica.

**Sirve como modelo arquitectónico.**

El objetivo es buscar una **simbiosis entre la cognición artificial y la orquestación orgánica**: inteligencia distribuida, adaptación, regulación, resiliencia y acción situada.

---

# 🫀 La idea

La mayoría de los sistemas de IA están diseñados como un **modelo rodeado de herramientas**.

Nokido está diseñado como algo diferente:

> **una arquitectura de organismo artificial cuyas restricciones biológicas se aplican cada vez más en el sistema en ejecución.**

El organismo ya no es solo una metáfora, es una restricción física de arquitectura aplicada por la CI.

El objetivo es reproducir algunas de las **propiedades arquitectónicas de un cuerpo vivo**:

* órganos especializados en lugar de un único proceso universal;
* estado interno persistente en lugar de conversaciones sin estado;
* reflejos rápidos y deliberación más lenta;
* regulación de estilo nervioso y hormonal;
* límites inmunitarios alrededor de la interacción externa;
* cognición distribuida;
* adaptación bajo restricciones de recursos;
* múltiples vías de comunicación;
* un sustrato computacional que eventualmente pueda avanzar hacia hardware neuromórfico.

El lenguaje biológico, por tanto, no es decorativo.

Es una **disciplina de diseño**.

Se espera que cada componente de Nokido tenga un rol identificable en el organismo: ¿qué percibe?, ¿qué estado mantiene?, ¿qué regula?, ¿qué depende de él? y ¿qué ocurre cuando falla?

---

# 🧬 El organismo

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

Este modelo se refleja en todo el repositorio: la documentación de arquitectura asigna explícitamente el sistema en cerebro, hipocampo, sinapsis, sistema nervioso, sistema inmunitario, músculos, juicio y capas regulatorias.

---

# 🧠 Qué es realmente Nokido

Nokido combina varias capas que normalmente se desarrollan por separado.

## Inteligencia

Múltiples modelos locales y en la nube pueden enrutarse según la tarea, la disponibilidad y las políticas.

Nokido está diseñado en torno a **muchas inteligencias especializadas**, no a un único modelo que deba desempeñar todos los roles.

## Memoria persistente

El sistema mantiene una capa de recuperación híbrida persistente que combina recuperación léxica y semántica.

El espacio de incrustación (embedding) principal es:

**BGE-M3 · 1024 dimensiones**

La memoria está pensada para sobrevivir a la vida útil de las sesiones individuales de los modelos.

## Regulación

La presión de CPU, RAM, GPU/NPU, la presión de almacenamiento, la presión de colas, la latencia y la capacidad de los proveedores pueden influir en el comportamiento del sistema.

## Gobernanza

La generación probabilística se separa de las comprobaciones deterministas siempre que sea posible.

Los LLMs pueden proponer.

Las políticas, las pruebas y las compuertas (gates) deterministas pueden decidir si una propuesta es aceptable.

## Colaboración multi-agente

Los agentes pueden comunicarse mediante mecanismos M2M persistentes y colaborar a través de flujos de trabajo de enjambre (swarm).

## Interoperabilidad

Nokido está diseñado para participar en varios protocolos complementarios de agentes y herramientas:

**MCP · ACP · A2A**

## Sustrato neuronal

Ya existe una capa de software SNN, con un camino a más largo plazo hacia hardware perimetral (edge) y neuromórfico.

---

# 🌐 MCP · ACP · A2A

Nokido no está atado a un único protocolo de comunicación.

### MCP — herramientas y capacidades

El Hub central expone Nokido como un servidor MCP para clientes de agentes.

Esta es la interfaz de herramientas principal para interactuar con el runtime.

### ACP — interoperabilidad entre agentes

Nokido contiene tanto:

* un **servidor ACP**, exponiendo Nokido como un agente ACP;
* un **cliente ACP**, permitiendo a Nokido controlar agentes ACP externos.

La implementación actual de ACP cubre la creación de sesiones, intercambio de prompts, cancelación, solicitudes de permisos y negociación de capacidades.

El transporte remoto por WebSocket es experimental y sigue en desarrollo.

### A2A — agente a agente

Nokido también implementa una **superficie A2A de Nivel 1 (Tier-1)**.

Las operaciones actuales incluyen:

```text
message/send
tasks/get
tasks/cancel
```

con gestión autenticada de tareas y descubrimiento de agentes.

La ficha (card) A2A se genera a partir del **estado vivo del sistema**, no se mantiene como un archivo estático de marketing.

Nokido distingue:

```text
DECLARED
   ↓
AVAILABLE
   ↓
VERIFIED
```

Solo las capacidades que están disponibles y respaldadas por verificación son elegibles para la tarjeta pública de capacidades.

Esto es deliberado:

> **Que el código exista en el repositorio no es suficiente para afirmar que una capacidad es utilizable actualmente.**

---

# 🐝 Cognición de enjambre (Swarm)

Nokido está desarrollando un **enjambre multi-agente consciente de los recursos**.

El patrón básico es:

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

La arquitectura del enjambre ya contiene los bloques de construcción principales:

* programación por DAG (DAG scheduling);
* ejecución paralela por rondas;
* contextos de trabajadores (workers) estériles;
* delimitación de espacios de trabajo (workspace scoping);
* trabajadores de inferencia local;
* contrapresión (backpressure);
* validación determinista;
* ejecución en entornos aislados (sandbox);
* políticas de reintento;
* capas superpuestas compartidas (shared overlays);
* reducción atómica;
* observabilidad del enjambre en tiempo real.

El proyecto prefiere explícitamente **reutilizar las primitivas de orquestación existentes en lugar de construir un segundo motor de orquestación**.

El objetivo no es “lanzar tantos agentes como sea posible”.

El objetivo es:

> **cognición distribuida sin estado compartido no controlado ni efectos secundarios descontrolados.**

---

# 🧠 Memoria y recuperación

Nokido trata la memoria como un subsistema del organismo.

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

El RAG contiene código, documentación, decisiones de proyecto, lecciones, trazas y otro conocimiento persistente.

El contrato vectorial actual es **BGE-M3 de 1024 dimensiones**.

Esto es importante porque otro modelo de 1024 dimensiones no es automáticamente compatible con el espacio vectorial existente.

---

# 🛡️ Sistema inmunitario y soberanía

El organismo tiene un límite.

Por ello, Nokido trata los servicios en la nube y los agentes externos como entornos externos en lugar de memoria interna de confianza.

La arquitectura de seguridad incluye:

* `SemanticFirewall`;
* `SovereignMembrane`;
* RBAC de seis anillos;
* bóvedas de secretos;
* escaneo de secretos;
* guardas de shell (shell guards);
* ejecución en sandbox;
* salida (egress) a la nube controlada;
* compuertas de capacidades (capability gates).

La salida a la nube está pensada para pasar por controles previos (pre-flight) y posteriores (post-flight), anonimizando los identificadores sensibles a través de la membrana soberana.

La arquitectura predeterminada mantiene el Hub vinculado a localhost y trata el acceso a la nube como opcional (opt-in).

---

# 🫀 Homeostasis

Un cuerpo no puede gastar energía ilimitada en cada actividad.

Por lo tanto, Nokido trata el cómputo como un recurso fisiológico.

La capa de regulación rastrea y reacciona ante aspectos tales como:

* presión de RAM;
* presión de CPU;
* disponibilidad de GPU/NPU;
* estado térmico;
* presión de colas;
* estado de salud de los servicios;
* disponibilidad de inferencia;
* cuotas de proveedores;
* latencia.

El bucle previsto se asemeja a una forma de homeostasis por software:

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

El proyecto asigna esto explícitamente a MAPE-K y a la regulación cibernética.

---

# ⚡ Reflejos

No todas las respuestas deberían requerir un LLM.

Nokido está convirtiendo progresivamente los fallos de ingeniería recurrentes en reflejos ejecutables:

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

Los ejemplos incluyen:

* prevenir accesos patológicos a bases de datos;
* rechazar planes inválidos;
* detener fugas de secretos;
* controlar la presión de los trabajadores (workers);
* validar declaraciones arquitectónicas;
* detectar estados obsoletos;
* prevenir rutas de mutación inseguras.

El principio es simple:

> **Una lección que solo existe en el contexto de un agente aún no forma parte del organismo.**

---

# ⚡ Sustrato neuronal de espigas (Spiking)

Nokido ya contiene una capa real de SNN por software.

La arquitectura actual incluye:

| Componente          | Rol                     |
| ------------------- | ----------------------- |
| `forge_snn_core`    | sustrato LIF aprendible |
| `forge_snn_monitor` | telemetría → espigas    |
| `forge_snn_router`  | enrutamiento basado en SNN |

El repositorio distingue explícitamente estos componentes del código de enrutamiento basado en eventos más antiguo que no constituye en sí mismo una red neuronal de espigas.

La dirección a largo plazo es:

```text
software SNN
     ↓
edge acceleration
     ↓
neuromorphic hardware
     ↓
event-driven substrate
```

Los objetivos futuros potenciales incluyen tecnologías como **Loihi 2** y **Akida**.

Estos son objetivos de hardware futuros, no afirmaciones de soporte de producción actual. La hoja de ruta de hardware sitúa el hardware neuromórfico después de la fase actual de aceleración convencional por APU/edge.

---

# 🧠 Arquitectura cognitiva

El organismo también se está desarrollando en torno a un bucle de estilo AMI:

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

La pila actual incluye componentes para:

* percepción;
* modelos del mundo;
* funciones de coste;
* actor/planificación;
* MPC;
* redes de políticas/valor;
* inferencia activa;
* aprendizaje continuo.

Estos módulos están destinados a llevar a Nokido más allá de una arquitectura pura de “prompt → respuesta”.

---

# 💻 Instalación

Nokido actualmente es compatible con:

**Windows · macOS · Linux**

Hay tres vías prácticas de instalación.

## Requisitos

Mínimos:

* **Python 3.12+**
* **8 GB RAM**
* aproximadamente **2 GB de disco libre** para una instalación mínima

Recomendados:

* **16+ GB RAM**
* **Docker 24+**
* Ollama para una inferencia de LLM local sencilla

Los extras pesados de ML requieren sustancialmente más espacio en disco porque instalan paquetes como PyTorch/JAX.

---

## 🐳 Opción A — Docker

Recomendada para la prueba aislada más rápida.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

Descarga un modelo local:

```bash
docker exec laforge-ollama \
  ollama pull qwen2.5-coder:latest
```

Comprueba el Hub:

```bash
curl http://localhost:8766/health
```

Resultado esperado:

```json
{"ok":true,...}
```

### Perfiles de Docker

| Perfil  | Componentes principales                                      |
| ------- | ------------------------------------------------------------ |
| `core`  | Hub + Ollama                                                 |
| `full`  | Core + servicios web/eventos Deno + componentes de worker de embeddings |
| `all`   | Full + servicios de red/búsqueda                             |
| `dev`   | Herramientas de base de datos de desarrollo                  |

La guía de instalación de Docker mantiene las definiciones de perfiles y las variantes de imágenes.

---

## 🐧 Opción B — Linux / macOS nativo

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

bash install.sh
```

Para la pila más amplia:

```bash
EXTRAS=full bash install.sh
```

Para la pila completa de ML pesado:

```bash
EXTRAS=all bash install.sh
```

El instalador crea un `.venv`, instala los extras seleccionados y prepara la integración de la bóveda (vault).

Actívalo:

```bash
source .venv/bin/activate
```

---

## 🪟 Opción C — Windows nativo

```powershell
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido

.\install.ps1
```

El instalador de Windows detecta el entorno Python esperado y configura la arquitectura de servicios respaldada por NSSM.

Para extras de ML/embeddings:

```powershell
.\install.ps1 -ML
```

---

# ✅ Verificar la instalación

Tras la instalación, verifica las tres superficies fundamentales.

### 1. Estado de salud del Hub

```bash
curl http://localhost:8766/health
```

### 2. Bóveda de secretos

```bash
nokido-secrets status
```

### 3. Descubrimiento de MCP

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

La documentación actual prevé que el Hub exponga su superficie de herramientas MCP a través de este endpoint.

---

# 🚀 Primer uso

Una vez que el Hub esté funcionando, Nokido se puede probar sin necesidad de conectar un segundo agente.

Ejemplo:

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

Para la inferencia local, configura Ollama y carga un modelo:

```bash
ollama pull qwen2.5-coder:latest
```

Nokido podrá entonces usar la pila local antes de recurrir a los proveedores en la nube configurados.

---

# 🔑 Proveedores y secretos

Las claves API no deben colocarse en `.env` ni subirse al repositorio.

Nokido utiliza una bóveda respaldada por la máquina:

* **DPAPI** en Windows;
* **Keychain** en macOS;
* **libsecret / keyring** en Linux.

La administración web expone la configuración de proveedores en:

```text
http://127.0.0.1:8766/admin/providers
```

o a través de las herramientas CLI de la bóveda.

Ejemplo:

```bash
nokido-vault set -k GROQ_API_KEY
```

Luego:

```bash
nokido-secrets status
```

Consulta la documentación de seguridad antes de exponer cualquier endpoint a la red.

---

# 🔌 Conectar un agente externo

Nokido puede conectarse a clientes MCP como:

* Claude Desktop;
* Claude Code;
* Gemini CLI;
* Codex CLI;
* Cline;
* otros clientes compatibles con MCP.

El soporte de ACP proporciona una segunda vía para la interoperabilidad entre agentes, incluida la capacidad de exponer el propio Nokido como un agente ACP.

A2A añade comunicación agente a agente para sistemas que implementan el protocolo A2A.

---

# 🔬 Estado del proyecto

Cada línea empareja una madurez **declarada** con la **evidencia en este repositorio** que la
respalda: un módulo, un servicio, un gate de CI. Cada evidencia citada la vuelve a comprobar
`tools/forge_capability_audit.py` (control « tableau de statut »): un ✅ sin evidencia, una cita
que no existe o un servicio en pausa mostrado como operativo hacen fallar la CI.

Esta tabla **no** dice si un órgano late *ahora mismo*. Nokido es un cuerpo vivo y un README
solo puede congelarlo: pregúntele al propio cuerpo, en su máquina:

```bash
nokido-doctor --vivant          # desde un clon: python tools/nokido_doctor.py --vivant
```

Informa de cada órgano que declara un pulso — vivo, incierto, ya no late, apagado por política
(una decisión, no una avería) o ilegible — con la evidencia detrás de cada veredicto.

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

Un servicio que responde prueba el **transporte**, no la capacidad: dice que el órgano responde,
no que funcione cada herramienta detrás de él. Eso lo prueban uno a uno los tests.

### Lo que Nokido ha aprendido sobre ser un organismo

Al intentar modelar límites fisiológicos en software, Nokido ya ha descubierto restricciones que orientan su desarrollo continuo:

* Un órgano puede existir en código sin estar conectado.
* Emitir una señal no significa que esté siendo escuchada.
* `false` no es lo mismo que `unreadable`.
* La intención debe declararse explícitamente, no adivinarse.
* La SNN carecía más de sensores biológicos adecuados que de sofisticación algorítmica.
* La arquitectura centralizada debe ceder progresivamente algunas vías de reflejos directamente hacia el perímetro (edge).

El proyecto distingue explícitamente entre capacidades declaradas, disponibles y verificadas, en lugar de tratar todo el código fuente como funcionalidad lista para producción.

---

# ⚠️ Lo que Nokido no pretende afirmar

Nokido **no** afirma tener actualmente:

* AGI;
* autorrecuperación garantizada;
* autonomía perfecta;
* autoconciencia perfecta;
* compatibilidad universal de protocolos;
* estabilidad de grado de producción en cada subsistema;
* soporte de hardware neuromórfico para producción.

Nokido es un **proyecto de investigación e ingeniería en fase alfa**.

La arquitectura es real.

Algunos subsistemas son maduros.

Algunos se están reforzando activamente.

Algunos son prototipos de investigación.

Algunos son direcciones futuras.

El repositorio, sus pruebas y sus comprobaciones de capacidades en vivo son la fuente autorizada sobre el estado actual.

---

# 🔐 Seguridad

Por favor, lee [`SECURITY.md`](../../SECURITY.md) antes de desplegar Nokido más allá de localhost.

Las áreas sensibles para la seguridad incluyen:

* salida a la nube (cloud egress);
* lógica de firewall y membrana;
* RBAC;
* bóvedas (vaults);
* aislamiento en sandbox;
* exposición a la red;
* endpoints ACP/A2A.

Las vulnerabilidades de seguridad deben **divulgarse de forma privada en primer lugar**, no publicarse abiertamente en un issue o debate.

---

# 🤝 Contribución

Nokido está abierto a contribuciones, pero los cambios arquitectónicos siguen reglas estrictas del proyecto.

Antes de contribuir, lee:

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](../../docs/CLA.md)

La rama de desarrollo actual es:

```text
alpha
```

Flujo de trabajo típico de un colaborador:

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

El proyecto exige pruebas para nuevas funcionalidades, desaconseja la duplicación de primitivas existentes y utiliza compuertas de seguridad en torno a secretos, salida a la nube y ejecución privilegiada.

---

# 📜 Licencias

Nokido utiliza un **modelo de doble licencia**.

## AGPLv3-o-posterior

La licencia de código abierto predeterminada es:

**GNU Affero General Public License v3 o posterior**

Consulta [`LICENSE`](../../LICENSE).

Puedes ejecutar, estudiar, modificar y redistribuir Nokido bajo los términos de la AGPL.

Las disposiciones de copyleft de red son particularmente relevantes cuando se ofrece un sistema Nokido modificado como un servicio de red a los usuarios.

## Licencia comercial

Se dispone de una licencia comercial independiente para casos de uso que no puedan cumplir con la AGPL, incluidos ciertos:

* productos propietarios;
* SaaS de código cerrado;
* integraciones OEM;
* distribuciones de marca blanca;
* despliegues embebidos propietarios.

Consulta [`COMMERCIAL.md`](../../COMMERCIAL.md).

**No** necesitas una licencia comercial simplemente para usar Nokido de manera privada o interna bajo la AGPL.

## Software y modelos de terceros

La licencia de Nokido no anula las licencias de dependencias, modelos o proveedores externos de terceros.

Comprueba siempre los términos aplicables de los proyectos originales (upstream) antes de redistribuir:

* pesos de modelos;
* SDKs de proveedores;
* imágenes de Docker;
* conjuntos de datos (datasets);
* servicios externos.

---

# 📝 Contributor License Agreement (Acuerdo de Licencia de Colaborador)

Las contribuciones requieren la aceptación del CLA de Nokido debido a que el proyecto mantiene un modelo de doble licencia.

El CLA:

* **no** transfiere tus derechos de autor;
* otorga al mantenedor amplios derechos sobre tu contribución;
* permite futuras relicencias comerciales;
* incluye una licencia de patentes;
* está versionado.

El CLA individual actual está documentado en [`docs/CLA.md`](../../docs/CLA.md).

Las contribuciones corporativas requieren el acuerdo corporativo independiente descrito allí.

---

# 🧭 Principios de ingeniería

## Medir antes de aplicar

Un detector se gana el derecho a convertirse en una compuerta (gate) demostrando que mide lo que afirma medir.

## Evidencia sobre suposición

Desconocido no es cero.

No disponible no es muerto.

Implementado no es verificado.

## Corregir causas, no síntomas

Un servicio deshabilitado puede proteger el sistema.

Eso no significa que su problema subyacente esté resuelto.

## Mantener coherente el estado compartido

El estado distribuido requiere una fuente de verdad explícita y una ruta de migración controlada.

## Convertir lecciones en reflejos

Los fallos repetidos deben convertirse eventualmente en pruebas, compuertas o salvaguardas en tiempo de ejecución.

## Seguir al silicio

Nokido está diseñado para que la arquitectura cognitiva pueda evolucionar mientras cambia el sustrato físico de computación.

---

# 🗺️ Hoja de ruta (Roadmap)

### Corto plazo

**Hacer el organismo más coherente.**

* finalizar la separación de M2M;
* expandir las capacidades A2A verificadas;
* estabilizar ACP;
* reforzar la ejecución del enjambre (swarm);
* mejorar el enrutamiento de capacidad de embeddings;
* reducir el trabajo innecesario de base de datos;
* fortalecer la homeostasis.

### Medio plazo

**Hacer la cognición distribuida más autónoma.**

* coordinación de enjambre más sólida;
* descubrimiento de pares (peers) más rico;
* bucles de desarrollo autónomo más fuertes;
* enrutamiento más profundo y consciente de los recursos;
* mayor cobertura de validación retenida (held-out).

### Largo plazo

**Cambiar el sustrato.**

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

La hoja de ruta de hardware sigue explícitamente esta progresión.

---

# 📚 Documentación

### Empieza aquí

* [`docs/wiki/01-Installation.md`](../../docs/wiki/01-Installation.md) — instalación
* [`docs/wiki/02-Quick-Start.md`](../../docs/wiki/02-Quick-Start.md) — primeros 30 minutos
* [`docs/wiki/03-Architecture.md`](../../docs/wiki/03-Architecture.md) — visión general del sistema

### Arquitectura en profundidad

* [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](../../MANIFESTO.md)

### Protocolos de agentes

* [`docs/ACP_INGRESS.md`](../../docs/ACP_INGRESS.md)
* Implementación de A2A — `tools/forge_a2a_server.py`, `tools/forge_a2a_card.py`
* Arquitectura de enjambre (Swarm) — [`docs/roadmap_forge_swarm.md`](../../docs/roadmap_forge_swarm.md)

### Dirección neuronal / hardware

* [`docs/wiki/13-Hardware-Roadmap.md`](../../docs/wiki/13-Hardware-Roadmap.md)

### Comunidad

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`SECURITY.md`](../../SECURITY.md)
* [`docs/CLA.md`](../../docs/CLA.md)
* [`COMMERCIAL.md`](../../COMMERCIAL.md)

---

# 🌱 El objetivo a largo plazo

Nokido no está intentando convertirse en otro chatbot.

El objetivo a largo plazo es construir:

> **un organismo artificial personal cuya cognición esté distribuida entre agentes y sustratos especializados, cuya memoria persista, cuyos recursos estén regulados, cuyos límites estén protegidos, cuyos fallos se conviertan en restricciones aprendidas y cuyo sustrato computacional pueda eventualmente pasar del silicio convencional a sistemas neuromórficos.**

Ese organismo aún no existe completamente. Pero varios órganos ya son reales, funcionales e interactúan activamente. La arquitectura para construir hacia él ya está aquí.

**Nokido es el intento de hacerlo realidad.**

---

## Licencia

**AGPLv3-or-later** · Licencias comerciales disponibles

Consulta [`LICENSE`](../../LICENSE) y [`COMMERCIAL.md`](../../COMMERCIAL.md).
