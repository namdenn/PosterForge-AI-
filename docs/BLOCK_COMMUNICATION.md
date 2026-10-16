# Block communication hints

## Boundary rule

Blocks communicate through typed contracts, not imports of each other's concrete
implementations. Domain models are the shared language.

Recommended direction:

```text
CLI -> Graph application -> Nodes -> Interfaces -> Infrastructure adapters
                         \-> Domain schemas
```

Infrastructure must not import the CLI. Domain modules must not import LangGraph, OpenAI,
LlamaIndex, SQLAlchemy, or Typer.

## Suggested contracts

Define these as Protocols or abstract interfaces before implementing adapters:

- `StrategyGenerator`: receives a campaign brief and returns a campaign strategy.
- `BrandRetriever`: receives a tenant-scoped query and returns evidence records.
- `DesignGenerator`: creates campaign-specific territories and validated Scene Graph concepts.
- `ImageGenerator`: creates an artwork layer while protected logo and copy stay outside generation.
- `CampaignRepository`: stores and retrieves campaign metadata.
- `ArtifactStore`: stores generated JSON and media artifacts.
- `CheckpointProvider`: provides the LangGraph checkpointer.

## Graph state

Keep state as raw typed data. Do not store formatted prompt strings in state. Each node
should read only the fields it needs and return only its own updates.

Suggested ownership:

| Block | Reads | Writes |
|---|---|---|
| Brief validation | raw brief | validated brief or validation errors |
| Brand retrieval | validated brief | evidence records |
| Strategy generation | brief and evidence | strategy |
| Quality gate | strategy and evidence | quality report |
| Persistence | approved result | identifiers and artifact locations |
| Creative director | approved blueprint and brand tokens | three dynamic territories |
| Parallel concept agent | one territory | one normalized Scene Graph |
| Generic renderer | Scene Graph and locked assets | composed candidate |

## Dependency injection

Build concrete dependencies at the application boundary, then inject them into node
factories. This lets tests use fake implementations without calling OpenAI or a database.

## OpenAI boundary

Only the OpenAI adapter should import and instantiate the OpenAI SDK. It should translate:

```text
Domain input -> API request -> validated domain output
```

Use Structured Outputs for domain results. Handle authentication, timeout, retry, usage,
and provider-specific errors inside this adapter rather than inside graph nodes.

## RAG boundary

LlamaIndex should be hidden behind `BrandRetriever`. The graph should receive evidence
records, not LlamaIndex nodes or query-engine objects.

Every evidence record should carry `tenant_id`, `document_id`, `chunk_id`, source version,
and relevance score.

## Database boundary

Repository interfaces live close to the domain. SQLAlchemy models and sessions live in
`persistence`. Nodes call repositories; nodes do not issue SQL.

Begin with SQLite through the repository interface. Switching to PostgreSQL should only
replace configuration and infrastructure adapters.

## Parallel execution

Parallel nodes must write to different state keys. Join results in a dedicated aggregator
node. Never allow parallel nodes to mutate the same list or database record without an
explicit merge policy.

## Error communication

Separate errors into:

- input errors: returned to the CLI without retry;
- transient provider errors: retried with bounded exponential backoff;
- invalid model output: validated, reported, and optionally regenerated;
- infrastructure errors: logged with correlation identifiers;
- unexpected errors: allowed to surface for debugging.

