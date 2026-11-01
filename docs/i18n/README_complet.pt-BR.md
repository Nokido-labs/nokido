# ⚡ Nokido

### Construindo um organismo artificial — não apenas mais um agente de IA

> **Um sistema que aprende, lembra, regula a si mesmo — na sua máquina, com o seu hardware, para os seus dados.**

[![License](https://img.shields.io/badge/license-AGPLv3-blue)](../../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14%20%7C%203.14t-blue?logo=python)](https://www.python.org/)
[![Deno](https://img.shields.io/badge/Deno-2.x-black?logo=deno)](https://deno.land/)
[![Rust](https://img.shields.io/badge/Rust-ONNX%20%2B%20BM25-orange?logo=rust)](../../go_services/forge_brain_worker/)
[![snnTorch](https://img.shields.io/badge/snnTorch-spiking%20substrate-8E44AD)](https://snntorch.readthedocs.io/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20sidecar-DC244C)](https://qdrant.tech/)
[![Go](https://img.shields.io/badge/Go-dispatcher-00ADD8?logo=go)](../../go_services/forge_dispatcher/)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05%20to%202026--07--28-9146FF?logo=anthropic&logoColor=white)](#-conectar-um-agente-externo)
[![Local-First](https://img.shields.io/badge/Local--First-zero%20telemetry-2EA043)](#-security)
[![Branch](https://img.shields.io/badge/branch-main-orange)](https://github.com/Nokido-labs/nokido)
[![CI](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml/badge.svg)](https://github.com/Nokido-labs/nokido/actions/workflows/release.yml)

**MCP clients & runtimes :**
[![llama.cpp](https://img.shields.io/badge/llama.cpp-server%20%26%20native-orange?logo=llama)](https://github.com/ggml-org/llama.cpp)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-MCP%20Streamable%20HTTP-D97757?logo=anthropic&logoColor=white)](#-conectar-um-agente-externo)
[![Antigravity agy](https://img.shields.io/badge/Antigravity%20(agy)-MCP%20HTTP-5C2D91?logo=google&logoColor=white)](#-conectar-um-agente-externo)
[![Codex CLI](https://img.shields.io/badge/Codex%20CLI-MCP%20HTTP-10A37F?logo=openai&logoColor=white)](#-conectar-um-agente-externo)
[![Cline](https://img.shields.io/badge/Cline-MCP%20STDIO-5C6BC0)](#-conectar-um-agente-externo)
[![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20STDIO-D97757?logo=anthropic&logoColor=white)](#-conectar-um-agente-externo)
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

## 🧭 Em um minuto

Nokido é um **runtime local-first para um organismo artificial**: o sistema nervoso e a fisiologia
que permitem que várias IAs — modelos locais, provedores na nuvem, agentes de código como Claude
Code, Codex CLI, OpenCode ou Antigravity — trabalhem juntas na sua máquina **sem virar um amontoado
de agentes independentes**.

Ele parte de três constatações, desenvolvidas no [Manifesto](MANIFESTO.en.md):

1. **A maior parte da IA é externa.** Prompts, código e documentos trafegam por uma infraestrutura que não é sua.
2. **A maior parte da IA é amnésica.** A memória é um acessório, não um alicerce.
3. **A maior parte da IA tem um só cérebro.** Um único grande modelo responde a tudo, enquanto a
   biologia mostra uma inteligência distribuída e especializada.

O Nokido não acrescenta mais um framework de agentes. Ele acrescenta a **camada de organismo** em torno dos modelos:

* **roteamento** entre modelos locais e na nuvem conforme o uso, com fallback local;
* **memória de longo prazo com proveniência** — busca textual e vetorial sobre o que o sistema aprendeu;
* **regulação** de CPU, RAM, filas e provedores — homeostase, reflexos, ciclos circadianos;
* **gates determinísticos** em torno das ações — verificações AST, detecção de segredos, RBAC, controle de egress;
* **mensageria entre agentes** (M2M, enxames) e **introspecção** do próprio código e estado;
* **um único hub** que os clientes acessam via MCP: o cliente é descartável, o sistema persiste.

### Um sistema de prova, não só uma arquitetura

O Nokido separa três coisas que a maioria dos projetos confunde: o que é **declarado**, o que é
**observado** e o que é **verificado**. Uma porta que responde não prova que um modelo está carregado;
um comando aceito não é um estado alcançado; uma sonda que não consegue olhar responde `ILLISIBLE`
(ilegível), nunca “não”. Essas distinções são aplicadas no código e na CI — e este README as segue:
sua [tabela de status](#-status-do-projeto) associa cada afirmação à sua evidência, e um controle de CI
falha quando um serviço pausado aparece como operacional.

Soberania é uma **arquitetura**, não uma garantia: o Nokido permite manter dados, memória e decisões
críticas na sua própria infraestrutura, com controle explícito do que sai dela. A sua conformidade
continua dependendo de como você o implanta — e o que o Nokido **não** afirma está escrito mais abaixo.

## 🚀 Início rápido

<!-- PIP:BEGIN nokido-agent version=0.20.15 -->
**Pelo PyPI** — [`nokido-agent 0.20.15`](https://pypi.org/project/nokido-agent/0.20.15/), publicado após a prova de instalação em Linux, Windows e macOS. O organismo completo, seus componentes fixados (somas de verificação conferidas) e depois o hub:

```bash
pip install "nokido-agent[organisme]==0.20.15"
nokido-composants --tout          # deno, llama.cpp, modelos, knowledge pack, token local
nokido-doctor                     # o que esta máquina tem, não tem ou não consegue ler
nokido-hub                        # depois: curl http://localhost:8766/health
```

Somente cliente (fala com um hub existente): `pip install nokido-agent==0.20.15`.
<!-- PIP:END -->

**A partir de um clone** — o caminho que a própria CI usa ([detalhes](#-instalação)):

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_doctor.py   # o que esta máquina tem, o que falta, o que não consegue ler
python tools/nokido_hub.py
```

Depois, `curl http://localhost:8766/health` deve responder. Próximos passos:
[requisitos e caminhos Docker / nativos](#-instalação) ·
[verificar a instalação](#-verificar-a-instalação) ·
[conectar Claude Code, Codex, OpenCode…](#-conectar-um-agente-externo).

---

## 🧠 Por que “Nokido”?

O **Nokido** busca inspiração no japonês:

* **脳 — Nō**: o cérebro, inteligência, cognição;
* **機動 — Kidō**: mobilidade, colocar em movimento, a capacidade de ação.

O nome expressa a ideia central do projeto:

> **convergir a inteligência artificial com uma orquestração inspirada na organização orgânica do corpo humano.**

O Nokido, portanto, não está apenas tentando construir um "cérebro" artificial melhor.

Ele busca construir um **organismo digital**: órgãos especializados, memória persistente, um sistema nervoso para comunicação, reflexos, regulação endócrina e homeostática, um sistema imune, músculos de execução — e, em última análise, um substrato neural capaz de evoluir em direção a hardware neuromórfico.

A biologia não é uma metáfora gráfica aqui.

**Ela serve como um modelo arquitetural.**

O objetivo é buscar uma **simbiose entre cognição artificial e orquestração orgânica**: inteligência distribuída, adaptação, regulação, resiliência e ação situada.

---

# 🫀 A ideia

A maioria dos sistemas de IA é projetada como um **modelo cercado por ferramentas**.

O Nokido é projetado como algo diferente:

> **uma arquitetura de organismo artificial cujas restrições biológicas são cada vez mais aplicadas no sistema em execução.**

O organismo não é mais apenas uma metáfora, é uma restrição física de arquitetura aplicada pela CI.

O objetivo é reproduzir algumas das **propriedades arquiteturais de um corpo vivo**:

* órgãos especializados em vez de um único processo universal;
* estado interno persistente em vez de conversas sem estado (stateless);
* reflexos rápidos e deliberação mais lenta;
* regulação nervosa e no estilo hormonal;
* fronteiras imunológicas ao redor da interação externa;
* cognição distribuída;
* adaptação sob restrições de recursos;
* múltiplos caminhos de comunicação;
* um substrato computacional que pode eventualmente migrar em direção a hardware neuromórfico.

A linguagem biológica, portanto, não é mera decoração.

É uma **disciplina de design**.

Espera-se que um componente do Nokido tenha um papel identificável no organismo: o que ele percebe, que estado ele mantém, o que ele regula, o que depende dele e o que acontece quando ele falha?

---

# 🧬 O organismo

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

Esse modelo é refletido em todo o repositório: a documentação de arquitetura mapeia explicitamente o sistema em cérebro, hipocampo, sinapses, sistema nervoso, sistema imune, músculos, camadas de julgamento e de regulação.

---

# 🧠 O que o Nokido realmente é

O Nokido combina várias camadas que geralmente são desenvolvidas separadamente.

## Inteligência

Múltiplos modelos locais e em nuvem podem ser roteados de acordo com a tarefa, disponibilidade e políticas.

O Nokido é projetado em torno de **muitas inteligências especializadas**, e não de um único modelo que deve desempenhar todos os papéis.

## Memória persistente

O sistema mantém uma camada de recuperação híbrida persistente combinando busca lexical e semântica.

O espaço principal de embeddings é:

**BGE-M3 · 1024 dimensões**

A memória foi concebida para sobreviver ao ciclo de vida de sessões individuais de modelos.

## Regulação

Pressão de CPU, RAM, GPU/NPU, pressão de armazenamento, pressão de filas, latência e capacidade de provedores podem influenciar o comportamento do sistema.

## Governança

A geração probabilística é separada de verificações determinísticas sempre que possível.

LLMs podem propor.

Políticas, testes e barreiras determinísticas podem decidir se uma proposta é aceitável.

## Colaboração multiagente

Os agentes podem se comunicar por meio de mecanismos persistentes M2M e colaborar através de fluxos de trabalho em enxame (swarm).

## Interoperabilidade

O Nokido foi projetado para participar de vários protocolos complementares de agentes/ferramentas:

**MCP · ACP · A2A**

## Substrato neural

Uma camada de SNN em software já existe, com um caminho de longo prazo em direção a hardware de borda (edge) e neuromórfico.

---

# 🌐 MCP · ACP · A2A

O Nokido não está atrelado a um único protocolo de comunicação.

### MCP — ferramentas e capacidades

O Hub central expõe o Nokido como um servidor MCP para clientes agentes.

Esta é a principal interface de ferramentas para interagir com o runtime.

### ACP — interoperabilidade de agentes

O Nokido contém ambos:

* um **servidor ACP**, expondo o Nokido como um agente ACP;
* um **cliente ACP**, permitindo que o Nokido pilote agentes ACP externos.

A implementação atual de ACP abrange criação de sessão, troca de prompts, cancelamento, solicitações de permissão e negociação de capacidades.

O transporte remoto via WebSocket é experimental e permanece em desenvolvimento.

### A2A — agente para agente (agent-to-agent)

O Nokido também implementa uma **superfície A2A Tier-1**.

As operações atuais incluem:

```text
message/send
tasks/get
tasks/cancel
```

com tratamento autenticado de tarefas e descoberta de agentes.

O cartão A2A é gerado a partir do **estado vivo do sistema**, não mantido como um arquivo de marketing estático.

O Nokido distingue:

```text
DECLARED
   ↓
AVAILABLE
   ↓
VERIFIED
```

Apenas capacidades que estão simultaneamente disponíveis e respaldadas por verificação são elegíveis para o cartão público de capacidades.

Isso é deliberado:

> **A existência de código no repositório não é suficiente para afirmar que uma capacidade está utilizável no momento.**

---

# 🐝 Cognição em enxame (Swarm cognition)

O Nokido está desenvolvendo um **enxame multiagente consciente de recursos**.

O padrão básico é:

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

A arquitetura de enxame já contém os principais blocos de construção:

* escalonamento por DAG;
* execução paralela por rodadas;
* contextos estéreis de workers;
* escopo restrito de workspace;
* workers de inferência local;
* contrapressão (backpressure);
* validação determinística;
* execução em sandbox;
* políticas de nova tentativa (retry);
* camadas sobrepostas compartilhadas (shared overlays);
* redução atômica;
* observabilidade do enxame em tempo real.

O projeto prefere explicitamente **reutilizar primitivas de orquestração existentes em vez de construir um segundo motor de orquestração**.

O objetivo não é “lançar o maior número possível de agentes”.

O objetivo é:

> **cognição distribuída sem estado compartilhado descontrolado ou efeitos colaterais descontrolados.**

---

# 🧠 Memória e recuperação

O Nokido trata a memória como um subsistema do organismo.

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

O RAG contém código, documentação, decisões de projeto, lições, rastros e outros conhecimentos persistentes.

O contrato vetorial atual é **BGE-M3 de 1024 dimensões**.

Isso é importante porque outro modelo de 1024 dimensões não é automaticamente compatível com o espaço vetorial existente.

---

# 🛡️ Sistema imune e soberania

O organismo possui uma fronteira.

O Nokido, portanto, trata serviços em nuvem e agentes externos como ambientes externos, em vez de memória interna confiável.

A arquitetura de segurança inclui:

* `SemanticFirewall`;
* `SovereignMembrane`;
* RBAC de seis anéis;
* cofres de segredos;
* varredura de segredos;
* guardas de shell;
* execução em sandbox;
* saída controlada para a nuvem;
* barreiras de capacidade (capability gates).

A saída para a nuvem foi projetada para passar por controles de pré-voo (pre-flight) e pós-voo (post-flight), com identificadores sensíveis sendo anonimizados por meio da membrana soberana.

A arquitetura padrão mantém o Hub vinculado a localhost e trata o acesso à nuvem como opcional (opt-in).

---

# 🫀 Homeostase

Um corpo não pode gastar energia ilimitada em todas as atividades.

O Nokido, portanto, trata a computação como um recurso fisiológico.

A camada de regulação monitora e reage a fatores como:

* pressão de RAM;
* pressão de CPU;
* disponibilidade de GPU/NPU;
* estado térmico;
* pressão de filas;
* integridade dos serviços;
* disponibilidade de inferência;
* cotas de provedores;
* latência.

O ciclo pretendido se assemelha a uma forma de homeostase em software:

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

O projeto mapeia isso explicitamente para o MAPE-K e a regulação cibernética.

---

# ⚡ Reflexos

Nem toda resposta deve exigir um LLM.

O Nokido está transformando progressivamente falhas repetidas de engenharia em reflexos executáveis:

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

Os exemplos incluem:

* prevenir acessos patológicos ao banco de dados;
* rejeitar planos inválidos;
* impedir o vazamento de segredos;
* controlar a pressão sobre os workers;
* validar declarações arquiteturais;
* detectar estados obsoletos;
* prevenir caminhos de mutação inseguros.

O princípio é simples:

> **Uma lição que existe apenas no contexto de um agente ainda não faz parte do organismo.**

---

# ⚡ Substrato neural de disparos (Spiking)

O Nokido já contém uma camada real de SNN em software.

A arquitetura atual inclui:

| Componente          | Papel                   |
| ------------------- | ----------------------- |
| `forge_snn_core`    | substrato LIF treinável |
| `forge_snn_monitor` | telemetria → spikes     |
| `forge_snn_router`  | roteamento baseado em SNN |

O repositório distingue explicitamente esses componentes do código de roteamento antigo baseado em eventos, que não é em si uma rede neural de disparos.

A direção de longo prazo é:

```text
software SNN
     ↓
edge acceleration
     ↓
neuromorphic hardware
     ↓
event-driven substrate
```

Alvos futuros potenciais incluem tecnologias como **Loihi 2** e **Akida**.

Estes são alvos futuros de hardware, e não alegações de suporte atual em produção. O roadmap de hardware posiciona o hardware neuromórfico após a atual fase convencional de aceleração em APU/borda (edge).

---

# 🧠 Arquitetura cognitiva

O organismo também está sendo desenvolvido em torno de um ciclo no estilo AMI:

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

A pilha atual inclui componentes para:

* percepção;
* modelos de mundo;
* funções de custo;
* ator/planejamento;
* MPC;
* redes de política/valor;
* inferência ativa;
* aprendizado contínuo.

Esses módulos têm como objetivo levar o Nokido além de uma arquitetura pura de “prompt → resposta”.

---

# 💻 Instalação

O Nokido atualmente suporta:

**Windows · macOS · Linux**

Existem três caminhos práticos de instalação.

## Requisitos

O Nokido roda **sobre** runtimes de terceiros que não pode redistribuir —
licenças, tamanho, builds por plataforma. O pacote entrega código e declarações; os
componentes abaixo são instalados separadamente.

Em vez de adivinhar o que falta em uma máquina, pergunte:

```bash
nokido-doctor          # o que está INSTALADO — não o que está rodando
```

Ele relata três estados por item — `PRESENT` / `ABSENT` / `ILLISIBLE` (ilegível) — e nunca
confunde *não está lá* com *não consegui olhar* na mesma resposta. Ele também nomeia
a capacidade que é desligada, para que uma ausência seja acionável em vez de alarmante.

### Base

| Componente | Carrega |
| ---------- | ------- |
| **Python 3.12+** | 78 dos 108 serviços declarados, e o próprio pacote |
| **git** | versionamento, gate de saída, caminho de publicação |
| **RAM — host de 24 GB recomendado** | medido em 19/10/2026 no host de referência: o organismo completo ocupa **~12 GB de memória privada** (hub, serviços, embedder local, llama-server) e a partida a frio do RAG acrescenta ~2 GB por ~10 min; perfis mais leves (apenas modelos em nuvem) **ainda não foram medidos** |
| **Disco — ~60 GB livres** | só a memória RAG ocupa **~53 GB** (`embeddings.db`, 1,58 M de fragmentos vetorizados); o pacote em si precisa de ~2 GB |

### Exigido pela topologia padrão

| Componente | Carrega | Sem ele |
| ---------- | ------- | ------- |
| **Deno 2.x** | web hub `:7401`, proxy `:8000`, proxy netcfg `:8767` | três serviços marcados `essential` não iniciam |
| **Ollama** | inferência local `:11434` | sem inferência local padrão; a cascata recorre ao llama.cpp ou a um provedor configurado |
| **netcfg-agent-mcp** | netcfg MCP `:8768` | é um **repositório separado**, portanto não acompanha o pacote |

### Opcional — cada ausência desliga uma capacidade nomeada

| Componente | Capacidade | Sem ele |
| ---------- | ---------- | ------- |
| **llama.cpp** (`llama-server`) + pesos GGUF | embeddings `:8099`, reranker, nativo, bitnet | o embedding e o reranking locais; a ingestão recorre a um embedder remoto |
| **Docker 24+** | SearXNG, Qdrant, baias de execução isoladas | a busca web local e o sidecar vetorial. Uma prótese, não um órgão — desligado não significa quebrado |
| **VeraCrypt** / **cryptsetup (LUKS)** | criptografia em repouso do volume de dados, multiplataforma | os bancos permanecem **em texto claro** no disco |
| **LM Studio** (`lms`) | backend local alternativo `:1234` | um backend de inferência entre outros |
| **Caddy** | terminação TLS `:8443` | HTTPS; o loopback continua funcionando |
| **toolchains Rust / Go** | reconstrução de `forge_brain_worker` e `forge_dispatcher` | apenas as reconstruções — binários já compilados continuam rodando |
| **Node / npx** | servidores MCP JavaScript de terceiros | esses servidores |
| **ripgrep · ffmpeg · uv · py-spy** | busca rápida, ingestão de mídia, resolução rápida de ambiente, profiling ao vivo | cada um degrada para um caminho mais lento, ou para nada |
| **semgrep · gitleaks · opa** | gates de auditoria | esses gates relatam `ILLISIBLE`, **nunca “nenhum problema encontrado”** |
| **nvidia-smi** / **AMD uProf** | detecção de GPU para posicionamento de modelos | o posicionamento recorre à CPU |

### Capacidades que chegam como imagens de contêiner

Algumas capacidades existem **apenas** como imagens — não têm equivalente binário, então
procurá-las no `PATH` as declararia erroneamente como ausentes:

| Imagem | Capacidade |
| ------ | ---------- |
| `searxng/searxng` | busca web local |
| `unclecode/crawl4ai` | rastreamento web |
| `ollama/ollama` · `denoland/deno` | variantes em contêiner dos runtimes acima |
| `adminer` | inspeção de bancos de dados, perfil `dev` |

`nokido:*` e `netcfg-agent-mcp` são construídos localmente em vez de baixados.

**Pesos de modelos nunca fazem parte de um pacote Python.** Três arquivos GGUF são esperados
em `data/llm_models/` e baixados separadamente; `nokido-doctor` os lista
com seu tamanho e seu uso, ao lado das imagens acima e do arquivo de
configuração `Nokido.env`.

Extras pesados de ML exigem substancialmente mais espaço em disco porque instalam pacotes como PyTorch/JAX.

---

## 📦 Distribuição e extras

<!-- DIST:nokido-agent -->

> **Alpha.** O pacote publicado no PyPI instala com pip (veja o bloco no topo), e
> cada versão é comprovada instalável em Linux, Windows e macOS antes de o PyPI servi-la. O
> **repositório clonado continua sendo o caminho de referência para o organismo completo** — serviços, supervisor
> Deno, modelos locais — até a entrega da instalação completa em um único comando.

`pyproject.toml` declara o nome de distribuição `nokido-agent` com cinco pontos de entrada
de console, e desde 10/09/2026 o pacote é construído sob um namespace
`nokido_agent` dedicado (`[tool.setuptools.package-dir]` mapeia `app/` e `tools/`
abaixo **sem movê-los no disco**). Um pipeline de release
(`.github/workflows/release.yml`, **OIDC Trusted Publishing** — sem token armazenado)
está ligado para publicar primeiro no **TestPyPI** — um gate obrigatório que instala a
wheel em um virtualenv limpo em Linux/Windows/macOS e verifica os bytes servidos —
antes do **PyPI** em uma tag `v*`, com o **GitHub Release criado somente depois que o PyPI
serve os mesmos bytes**.

Esse pipeline não é o mesmo que uma instalação que funciona — mas a lacuna é menor do que
este README afirmava até 19/09/2026. A redação antiga falava de “~4 449 imports
planos”; uma contagem **AST** diz **36 arquivos de 1 855**, 26 símbolos distintos e
**nenhum em `nokido_hub.py`**. O número anterior contava menções textuais, não
imports.

O que agora está medido, construindo a wheel e instalando-a em um virtualenv
limpo (`tools/forge_dist_install_probe.py`, na árvore versionada):

| | |
| --- | --- |
| a wheel é construída, instala com `--no-deps` | ✅ |
| import de `nokido_agent`, `.app`, `.tools` | ✅ |
| import de `forge_secrets`, `forge_db_path`, **`nokido_hub`** | ✅ mesmo sem nenhuma dependência instalada |
| o ponto de entrada `nokido-doctor` responde | ✅ |
| o hub **inicia e serve** a partir da wheel | ainda não medido |

Portanto, a lacuna restante é *iniciar*, não *importar*. Um comando `pip install` só será
documentado quando uma release for cortada e sua prova de instalação estiver verde — uma
promessa feita a um estranho se prova executando-a, não escrevendo-a. O
caminho suportado hoje é o que a própria CI usa:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
python tools/nokido_hub.py
```

`pyproject.toml` declara **17 extras** — `ami`, `bench`, `cli`, `cloud`, `dev`,
`docker`, `docs`, `git`, `hub`, `llm`, `ml`, `netcfg`, `organisme`, `rag`, `sauvegarde`, `security`, `ui` —
mais dois pacotes agregados, `all` e `full`, que não são contados entre eles.
Eles se aplicam ao layout acima, não a uma wheel publicada.

`organisme` é o que os serviços do supervisor importam na inicialização além do núcleo; a partir de um clone,
`pip install -r requirements-organisme.txt` instala o mesmo conjunto com versões exatas (no Linux,
instale `torch` a partir do índice CPU do PyTorch primeiro: a wheel Linux do PyPI puxa CUDA).

---

## 🐳 Opção A — Docker

Recomendado para o teste isolado mais rápido.

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

cp Nokido.env.example Nokido.env

docker compose \
  -f docker/nokido/docker-compose.yml \
  --profile core up -d
```

Baixar um modelo local:

```bash
docker exec laforge-ollama \
  ollama pull qwen2.5-coder:latest
```

Verificar o Hub:

```bash
curl http://localhost:8766/health
```

Resultado esperado:

```json
{"ok":true,...}
```

### Perfis Docker

| Perfil  | Principais componentes                                       |
| ------- | ------------------------------------------------------------ |
| `core`  | Hub + Ollama                                                 |
| `full`  | Core + serviços web/eventos Deno + componentes de worker de embeddings |
| `all`   | Full + serviços de rede/busca                                |
| `dev`   | Ferramentas de banco de dados para desenvolvimento           |

O guia de instalação do Docker mantém as definições dos perfis e as variantes de imagem.

---

## 🐧 Opção B — Linux / macOS nativo

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

bash install.sh
```

Para a pilha mais ampla:

```bash
EXTRAS=full bash install.sh
```

Para a pilha pesada completa de ML:

```bash
EXTRAS=all bash install.sh
```

O instalador cria um `.venv`, instala os extras selecionados e prepara a integração com o cofre.

Ative-o:

```bash
source .venv/bin/activate
```

---

## 🪟 Opção C — Windows nativo

```powershell
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

.\install.ps1
```

O instalador do Windows detecta o ambiente Python esperado e configura a arquitetura de serviços suportada pelo NSSM.

Para extras de ML/embeddings:

```powershell
.\install.ps1 -ML
```

---

# ✅ Verificar a instalação

Após a instalação, verifique as três superfícies fundamentais.

### 1. Saúde do hub

```bash
curl http://localhost:8766/health
```

### 2. Cofre de segredos

```bash
nokido-secrets status
```

### 3. Descoberta MCP

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

A documentação atual espera que o Hub exponha sua superfície de ferramentas MCP através deste endpoint.

---

# 🚀 Primeiro uso

Uma vez executado `nokido-composants --tout` e com o Hub respondendo, consulte o Knowledge Pack incluído — sem chave de provedor,
nada para copiar:

```bash
nokido hub rag '{"action": "search", "topic": "Como instalo o Nokido com pip?", "limit": 5}'
```

A CLI `nokido` apresenta por si só o token de cliente local que `nokido-composants` armazenou no cofre da máquina
(identidade `EDITOR`, ring 2). Chamadores anônimos permanecem no ring 3 por design: em uma instalação nova eles podem listar as ferramentas,
e a busca acima lhes é recusada.
Esta primeira requisição é medida em máquinas limpas por `tools/forge_install_acceptance.py --paquete`.

Instalado com pip, o Nokido mantém seus dados (base de conhecimento, modelos, logs, cofre) **fora** de `site-packages`, na
pasta padrão de dados do usuário: `%LOCALAPPDATA%\Nokido`, `~/Library/Application Support/Nokido` ou
`~/.local/share/nokido` (`NOKIDO_DATA_DIR` a substitui). Eles sobrevivem a atualizações. Para desinstalar:

```bash
nokido-composants --desinstaller            # adicione --purger para apagar também seus dados
pip uninstall nokido-agent
```

Perguntar a um modelo (`ask`) exige um modelo: local (llama.cpp, Ollama) ou uma chave de provedor guardada no cofre
(`nokido-vault set -k GROQ_API_KEY`). Para inferência local com Ollama:

```bash
ollama pull qwen2.5-coder:latest
```

O Nokido pode então usar a pilha local antes de recorrer aos provedores em nuvem configurados.

---

# 🔑 Provedores e segredos

As chaves de API não devem ser colocadas em `.env` nem comitadas no repositório.

O Nokido usa um cofre baseado na máquina:

* **DPAPI** no Windows;
* **Keychain** no macOS;
* **libsecret / keyring** no Linux.

A interface web de administração expõe a configuração de provedores em:

```text
http://127.0.0.1:8766/admin/providers
```

ou por meio das ferramentas de cofre da CLI.

Exemplo:

```bash
nokido-vault set -k GROQ_API_KEY
```

Depois:

```bash
nokido-secrets status
```

Consulte a documentação de segurança antes de expor qualquer endpoint voltado para a rede.

---

## 🧭 Propriocepção do código

O hub expõe um endpoint de introspecção somente leitura sobre seu próprio código-fonte:

```text
GET /api/graph/proprioception
```

Ele responde com **imports / imported-by / grafo de chamadas por arquivo**, calculados a partir do
índice AST. Foi religado em 20/08/2026: antes retornava estatísticas do grafo de
conhecimento, que descrevem algo totalmente diferente — o grafo do saber ingerido, não a estrutura do código.

---

# 🔌 Conectar um agente externo

O Nokido pode ser conectado a clientes MCP como (transporte entre parênteses; o hub serve `http://localhost:8766/mcp`):

* Claude Code (MCP Streamable HTTP);
* Antigravity / `agy` (MCP HTTP);
* Codex CLI (MCP HTTP);
* Mistral Vibe, ZCode, Mammouth Code (MCP HTTP);
* Claude Desktop (MCP STDIO, pela ponte stdio);
* Cline (MCP STDIO);
* **OpenCode** — token de agente próprio e uma configuração governada que desliga seu bash e edição nativos
  ([`config/clients/opencode/`](../../config/clients/opencode/README.md)); sua UI web é lançada sob
  demanda pelo launcher `:7400`, protegida por senha, apenas em `127.0.0.1`;
* **claude.ai** e **ChatGPT web**, como *pares* na nuvem via HTTPS — um servidor MCP separado, nunca
  o `/mcp` do próprio hub, com uma quarentena aprovada pelo owner para tudo o que depositam
  ([24 — Pares na nuvem](../../docs/wiki/24-Cloud-Peers.md));
* outros clientes compatíveis com MCP.

O ACP é um segundo caminho para a interoperabilidade de agentes. O lado cliente está operacional: por meio do `NokidoAcpWorker`, o hub abre e conduz sessões ACP com claude, codex, opencode e agy. Expor o próprio Nokido como agente ACP (`NokidoAcpWs`, WebSocket) existe e está desativado por padrão.

O A2A Tier-1 (agente-para-agente, para sistemas que implementam o protocolo A2A) está presente no código e pausado: `NokidoA2A` está desativado por padrão.

---

# 🔬 Status do projeto

Cada linha associa uma maturidade **declarada** à **evidência neste repositório** que a
sustenta: um módulo, um serviço, um gate de CI. Cada evidência citada é reverificada por
`tools/forge_capability_audit.py` (controle « tableau de statut »): um ✅ sem evidência, uma
citação que não existe ou um serviço pausado exibido como operacional fazem a CI falhar.

Esta tabela **não** diz se um órgão está batendo *agora*. O Nokido é um corpo vivo e um README
só pode congelá-lo: pergunte ao próprio corpo, na sua máquina:

```bash
nokido-doctor --vivant          # a partir de um clone: python tools/nokido_doctor.py --vivant
```

Ele informa cada órgão que declara um pulso — vivo, incerto, não bate mais, desligado por
política (uma escolha, não uma falha) ou ilegível — com a evidência por trás de cada veredito.

```text
                                  DECLARED             EVIDENCE IN THIS REPOSITORY
ANATOMY / ORGANISM
  Strict anatomical census        ✅ achieved          `forge_module_census` --check, 0 unclassified
  CI architectural gate           ✅ achieved          `anatomie` gate, blocking since 2026-09-06
  M2M memory separation           ✅ achieved          `forge_db_path`: one switch read by every process
  Emergency homeostasis           ✅ achieved          `NokidoHomeostasis` + `forge_homeostasis_orchestrator`
  Sleep / circadian regulation    🟡 partial           all 6 phases fire on measured inactivity (`forge_circadian_runner --auto`); 4 of their 10 service targets disabled by policy

COMMUNICATION
  MCP                             ✅ operational       `NokidoMCP` hub, enabled by default
  ACP                             🟡 partial           client side operational (`NokidoAcpWorker` drives claude, codex, opencode, agy sessions); server `NokidoAcpWs` disabled by default
  A2A Tier-1                      ⏸️ paused            `NokidoA2A`, disabled by default (code present)
  M2M                             ✅ operational       `forge_m2m_protocol` validator (intents, pointers)
  Swarm                           🟡 hardening         `forge_swarm` family: NR in CI for 13 of 14 modules (not the base one)

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

Um serviço que responde prova o **transporte**, não a capacidade: diz que o órgão responde,
não que cada ferramenta por trás dele funcione. Isso é provado uma a uma pelos testes.

### O que o Nokido aprendeu sobre ser um organismo

Ao tentar modelar fronteiras fisiológicas em software, o Nokido já descobriu restrições que orientam seu desenvolvimento contínuo:

* Um órgão pode existir no código sem estar conectado.
* Emitir um sinal não significa que ele esteja sendo ouvido.
* `false` não é o mesmo que `ilegível`.
* A intenção deve ser explicitamente declarada, não adivinhada.
* A SNN carecia mais de sensores biológicos adequados do que de sofisticação algorítmica.
* A arquitetura centralizada deve progressivamente ceder alguns caminhos de reflexo diretamente para a borda (edge).

O projeto distingue explicitamente capacidades declaradas, disponíveis e verificadas, em vez de tratar todo o código-fonte como funcionalidade pronta para produção.

---

# ⚠️ O que o Nokido não alega

O Nokido **não** alega atualmente:

* AGI;
* autorreparo garantido;
* autonomia perfeita;
* autoconsciência perfeita;
* compatibilidade universal de protocolos;
* estabilidade de nível de produção para cada subsistema;
* suporte a hardware neuromórfico em produção.

O Nokido é um **projeto de pesquisa e engenharia em estágio alfa**.

A arquitetura é real.

Alguns subsistemas são maduros.

Alguns estão sendo ativamente endurecidos.

Alguns são protótipos de pesquisa.

Alguns são direções futuras.

O repositório, seus testes e suas verificações de capacidade em tempo real são a fonte fidedigna para o estado atual.

---

# 🔐 Segurança

Por favor, leia [`SECURITY.md`](../../SECURITY.md) antes de implantar o Nokido além do localhost.

As áreas sensíveis à segurança incluem:

* saída para a nuvem (cloud egress);
* lógica de firewall e membrana;
* RBAC;
* cofres;
* sandboxing;
* exposição de rede;
* endpoints ACP/A2A.

Vulnerabilidades de segurança devem ser **divulgadas privadamente primeiro**, e não postadas publicamente em uma issue ou discussão.

---

# 🤝 Contribuindo

O Nokido está aberto a contribuições, mas mudanças arquiteturais seguem regras rígidas do projeto.

Antes de contribuir, leia:

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`docs/CLA.md`](../../docs/CLA.md)

A branch de desenvolvimento é atualmente:

```text
alpha
```

Fluxo de trabalho típico de contribuição:

```bash
git clone https://github.com/Nokido-labs/nokido.git
cd nokido

git checkout -b feat/my-change alpha

bash install.sh
source .venv/bin/activate

pip install -e ".[dev,security]"

ruff check app/ tools/
pytest -m unit
```

O projeto exige testes para novas funcionalidades, desencoraja a duplicação de primitivas existentes e usa barreiras de segurança em torno de segredos, saída para nuvem e execução privilegiada.

---

# 📜 Licenciamento

O Nokido usa um **modelo de duplo licenciamento**.

## AGPLv3-or-later

A licença de código aberto padrão é:

**GNU Affero General Public License v3 ou posterior**

Consulte [`LICENSE`](../../LICENSE).

Você pode executar, estudar, modificar e redistribuir o Nokido sob os termos da AGPL.

As disposições de copyleft de rede são particularmente relevantes quando um sistema Nokido modificado é oferecido como um serviço de rede para usuários.

## Licença comercial

Uma licença comercial separada está disponível para casos de uso que não possam estar em conformidade com a AGPL, incluindo determinados:

* produtos proprietários;
* SaaS de código fechado;
* integrações OEM;
* distribuições white-label;
* implantações embarcadas proprietárias.

Consulte [`COMMERCIAL.md`](../archive/COMMERCIAL.md).

Você **não** precisa de uma licença comercial apenas para usar o Nokido de forma privada ou internamente sob a AGPL.

## Softwares e modelos de terceiros

A licença do Nokido não substitui as licenças de dependências, modelos ou provedores externos de terceiros.

Sempre verifique os termos aplicáveis de upstream antes de redistribuir:

* pesos de modelos;
* SDKs de provedores;
* imagens Docker;
* conjuntos de dados (datasets);
* serviços externos.

---

# 📝 Acordo de Licença de Contribuidor (CLA)

As contribuições exigem a aceitação do CLA do Nokido porque o projeto mantém um modelo de duplo licenciamento.

O CLA:

* **não** transfere seus direitos autorais (copyright);
* concede ao mantenedor amplos direitos sobre a sua contribuição;
* permite futuro relicenciamento comercial;
* inclui uma licença de patente;
* é versionado.

O CLA individual atual está documentado em [`docs/CLA.md`](../../docs/CLA.md).

Contribuições corporativas exigem o acordo corporativo separado descrito no documento.

---

# 🧭 Princípios de engenharia

## Medir antes de aplicar

Um detector conquista o direito de se tornar uma barreira (gate) ao demonstrar que mede aquilo que alega medir.

## Evidência acima de suposição

Desconhecido não é zero.

Indisponível não é morto.

Implementado não é verificado.

## Corrigir causas, não sintomas

Um serviço desativado pode proteger o sistema.

Isso não significa que o seu problema fundamental esteja resolvido.

## Manter o estado compartilhado coerente

O estado distribuído exige uma fonte explícita da verdade e um caminho de migração controlado.

## Transformar lições em reflexos

Falhas repetidas devem eventualmente se tornar testes, barreiras ou salvaguardas em tempo de execução.

## Acompanhar o silício

O Nokido foi projetado para que a arquitetura cognitiva possa evoluir enquanto o substrato físico de computação muda.

---

# 🗺️ Roteiro

### Curto prazo

**Tornar o organismo mais coerente.**

* concluir a separação de M2M;
* expandir capacidades A2A verificadas;
* estabilizar o ACP;
* endurecer a execução do enxame (swarm);
* aprimorar o roteamento de capacidade de embeddings;
* reduzir trabalho desnecessário no banco de dados;
* fortalecer a homeostase.

### Médio prazo

**Tornar a cognição distribuída mais autônoma.**

* coordenação de enxame mais robusta;
* descoberta de pares mais rica;
* ciclos de desenvolvimento autônomo mais fortes;
* roteamento mais profundo e consciente de recursos;
* maior cobertura de validação com conjuntos retidos (held-out).

### Longo prazo

**Mudar o substrato.**

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

O roadmap de hardware segue explicitamente essa progressão.

---

# 📚 Documentação

### Comece aqui

* [`docs/wiki/01-Installation.md`](../../docs/wiki/01-Installation.md) — instalação
* [`docs/wiki/02-Quick-Start.md`](../../docs/wiki/02-Quick-Start.md) — primeiros 30 minutos
* [`docs/wiki/03-Architecture.md`](../../docs/wiki/03-Architecture.md) — visão geral do sistema
* [`docs/wiki/Home.md`](../../docs/wiki/Home.md) — o índice completo da wiki (EN / FR)

### Conectar e operar

* [`docs/wiki/04-MCP-Clients-Setup.md`](../../docs/wiki/04-MCP-Clients-Setup.md) — clientes MCP e
  ressincronização de cada cliente após uma rotação de token
* [`docs/wiki/24-Cloud-Peers.md`](../../docs/wiki/24-Cloud-Peers.md) — claude.ai e ChatGPT web como
  pares na nuvem via HTTPS, quarentena do owner
* [`docs/wiki/07-Security-Model.md`](../../docs/wiki/07-Security-Model.md) — as camadas defensivas
* [`docs/wiki/08-Vault-and-Secrets.md`](../../docs/wiki/08-Vault-and-Secrets.md) — cofre, nomes
  reservados, criptografia em repouso (`V:`)

### Arquitetura aprofundada

* [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
* [`MANIFESTO.md`](../../MANIFESTO.md) · [English](MANIFESTO.en.md)

### Protocolos de agentes

* [`docs/ACP_INGRESS.md`](../../docs/ACP_INGRESS.md)
* Implementação de A2A — `tools/forge_a2a_server.py`, `tools/forge_a2a_card.py`
* Arquitetura de enxame — [`docs/roadmap_forge_swarm.md`](../../docs/roadmap_forge_swarm.md)

### Direção neural / hardware

* [`docs/wiki/13-Hardware-Roadmap.md`](../../docs/wiki/13-Hardware-Roadmap.md)

### Comunidade

* [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
* [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md)
* [`SECURITY.md`](../../SECURITY.md)
* [`docs/CLA.md`](../../docs/CLA.md)
* [`COMMERCIAL.md`](../archive/COMMERCIAL.md)

---

# 🌱 O objetivo de longo prazo

O Nokido não está tentando se tornar mais um chatbot.

O objetivo de longo prazo é construir:

> **um organismo artificial pessoal cuja cognição é distribuída entre agentes e substratos especializados, cuja memória persiste, cujos recursos são regulados, cujas fronteiras são protegidas, cujas falhas se tornam restrições aprendidas, e cujo substrato computacional pode eventualmente migrar do silício convencional em direção a sistemas neuromórficos.**

Esse organismo ainda não existe completamente. Mas vários órgãos já são reais, funcionais e interagem ativamente. A arquitetura para construí-lo está aqui.

**O Nokido é a tentativa de torná-lo real.**

---

## Licença

**AGPLv3-or-later** · Licenciamento comercial disponível

Consulte [`LICENSE`](../../LICENSE) e [`COMMERCIAL.md`](../archive/COMMERCIAL.md).

<p align="center"><img src="https://raw.githubusercontent.com/Nokido-labs/nokido/stats/stats.svg" alt="Public statistics: GitHub traffic, PyPI downloads, organism size" width="640"></p>

<!-- STATS:0690e3a84:2026-09-23 modules=582 rag_chunks=4899487 embeddings=1581437 -->
