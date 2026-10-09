# data/

Isi folder ini tidak di-commit ke git (lihat `.gitignore`), kecuali file ini.

```
data/
├── raw/            <- letakkan dataset di sini (subfolder apa pun boleh)
│   ├── Datasets/
│   │   ├── Daily Geological Operations Summary/*.pdf
│   │   └── Daily Operation Report/*.pdf
│   └── Glossaries.docx
├── parsed/         <- JSON hasil `python -m wellchat.ingest` (satu file per dokumen sumber)
└── wellchat.db     <- indeks SQLite yang dibangun ulang dari parsed/ setiap kali ingest
```
