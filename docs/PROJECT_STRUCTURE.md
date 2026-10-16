# Project structure and file responsibilities

## Root

- `.env`: local secrets and runtime values. Git ignores it.
- `.env.example`: safe configuration template with no secret values.
- `pyproject.toml`: package metadata, dependencies, CLI entry point, and test/lint configuration.
- `compose.yaml`: optional PostgreSQL service for a later deployed environment.
- `alembic.ini`: database-migration configuration.
- `README.md`: setup and operator commands.

## `src/poster_agent`

- `__init__.py`: package identity and version.
- `config.py`: reads environment variables into typed `Settings`; validates OpenAI settings only
  when an API-backed command runs.
- `cli.py`: parses terminal input, constructs dependencies, opens the checkpointer, invokes the
  graph, and renders results. Business logic does not belong here.

### `assets`

- `registry.py`: validates tenant/brand/channel scope, blocks path traversal, hashes files, and
  resolves one protected logo plus optional approved product, font, and reference assets.
- `__init__.py`: public asset-boundary exports.

### `domain`

This folder is the shared business language. It must not import LangGraph, OpenAI, SQLAlchemy,
Typer, or LlamaIndex.

- `enums.py`: controlled values for objective, channel, language, campaign status, and risk.
- `brief.py`: validated input schema for one campaign.
- `strategy.py`: structured marketing and visual-direction output schema.
- `brand.py`: evidence and brand-profile schemas used by Sprint 2 RAG.
- `blueprint.py`: context, specialist proposals, reviews, and final `CreativeBlueprint` schemas.
- `render.py`: brand tokens, creative territories, Scene Graph, render plan, candidate, QA,
  selection, and manifest schemas.
- `errors.py`: application exceptions that hide vendor-specific implementation details.
- `__init__.py`: convenient exports for domain consumers.

### `llm`

- `gateway.py`: provider-neutral `StrategyGenerator` protocol and generation metadata.
- `openai_gateway.py`: the only module that knows the OpenAI SDK. It builds the request, calls the
  Responses API, parses directly into `CampaignStrategy`, retries transient errors, and translates
  missing output into a domain error.
- `embedding_gateway.py`: embedding protocol and batched OpenAI embeddings adapter.
- `creative_gateway.py`: provider-neutral contract for the three Sprint 2 concept agents.
- `openai_creative_gateway.py`: Structured Output adapter for BrandProfile and specialist agents.
- `design_gateway.py`: provider-neutral Creative Director and Concept Agent contracts.
- `openai_design_gateway.py`: Structured Output adapter for territories and dynamic Scene Graphs.
- `image_gateway.py`: provider-neutral image generation and vision-review protocols.
- `openai_image_gateway.py`: OpenAI Images API generation and Structured Output visual QA.
- `__init__.py`: public LLM-boundary exports.

### `prompts`

- `strategy_v1.md`: versioned system instructions bundled with the Python package.
- `brand_profile_v1.md`, `messaging_v1.md`, `visual_v1.md`, and `campaign_strategy_v2.md`:
  versioned Sprint 2 specialist instructions.
- `creative_director_v1.md` and `concept_designer_v1.md`: dynamic territory and Scene Graph
  instructions with brand-lock rules.
- `__init__.py`: makes prompt files addressable through `importlib.resources` after installation.

### `graph`

- `state.py`: the checkpointed contract shared by all nodes.
- `routing.py`: pure branch decisions; no I/O and no API calls.
- `builder.py`: registers nodes and edges and compiles the graph with injected adapters.
- `rag_state.py`: multi-agent state and the reducer for parallel generation metadata.
- `rag_builder.py`: three-stage fan-out/fan-in graph composition.
- `rag_routing.py`: bounded automated-review retry decisions.
- `render_state.py`: durable state for candidates, reviews, selection, and final artifacts.
- `render_builder.py`: dynamic director, three parallel concept/image agents, and five parallel
  quality gates.
- `render_routing.py`: bounded render revision decisions.
- `__init__.py`: public graph exports.

#### `graph/nodes`

