# 🔴 YouTube Live Streaming 1080p 24/7 Looping

Skrip otomatis untuk live streaming YouTube 24/7 di **Linux / Android (Termux)** dengan fitur:
- 🔁 **Video Looping 1080p Full HD** (30 FPS, aspect ratio aman dengan auto-letterbox/pillarbox).
- 🎵 **Playlist Musik Looping** (Mendukung MP3, M4A, WAV, FLAC, AAC, OGG). Lagu berganti mulus tanpa jeda/putus.
- 🔀 **Fitur Shuffle Playlist** (Acak urutan lagu setiap putaran musik selesai).
- 📺 **Indikator Realtime** (Menampilkan judul lagu yang sedang aktif `[NOW PLAYING]` di terminal).
- ⚡ **Auto-Reconnect** (Otomatis menyambung ulang jika jaringan internet sempat terputus).
- 🔋 **Optimasi Termux & Baterai** (Mendukung `termux-wake-lock` agar streaming tetap aktif meski layar HP mati).

---

## 📁 Struktur Folder

```text
~/live/
├── config.py           # Aplikasi Python antarmuka konfigurasi (CLI & Web UI)
├── stream.sh           # Skrip utama untuk menjalankan siaran live streaming
├── config.env          # File konfigurasi (Stream Key, Volume, Mode Musik, dll)
├── playlist.txt        # File urutan playlist lagu kustom
├── sample_media.sh     # Skrip pembuat video demo & musik demo untuk uji coba
├── video/              # Letakkan file video background Anda di sini (misal: background.mp4)
├── music/              # Letakkan kumpulan lagu Anda di sini (.mp3, .m4a, dll)
└── README.md           # Panduan lengkap penggunaan
```

---

## 🚀 Cara Penggunaan Cepat

### 1. Masukkan Video dan Lagu Anda

- **Salin Video Anda:** Letakkan file video background (MP4/MKV) ke dalam folder `video/`.
  ```bash
  cp /sdcard/Download/video.mp4 video/
  ```
- **Salin Lagu Anda:** Letakkan file-file audio ke dalam folder `music/`.
  ```bash
  cp /sdcard/Music/*.mp3 music/
  ```

> 💡 **Tip Uji Coba Cepat:** Jika belum menyiapkan video/lagu, Anda bisa menjalankan `./sample_media.sh` untuk membuat video dan musik demo otomatis.

---

### 2. Atur Konfigurasi Menggunakan Aplikasi Python

Gunakan aplikasi Python interaktif untuk mengatur letak video, letak musik, volume video & musik, urutan lagu, dan Stream Key YouTube:

```bash
python3 config.py
```
*(Atau `./config_app.py`)*

#### Mode yang Tersedia:
- **Mode Terminal Interaktif (CLI):**
  Jalankan `python3 config.py` untuk menu nomor yang rapi dan mudah di navigasi langsung di terminal Termux.
- **Mode Web Dashboard (Mobile Friendly UI):**
  Jalankan:
  ```bash
  python3 config.py --web
  ```
  Lalu buka browser HP ke **`http://localhost:5000`** untuk tampilan kontrol visual dengan slider volume, drag-and-drop urutan lagu, tombol tes, dan pemantau siaran langsung!

*(Atau Anda juga tetap bisa mengedit file `config.env` secara manual menggunakan `nano config.env`).*

---

### 3. Uji Coba Lokal (Rekomendasi Sebelum Live)

Jalankan perintah ini untuk melakukan simulasi encode selama 15 detik tanpa mengirim data ke YouTube:
```bash
./stream.sh --test
```
Skrip akan memvalidasi apakah video looping dan playlist musik berjalan normal.

---

### 4. Mulai Live Streaming ke YouTube

Cukup jalankan:
```bash
./stream.sh
```

---

## 🌙 Menjalankan 24/7 di Background (Layar HP Mati)

Agar live streaming tetap berjalan nonstop saat aplikasi Termux diminimalkan atau layar HP dimatikan:

### Opsi 1: Menggunakan `tmux` (Sangat Disarankan)

1. Pasang `tmux`:
   ```bash
   pkg install tmux -y
   ```
2. Buat sesi baru:
   ```bash
   tmux new -s ytlive
   ```
3. Di dalam sesi tmux, jalankan skrip:
   ```bash
   ./stream.sh
   ```
4. **Keluar dari sesi tmux tanpa mematikan live:**
   Tekan kombinasi tombol: `Ctrl + B`, lalu lepaskan dan tekan tombol `D` (*Detach*).
5. Layar HP sekarang aman untuk dimatikan.
6. Untuk membuka kembali sesi live streaming:
   ```bash
   tmux attach -t ytlive
   ```

### Opsi 2: Menggunakan `nohup`

```bash
nohup ./stream.sh > live.log 2>&1 &
```
Untuk memantau log siaran:
```bash
tail -f live.log
```

---

## ⚙️ Pengaturan di `config.env`

| Parameter | Default | Keterangan |
| :--- | :--- | :--- |
| `STREAM_KEY` | `""` | Kunci streaming rahasia dari YouTube Studio |
| `RTMP_URL` | `rtmp://a.rtmp.youtube.com/live2` | Server RTMP YouTube / Facebook / Twitch |
| `VIDEO_FILE` | `""` | Lokasi file video (kosongkan untuk otomatis deteksi di folder `video/`) |
| `VIDEO_VOLUME` | `0.0` | Volume audio video (`0.0` = mute, `1.0` = 100%, `0.5` = 50% di-mix dengan musik) |
| `MUSIC_DIR` | `music` | Folder berisi lagu-lagu siaran |
| `MUSIC_VOLUME` | `1.0` | Volume playlist musik (`1.0` = 100%, `0.5` = 50%) |
| `PLAYLIST_MODE` | `shuffle` | Mode urutan musik (`shuffle`, `alphabetical`, `reverse`, atau `custom`) |
| `PLAYLIST_FILE` | `playlist.txt` | File daftar lagu saat `PLAYLIST_MODE="custom"` |
| `VIDEO_WIDTH` | `1920` | Lebar resolusi video (1080p) |
| `VIDEO_HEIGHT`| `1080` | Tinggi resolusi video (1080p) |
| `VIDEO_FPS` | `30` | Frame rate siaran |
| `VIDEO_BITRATE`| `3500k` | Bitrate video (3500k - 4500k standar YouTube 1080p) |
| `ENCODER_PRESET`| `ultrafast` | Preset x264 (`ultrafast` sangat hemat CPU & baterai) |
| `AUDIO_BITRATE`| `128k` | Kualitas audio AAC |
| `AUTO_RECONNECT`| `true` | Otomatis reconnect jika WiFi/internet terputus |
| `RECONNECT_DELAY`| `5` | Jeda waktu (detik) sebelum mencoba sambung ulang |

---

## 🛑 Cara Menghentikan Live Streaming

- Jika sedang di layar aktif: Tekan `Ctrl + C`.
- Skrip akan otomatis membersihkan file sementara, mematikan audio feeder background, dan melepaskan wake-lock Termux secara aman.
