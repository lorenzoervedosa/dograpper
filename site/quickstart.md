# Quickstart

After [installing](install.md):

```bash
# One-time setup: generate a config for your target (notebooklm / rag / claude-project / claude-code)
dograpper init

# Full pipeline: download + pack optimized for NotebookLM
dograpper download https://flask.palletsprojects.com/en/stable/ -o ./flask-docs
dograpper pack ./flask-docs -o ./chunks --bundle notebooklm --context-header --score

# Or in a single command:
dograpper sync https://flask.palletsprojects.com/en/stable/ -o ./flask-docs

# For RAG: JSONL export with cross-references
dograpper pack ./flask-docs -o ./chunks --format jsonl --cross-refs --score

# Change-gated re-pack: no-op if nothing changed, full repack if anything did
dograpper pack ./flask-docs -o ./chunks --delta
```