- `load_brief.py`: reads and decodes input JSON.
- `validate_brief.py`: converts raw JSON to `CampaignBrief` or field-level errors.
- `normalize_brief.py`: applies deterministic cleanup after validation.
- `generate_strategy.py`: calls the injected `StrategyGenerator` and counts attempts.
- `quality_gate.py`: checks invariants that span the brief and generated strategy.
- `save_artifact.py`: asks the injected artifact store to persist an approved result.
- `context_agents.py`: parallel brand/product/audience retrieval plus channel constraints.
- `concept_agents.py`: parallel messaging, visual, and strategy generation.
- `synthesize_blueprint.py`: deterministic proposal aggregation.
- `review_agents.py`: parallel brand, compliance, and feasibility checks.
- `design_nodes.py`: Creative Director, parallel Concept Agents, Scene Graph validation, and
  deterministic diversity scoring.
- `save_blueprint.py`: persists approved or needs-review Sprint 2 output.
- `render_nodes.py`: loads Sprint 2 output, plans, renders, composes, and reviews candidates.
- `save_render.py`: persists the selected Sprint 3 poster and manifest.
- `__init__.py`: marks the node package.

### `persistence`

There are three distinct kinds of persistence: LangGraph checkpoints capture execution state;
business tables store campaign metadata; artifacts are outputs for downstream creative systems.

- `checkpointer.py`: async SQLite checkpointer lifecycle for local terminal execution.
- `artifact_store.py`: storage protocol and atomic local JSON implementation.
- `render_store.py`: atomic selected-poster copy and Sprint 3 render manifest persistence.
- `database.py`: async SQLAlchemy engine/session lifecycle for business tables.
- `models.py`: SQLAlchemy campaign and workflow-run records.
- `repositories.py`: repository protocol and SQLAlchemy campaign adapter.
- `__init__.py`: public persistence exports.

### `rendering`

- `compositor.py`: generic normalized Scene Graph renderer; positions come from agents while exact
  logo, optional product assets, fonts, and campaign copy come from trusted inputs.
- `__init__.py`: public compositor exports.

### `rag`

These modules contain typed ports and the local terminal implementations.

- `ingestion.py`: discovery, parsing, chunking, embedding, and document replacement.
- `retrieval.py`: tenant-scoped semantic `BrandRetriever` returning domain evidence.
- `brand_profile.py`: `BrandProfileBuilder` synthesis contract.
- `store.py`: SQLite vector storage, cosine ranking, tenant filters, and BrandProfile persistence.
- `__init__.py`: public RAG-contract exports.

### `observability`

- `logging.py`: one central structlog configuration.
- `tracing.py`: provider-neutral timed span helper.
- `__init__.py`: public observability exports.

## Other folders

- `examples/`: safe sample input for terminal commands.
- `tests/unit/domain/`: fast schema and business-rule tests.
- `tests/unit/graph/`: graph tests with fake dependencies and durable-checkpoint coverage.
- `tests/integration/`: reserved for tests requiring infrastructure.
- `tests/smoke/`: reserved for explicitly enabled, billable external API tests.
- `migrations/env.py`: Alembic's async connection and model-metadata bridge.
- `migrations/script.py.mako`: template used when generating later migration revisions.
- `migrations/versions/20260923_0001_create_campaign_tables.py`: initial reversible schema for
  campaign and workflow-run metadata.
- `artifacts/`: generated strategy, blueprint, poster, and audit files; runtime contents are ignored
  by Git.
- `data/`: SQLite business/checkpoint databases; runtime contents are ignored by Git.
- `logs/`: optional local logs; runtime contents are ignored by Git.
- `database/`: PostgreSQL initialization assets for Docker Compose.
- `prompts/`: legacy/root prompt workspace; runtime code uses packaged `src/poster_agent/prompts`.

## Dependency direction

```text
CLI -> graph builder -> nodes -> protocols -> infrastructure adapters
                    \-> domain models
```

The domain imports no infrastructure. Concrete dependencies are assembled in the CLI, which
keeps the graph testable and lets a later HTTP API reuse the same application.
