# Hasil Pengujian Lokal

Dokumen ini merangkum pengujian yang saya jalankan di mesin sendiri pada **9 Oktober 2026**, terhadap kode versi terakhir di repositori ini. Cara mengulanginya ada di [bagian terakhir](#cara-mengulangi).

## Ringkasan

| Pengujian | Hasil |
|---|---|
| Unit test (`python -m pytest -q`) | **28/28 lulus** dalam ±4 detik |
| Evaluasi end-to-end (`python -m eval.run_eval`) | **23/23 lulus** |
| Waktu respons paling lambat | **11,1 detik** (syarat soal: maksimal 180 detik) |
| Rata-rata / median waktu respons | 5,6 detik / 4,5 detik |
| Re-parse dataset setelah perubahan parser | Output JSON identik dengan sebelumnya (hanya `parsed_at` yang berbeda) |

## Lingkungan

| Komponen | Versi |
|---|---|
| OS | macOS 27.0.1 |
| Python | 3.14.6 |
| pdfplumber / python-docx | 0.11.10 / 1.2.0 |
| openai (SDK) | 3.26.1 |
| streamlit | 1.65.0 |
| pytest / reportlab | 9.1.1 / 5.0.1 |
| LLM | `deepseek-v4.1-flash` lewat endpoint yang kompatibel dengan OpenAI (`OPENAI_BASE_URL`) |

Untuk pengujian lokal, saya tidak memakai api.openai.com langsung, melainkan penyedia lain yang kompatibel dengan OpenAI API. Konfigurasinya cukup tiga variabel di `.env`: `OPENAI_API_KEY` (diisi key dari penyedia tersebut), `OPENAI_BASE_URL`, dan `OPENAI_MODEL`. Dengan key OpenAI biasa, cukup isi `OPENAI_API_KEY` saja, karena model default-nya `gpt-5.4-mini`.

Dataset yang dipakai: 2 DDR (#32 dan #53), 2 DGOS (#72 dan #84), dan `Glossaries.docx` (196 istilah).

## Unit test

Semua unit test berjalan tanpa API key. Bagian agen memakai LLM palsu yang jawabannya sudah diskenariokan.

| File | Jumlah | Yang diuji |
|---|---|---|
| `tests/test_agent.py` | 12 | Jawaban dengan sitasi, penolakan baku, jawaban tanpa tool ditolak, sumber halusinasi dibuang, pesan "tidak ditemukan", `reasoning_effort` hanya untuk model reasoning, pertanyaan *offset well* tanpa memanggil LLM, batas waktu jawaban |
| `tests/test_parsers.py` | 8 | Header dan lokasi DGOS, pembersihan label putih tersembunyi, rencana wireline, tabel DGOS, header dan NPT DDR, baris operasi DDR, glosarium, baris MD bulat/kosong dan laporan tanpa heading `BIT DATA` |
| `tests/test_synthetic.py` | 4 | PDF buatan dengan layout serupa tetapi nilai berbeda: semua file terparsing, field dan NPT DDR baru, DGOS baru bisa dicari, PDF dengan layout tak dikenal tetap bisa dicari |
| `tests/test_tools.py` | 4 | Rencana operasi dari semua laporan, daftar sumur, hasil tool yang terlalu panjang tetap JSON valid (baik teks panjang maupun list panjang) |

Test di `test_parsers.py` dan `test_tools.py` yang memakai dataset asli otomatis di-skip kalau `data/raw` kosong. Test sintetis dan test agen tetap berjalan tanpa dataset.

Untuk empat test yang saya tambahkan terakhir (batas waktu, JSON valid, MD bulat/kosong, laporan tanpa `BIT DATA`), saya juga memastikan test tersebut **gagal** di kode sebelum perbaikan dan **lulus** setelahnya. Dengan begitu, test-nya benar-benar menangkap masalah yang dimaksud.

## Evaluasi end-to-end

Evaluasi ini memakai LLM sungguhan dan dataset asli. Sebuah pertanyaan dianggap lulus kalau status jawabannya sesuai dan semua kata kunci wajibnya muncul di jawaban.

| Kategori | Jumlah | Lulus |
|---|---|---|
| Contoh pertanyaan dari soal | 3 | 3 |
| Pertanyaan faktual lain dari laporan | 11 | 11 |
| Glosarium | 3 | 3 |
| Di luar cakupan (harus ditolak) | 5 | 5 |
| *Offset well* tanpa laporan (harus "tidak ditemukan") | 1 | 1 |
| **Total** | **23** | **23** |

### Rincian per pertanyaan

| # | Pertanyaan | Status | Waktu (detik) |
|---|---|---|---|
| 1 | Dimana letak lokasi sumur? | answered | 9,4 |
| 2 | Berapa Total NPT sumur? | answered | 9,8 |
| 3 | Wireline run apa yang direncanakan? | answered | 9,4 |
| 4 | Apa arti NPT? | answered | 3,6 |
| 5 | What does BHA stand for? | answered | 2,9 |
| 6 | Apa nama rig yang digunakan? | answered | 3,4 |
| 7 | Siapa operator sumur ini? | answered | 8,6 |
| 8 | Berapa water depth sumur? | answered | 3,9 |
| 9 | Berapa kedalaman MD pada DDR nomor 53? | answered | 6,8 |
| 10 | Berapa daily cost pada laporan tanggal 19 Juli 2026? | answered | 6,1 |
| 11 | Apa penyebab NPT pada DGOS report 84? | answered | 7,8 |
| 12 | What was the mud weight in DGOS report 72? | answered | 3,8 |
| 13 | Kapan spud date sumur? | answered | 4,5 |
| 14 | What is the actual MD of formation top K-28? | answered | 4,9 |
| 15 | Apa arti BMP? | answered | 10,3 |
| 16 | Berapa jumlah personel di rig pada DDR 53? | answered | 7,1 |
| 17 | What is the objective of the well? | answered | 11,1 |
| 18 | Siapa presiden Indonesia saat ini? | out_of_scope | 2,3 |
| 19 | Buatkan kode Python untuk mengurutkan list. | out_of_scope | 4,0 |
| 20 | Berapa harga minyak Brent hari ini? | out_of_scope | 2,3 |
| 21 | What's the weather in Jakarta tomorrow? | out_of_scope | 2,0 |
| 22 | Halo, apa kabar? | out_of_scope | 4,2 |
| 23 | Berapa NPT sumur TAPIS-F? | not_found | 0,0 |

Pertanyaan #23 selesai dalam 0,0 detik karena guardrail *offset well* langsung menjawab "tidak ditemukan" tanpa memanggil LLM.

## Catatan dari beberapa kali run

Saya menjalankan evaluasi penuh beberapa kali selama pengembangan. Ada dua kejadian yang menurut saya perlu dicatat:

1. **Provider sempat lambat.** Di satu run, pertanyaan #1 butuh 124 detik dan jawabannya kurang lengkap. Setelah saya telusuri per panggilan API, setiap panggilan normalnya selesai sekitar 2 detik, jadi lambatnya berasal dari sisi provider. Batas waktu jawaban bekerja sesuai rencana: agen berhenti memanggil tool dan tetap menjawab di bawah 3 menit. Dengan kode sebelumnya, kondisi yang sama secara teori bisa makan waktu jauh lebih lama.
2. **Pertanyaan #14 sempat gagal.** Saat saya telusuri, model memanggil pencarian dengan `limit` 15, dan hasilnya melewati batas 14.000 karakter sehingga dipotong. Waktu itu pemotongannya membuat isi hasil sulit dibaca model. Setelah saya ubah menjadi pemangkasan per item (JSON tetap valid dan sitasi tetap utuh), #14 lulus di semua run berikutnya.

Hasil di atas berasal dari run terakhir setelah kedua perbaikan tersebut. Karena jawaban LLM tidak sepenuhnya deterministik, angka waktu dan isi jawaban bisa sedikit berbeda di setiap run.

## Cara mengulangi

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m wellchat.ingest     # parsing dataset di data/raw
python -m pytest -q           # unit test, tanpa API key
python -m eval.run_eval       # evaluasi end-to-end, butuh API key di .env
```

Hasil lengkap evaluasi, termasuk potongan jawaban dan sumber untuk setiap pertanyaan, ditulis ke `eval/results.md`. File tersebut tidak saya commit karena isinya berubah di setiap run.
