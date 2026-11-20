# dograpper eval

Empirically validates a packed context's retrieval quality: generates
deterministic golden Q&A from heading breadcrumbs, runs BM25 retrieval,
and reports hit-rate@k, MRR, and a per-grade breakdown. Fully offline —
no network calls.

```bash
dograpper eval <chunks_dir> [options]
```

Prerequisite: a pack built with `--format jsonl --context-header` —
golden Q&A generation needs the heading breadcrumbs that flag injects.
Exits 1 if no JSONL chunks match `--prefix`, or if none of the loaded
chunks carry a heading breadcrumb to generate a question from.

## Examples

```bash
dograpper eval ./chunks
dograpper eval ./chunks -k 3 -o eval-report.json
```

## Options

```{dograpper-options} eval
```

## Options in detail

### `--output`

Write the JSON report (`k`, `total_questions`, `hits`, `hit_rate`, `mrr`, `per_grade`) to this path; the summary is printed either way
