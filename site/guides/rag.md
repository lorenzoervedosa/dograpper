# RAG / Vector DB
```bash
dograpper pack ./docs -o ./chunks --format jsonl --cross-refs --score
# JSONL ready for embeddings, with cross-reference graph
```

## More on RAG ingestion

Add `--context-header` to the recommended pipeline:

```bash
dograpper download <url> -o ./docs
dograpper pack ./docs -o ./chunks --format jsonl --cross-refs --score --context-header
```

Each line of the JSONL output is one JSON record with the
`dograpper-context-v1` schema, for example:

```json
{"id":"01_api.html","source":"api.html","words":4820,"breadcrumb":["API","Auth"],"readiness_grade":"A","content":"...","schema_version":"v1"}
```

`cross_refs.json` maps the reference graph between chunks, which enables
multi-hop retrieval.

A typical pipeline:

```
dograpper pack --format jsonl
    → embeddings (OpenAI/Cohere/local)
    → vector DB (Pinecone/Chroma/Qdrant)
    → retriever with the cross-reference graph
```

Use `--score` to find the chunks graded C and filter them out before you
vectorize.
