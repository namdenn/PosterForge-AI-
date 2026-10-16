# Start here

```powershell
poster-agent brand ingest examples\brand\acme-coffee `
  --tenant-id demo-company `
  --brand-id acme-coffee `
  --brand-name "Acme Coffee"

poster-agent campaign run examples\campaign_brief.json

poster-agent render validate <creative_blueprint.json> --assets <asset_manifest.json>
poster-agent render run <creative_blueprint.json> --assets <asset_manifest.json>
```

Learn the implementation by following one request through the code:

1. Run `poster-agent brief validate examples/campaign_brief.json`.
2. Read `domain/brief.py` to see the input contract.
3. Read `rag/ingestion.py`, `rag/store.py`, then `rag/retrieval.py`.
4. Read `graph/rag_state.py`, then `graph/rag_builder.py`.
5. Follow context, concept, synthesis, and review modules in `graph/nodes`.
6. Read `llm/creative_gateway.py` before `llm/openai_creative_gateway.py`.
7. Read `persistence/checkpointer.py` and `artifact_store.py` to distinguish execution state from
   business output.
8. Read `domain/render.py`, `assets/registry.py`, then `graph/render_builder.py`.
9. Read `llm/design_gateway.py`, `llm/openai_design_gateway.py`, and
   `graph/nodes/design_nodes.py` to follow dynamic territories and Scene Graphs.
10. Follow generation, generic composition, and QA in `graph/nodes/render_nodes.py`.
11. Read `llm/image_gateway.py`, `llm/openai_image_gateway.py`, and
    `rendering/compositor.py`.
12. Run `pytest -q`, then change one review rule and add its test.

Use `PROJECT_STRUCTURE.md` as the complete file map, `Overall.md` for the baseline,
`RAG_and_multi-parallel-workflow.md` for RAG/creative planning, and `Render_Visualize.md` for rendering and visual
quality control.
