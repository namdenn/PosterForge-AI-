# Poster Agent Backend

Terminal-first enterprise poster workflow. Sprint 3.5 is the active workflow:

- tenant-scoped brand ingestion for Markdown, text, JSON, and PDF;
- OpenAI embeddings persisted in a local SQLite vector store;
- evidence-backed `BrandProfile` synthesis;
- three LangGraph fan-out/fan-in stages;
- OpenAI Structured Outputs for messaging, visual, and campaign strategy proposals;
- deterministic brand, compliance, and feasibility review;
- bounded revision, durable checkpoints, and human approval;
- atomic `creative_blueprint.json` output;
- a campaign-specific Creative Territory Director and three parallel Concept Agents;
- Structured Output overlay plans instead of fixed poster layout templates;
- image generation that may create UI, products, people, symbols, and recognizable objects;
- generated artwork preserved as the composed poster's visible key visual;
- parallel post-generation visual-layout agents that protect hero subjects and diversify typography;
- an original-logo final layer protected by asset checksum and brand tokens;
- agent-directed typography rendered deterministically for exact campaign copy;
- parallel brand, content, layout, technical, and vision QA;
- bounded render revision, checkpoints, human approval, and final PNG output.

Sprint 2 creates approved RAG-grounded copy and strategy. Sprint 3.5 turns it into three autonomous
creative concepts and a reviewed poster.

## Setup

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
```

Your local `.env` needs:

```dotenv
OPENAI_API_KEY=your_project_api_key
OPENAI_MODEL=your_structured_output_capable_model
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_IMAGE_MODEL=gpt-image-2.5-flare
```

The embedding model has a safe default in code, so existing `.env` files continue to work.

## Run Sprint 3

Prepare an approved transparent logo and optional product PNG as described in
`examples/assets/acme-coffee/README.md`, then copy and update the example manifest:

```powershell
Copy-Item examples\assets\acme-coffee\asset_manifest.example.json `
  examples\assets\acme-coffee\asset_manifest.json
```

Validate locally before spending an API call:

```powershell
poster-agent render validate `
  artifacts\summer-launch-2026\63463e1e-2b75-461e-ab58-93b8c3568aa2\creative_blueprint.json `
  --assets examples\assets\acme-coffee\asset_manifest.json
```

Run the renderer:

```powershell
poster-agent render run `
  artifacts\summer-launch-2026\63463e1e-2b75-461e-ab58-93b8c3568aa2\creative_blueprint.json `
  --assets examples\assets\acme-coffee\asset_manifest.json `
  --variants 3 --max-attempts 2
```

See `docs/SPRINT_03_GRAPH.md` for the graph, output tree, QA rules, resume, and approval commands.

## Run Sprint 2

First ingest brand knowledge:

```powershell
poster-agent brand ingest examples\brand\acme-coffee `
  --tenant-id demo-company `
  --brand-id acme-coffee `
  --brand-name "Acme Coffee"
```

Inspect the indexed profile without an API call:

```powershell
poster-agent brand inspect --tenant-id demo-company --brand-id acme-coffee
```

Then run the campaign graph:

```powershell
poster-agent brief validate examples\campaign_brief.json
poster-agent campaign run examples\campaign_brief.json --max-attempts 2
```

The command prints a new `thread_id`. Inspect or resume it with:

```powershell
poster-agent campaign inspect YOUR_THREAD_ID
poster-agent campaign resume YOUR_THREAD_ID
```

If automated reviewers return `needs_review`, inspect the evidence and approve explicitly:

```powershell
poster-agent campaign approve YOUR_THREAD_ID `
  --reason "Reviewed brand, compliance, and production risks."
```

Output is written to:

```text
artifacts/<campaign_id>/<thread_id>/creative_blueprint.json
```

Use the correct command spelling: `campaign`, not `campaing`.

## API usage

- `brand ingest`: embeddings calls plus one BrandProfile Structured Output call.
- `campaign run`: three retrieval embedding calls and three parallel Structured Output calls per
  concept attempt.
- `render run`: one Creative Director call, up to three parallel Concept Agent calls, then one
  image/edit call, one artwork gate, and one final vision-QA call per enabled variant and artwork
  attempt.
- `doctor`, `brief validate`, `brand inspect`, `campaign inspect`, and unit tests do not call API.

## Quality checks

```powershell
python -m ruff format --check .
python -m ruff check .
python -m mypy src tests
python -m pytest -q
```

## Documentation

- `docs/SPRINT_01.md`: completed baseline workflow.
- `docs/SPRINT_02_GRAPH.md`: active RAG and multi-parallel workflow.
- `docs/SPRINT_03_GRAPH.md`: active autonomous composition, brand locking, and QA workflow.
- `docs/PROJECT_STRUCTURE.md`: responsibility of every source folder and module.
- `docs/BLOCK_COMMUNICATION.md`: typed boundary rules.
