# Well Data Chat

Aplikasi chat yang menjawab pertanyaan **hanya** dari laporan sumur (PDF *Daily Operation Report* / DDR dan *Daily Geological Operations Summary* / DGOS) serta glosarium istilah Oil & Gas (`Glossaries.docx`). Pertanyaan di luar cakupan ditolak dengan pesan baku, dan setiap jawaban menyertakan file sumber beserta halamannya.

```
PDF/DOCX ──► parser (pdfplumber, python-docx) ──► JSON per file ──► SQLite + FTS5
                                                                     │
          Streamlit UI / CLI ◄── agen LLM (OpenAI tool calling) ◄────┘
```

---

## Daftar isi

1. [Prasyarat](#1-prasyarat)
2. [Instalasi](#2-instalasi)
3. [Konfigurasi](#3-konfigurasi)
4. [Meletakkan dataset](#4-meletakkan-dataset)
5. [Menjalankan](#5-menjalankan)
6. [Menambah PDF baru](#6-menambah-pdf-baru)
7. [Struktur JSON hasil parsing](#7-struktur-json-hasil-parsing)
8. [Database SQLite](#8-database-sqlite)
9. [Pengujian dan evaluasi](#9-pengujian-dan-evaluasi)
10. [Planning](#10-planning)
11. [Resolution](#11-resolution)

---

## 1. Prasyarat

- Python **3.10 atau lebih baru** (dikembangkan dan diuji dengan Python 3.13).
- API key OpenAI. Penyedia lain yang kompatibel dengan OpenAI API juga bisa dipakai, lihat [Konfigurasi](#3-konfigurasi).
- Tidak perlu Docker atau database server. SQLite sudah termasuk di Python.

## 2. Instalasi

```bash
git clone https://github.com/hairuljr/wellchat.git
cd wellchat

python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## 3. Konfigurasi

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Isi `OPENAI_API_KEY` di `.env`. Variabel lainnya opsional:

| Variabel | Default | Keterangan |
|---|---|---|
| `OPENAI_API_KEY` | (wajib) | Key OpenAI milik reviewer. |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Model apa pun yang mendukung *tool calling* dan *structured output* (JSON schema). |
| `OPENAI_REASONING_EFFORT` | `none` | Hanya dikirim ke model *reasoning* (`gpt-5*`, `o*`). Untuk `gpt-5.4-mini`, Chat Completions menolak *tool calling* dengan effort selain `none`. Kosongkan untuk tidak mengirim. |
| `OPENAI_BASE_URL` | (kosong) | Isi untuk memakai endpoint lain yang kompatibel dengan OpenAI (Azure OpenAI, OpenRouter, vLLM/Ollama lokal). Key yang dibutuhkan adalah key dari penyedia tersebut, diisi di `OPENAI_API_KEY`. |
| `DATA_DIR`, `RAW_DIR`, `PARSED_DIR`, `DB_PATH` | `./data`, `./data/raw`, `./data/parsed`, `./data/wellchat.db` | Lokasi data. |

API key tidak pernah disimpan di repositori: `.env` ada di `.gitignore`.

## 4. Meletakkan dataset

Dataset dan hasil parsing **tidak** ada di repositori. Salin folder `Datasets` dan file `Glossaries.docx` ke `data/raw/`:

```
data/raw/
├── Datasets/
│   ├── Daily Geological Operations Summary/
│   │   ├── BARAKUDA-1_DGOS_72_20260829.pdf
│   │   └── BARAKUDA-1_DGOS_84_20260910.pdf
│   └── Daily Operation Report/
│       ├── NAGA-2_BARAKUDA-1_DDR_32_19_07_2026_Drill_17_5in_x_20in_Hole.pdf
│       └── NAGA-2_BARAKUDA-1_DDR_53_09_08_2026_LD_14_75in_Motor_BHA__Wireline_Operation.pdf
└── Glossaries.docx
```

Nama subfolder dan nama file bebas. Parser membaca semua `*.pdf` dan `*.docx` di bawah `data/raw/` secara rekursif, dan jenis laporan dikenali dari isi halaman pertama, bukan dari nama file.

Hasil parsing ditulis ke:

- `data/parsed/*.json`: satu file JSON per dokumen sumber (lihat [bagian 7](#7-struktur-json-hasil-parsing)).
- `data/wellchat.db`: database SQLite yang dibangun ulang dari JSON tersebut.

## 5. Menjalankan

```bash
# 1. Parsing semua dokumen -> JSON + SQLite (satu perintah)
python -m wellchat.ingest

# 2a. Antarmuka chat di browser (http://localhost:8501)
streamlit run app.py

# 2b. Atau lewat terminal
python -m wellchat.cli "Dimana letak lokasi sumur?"
python -m wellchat.cli          # mode interaktif
```

Contoh keluaran `ingest`:

```
  parsed  Datasets/Daily Operation Report/NAGA-2_BARAKUDA-1_DDR_32_...pdf -> ...json (DDR #32 2026-07-19, 1.5s)
          warning: Spud date 27/06/2027 is after report date 19/07/2026 (probably a typo in the source report).
  parsed  Glossaries.docx -> Glossaries.docx.json (GLOSSARY, 196 terms, 0.0s)
Done: {'parsed': 5, 'skipped': 0, 'failed': 0, 'removed': 0, 'documents': 5}
```

Di UI, setiap jawaban menampilkan daftar sumber (nama file, halaman, bagian laporan) dengan tombol untuk mengunduh PDF aslinya, serta waktu respons.

## 6. Menambah PDF baru

Tidak ada kode yang perlu diubah:

1. Letakkan PDF baru (format DDR atau DGOS yang serupa) di mana saja di bawah `data/raw/`.
2. Jalankan `python -m wellchat.ingest`. Hanya file baru atau yang berubah yang diparsing ulang (dicek dengan SHA-256). `--force` memparsing ulang semuanya.
3. Langsung tanyakan lewat chat. Aplikasi membaca database pada setiap pertanyaan, jadi tidak perlu restart.

Alternatif di UI: sidebar **Tambah PDF/DOCX baru**, lalu **Simpan & parse file baru**. File disimpan ke `data/raw/uploads/` dan langsung diindeks. Tombol **Parse ulang folder data** menjalankan ingest untuk file yang disalin manual.

PDF yang tidak dikenali sebagai DDR/DGOS tetap diparsing sebagai `UNKNOWN`: teksnya per halaman diindeks sehingga masih bisa ditanyakan, hanya tanpa field terstruktur.

## 7. Struktur JSON hasil parsing

Satu file JSON per dokumen sumber. Field umum untuk semua laporan PDF:

| Field | Tipe | Keterangan |
|---|---|---|
| `schema_version` | string | Versi struktur, saat ini `"1.0"`. |
| `source` | object | `file_name`, `relative_path` (relatif ke `data/raw`), `sha256`, `page_count`. |
| `parsed_at` | string | Waktu parsing (ISO 8601, UTC). |
| `doc_type` | string | `DDR`, `DGOS`, `UNKNOWN`, atau `GLOSSARY`. |
| `well_name`, `report_no` | string \| null | Dari header laporan. |
| `report_date` | string \| null | Tanggal laporan, ISO `yyyy-mm-dd`. |
| `fields` | array | Field header `Label : value`: `{key, label, value, page}`. Nilai disimpan persis seperti di PDF (termasuk satuan). |
| `sections` | array | Blok teks per bagian laporan: `{name, pages, text}`. |
| `warnings` | array of string | Masalah kualitas data yang terdeteksi saat parsing. |
| `pages` | array | Teks bersih per halaman `{page, text}`. Cadangan bila struktur gagal dikenali. |

Khusus **DDR**: `operations` (baris tabel *Operation Summary*), `next_day_operations` (update 00:00–06:00 hari berikutnya), `derived.npt_hours_from_operation_rows`.
Khusus **DGOS**: `npt` (baris NPT di blok *Last 24 hrs*), `progress` (phase/AFE/mud), `daily_remarks`, `tables` (Drilling Summary/Casing, Formation Tops).
Khusus **GLOSSARY**: `entries` menggantikan `fields`/`sections`.

### Contoh DDR (data dummy)

```json
{
  "schema_version": "1.0",
  "source": {
    "file_name": "RIG-X_SAMPLE-1_DDR_05_01_02_2030.pdf",
    "relative_path": "Datasets/Daily Operation Report/RIG-X_SAMPLE-1_DDR_05_01_02_2030.pdf",
    "sha256": "3f1c...e9a2",
    "page_count": 6
  },
  "parsed_at": "2030-02-02T01:00:00+00:00",
  "doc_type": "DDR",
  "well_name": "SAMPLE-1",
  "report_no": "5",
  "report_date": "2030-02-01",
  "fields": [
    {"key": "rig_name", "label": "Rig Name", "value": "RIG-X", "page": 1},
    {"key": "daily_npt", "label": "Daily NPT", "value": "2.00 hr", "page": 1},
    {"key": "cumm_npt", "label": "Cumm NPT", "value": "6.50 hr", "page": 1},
    {"key": "current_status", "label": "Current status", "value": "Drilling ahead - Ongoing.", "page": 1}
  ],
  "sections": [
    {"name": "STATUS", "pages": [1], "text": "STATUS\nCurrent status : Drilling ahead - Ongoing.\n24 hr summary : ..."}
  ],
  "operations": [
    {
      "from": "0:00", "to": "22:00", "hours": 22.0, "phase": "D18", "activity": "DRL",
      "productive_code": "OPRN", "npt": false, "rig_status": "OPRN", "md_from_m": 900.0,
      "operation": "Drill 12-1/4\" hole from 700m to 900m MDDF.", "page": 1
    },
    {
      "from": "22:00", "to": "0:00", "hours": 2.0, "phase": "D18", "activity": "RRP",
      "productive_code": "TPQP", "npt": true, "rig_status": "OPRN", "md_from_m": 900.0,
      "operation": "Repair top drive hydraulic hose.", "page": 2
    }
  ],
  "next_day_operations": [
    {"date": "2 February 2030", "from": "00:00", "to": "06:00", "operation": "Continue drilling.", "page": 2}
  ],
  "derived": {"npt_hours_from_operation_rows": 2.0},
  "warnings": [],
  "pages": [{"page": 1, "text": "PTT PUBLIC COMPANY LIMITED\nDaily Operation Report\n..."}]
}
```

### Contoh DGOS (data dummy, field khusus saja)

```json
{
  "doc_type": "DGOS",
  "well_name": "SAMPLE-1",
  "report_no": "12",
  "report_date": "2030-02-03",
  "fields": [
    {"key": "country", "label": "COUNTRY", "value": "XYZ | EXAMPLELAND", "page": 1},
    {"key": "basin", "label": "BASIN", "value": "OFFSHORE SAMPLE", "page": 1}
  ],
  "npt": "1.00 hrs due to pump repair.",
  "progress": {
    "phase": {"phase": "D12", "days": 15.5, "cost_musd": 8.2, "depth_m_mddf": 1500.0, "depth_m_tvdss": 1470.0, "page": 1},
    "afe":   {"days": 40.0, "cost_musd": 20.0, "depth_m_mddf": 3000.0, "depth_m_tvdss": 2970.0, "page": 1},
    "mud":   {"progress_m": "-", "avg_rop_m_per_hr": "-", "mud_weight_ppg": 11.5, "mud_type": "SBM", "date": "03-02-2030", "time": "06:00", "page": 1}
  },
  "daily_remarks": [{"no": 1, "text": "Observed background gas 0.5%.", "page": 1}],
  "tables": [
    {
      "name": "FORMATION TOPS", "page": 1,
      "columns": ["Formation", "MD Prog (m MDDF)", "TVD Prog (m TVDDF)", "TVDSS Prog (m)", "MD Act (m MDDF)", "TVD Act (m TVDDF)", "TVDSS Act (m)", "Diff Hi/Lo (m)", "Remarks"],
      "rows": [{"Formation": "Top A", "MD Prog (m MDDF)": "800.0", "TVD Prog (m TVDDF)": "800.0", "TVDSS Prog (m)": "770.0", "MD Act (m MDDF)": "805.0", "TVD Act (m TVDDF)": "805.0", "TVDSS Act (m)": "775.0", "Diff Hi/Lo (m)": "5.0", "Remarks": "Preliminary."}]
    }
  ]
}
```

### Contoh glosarium (data dummy)

```json
{
  "schema_version": "1.0",
  "source": {"file_name": "Glossaries.docx", "relative_path": "Glossaries.docx", "sha256": "..."},
  "doc_type": "GLOSSARY",
  "entries": [
    {"term": "ROP", "meaning": "Rate of Penetration – Drilling speed.", "full_form": "Rate of Penetration",
     "description": "Drilling speed.", "category": "abbreviation", "to_be_confirmed": false, "table": 2},
    {"term": "XYZ", "meaning": "Unknown – Seen in the mud table. (to be confirmed)", "full_form": "Unknown",
     "description": "Seen in the mud table. (to be confirmed)", "category": "abbreviation", "to_be_confirmed": true, "table": 2}
  ]
}
```

## 8. Database SQLite

Database (`data/wellchat.db`) adalah indeks turunan: dibangun ulang dari `data/parsed/*.json` pada setiap `ingest`, lalu ditukar secara atomik sehingga aplikasi yang sedang berjalan tidak pernah membaca database setengah jadi. Aman dihapus kapan saja.

| Tabel | Isi |
|---|---|
| `documents` | Satu baris per file: tipe, nomor dan tanggal laporan, warnings. |
| `fields` | Field header per laporan (`Cumm NPT`, `COUNTRY`, ...). |
| `sections` | Teks per bagian laporan. |
| `operations` | Baris *Operation Summary* DDR, termasuk flag NPT. |
| `report_tables` | Tabel DGOS (casing, formation tops) sebagai JSON. |
| `glossary` | Entri glosarium. |
| `chunks` + `chunks_fts` | Potongan teks untuk pencarian full-text FTS5 (BM25). |

## 9. Pengujian dan evaluasi

```bash
pip install -r requirements-dev.txt

# Unit test parser, store, tool, dan guardrail agen (tanpa API key; LLM dipalsukan)
python -m pytest -q

# Evaluasi end-to-end dengan LLM sungguhan (butuh API key + data sudah di-ingest)
python -m eval.run_eval
```

- `tests/test_parsers.py`: memeriksa hasil parsing dataset asli (di-skip bila `data/raw` kosong).
- `tests/test_synthetic.py`: membuat PDF baru dengan layout serupa tetapi nilai berbeda (nama sumur, tanggal, NPT), lalu memastikan semuanya terparsing dan bisa dicari. Ini bukti bahwa parser tidak terikat pada file contoh.
- `tests/test_agent.py`: memeriksa loop agen dan guardrail dengan LLM palsu (penolakan baku, jawaban tanpa tool dianggap di luar cakupan, sumber halusinasi dibuang, pertanyaan tentang *offset well*).
- `tests/test_tools.py`: memeriksa tool yang dipanggil LLM, misalnya rencana operasi dari semua laporan dan daftar sumur.
- `eval/questions.json`: 23 pertanyaan uji (3 contoh dari soal, pertanyaan faktual lain, glosarium, di luar cakupan). `run_eval` mengukur akurasi dan waktu respons, lalu menulis `eval/results.md`.

---

## 10. Planning

### Pendekatan

Masalahnya adalah tanya jawab faktual atas sedikit dokumen semi-terstruktur: angka, tanggal, kode, dan nama yang muncul literal di laporan. Akurasi ditentukan oleh dua hal: (1) kualitas ekstraksi dari PDF dan (2) kemampuan model menemukan field yang tepat dan tidak mengarang. Karena itu desainnya:

1. **Parser berbasis label dan heading, bukan posisi.** DDR dan DGOS adalah formulir dengan label tetap (`Cumm NPT :`, `COUNTRY :`, `NEXT 24 HRS OPERATION`). Parser mencari label tersebut, sehingga PDF baru dengan format serupa tetapi isi dan panjang berbeda tetap terbaca. Teks bersih per halaman selalu disimpan sebagai cadangan.
2. **JSON sebagai sumber kebenaran, SQLite sebagai indeks.** JSON memenuhi syarat penyimpanan dan mudah diperiksa manusia. SQLite (nilai tambah) memberi query terstruktur dan pencarian full-text tanpa setup tambahan.
3. **Agen dengan tool, bukan RAG vektor sekali ambil.** LLM memanggil tool read-only (`list_reports`, `get_report_fields`, `get_planned_operations`, `search_reports`, `read_report_section`, `lookup_glossary`) sebanyak yang dibutuhkan, lalu menjawab dengan sitasi. Untuk pertanyaan seperti "berapa total NPT", model bisa mengambil field yang sama dari semua laporan sekaligus dan membandingkannya.
4. **Guardrail di kode, bukan hanya di prompt.** Output model dibatasi JSON schema (`status`, `answer`, `sources`). Pesan penolakan adalah teks tetap dari aplikasi sehingga konsisten. Jawaban yang tidak didahului pemanggilan tool otomatis dianggap di luar cakupan, sumber yang tidak ada di database dibuang, dan pertanyaan yang hanya menyebut *offset well* (sumur tanpa laporan, misalnya TAPIS-F) langsung dijawab "tidak ditemukan" tanpa memanggil LLM.

### Arsitektur

```
wellchat/
├── pdf_text.py         ekstraksi teks bersih (buang teks putih tersembunyi & karakter ganda)
├── parsers/
│   ├── ddr.py          Daily Operation Report: header, status, operation rows, NPT, warnings
│   ├── dgos.py         DGOS: header, blok operasi, NPT, remarks, tabel casing & formation tops
│   ├── glossary.py     tabel 2 kolom di .docx -> entri istilah
│   └── __init__.py     deteksi jenis dokumen + fallback UNKNOWN
├── ingest.py           CLI: raw -> JSON (inkremental, SHA-256) -> SQLite
├── store.py            skema SQLite + FTS5, rebuild atomik
├── tools.py            tool read-only untuk LLM, setiap hasil membawa file + halaman
├── agent.py            loop tool-calling OpenAI, structured output, guardrail
└── cli.py              chat di terminal
app.py                  UI Streamlit
eval/                   pertanyaan uji + skrip evaluasi
tests/                  unit test (parser, PDF sintetis, agen dengan LLM palsu)
```

### Alasan pemilihan teknologi

| Pilihan | Alasan | Alternatif yang tidak dipilih |
|---|---|---|
| **pdfplumber** | Akses ke properti tiap karakter (warna, posisi) dibutuhkan untuk membuang label putih tersembunyi; ringan, murni Python, tanpa unduhan model. | Docling/Marker: lebih kuat untuk layout acak, tetapi instalasinya berat (model ML lokal) dan menambah risiko gagal di mesin reviewer. PyPDF: tidak memberi info warna karakter. |
| **SQLite + FTS5** | Bawaan Python, tanpa server, mendukung query terstruktur dan BM25. | Vector DB / embedding: pertanyaan di sini berupa fakta literal (angka, kode seperti `PEX-QAIT`) yang lebih cocok dengan pencarian leksikal; embedding menambah biaya dan dependensi tanpa jelas menambah akurasi pada korpus sekecil ini. |
| **OpenAI Chat Completions + tool calling + JSON schema** | Key disediakan; tool calling memberi kontrol atas data apa yang dilihat model; structured output membuat penolakan dan sitasi bisa ditegakkan di kode. `OPENAI_BASE_URL` membuka opsi penyedia lain. | Framework orkestrasi (LangChain/LlamaIndex): menambah lapisan abstraksi untuk loop yang cukup ditulis dalam satu file kecil (`agent.py`). |
| **Streamlit** | UI chat lengkap dengan satu file Python dan satu perintah. | FastAPI + frontend terpisah: lebih fleksibel, tetapi dua proses dan lebih banyak langkah untuk reviewer. |

---

## 11. Resolution

### Kendala dan penyelesaian

1. **Teks PDF rusak karena label tersembunyi.** DGOS memuat label berwarna putih yang ditumpuk di atas nilai, sehingga ekstraksi biasa menghasilkan `Cu1r0r-e0n9t- 2D0a2t6e` (seharusnya `Current Date : 10-09-2026`) dan `NNNPPPTTT`. *Solusi:* filter karakter berdasarkan warna (`non_stroking_color` putih) dan ukuran, lalu `dedupe_chars` untuk teks "fake bold" yang digambar dua kali. Diuji di `test_dgos_hidden_white_labels_are_removed`.
2. **Satu baris berisi banyak pasangan label–nilai** (`DOL : 50.04 days MD : 2,423.11 m Rotating Hrs : ...`), kadang dengan nilai kosong. *Solusi:* pemisah berbasis daftar label yang dicocokkan dari label terpanjang, sehingga `Cum Rot Hrs` tidak terpotong menjadi `Rot Hrs`.
3. **Tabel DGOS terdeteksi sebagai satu grid besar satu halaman.** *Solusi:* tabel logis diambil sebagai rangkaian baris setelah sel heading (`HOLE SIZE`, `FORMATION TOPS`), kolom kosong di semua baris dibuang, lalu dipetakan ke nama kolom.
4. **Baris operasi DDR berlanjut lintas halaman** dan diikuti update 00:00–06:00 hari berikutnya dalam sel yang sama. *Solusi:* state machine per baris: baris berawalan rentang waktu memulai entri baru, baris lain disambung ke entri aktif, header/footer halaman dibuang, dan blok tanggal hari berikutnya disimpan terpisah di `next_day_operations`.
5. **Nilai berbeda antar laporan.** Laporan harian adalah potret per tanggal. Contohnya NPT: DDR #32 (19/07/2026) mencatat *Cumm NPT* 1.50 hr, DDR #53 (09/08/2026) mencatat 41.25 hr, dan DGOS #84 (10/09/2026) mencatat NPT harian 1.50 hr (redress Saturn packer) + 0.75 hr (WOW). Satu angka "total NPT" tanpa konteks akan menyesatkan. *Solusi:* tool `get_report_fields` mengembalikan field yang sama dari semua laporan, dan prompt mewajibkan jawaban menyebut nilai per laporan beserta tanggal dan laporan terbaru.
6. **Data sumber tidak konsisten.** Kedua DDR menulis *Spud date* `27/06/2027`, sesudah tanggal laporannya, sementara DGOS menulis `27-06-2026`. *Solusi:* nilai tidak dikoreksi diam-diam; parser menambahkan `warnings` yang diteruskan ke model dan ditampilkan di UI.
7. **Istilah glosarium yang belum pasti** (`BMP`, `COB`, `CSS`, entri bertanda *to be confirmed*). *Solusi:* flag `to_be_confirmed` di JSON; model diinstruksikan menyampaikannya sebagai belum pasti.
8. **Menjaga jawaban tetap di dalam dokumen.** *Solusi:* penolakan ditegakkan di kode (lihat Planning poin 4) dan diuji dengan LLM palsu di `tests/test_agent.py`.

### Hasil evaluasi

Jalankan `python -m eval.run_eval`; hasil terbaru tersimpan di `eval/results.md` (akurasi per pertanyaan dan waktu respons, batas 180 detik).

### Rencana perbaikan ke depan

- **Parser hybrid untuk layout yang lebih bervariasi:** fallback ke Docling atau model vision bila field wajib gagal ditemukan, dengan skor kepercayaan per field.
- **Normalisasi nilai:** simpan juga angka dan satuan terpisah (`41.25`, `hr`) supaya agregasi lintas laporan (misalnya total biaya per bulan) bisa dihitung dengan SQL, bukan oleh LLM.
- **Pencarian hybrid:** tambah embedding di samping BM25 untuk pertanyaan parafrase yang tidak memakai istilah laporan.
- **Evaluasi yang lebih besar:** perluas set pertanyaan dari laporan baru, ukur secara otomatis di CI, dan lacak regresi per perubahan prompt atau parser.
- **Multi-sumur:** filter per sumur di UI dan tool, bila dataset berisi lebih dari satu sumur.
- **Streaming jawaban** di UI untuk respons yang terasa lebih cepat.
