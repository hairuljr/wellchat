# Hasil Pengujian Lokal

Dokumen ini merangkum pengujian yang saya jalankan di mesin sendiri pada **9 Oktober 2026**, terhadap kode versi terakhir di repositori ini. Evaluasi end-to-end memakai konfigurasi default yang sama dengan yang akan dipakai reviewer: **`gpt-5.4-mini` langsung di api.openai.com**. Cara mengulanginya ada di [bagian terakhir](#cara-mengulangi).

## Ringkasan

| Pengujian | Hasil |
|---|---|
| Unit test (`python -m pytest -q`) | **53/53 lulus** dalam ±6 detik |
| Evaluasi end-to-end (`python -m eval.run_eval`) | **23/23 lulus** di empat run terakhir berturut-turut, termasuk run final dengan pengecekan `must_not` |
| Waktu respons paling lambat | **10,1 detik** di run final (syarat soal: maksimal 180 detik) |
| Rata-rata / median waktu respons | 4,6 detik / 4,5 detik (run final) |
| Re-parse dataset setelah perbaikan parser | Hanya field `OPERATOR` di kedua DGOS yang berubah (dari kosong menjadi `PTT PUBLIC COMPANY LIMITED`); semua nilai lain identik |

## Lingkungan

| Komponen | Versi |
|---|---|
| OS | macOS 27.0.1 |
| Python | 3.14.6 |
| pdfplumber / python-docx | 0.11.10 / 1.2.0 |
| openai (SDK) | 3.26.1 |
| streamlit | 1.65.0 |
| pytest / reportlab | 9.1.1 / 5.0.1 |
| LLM | `gpt-5.4-mini` di api.openai.com, `OPENAI_REASONING_EFFORT=none`, `OPENAI_BASE_URL` kosong |

`OPENAI_REASONING_EFFORT` harus `none` untuk `gpt-5.4-mini`. Saya sudah mengeceknya: dengan `low` atau `medium`, API menolak request yang membawa tool (`Function tools with reasoning_effort are not supported for gpt-5.4-mini`).

Dataset yang dipakai: 2 DDR (#32 dan #53), 2 DGOS (#72 dan #84), dan `Glossaries.docx` (196 istilah). Evaluasi saya jalankan di folder data terpisah yang hanya berisi dataset asli, supaya PDF lain yang sempat saya unggah untuk mencoba fitur upload tidak ikut memengaruhi hasil.

## Unit test

Semua unit test berjalan tanpa API key. Bagian agen memakai LLM palsu yang jawabannya sudah diskenariokan, dan bagian UI memakai `streamlit.testing`.

| File | Jumlah | Yang diuji |
|---|---|---|
| `tests/test_agent.py` | 25 | Jawaban dengan sitasi, penolakan baku, jawaban tanpa tool ditolak, "tidak ditemukan" tanpa mencari memicu riset ulang, sumber halusinasi dibuang, JSON schema hanya dikirim di panggilan akhir, JSON dalam blok kode, JSON dengan baris baru di dalam string, jawaban kosong atau `READY`, endpoint yang tidak mendukung `tool_choice="required"`, jawaban teks biasa hanya mengutip laporan yang disebut, `reasoning_effort` hanya untuk model reasoning kecuali dipilih eksplisit, *offset well*, batas waktu jawaban, request yang macet dihentikan sesuai batas waktu dinding, `OPENAI_BASE_URL` kosong tetap ke api.openai.com |
| `tests/test_models.py` | 7 | Dropdown model: urutan pilihan, entri `model@effort` dan labelnya, model dan effort pilihan diteruskan ke agen, tanpa allowlist tidak ada dropdown, endpoint gagal atau tidak ada model yang cocok kembali ke `OPENAI_MODEL`, pilihan model tidak bocor ke sesi lain |
| `tests/test_parsers.py` | 8 | Header dan lokasi DGOS (termasuk `OPERATOR`), pembersihan label putih tersembunyi, rencana wireline, tabel DGOS, header dan NPT DDR, baris operasi DDR, glosarium, baris MD bulat/kosong dan laporan tanpa heading `BIT DATA` |
| `tests/test_synthetic.py` | 4 | PDF buatan dengan layout serupa tetapi nilai berbeda: semua file terparsing, field dan NPT DDR baru, DGOS baru (termasuk `OPERATOR` dan `AFE No.`) bisa dicari, PDF dengan layout tak dikenal tetap bisa dicari |
| `tests/test_tools.py` | 9 | Rencana operasi dari semua laporan, rencana yang disaring per topik (`wireline`, `WL`, `wireline run` hanya mengembalikan DDR #53 dan DGOS #72; topik tanpa kecocokan tetap mengembalikan semua rencana), daftar sumur, hasil tool yang terlalu panjang tetap JSON valid (teks panjang maupun list panjang), mud weight DGOS bisa diambil sebagai field |

Test di `test_parsers.py`, `test_tools.py`, dan hampir semua test di `test_agent.py` memakai dataset asli, dan otomatis di-skip kalau `data/raw` kosong.

Untuk test yang menutup bug, saya memastikan test tersebut **gagal** di kode sebelum perbaikan dan **lulus** setelahnya, supaya test-nya benar-benar menangkap masalah yang dimaksud.

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

### Rincian per pertanyaan (run final)

| # | Pertanyaan | Status | Waktu (detik) |
|---|---|---|---|
| 1 | Dimana letak lokasi sumur? | answered | 10,1 |
| 2 | Berapa Total NPT sumur? | answered | 6,4 |
| 3 | Wireline run apa yang direncanakan? | answered | 5,0 |
| 4 | Apa arti NPT? | answered | 3,8 |
| 5 | What does BHA stand for? | answered | 3,2 |
| 6 | Apa nama rig yang digunakan? | answered | 4,5 |
| 7 | Siapa operator sumur ini? | answered | 3,9 |
| 8 | Berapa water depth sumur? | answered | 4,6 |
| 9 | Berapa kedalaman MD pada DDR nomor 53? | answered | 4,5 |
| 10 | Berapa daily cost pada laporan tanggal 19 Juli 2026? | answered | 5,2 |
| 11 | Apa penyebab NPT pada DGOS report 84? | answered | 5,7 |
| 12 | What was the mud weight in DGOS report 72? | answered | 4,5 |
| 13 | Kapan spud date sumur? | answered | 7,0 |
| 14 | What is the actual MD of formation top K-28? | answered | 4,9 |
| 15 | Apa arti BMP? | answered | 3,1 |
| 16 | Berapa jumlah personel di rig pada DDR 53? | answered | 4,6 |
| 17 | What is the objective of the well? | answered | 8,2 |
| 18 | Siapa presiden Indonesia saat ini? | out_of_scope | 2,5 |
| 19 | Buatkan kode Python untuk mengurutkan list. | out_of_scope | 2,1 |
| 20 | Berapa harga minyak Brent hari ini? | out_of_scope | 3,7 |
| 21 | What's the weather in Jakarta tomorrow? | out_of_scope | 4,4 |
| 22 | Halo, apa kabar? | out_of_scope | 4,1 |
| 23 | Berapa NPT sumur TAPIS-F? | not_found | 0,0 |

Pertanyaan #23 selesai dalam 0,0 detik karena guardrail *offset well* langsung menjawab "tidak ditemukan" tanpa memanggil LLM.

## Catatan dari beberapa kali run

Saya menjalankan evaluasi penuh tujuh kali dengan `gpt-5.4-mini`. Empat run pertama masing-masing gagal di dua pertanyaan, dan setiap kegagalan saya telusuri sampai ke tool call-nya:

| Run | Hasil | Pertanyaan yang gagal | Penyebab dan perbaikan |
|---|---|---|---|
| 1 | 21/23 | #7 operator, #16 personel | #7: bug parser. Nilai `OPERATOR` di DGOS tersimpan kosong karena pembersih judul halaman ikut menghapus nilai yang isinya persis "PTT PUBLIC COMPANY LIMITED". Model lalu menjawab dari field `OPERATORSHIP` (COB). #16: model berhenti setelah melihat daftar nama section tanpa membuka section personel. |
| 2 | 21/23 | #9 MD, #12 mud weight | #7 dan #16 sudah lulus setelah parser diperbaiki dan prompt menambahkan aturan "buka section yang relevan sebelum menyimpulkan data tidak ada". #12: mud weight DGOS hanya ada di teks, belum menjadi field, jadi tidak bisa diambil lewat `get_report_fields`. |
| 3–4 | 21/23, 23/23 | #9, #12 (run 3) | Setelah mud weight, mud type, progress, dan ROP DGOS didaftarkan sebagai field. Kegagalan yang tersisa: model memilih angka dari teks bebas (#9 mengutip kedalaman wireline `2426.7m-WLD`, bukan MD header `2,423.11 m`). |
| 5–7 | 23/23, 23/23, 23/23 | – | Setelah prompt menambahkan aturan "untuk nilai header laporan, pakai `get_report_fields` lebih dulu". |

Karena jawaban LLM tidak sepenuhnya deterministik, angka waktu dan isi jawaban bisa sedikit berbeda di setiap run. Tiga run terakhir berturut-turut lulus 23/23 dengan respons paling lambat 8,9 detik.

## Pemeriksaan jawaban mentah: pertanyaan wireline

Setelah tiga run 23/23 di atas, saya memeriksa jawaban utuh untuk "Wireline run apa yang direncanakan?". Kata kunci wajibnya selalu ada, tetapi di salah satu run jawabannya ikut memuat rencana pengeboran DDR #32 dan mengutip DDR #32 serta DGOS #84, padahal keduanya tidak menyebut wireline. Eval menghitungnya lulus karena hanya memeriksa kata kunci wajib.

| Perubahan | Percobaan pertanyaan wireline | Hasil (hanya DDR #53 dan DGOS #72, tanpa rencana lain) |
|---|---|---|
| Aturan tambahan di prompt | 3 kali | 2/3 |
| Aturan prompt dipisah dan dinyatakan mengalahkan aturan "satu baris per laporan" | 5 kali | 3/5 |
| `get_planned_operations(topic=...)` menyaring di kode, dengan padanan singkatan dari glosarium | 5 kali | **5/5** |

Pertanyaan rencana tanpa topik ("Apa rencana operasi berikutnya?") tetap menampilkan rencana dari keempat laporan. Pengecekan `must_not` dan `sources_must_not` yang baru di eval menghitung run bermasalah tadi sebagai gagal (saya cek ulang secara offline terhadap jawaban yang tersimpan).

Setelah perubahan ini saya menjalankan evaluasi penuh sekali lagi, kini dengan pengecekan `must_not` yang lebih ketat: **23/23 lulus**, respons paling lambat 10,1 detik, rata-rata 4,6 detik. Untuk pertanyaan wireline, model memanggil `get_planned_operations(topic="wireline")` dan hanya menyebut serta mengutip DDR #53 dan DGOS #72.

## Mencoba model dan endpoint lain

Aplikasi juga bisa diarahkan ke endpoint lain yang kompatibel dengan OpenAI (`OPENAI_BASE_URL`), dan model bisa dipilih lewat dropdown di UI bila `MODEL_ALLOWLIST` diisi. Yang sudah saya cek:

- **Model OpenAI lain.** Dengan satu pertanyaan glosarium lewat agen lengkap, `gpt-6-luna`, `gpt-5.4-nano`, `gpt-5.6-luna`, dan `gpt-4.1-mini` menjawab benar dalam 3–8 detik. `gpt-4.1-nano` dan `gpt-4o-mini` juga benar, tetapi menjawab dalam bahasa Inggris untuk pertanyaan berbahasa Indonesia. `gpt-5-nano` menolak `reasoning_effort=none`, jadi perlu effort lain.
- **Model dengan reasoning effort.** Saya mengecek model murah mana yang menerima tool calling bersama effort selain `none`: hanya `gpt-5-nano` dan `gpt-5-mini` (keduanya justru menolak `none`), sementara `gpt-5.4-*`, `gpt-6-luna`, dan `gpt-5.6-luna` hanya menerima `none`. Karena itu entri allowlist bisa membawa effort sendiri (`gpt-5-nano@low`). Satu pertanyaan wireline dengan `gpt-5-nano@low` lulus penilaian eval dalam 20,6 detik; effort `low` terkirim di setiap panggilan.
- **Endpoint OpenAI-compatible lain.** Saya menemukan dua masalah yang hanya muncul di sebagian proxy, dan keduanya sudah diperbaiki di kode (lihat README bagian Resolution poin 10 dan 11):
  - proxy yang menerapkan JSON schema dengan memaksa model langsung menjawab, sehingga tool tidak pernah dipanggil;
  - proxy yang terus mengirim keep-alive sehingga satu request bisa bertahan sampai 10 menit.
- Daftar model dari `GET /v1/models` dan dropdown di UI sudah saya cek ke endpoint sungguhan. Evaluasi penuh 23 pertanyaan di endpoint selain OpenAI belum saya ulang, karena kuota harian model gratis yang saya pakai sudah habis.

## Cara mengulangi

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m wellchat.ingest     # parsing dataset di data/raw
python -m pytest -q           # unit test, tanpa API key
python -m eval.run_eval       # evaluasi end-to-end, butuh API key di .env
```

Pastikan `data/raw` hanya berisi dataset asli sebelum menjalankan evaluasi, karena laporan tambahan bisa mengubah jawaban yang diharapkan (misalnya "Total NPT"). Hasil lengkap evaluasi, termasuk potongan jawaban dan sumber untuk setiap pertanyaan, ditulis ke `eval/results.md`. File tersebut tidak saya commit karena isinya berubah di setiap run.
