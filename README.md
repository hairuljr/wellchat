# Well Data Chat

Well Data Chat adalah aplikasi chat yang saya buat untuk menjawab pertanyaan **hanya** dari laporan sumur (PDF *Daily Operation Report* / DDR dan *Daily Geological Operations Summary* / DGOS) serta glosarium istilah Oil & Gas (`Glossaries.docx`). Kalau pertanyaannya di luar cakupan, aplikasi menolak dengan pesan baku. Setiap jawaban selalu menyertakan file sumber beserta halamannya.

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

- Python **3.10 atau lebih baru**. Pengujian terakhir saya jalankan di Python 3.14 (detailnya di [HASIL_PENGUJIAN.md](HASIL_PENGUJIAN.md)).
- API key OpenAI. Penyedia lain yang kompatibel dengan OpenAI API juga bisa dipakai, lihat [Konfigurasi](#3-konfigurasi).
- Tidak perlu Docker atau database server, karena SQLite sudah bawaan Python.

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
| `OPENAI_API_KEY` | (wajib) | API key OpenAI milik reviewer. |
| `OPENAI_MODEL` | `gpt-5.4-mini` | Model apa pun yang mendukung *tool calling* dan *structured output* (JSON schema). |
| `OPENAI_REASONING_EFFORT` | `none` | Hanya dikirim ke model *reasoning* (`gpt-5*`, `o*`). Untuk `gpt-5.4-mini`, Chat Completions menolak *tool calling* dengan effort selain `none`. Kosongkan kalau tidak ingin dikirim. |
| `OPENAI_BASE_URL` | (kosong) | Isi kalau ingin memakai endpoint lain yang kompatibel dengan OpenAI (Azure OpenAI, OpenRouter, vLLM/Ollama lokal). Dalam hal ini, `OPENAI_API_KEY` diisi dengan key dari penyedia tersebut. |
| `ANSWER_DEADLINE_S` | `150` | Batas waktu (detik) untuk satu jawaban, termasuk semua putaran *tool*. Putaran *tool* berhenti lebih awal supaya jawaban akhir tetap selesai dalam batas ini. |
| `FINAL_ROUND_RESERVE_S` | `30` | Waktu yang disisihkan khusus untuk jawaban akhir; tidak dipakai putaran *tool*. |
| `MAX_TOOL_RESULT_CHARS` | `14000` | Batas karakter satu hasil *tool* sebelum dipangkas. Hasil yang dipangkas tetap JSON valid: item list dibuang dari belakang, dan bila tetap kepanjangan teksnya dipotong lalu dibungkus. Naikkan bila model punya *context window* besar, turunkan bila permintaan terasa lambat. |
| `MODEL_ALLOWLIST` | (kosong) | Model lain yang boleh dipilih lewat dropdown di UI, dipisahkan koma. Kosong berarti tanpa dropdown; lihat [Memilih model di UI](#memilih-model-di-ui-opsional). |
| `DATA_DIR`, `RAW_DIR`, `PARSED_DIR`, `DB_PATH` | `./data`, `./data/raw`, `./data/parsed`, `./data/wellchat.db` | Lokasi data. |

API key tidak pernah masuk ke repositori karena `.env` sudah ada di `.gitignore`.

### Memakai penyedia LLM selain OpenAI

Aplikasi ini memanggil **Chat Completions API yang kompatibel dengan OpenAI**. Endpoint default adalah `api.openai.com`; bila Anda memakai penyedia lain, cukup isi `OPENAI_BASE_URL` dan `OPENAI_MODEL`, lalu isi `OPENAI_API_KEY` **dengan key milik penyedia tersebut** (bukan key OpenAI).

Contoh konfigurasi yang sudah teruji:

```bash
OPENAI_API_KEY=<key milik penyedia Anda>
OPENAI_BASE_URL=https://<host-penyedia>/v1
OPENAI_MODEL=<nama model di penyedia tersebut>
```

Yang dibutuhkan dari model/penyedia:

- Mendukung **tool calling** (function calling).
- Mendukung **structured output** ber-JSON schema (dipakai untuk menegakkan status jawaban dan sitasi). Schema hanya dikirim di panggilan jawaban akhir, jadi proxy yang menerapkan JSON schema dengan memaksa model langsung menjawab tetap bisa dipakai (lihat [Resolution poin 11](#kendala-dan-cara-saya-menyelesaikannya)).
- Kompatibel dengan pustaka `openai` Python (endpoint bergaya `/v1/chat/completions`).

Apa yang perlu disesuaikan bila penyedia berbeda:

| Situasi | Yang dilakukan |
|---|---|
| Model bukan model *reasoning* | `OPENAI_REASONING_EFFORT` diabaikan dan `temperature=0` dikirim. |
| Model *reasoning* (`gpt-5*`, `o*`) | Set `OPENAI_REASONING_EFFORT` sesuai yang didukung; beberapa model menolak *tool calling* bila effort tidak sesuai. |
| Endpoint atau payload error | Pesan aslinya ditampilkan di UI/CLI, bukan ditelan. |
| Respons terasa lambat | Turunkan `ANSWER_DEADLINE_S` atau `MAX_TOOL_RESULT_CHARS`. |
| Model membalas JSON dalam blok ```` ```json ```` atau teks biasa | Tetap terbaca: pembungkusnya dibuang, dan untuk teks biasa sumber diambil dari laporan yang disebut di jawaban. |

Catatan: evaluasi terakhir saya jalankan langsung di api.openai.com dengan `gpt-5.4-mini` (konfigurasi default) dan lulus 23/23. Selama pengembangan, aplikasi juga saya coba di endpoint OpenAI-compatible lain lewat `OPENAI_BASE_URL`; masalah yang hanya muncul di sebagian proxy sudah ditangani di kode (lihat [Resolution poin 10 dan 11](#kendala-dan-cara-saya-menyelesaikannya)).

### Memilih model di UI (opsional)

Secara default aplikasi hanya memakai `OPENAI_MODEL`, dan sidebar cukup menampilkan nama model tersebut. Kalau ingin membandingkan beberapa model atau berpindah ke endpoint lain yang kompatibel dengan OpenAI, isi `MODEL_ALLOWLIST` di `.env` (dipisahkan koma):

```bash
MODEL_ALLOWLIST=<model-1>,<model-2>
```

Setelah itu sidebar menampilkan dropdown **Model**. Isinya `OPENAI_MODEL` ditambah model di `MODEL_ALLOWLIST`, tetapi hanya yang benar-benar tersedia di endpoint (dicek lewat `GET /v1/models`, di-cache 10 menit). Daftar ini sengaja dibatasi karena endpoint bisa mengembalikan ratusan model, termasuk model embedding, gambar, atau audio yang tidak mendukung *tool calling* dan *structured output*.

- Pilihan model berlaku per sesi browser, jadi tidak mengubah model pengguna lain.
- Bila daftar gagal diambil atau tidak ada model allowlist yang tersedia di endpoint, UI kembali memakai `OPENAI_MODEL` dan menampilkan keterangannya.

## 4. Meletakkan dataset

Dataset dan hasil parsing sengaja **tidak** saya masukkan ke repositori. Salin folder `Datasets` dan file `Glossaries.docx` ke `data/raw/`:

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

Nama subfolder dan nama file bebas. Parser membaca semua `*.pdf` dan `*.docx` di bawah `data/raw/` secara rekursif, lalu mengenali jenis laporan dari isi halaman pertamanya, bukan dari nama file.

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

Di UI, setiap jawaban menampilkan waktu respons dan daftar sumber (nama file, halaman, bagian laporan), lengkap dengan tombol untuk mengunduh PDF aslinya.

## 6. Menambah PDF baru

Tidak ada kode yang perlu diubah:

1. Letakkan PDF baru (format DDR atau DGOS yang serupa) di mana saja di bawah `data/raw/`.
2. Jalankan `python -m wellchat.ingest`. Hanya file baru atau yang berubah yang diparsing ulang (dicek lewat SHA-256). Pakai `--force` untuk memparsing ulang semuanya.
3. Langsung bertanya lewat chat. Aplikasi membuka database baru di setiap pertanyaan, jadi tidak perlu restart.

Cara lain lewat UI: buka sidebar **Tambah PDF/DOCX baru**, lalu klik **Simpan & parse file baru**. File akan disimpan ke `data/raw/uploads/` dan langsung diindeks. Tombol **Parse ulang folder data** menjalankan ingest untuk file yang disalin manual.

PDF yang tidak dikenali sebagai DDR/DGOS tetap diparsing sebagai `UNKNOWN`. Teks per halamannya tetap diindeks sehingga masih bisa ditanyakan, hanya saja tanpa field terstruktur.

## 7. Struktur JSON hasil parsing

Setiap dokumen sumber menghasilkan satu file JSON. Field umum untuk semua laporan PDF:

| Field | Tipe | Keterangan |
|---|---|---|
| `schema_version` | string | Versi struktur, saat ini `"1.0"`. |
| `source` | object | `file_name`, `relative_path` (relatif ke `data/raw`), `sha256`, `page_count`. |
| `parsed_at` | string | Waktu parsing (ISO 8601, UTC). |
| `doc_type` | string | `DDR`, `DGOS`, `UNKNOWN`, atau `GLOSSARY`. |
| `well_name`, `report_no` | string \| null | Diambil dari header laporan. |
| `report_date` | string \| null | Tanggal laporan, format ISO `yyyy-mm-dd`. |
| `fields` | array | Field header `Label : value`: `{key, label, value, page}`. Nilai disimpan persis seperti di PDF, termasuk satuannya. |
| `sections` | array | Blok teks per bagian laporan: `{name, pages, text}`. |
| `warnings` | array of string | Masalah kualitas data yang terdeteksi saat parsing. |
| `pages` | array | Teks bersih per halaman `{page, text}`, sebagai cadangan kalau struktur gagal dikenali. |

Khusus **DDR**: `operations` (baris tabel *Operation Summary*), `next_day_operations` (update 00:00–06:00 hari berikutnya), dan `derived.npt_hours_from_operation_rows`.
Khusus **DGOS**: `npt` (baris NPT di blok *Last 24 hrs*), `progress` (phase/AFE/mud), `daily_remarks`, dan `tables` (Drilling Summary/Casing, Formation Tops).
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

`md_from_m` bernilai `null` kalau kolom MD di laporan kosong (`-`).

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

Database (`data/wellchat.db`) hanyalah indeks turunan. Setiap kali `ingest` dijalankan, database dibangun ulang dari `data/parsed/*.json`, lalu ditukar secara atomik supaya aplikasi yang sedang berjalan tidak pernah membaca database yang setengah jadi. File ini aman dihapus kapan saja.

| Tabel | Isi |
|---|---|
| `documents` | Satu baris per file: tipe, nomor dan tanggal laporan, warnings. |
| `fields` | Field header per laporan (`Cumm NPT`, `COUNTRY`, ...), ditambah nilai baris mud DGOS (`Mud Weight`, `Mud Type`, `Progress`, `Avg ROP`). |
| `sections` | Teks per bagian laporan. |
| `operations` | Baris *Operation Summary* DDR, termasuk flag NPT. |
| `report_tables` | Tabel DGOS (casing, formation tops) dalam bentuk JSON. |
| `glossary` | Entri glosarium. |
| `chunks` + `chunks_fts` | Potongan teks untuk pencarian full-text FTS5 (BM25). |

## 9. Pengujian dan evaluasi

```bash
pip install -r requirements-dev.txt

# Unit test parser, store, tool, dan guardrail agen (tanpa API key; LLM-nya dipalsukan)
python -m pytest -q

# Evaluasi end-to-end dengan LLM sungguhan (butuh API key dan data yang sudah di-ingest)
python -m eval.run_eval
```

Isi test suite:

- `tests/test_parsers.py`: memeriksa hasil parsing dataset asli (di-skip kalau `data/raw` kosong), ditambah kasus baris operasi DDR dengan MD bulat atau kosong dan laporan tanpa heading `BIT DATA`.
- `tests/test_synthetic.py`: membuat PDF baru dengan layout serupa tetapi nilai berbeda (nama sumur, tanggal, NPT), lalu memastikan semuanya terparsing dan bisa dicari. Test ini yang saya pakai sebagai bukti bahwa parser tidak terikat pada file contoh.
- `tests/test_agent.py`: memeriksa loop agen dan guardrail dengan LLM palsu: penolakan baku, jawaban tanpa tool dianggap di luar cakupan, "tidak ditemukan" tanpa mencari memicu riset ulang, sumber halusinasi dibuang, JSON dalam blok kode atau jawaban kosong, pertanyaan tentang *offset well*, schema yang hanya dikirim di panggilan akhir, serta batas waktu jawaban.
- `tests/test_models.py`: memeriksa dropdown model di UI Streamlit (lewat `streamlit.testing`): tanpa allowlist tidak ada dropdown, endpoint gagal atau tidak ada model yang cocok kembali ke `OPENAI_MODEL`, dan pilihan model tidak bocor ke sesi lain.
- `tests/test_tools.py`: memeriksa tool yang dipanggil LLM, misalnya rencana operasi dari semua laporan, daftar sumur, dan hasil tool yang terlalu panjang tetap berupa JSON valid.
- `eval/questions.json`: 23 pertanyaan uji (3 contoh dari soal, pertanyaan faktual lain, glosarium, dan di luar cakupan). `run_eval` mengukur akurasi dan waktu respons, lalu menulis hasilnya ke `eval/results.md`.

### Ringkasan hasil di mesin saya

| Pengujian | Hasil |
|---|---|
| Unit test (`pytest`) | **44/44 lulus** dalam ±6 detik |
| Evaluasi end-to-end (`eval.run_eval`) dengan `gpt-5.4-mini` di api.openai.com | **23/23 lulus** di tiga run terakhir berturut-turut, respons paling lambat **8,9 detik**, rata-rata 4,0 detik (batas 180 detik) |

Lingkungan pengujian, rincian per pertanyaan, dan catatan dari beberapa kali run ada di **[HASIL_PENGUJIAN.md](HASIL_PENGUJIAN.md)**.

---

## 10. Planning

### Pendekatan

Inti masalahnya adalah tanya jawab faktual atas sedikit dokumen semi-terstruktur: angka, tanggal, kode, dan nama yang tertulis apa adanya di laporan. Menurut saya akurasinya ditentukan oleh dua hal: (1) kualitas ekstraksi dari PDF, dan (2) kemampuan model menemukan field yang tepat tanpa mengarang. Karena itu desain saya seperti ini:

1. **Parser berbasis label dan heading, bukan posisi.** DDR dan DGOS adalah formulir dengan label tetap (`Cumm NPT :`, `COUNTRY :`, `NEXT 24 HRS OPERATION`). Parser mencari label tersebut, jadi PDF baru dengan format serupa tetapi isi dan panjang berbeda tetap terbaca. Teks bersih per halaman selalu ikut disimpan sebagai cadangan.
2. **JSON sebagai sumber kebenaran, SQLite sebagai indeks.** JSON memenuhi syarat penyimpanan dan mudah diperiksa manusia. SQLite (nilai tambah) memberi query terstruktur dan pencarian full-text tanpa setup tambahan.
3. **Agen dengan tool, bukan RAG vektor yang mengambil konteks sekali saja.** LLM memanggil tool read-only (`list_reports`, `get_report_fields`, `get_planned_operations`, `search_reports`, `read_report_section`, `lookup_glossary`) sebanyak yang dibutuhkan, lalu menjawab dengan sitasi. Untuk pertanyaan seperti "berapa total NPT", model bisa mengambil field yang sama dari semua laporan sekaligus lalu membandingkannya.
4. **Guardrail di kode, bukan hanya di prompt.** Jawaban akhir dibatasi JSON schema (`status`, `answer`, `sources`). Pesan penolakan berupa teks tetap dari aplikasi, sehingga selalu konsisten. Jawaban yang tidak didahului pemanggilan tool otomatis dianggap di luar cakupan, "tidak ditemukan" baru diterima setelah model benar-benar mencari, sumber yang tidak ada di database dibuang, dan pertanyaan yang hanya menyebut *offset well* (sumur tanpa laporan, misalnya TAPIS-F) langsung dijawab "tidak ditemukan" tanpa memanggil LLM. Semua prompt dan pesan baku dikumpulkan di `prompts.py`, terpisah dari logika agen.
5. **Batas waktu ditegakkan di kode.** Satu jawaban dibatasi 150 detik, jauh di bawah syarat 3 menit. Kalau waktunya hampir habis, agen berhenti memanggil tool dan langsung menyusun jawaban dari data yang sudah didapat.

### Arsitektur

```
wellchat/
├── pdf_text.py         ekstraksi teks bersih (buang teks putih tersembunyi & karakter ganda)
├── parsers/
│   ├── ddr.py          Daily Operation Report: header, status, baris operasi, NPT, warnings
│   ├── dgos.py         DGOS: header, blok operasi, NPT, remarks, tabel casing & formation tops
│   ├── glossary.py     tabel 2 kolom di .docx -> entri istilah
│   └── __init__.py     deteksi jenis dokumen + fallback UNKNOWN
├── ingest.py           CLI: raw -> JSON (inkremental, SHA-256) -> SQLite
├── store.py            skema SQLite + FTS5, rebuild atomik
├── tools.py            tool read-only untuk LLM, setiap hasil membawa file + halaman
├── models.py           pilihan model untuk dropdown UI (allowlist ∩ GET /v1/models)
├── prompts.py          system prompt, JSON schema jawaban, pesan penolakan & "tidak ditemukan"
├── agent.py            loop dua fase (riset dengan tool, lalu jawaban JSON), guardrail, batas waktu
└── cli.py              chat di terminal
app.py                  UI Streamlit
eval/                   pertanyaan uji + skrip evaluasi
tests/                  unit test (parser, PDF sintetis, agen dengan LLM palsu)
```

### Alasan pemilihan teknologi

| Pilihan | Alasan | Alternatif yang tidak saya pilih |
|---|---|---|
| **pdfplumber** | Saya butuh akses ke properti tiap karakter (warna, posisi) untuk membuang label putih tersembunyi. Library-nya ringan, murni Python, dan tidak perlu mengunduh model. | Docling/Marker: lebih kuat untuk layout acak, tetapi instalasinya berat (model ML lokal) dan menambah risiko gagal di mesin reviewer. PyPDF: tidak memberi informasi warna karakter. |
| **SQLite + FTS5** | Bawaan Python, tanpa server, dan sudah mendukung query terstruktur serta BM25. | Vector DB / embedding: pertanyaan di sini berupa fakta literal (angka, kode seperti `PEX-QAIT`) yang lebih cocok dengan pencarian leksikal. Embedding menambah biaya dan dependensi tanpa jaminan akurasinya naik untuk korpus sekecil ini. |
| **OpenAI Chat Completions + tool calling + JSON schema** | Key-nya disediakan. Tool calling memberi saya kontrol atas data apa saja yang dilihat model, dan structured output membuat penolakan serta sitasi bisa ditegakkan di kode. `OPENAI_BASE_URL` membuka opsi penyedia lain. | Framework orkestrasi (LangChain/LlamaIndex): menambah lapisan abstraksi untuk loop yang cukup ditulis dalam satu file kecil (`agent.py`). |
| **Streamlit** | UI chat lengkap cukup dengan satu file Python dan satu perintah. | FastAPI + frontend terpisah: lebih fleksibel, tetapi butuh dua proses dan lebih banyak langkah untuk reviewer. |

---

## 11. Resolution

### Kendala dan cara saya menyelesaikannya

1. **Teks PDF rusak karena label tersembunyi.** DGOS memuat label berwarna putih yang ditumpuk di atas nilai, sehingga ekstraksi biasa menghasilkan `Cu1r0r-e0n9t- 2D0a2t6e` (seharusnya `Current Date : 10-09-2026`) dan `NNNPPPTTT`. *Solusi:* saya menyaring karakter berdasarkan warna (`non_stroking_color` putih) dan ukuran, lalu memakai `dedupe_chars` untuk teks "fake bold" yang digambar dua kali. Kasus ini diuji di `test_dgos_hidden_white_labels_are_removed`.
2. **Satu baris berisi banyak pasangan label–nilai** (`DOL : 50.04 days MD : 2,423.11 m Rotating Hrs : ...`), kadang dengan nilai kosong. *Solusi:* pemisah berbasis daftar label yang dicocokkan mulai dari label terpanjang, supaya `Cum Rot Hrs` tidak terpotong menjadi `Rot Hrs`.
3. **Tabel DGOS terdeteksi sebagai satu grid besar selebar halaman.** *Solusi:* tabel logis saya ambil sebagai rangkaian baris setelah sel heading (`HOLE SIZE`, `FORMATION TOPS`). Kolom yang kosong di semua baris dibuang, lalu sisanya dipetakan ke nama kolom.
4. **Baris operasi DDR berlanjut lintas halaman**, dan di sel yang sama diikuti update 00:00–06:00 hari berikutnya. *Solusi:* state machine per baris. Baris yang diawali rentang waktu memulai entri baru, baris lain disambung ke entri yang sedang aktif, header/footer halaman dibuang, dan blok tanggal hari berikutnya disimpan terpisah di `next_day_operations`. Tabel dianggap selesai di heading berikutnya mana pun, dan kolom MD boleh bulat atau kosong, supaya PDF dengan variasi kecil tidak kehilangan baris diam-diam.
5. **Nilai berbeda antar laporan.** Laporan harian adalah potret per tanggal. Contohnya NPT: DDR #32 (19/07/2026) mencatat *Cumm NPT* 1.50 hr, DDR #53 (09/08/2026) mencatat 41.25 hr, dan DGOS #84 (10/09/2026) mencatat NPT harian 1.50 hr (redress Saturn packer) + 0.75 hr (WOW). Satu angka "total NPT" tanpa konteks akan menyesatkan. *Solusi:* tool `get_report_fields` mengembalikan field yang sama dari semua laporan, dan prompt mewajibkan jawaban menyebut nilai per laporan beserta tanggalnya, lalu menunjukkan laporan yang terbaru.
6. **Data sumber tidak konsisten.** Kedua DDR menulis *Spud date* `27/06/2027`, sesudah tanggal laporannya sendiri, sementara DGOS menulis `27-06-2026`. Saya sudah mengecek posisi teks di PDF: nilai itu memang berada tepat di bawah label *Spud date* (kolom *End date* kosong), jadi ini bukan kesalahan pemetaan kolom. *Solusi:* nilainya tidak saya koreksi diam-diam. Parser menambahkan `warnings` yang diteruskan ke model dan ditampilkan di UI.
7. **Istilah glosarium yang belum pasti** (`BMP`, `COB`, `CSS`, entri bertanda *to be confirmed*). *Solusi:* flag `to_be_confirmed` di JSON, dan model diinstruksikan menyampaikannya sebagai informasi yang belum pasti.
8. **Menjaga jawaban tetap di dalam dokumen.** *Solusi:* penolakan ditegakkan di kode (lihat Planning poin 4) dan diuji dengan LLM palsu di `tests/test_agent.py`.
9. **Hasil tool yang terlalu panjang.** Pencarian dengan `limit` besar bisa melewati batas 14.000 karakter. Versi awal memotong string JSON mentah sehingga hasilnya rusak. *Solusi:* hasil yang kepanjangan dipangkas per item (item terakhir dibuang dulu), jadi model tetap menerima JSON yang valid dan sitasi item yang tersisa tetap utuh.
10. **Waktu respons harus terjamin, bukan kebetulan cepat.** Sebelumnya jumlah putaran tool dibatasi, tetapi waktunya tidak, sehingga kalau API lambat, satu jawaban secara teori bisa makan belasan menit. *Solusi:* batas waktu 150 detik per jawaban, 30 detik di antaranya disisihkan untuk jawaban akhir, dan timeout per request ikut menghitung retry SDK. Belakangan saya menemukan bahwa timeout SDK dihitung per jeda baca data, sehingga provider yang terus mengirim keep-alive bisa menahan satu request sampai 10 menit. Karena itu setiap panggilan model sekarang juga dibatasi waktu dinding (wall-clock) di thread terpisah: kalau fase riset kehabisan waktu, agen langsung menyusun jawaban dari data yang sudah ada, dan kalau fase jawaban yang kehabisan waktu, pengguna mendapat pesan error yang jelas.
11. **Sebagian proxy tidak pernah memanggil tool.** Saat saya mencoba dua model lain lewat proxy OpenAI-compatible, keduanya sering langsung menjawab "tidak ditemukan" tanpa satu pun tool call. Setelah saya uji request yang sama dengan dan tanpa `response_format`, ternyata proxy yang saya pakai menerapkan JSON schema dengan memaksa model langsung mengeluarkan jawaban akhir, sehingga tool tidak pernah sempat dipanggil. *Solusi:* jawaban dibagi dua fase. Fase riset memanggil tool tanpa `response_format`, dan model cukup membalas `READY` bila datanya sudah lengkap (supaya jawaban tidak ditulis dua kali). Setelah itu ada satu panggilan jawaban dengan `response_format` dan `tool_choice="none"`. Model yang tetap menjawab "tidak ditemukan" tanpa mencari diwajibkan memanggil tool sekali lagi, JSON dalam blok kode tetap dibaca, dan jawaban kosong diperlakukan sebagai "tidak ditemukan".
12. **Data yang ada di PDF tapi tidak terjangkau model.** Evaluasi dengan `gpt-5.4-mini` menemukan dua kasus. Pertama, nilai `OPERATOR` di DGOS tersimpan kosong: pembersih judul halaman (`PTT PUBLIC COMPANY LIMITED` yang menempel di ujung baris) ikut menghapus nilai yang isinya persis judul itu, sehingga model menjawab dari `OPERATORSHIP` (COB). Kedua, mud weight DGOS hanya ada di teks, bukan sebagai field. *Solusi:* judul hanya dibuang bila menempel di belakang teks lain, nilai baris mud DGOS (mud weight, mud type, progress, ROP) didaftarkan sebagai field, dan prompt meminta model memakai `get_report_fields` lebih dulu untuk nilai header (teks bebas sering memuat angka lain dengan nama mirip, misalnya kedalaman wireline `2426.7m-WLD` yang bukan MD laporan).
13. **`OPENAI_BASE_URL=` tanpa nilai membuat semua request gagal.** SDK OpenAI membaca variabel itu sendiri dari environment dan memakai string kosong sebagai URL ("Connection error"). *Solusi:* base URL selalu dikirim eksplisit ke SDK, dengan default `https://api.openai.com/v1`.

### Hasil evaluasi

Di mesin saya, dengan `gpt-5.4-mini` langsung di api.openai.com, tiga run evaluasi terakhir berturut-turut lulus **23/23**, dengan respons paling lambat **8,9 detik** (batas 180 detik). Rinciannya ada di [HASIL_PENGUJIAN.md](HASIL_PENGUJIAN.md). Untuk mengulanginya, jalankan `python -m eval.run_eval`; hasil terbaru akan ditulis ke `eval/results.md`.

### Rencana perbaikan ke depan

- **Parser hybrid untuk layout yang lebih bervariasi:** fallback ke Docling atau model vision kalau field wajib gagal ditemukan, dengan skor kepercayaan per field.
- **Normalisasi nilai:** simpan juga angka dan satuan secara terpisah (`41.25`, `hr`), supaya agregasi lintas laporan (misalnya total biaya per bulan) bisa dihitung dengan SQL, bukan oleh LLM.
- **Pencarian hybrid:** tambahkan embedding di samping BM25 untuk pertanyaan parafrase yang tidak memakai istilah laporan.
- **Evaluasi yang lebih besar:** perluas set pertanyaan dari laporan baru, jalankan otomatis di CI, dan pantau regresi setiap kali prompt atau parser berubah.
- **Multi-sumur:** filter per sumur di UI dan di tool, kalau dataset berisi lebih dari satu sumur.
- **Streaming jawaban** di UI supaya respons terasa lebih cepat.
