# NotebookLM
```bash
dograpper pack ./docs -o ./chunks --bundle notebooklm --context-header --score
# Produces ≤50 balanced chunks + IMPORT_GUIDE.md with upload ordering
```

## More on NotebookLM ingestion

`--bundle notebooklm` caps the output at 50 chunks because 50 is NotebookLM's
source ceiling.

Tips for Audio Overview:

- Upload all the chunks before generating the overview.
- Balanced chunks produce more complete overviews.
- Remove changelog and FAQ chunks for a more focused overview.

To calibrate the parameters, simulate the run without writing any files:

```bash
dograpper pack ./docs -o ./chunks --bundle notebooklm --dry-run --score
```

Upload the files from the chunks directory in the order given by
`IMPORT_GUIDE.md`.
