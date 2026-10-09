# data/

Not committed to git (see `.gitignore`), except this file.

```
data/
├── raw/            <- put the dataset here (any sub-folders are fine)
│   ├── Datasets/
│   │   ├── Daily Geological Operations Summary/*.pdf
│   │   └── Daily Operation Report/*.pdf
│   └── Glossaries.docx
├── parsed/         <- JSON written by `python -m wellchat.ingest` (one file per source)
└── wellchat.db     <- SQLite index rebuilt from parsed/ on every ingest
```
