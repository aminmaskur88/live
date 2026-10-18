#!/usr/bin/env python3
# ==============================================================================
# STREAM CONFIGURATOR & MANAGER
# Aplikasi Konfigurasi Live Streaming (Video, Musik, Volume, Urutan, & Stream Key)
# Dibuat & dioptimasi khusus untuk Termux / Android & Linux
# ==============================================================================

import os
import sys
import re
import json
import random
import signal
import subprocess
import threading
import time
from pathlib import Path

# Direktori kerja saat ini
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.env"
PLAYLIST_PATH = BASE_DIR / "playlist.txt"
STREAM_SH = BASE_DIR / "stream.sh"

# Warna ANSI untuk tampilan terminal
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[0;31m"
    GREEN   = "\033[0;32m"
    YELLOW  = "\033[1;33m"
    BLUE    = "\033[0;34m"
    MAGENTA = "\033[0;35m"
    CYAN    = "\033[0;36m"
    WHITE   = "\033[1;37m"
    GRAY    = "\033[0;90m"
    BG_BLUE = "\033[44m"


# ==============================================================================
# FUNGSI PENGELOLA KONFIGURASI (config.env)
# ==============================================================================

def load_config() -> dict:
    """Membaca file config.env dan mengembalikan dictionary konfigurasi."""
    defaults = {
        "STREAM_KEY": "",
        "RTMP_URL": "rtmp://a.rtmp.youtube.com/live2",
        "VIDEO_FILE": "",
        "VIDEO_VOLUME": "0.0",
        "MUSIC_DIR": "music",
        "MUSIC_VOLUME": "1.0",
        "PLAYLIST_MODE": "shuffle",
        "PLAYLIST_FILE": "playlist.txt",
        "SHUFFLE_PLAYLIST": "true",
        "VIDEO_WIDTH": "1920",
        "VIDEO_HEIGHT": "1080",
        "VIDEO_FPS": "30",
        "VIDEO_BITRATE": "3500k",
        "VIDEO_MAXRATE": "4000k",
        "VIDEO_BUFSIZE": "7000k",
        "ENCODER_PRESET": "ultrafast",
        "AUDIO_BITRATE": "128k",
        "AUDIO_SAMPLERATE": "44100",
        "AUTO_RECONNECT": "true",
        "RECONNECT_DELAY": "5",
    }

    if not CONFIG_PATH.exists():
        return defaults

    config = defaults.copy()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                config[key] = val

    # Sinkronisasi SHUFFLE_PLAYLIST dan PLAYLIST_MODE
    if "PLAYLIST_MODE" not in config or not config["PLAYLIST_MODE"]:
        if config.get("SHUFFLE_PLAYLIST") == "false":
            config["PLAYLIST_MODE"] = "alphabetical"
        else:
            config["PLAYLIST_MODE"] = "shuffle"

    return config


def save_config(updates: dict) -> bool:
    """Menyimpan pembaruan konfigurasi ke file config.env tanpa merusak komentar."""
    try:
        lines = []
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()

        updated_keys = set()
        new_lines = []

        # Sinkronisasi mundur untuk SHUFFLE_PLAYLIST jika PLAYLIST_MODE diubah
        if "PLAYLIST_MODE" in updates and "SHUFFLE_PLAYLIST" not in updates:
            mode = updates["PLAYLIST_MODE"]
            updates["SHUFFLE_PLAYLIST"] = "true" if mode == "shuffle" else "false"

        for line in lines:
            matched = False
            for k, v in updates.items():
                pattern = rf'^\s*{re.escape(k)}\s*='
                if re.match(pattern, line):
                    new_lines.append(f'{k}="{v}"\n')
                    updated_keys.add(k)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)

        # Tambahkan kunci baru yang belum ada di file
        for k, v in updates.items():
            if k not in updated_keys:
                new_lines.append(f'{k}="{v}"\n')

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except Exception as e:
        print(f"{C.RED}[ERROR] Gagal menyimpan config.env: {e}{C.RESET}")
        return False


# ==============================================================================
# FUNGSI PEMERIKSAAN MEDIA & PLAYLIST
# ==============================================================================

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".ts"}


def probe_video(video_path: str) -> dict:
    """Mengambil metadata video menggunakan ffprobe."""
    if not video_path:
        # Coba cari file video default
        v_candidates = scan_available_videos()
        if v_candidates:
            video_path = v_candidates[0]
        else:
            return {"exists": False, "path": "", "message": "Belum ada video yang dipilih"}

    full_path = Path(video_path)
    if not full_path.is_absolute():
        full_path = BASE_DIR / video_path

    if not full_path.exists():
        return {"exists": False, "path": str(video_path), "message": "File tidak ditemukan"}

    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate:format=duration,size",
            "-of", "json", str(full_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
            fmt = data.get("format", {})

            width = v_stream.get("width") if v_stream else None
            height = v_stream.get("height") if v_stream else None
            fps_str = v_stream.get("r_frame_rate", "30/1") if v_stream else "30/1"
            try:
                fps = round(eval(fps_str), 1) if "/" in fps_str else round(float(fps_str), 1)
            except Exception:
                fps = 30.0

            duration = round(float(fmt.get("duration", 0)), 1)
            size_mb = round(int(fmt.get("size", 0)) / (1024 * 1024), 1)

            return {
                "exists": True,
                "path": str(video_path),
                "full_path": str(full_path),
                "filename": full_path.name,
                "width": width,
                "height": height,
                "fps": fps,
                "duration": duration,
                "size_mb": size_mb,
                "has_audio": a_stream is not None,
                "audio_codec": a_stream.get("codec_name") if a_stream else None
            }
    except Exception as e:
        return {"exists": True, "path": str(video_path), "has_audio": False, "error": str(e)}

    return {"exists": True, "path": str(video_path), "has_audio": False}


def scan_available_videos() -> list:
    """Memindai file video di folder video/ dan root direktori proyek."""
    videos = []
    # 1. Folder video/
    v_dir = BASE_DIR / "video"
    if v_dir.exists() and v_dir.is_dir():
        for p in sorted(v_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                videos.append(str(p.relative_to(BASE_DIR)))

    # 2. Folder saat ini
    for p in sorted(BASE_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            rel = str(p.relative_to(BASE_DIR))
            if rel not in videos:
                videos.append(rel)

    return videos


def scan_android_video_dirs() -> list:
    """Mencari file video di lokasi penyimpanan Android umum jika ada."""
    found = []
    common_dirs = [
        Path("/sdcard/Movies"),
        Path("/sdcard/Download"),
        Path("/sdcard/DCIM/Camera"),
        Path("/sdcard/DCIM")
    ]
    for d in common_dirs:
        if d.exists() and d.is_dir():
            try:
                for p in d.iterdir():
                    if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                        found.append(str(p))
            except Exception:
                pass
    return found


def scan_music_files(music_dir_str: str) -> list:
    """Memindai semua file musik di direktori yang ditentukan."""
    m_path = Path(music_dir_str)
    if not m_path.is_absolute():
        m_path = BASE_DIR / music_dir_str

    tracks = []
    if m_path.exists() and m_path.is_dir():
        try:
            for p in sorted(m_path.iterdir()):
                if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                    tracks.append(p.name)
        except Exception:
            pass
    return tracks


def load_playlist_file(playlist_file_str: str, music_dir_str: str) -> list:
    """Membaca daftar urutan lagu dari file playlist.txt."""
    p_path = Path(playlist_file_str)
    if not p_path.is_absolute():
        p_path = BASE_DIR / playlist_file_str

    tracks = []
    if p_path.exists():
        with open(p_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    tracks.append(line)

    # Jika file playlist belum ada atau kosong, ambil dari folder musik
    if not tracks:
        tracks = scan_music_files(music_dir_str)
        if tracks:
            save_playlist_file(playlist_file_str, tracks)

    return tracks


def save_playlist_file(playlist_file_str: str, tracks: list) -> bool:
    """Menyimpan urutan lagu ke file playlist.txt."""
    p_path = Path(playlist_file_str)
    if not p_path.is_absolute():
        p_path = BASE_DIR / playlist_file_str

    try:
        with open(p_path, "w", encoding="utf-8") as f:
            f.write("# ========================================================\n")
            f.write("# DAFTAR URUTAN PLAYLIST MUSIK LIVE STREAMING\n")
            f.write("# Baris ini dibaca otomatis saat PLAYLIST_MODE=\"custom\"\n")
            f.write("# ========================================================\n\n")
            for t in tracks:
                t = t.strip()
                if t:
                    f.write(f"{t}\n")
        return True
    except Exception as e:
        print(f"{C.RED}[ERROR] Gagal menyimpan playlist: {e}{C.RESET}")
        return False


def volume_to_percent(vol_str: str) -> int:
    """Mengubah string volume (misal '0.5' atau '50%') menjadi persentase integer (50)."""
    if not vol_str:
        return 0
    vol_str = str(vol_str).strip()
    if vol_str.endswith("%"):
        try:
            return int(float(vol_str[:-1]))
        except ValueError:
            return 100
    try:
        val = float(vol_str)
        return int(round(val * 100))
    except ValueError:
        return 100


def percent_to_volume_str(percent: int) -> str:
    """Mengubah persentase integer (50) menjadi format desimal string ('0.5')."""
    val = round(percent / 100.0, 2)
    return str(val)


# ==============================================================================
# PROSES STREAMING MANAGER (START, STOP, TEST)
# ==============================================================================

STREAM_PROCESS = None
STREAM_LOGS = []
MAX_LOG_LINES = 100


def add_log(text: str):
    global STREAM_LOGS
    lines = text.splitlines()
    STREAM_LOGS.extend(lines)
    if len(STREAM_LOGS) > MAX_LOG_LINES:
        STREAM_LOGS = STREAM_LOGS[-MAX_LOG_LINES:]


def run_stream_process(args_list: list):
    global STREAM_PROCESS
    if STREAM_PROCESS and STREAM_PROCESS.poll() is None:
        return False, "Streaming sudah berjalan!"

    try:
        cmd = [str(STREAM_SH)] + args_list
        STREAM_PROCESS = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        def log_reader(proc):
            for line in iter(proc.stdout.readline, ''):
                if line:
                    add_log(line.rstrip())
            proc.stdout.close()

        t = threading.Thread(target=log_reader, args=(STREAM_PROCESS,), daemon=True)
        t.start()
        return True, "Streaming berhasil dimulai."
    except Exception as e:
        return False, str(e)


def stop_stream_process():
    global STREAM_PROCESS
    if not STREAM_PROCESS or STREAM_PROCESS.poll() is not None:
        return False, "Tidak ada streaming yang sedang berjalan."

    try:
        STREAM_PROCESS.send_signal(signal.SIGINT)
        time.sleep(1)
        if STREAM_PROCESS.poll() is None:
            STREAM_PROCESS.terminate()
        return True, "Streaming dihentikan."
    except Exception as e:
        return False, str(e)


# ==============================================================================
# ANTARMUKA TERMINAL CLI INTERAKTIF
# ==============================================================================

def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")


def print_header(title: str):
    clear_screen()
    print(f"{C.CYAN}╔══════════════════════════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.CYAN}║{C.BOLD}{C.WHITE} {title.center(64)} {C.RESET}{C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}╚══════════════════════════════════════════════════════════════════╝{C.RESET}\n")


def mask_stream_key(key: str) -> str:
    if not key:
        return f"{C.RED}(Belum Diisi){C.RESET}"
    if len(key) <= 8:
        return f"{C.YELLOW}****{C.RESET}"
    return f"{C.GREEN}{key[:4]}****{key[-4:]}{C.RESET}"


def menu_stream_key(cfg: dict):
    while True:
        print_header("🔑 PENGATURAN STREAM KEY & RTMP SERVER")
        cur_key = cfg.get("STREAM_KEY", "")
        cur_rtmp = cfg.get("RTMP_URL", "rtmp://a.rtmp.youtube.com/live2")

        print(f"  • Stream Key Saat Ini : {mask_stream_key(cur_key)}")
        print(f"  • Server RTMP Saat Ini: {C.CYAN}{cur_rtmp}{C.RESET}\n")
        print(f"{C.BOLD}Pilihan Menu:{C.RESET}")
        print(f"  {C.CYAN}[1]{C.RESET} Masukkan / Ubah Stream Key")
        print(f"  {C.CYAN}[2]{C.RESET} Pilih Server RTMP (YouTube, Facebook, Twitch, Kustom)")
        print(f"  {C.CYAN}[3]{C.RESET} Lihat Stream Key Lengkap")
        print(f"  {C.CYAN}[0]{C.RESET} Kembali ke Menu Utama\n")

        choice = input(f"{C.YELLOW}Pilih opsi [0-3]: {C.RESET}").strip()
        if choice == "1":
            print(f"\n{C.DIM}Tips: Tekan lama di layar Termux lalu pilih 'Paste' untuk menempel stream key.{C.RESET}")
            new_key = input(f"{C.BOLD}Masukkan Stream Key YouTube Anda: {C.RESET}").strip()
            if new_key:
                cfg["STREAM_KEY"] = new_key
                save_config({"STREAM_KEY": new_key})
                print(f"{C.GREEN}[✓] Stream Key berhasil disimpan!{C.RESET}")
                time.sleep(1)
        elif choice == "2":
            print(f"\n{C.BOLD}Pilih Server RTMP:{C.RESET}")
            print(f"  [1] YouTube Live RTMP (Standar): rtmp://a.rtmp.youtube.com/live2")
            print(f"  [2] YouTube Live RTMPS (Aman SSL): rtmps://a.rtmp.youtube.com/live2")
            print(f"  [3] Facebook Live: rtmps://live-api-s.facebook.com:443/rtmp/")
            print(f"  [4] Twitch: rtmp://live.twitch.tv/app/")
            print(f"  [5] Kustom (Ketik URL RTMP sendiri)")
            rt_opt = input(f"{C.YELLOW}Pilih [1-5]: {C.RESET}").strip()
            servers = {
                "1": "rtmp://a.rtmp.youtube.com/live2",
                "2": "rtmps://a.rtmp.youtube.com/live2",
                "3": "rtmps://live-api-s.facebook.com:443/rtmp/",
                "4": "rtmp://live.twitch.tv/app/",
            }
            if rt_opt in servers:
                cfg["RTMP_URL"] = servers[rt_opt]
                save_config({"RTMP_URL": servers[rt_opt]})
                print(f"{C.GREEN}[✓] RTMP URL berhasil diatur ke {servers[rt_opt]}{C.RESET}")
                time.sleep(1)
            elif rt_opt == "5":
                cust_rtmp = input("Masukkan URL RTMP kustom: ").strip()
                if cust_rtmp:
                    cfg["RTMP_URL"] = cust_rtmp
                    save_config({"RTMP_URL": cust_rtmp})
                    print(f"{C.GREEN}[✓] RTMP URL berhasil disimpan!{C.RESET}")
                    time.sleep(1)
        elif choice == "3":
            print(f"\n{C.BOLD}Stream Key Lengkap:{C.RESET} {C.GREEN}{cur_key if cur_key else '(Kosong)'}{C.RESET}")
            input(f"\n{C.DIM}Tekan Enter untuk melanjutkan...{C.RESET}")
        elif choice == "0":
            break


def menu_video_location(cfg: dict):
    while True:
        print_header("📹 PENGATURAN LOKASI VIDEO BACKGROUND")
        cur_v = cfg.get("VIDEO_FILE", "")
        v_info = probe_video(cur_v)

        print(f"  • File Video Aktif: {C.CYAN}{cur_v if cur_v else '(Otomatis deteksi di folder video/)'}{C.RESET}")
        if v_info.get("exists"):
            dim = f"{v_info.get('width', '?')}x{v_info.get('height', '?')}"
            fps = f"{v_info.get('fps', '?')} fps"
            dur = f"{v_info.get('duration', '?')} detik"
            sz = f"{v_info.get('size_mb', '?')} MB"
            has_a = f"{C.GREEN}Ada Audio ({v_info.get('audio_codec')}){C.RESET}" if v_info.get("has_audio") else f"{C.YELLOW}Tidak Ada Track Audio{C.RESET}"
            print(f"  • Rincian Video   : {C.WHITE}{dim} | {fps} | {dur} | {sz}{C.RESET}")
            print(f"  • Status Suara    : {has_a}")
        else:
            print(f"  • Status          : {C.RED}File video tidak ditemukan!{C.RESET}")

        print(f"\n{C.BOLD}Daftar File Video Ditemukan di Proyek:{C.RESET}")
        videos = scan_available_videos()
        if videos:
            for idx, vid in enumerate(videos, 1):
                is_active = " (AKTIF)" if vid == cur_v else ""
                print(f"  {C.CYAN}[{idx}]{C.RESET} {vid}{C.GREEN}{is_active}{C.RESET}")
        else:
            print(f"  {C.DIM}(Tidak ada file video di folder video/ atau root){C.RESET}")

        print(f"\n{C.BOLD}Opsi Lainnya:{C.RESET}")
        print(f"  {C.CYAN}[S]{C.RESET} Pindai File Video di Penyimpanan HP (/sdcard/Movies, Download, dsb)")
        print(f"  {C.CYAN}[M]{C.RESET} Masukkan Path File Video Manual (contoh: /sdcard/video.mp4)")
        print(f"  {C.CYAN}[A]{C.RESET} Gunakan Mode Otomatis (cari file video pertama di folder video/)")
        print(f"  {C.CYAN}[0]{C.RESET} Kembali ke Menu Utama\n")

        choice = input(f"{C.YELLOW}Pilih opsi: {C.RESET}").strip().upper()
        if choice.isdigit() and 1 <= int(choice) <= len(videos):
            selected = videos[int(choice) - 1]
            cfg["VIDEO_FILE"] = selected
            save_config({"VIDEO_FILE": selected})
            print(f"{C.GREEN}[✓] Video dipilih: {selected}{C.RESET}")
            time.sleep(1)
        elif choice == "S":
            sd_videos = scan_android_video_dirs()
            if not sd_videos:
                print(f"\n{C.YELLOW}[!] Tidak ada video ditemukan di /sdcard/Movies atau /sdcard/Download.{C.RESET}")
                time.sleep(1.5)
            else:
                print(f"\n{C.BOLD}Video Ditemukan di HP (/sdcard):{C.RESET}")
                for idx, sv in enumerate(sd_videos, 1):
                    print(f"  [{idx}] {sv}")
                pick = input(f"\n{C.YELLOW}Pilih nomor video (atau Enter batal): {C.RESET}").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(sd_videos):
                    chosen = sd_videos[int(pick) - 1]
                    cfg["VIDEO_FILE"] = chosen
                    save_config({"VIDEO_FILE": chosen})
                    print(f"{C.GREEN}[✓] Video dipilih: {chosen}{C.RESET}")
                    time.sleep(1)
        elif choice == "M":
            manual_path = input("\nMasukkan path file video: ").strip()
            if manual_path:
                if os.path.exists(manual_path):
                    cfg["VIDEO_FILE"] = manual_path
                    save_config({"VIDEO_FILE": manual_path})
                    print(f"{C.GREEN}[✓] Video valid & disimpan: {manual_path}{C.RESET}")
                else:
                    print(f"{C.RED}[!] Peringatan: Path '{manual_path}' saat ini belum ditemukan.{C.RESET}")
                    yn = input("Tetap simpan? (y/n): ").strip().lower()
                    if yn == "y":
                        cfg["VIDEO_FILE"] = manual_path
                        save_config({"VIDEO_FILE": manual_path})
                time.sleep(1)
        elif choice == "A":
            cfg["VIDEO_FILE"] = ""
            save_config({"VIDEO_FILE": ""})
            print(f"{C.GREEN}[✓] Diatur ke mode otomatis (folder video/){C.RESET}")
            time.sleep(1)
        elif choice == "0":
            break


def menu_video_volume(cfg: dict):
    while True:
        print_header("🔊 PENGATURAN VOLUME VIDEO")
        cur_vol = cfg.get("VIDEO_VOLUME", "0.0")
        pct = volume_to_percent(cur_vol)
        v_info = probe_video(cfg.get("VIDEO_FILE", ""))

        print(f"  • Volume Video Saat Ini: {C.BOLD}{C.GREEN}{pct}%{C.RESET} ({cur_vol})")
        if v_info.get("has_audio"):
            print(f"  • Status Audio Video   : {C.GREEN}✅ Video memiliki track audio ({v_info.get('audio_codec')}).{C.RESET}")
            if pct > 0:
                print(f"  • Efek                 : {C.CYAN}Suara video akan dicampur (mix) dengan playlist musik.{C.RESET}")
            else:
                print(f"  • Efek                 : {C.YELLOW}Suara video dibisukan (Mute). Hanya memutar musik.{C.RESET}")
        else:
            print(f"  • Status Audio Video   : {C.YELLOW}⚠️ Video ini tidak memiliki track audio.{C.RESET}")
            print(f"  • Catatan              : {C.DIM}Meskipun volume diatur > 0%, stream tetap berjalan normal tanpa error.{C.RESET}")

        print(f"\n{C.BOLD}Pilihan Preset Cepat:{C.RESET}")
        print(f"  {C.CYAN}[1]{C.RESET} Mute / Senyap (0%) - [Rekomendasi untuk background looping]")
        print(f"  {C.CYAN}[2]{C.RESET} Lembut / Latar (25%)")
        print(f"  {C.CYAN}[3]{C.RESET} Sedang (50%)")
        print(f"  {C.CYAN}[4]{C.RESET} Normal (100%)")
        print(f"  {C.CYAN}[5]{C.RESET} Keras (150%)")
        print(f"  {C.CYAN}[K]{C.RESET} Masukkan Angka Persentase Kustom (0 - 200%)")
        print(f"  {C.CYAN}[0]{C.RESET} Kembali ke Menu Utama\n")

        choice = input(f"{C.YELLOW}Pilih opsi: {C.RESET}").strip().upper()
        presets = {"1": 0, "2": 25, "3": 50, "4": 100, "5": 150}
        if choice in presets:
            new_pct = presets[choice]
            new_vol = percent_to_volume_str(new_pct)
            cfg["VIDEO_VOLUME"] = new_vol
            save_config({"VIDEO_VOLUME": new_vol})
            print(f"{C.GREEN}[✓] Volume video diatur ke: {new_pct}% ({new_vol}){C.RESET}")
            time.sleep(1)
        elif choice == "K":
            raw = input("Masukkan persentase volume video (0-200): ").strip().replace("%", "")
            try:
                val = int(raw)
                val = max(0, min(200, val))
                new_vol = percent_to_volume_str(val)
                cfg["VIDEO_VOLUME"] = new_vol
                save_config({"VIDEO_VOLUME": new_vol})
                print(f"{C.GREEN}[✓] Volume video berhasil diatur ke: {val}% ({new_vol}){C.RESET}")
                time.sleep(1)
            except ValueError:
                print(f"{C.RED}[!] Input angka tidak valid!{C.RESET}")
                time.sleep(1)
        elif choice == "0":
            break


def menu_music_location(cfg: dict):
    while True:
        print_header("📂 PENGATURAN FOLDER MUSIK")
        cur_m = cfg.get("MUSIC_DIR", "music")
        tracks = scan_music_files(cur_m)

        print(f"  • Folder Musik Saat Ini: {C.CYAN}{cur_m}{C.RESET}")
        print(f"  • Total Lagu Ditemukan : {C.BOLD}{C.GREEN}{len(tracks)} lagu{C.RESET}")
        if tracks:
            print(f"  • Contoh lagu          : {C.DIM}{', '.join(tracks[:3])}{'...' if len(tracks) > 3 else ''}{C.RESET}")

        print(f"\n{C.BOLD}Pilihan Lokasi Folder Musik:{C.RESET}")
        print(f"  {C.CYAN}[1]{C.RESET} music/ (Folder default proyek)")
        print(f"  {C.CYAN}[2]{C.RESET} /sdcard/Music (Folder Musik bawaan HP Android)")
        print(f"  {C.CYAN}[3]{C.RESET} /sdcard/Download (Folder Download HP Android)")
        print(f"  {C.CYAN}[4]{C.RESET} Ketik path folder musik kustom")
        print(f"  {C.CYAN}[0]{C.RESET} Kembali ke Menu Utama\n")

        choice = input(f"{C.YELLOW}Pilih opsi [0-4]: {C.RESET}").strip()
        if choice == "1":
            cfg["MUSIC_DIR"] = "music"
            save_config({"MUSIC_DIR": "music"})
            print(f"{C.GREEN}[✓] Folder musik diatur ke: music/{C.RESET}")
            time.sleep(1)
        elif choice == "2":
            cfg["MUSIC_DIR"] = "/sdcard/Music"
            save_config({"MUSIC_DIR": "/sdcard/Music"})
            print(f"{C.GREEN}[✓] Folder musik diatur ke: /sdcard/Music{C.RESET}")
            time.sleep(1)
        elif choice == "3":
            cfg["MUSIC_DIR"] = "/sdcard/Download"
            save_config({"MUSIC_DIR": "/sdcard/Download"})
            print(f"{C.GREEN}[✓] Folder musik diatur ke: /sdcard/Download{C.RESET}")
            time.sleep(1)
        elif choice == "4":
            new_path = input("Masukkan path folder musik: ").strip()
            if new_path:
                cfg["MUSIC_DIR"] = new_path
                save_config({"MUSIC_DIR": new_path})
                found = len(scan_music_files(new_path))
                print(f"{C.GREEN}[✓] Folder disimpan. ({found} lagu ditemukan){C.RESET}")
                time.sleep(1)
        elif choice == "0":
            break


def menu_playlist_mode(cfg: dict):
    while True:
        print_header("🎵 PENGATURAN MODE URUTAN MUSIK")
        cur_mode = cfg.get("PLAYLIST_MODE", "shuffle")
        modes_desc = {
            "shuffle": "Acak (Shuffle) - Lagu diacak otomatis setiap putaran playlist",
            "alphabetical": "Urut Abjad Nama File (A - Z)",
            "reverse": "Urut Abjad Terbalik (Z - A)",
            "custom": "Urutan Kustom - Urutan persis seperti yang diatur di playlist.txt",
        }

        print(f"  • Mode Saat Ini: {C.BOLD}{C.GREEN}{modes_desc.get(cur_mode, cur_mode)}{C.RESET}\n")
        print(f"{C.BOLD}Pilih Mode Urutan Musik:{C.RESET}")
        print(f"  {C.CYAN}[1]{C.RESET} Acak (Shuffle) [Paling disukai untuk live 24/7]")
        print(f"  {C.CYAN}[2]{C.RESET} Urut Abjad Nama File (A - Z)")
        print(f"  {C.CYAN}[3]{C.RESET} Urut Abjad Terbalik (Z - A)")
        print(f"  {C.CYAN}[4]{C.RESET} Urutan Kustom (Tentukan urutan lagu sendiri di menu berikutnya)")
        print(f"  {C.CYAN}[0]{C.RESET} Kembali ke Menu Utama\n")

        choice = input(f"{C.YELLOW}Pilih opsi [0-4]: {C.RESET}").strip()
        mapping = {
            "1": "shuffle",
            "2": "alphabetical",
            "3": "reverse",
            "4": "custom",
        }
        if choice in mapping:
            selected_mode = mapping[choice]
            cfg["PLAYLIST_MODE"] = selected_mode
            save_config({"PLAYLIST_MODE": selected_mode})
            print(f"{C.GREEN}[✓] Mode urutan musik diubah menjadi: {selected_mode}{C.RESET}")
            if selected_mode == "custom":
                print(f"{C.CYAN}[i] Anda dapat mengatur urutan daftar lagu di Menu [7].{C.RESET}")
            time.sleep(1.2)
            break
        elif choice == "0":
            break


def menu_music_volume(cfg: dict):
    while True:
        print_header("🔉 PENGATURAN VOLUME MUSIK")
        cur_vol = cfg.get("MUSIC_VOLUME", "1.0")
        pct = volume_to_percent(cur_vol)

        print(f"  • Volume Musik Saat Ini: {C.BOLD}{C.GREEN}{pct}%{C.RESET} ({cur_vol})\n")
        print(f"{C.BOLD}Pilihan Preset Cepat:{C.RESET}")
        print(f"  {C.CYAN}[1]{C.RESET} Lembut (25%)")
        print(f"  {C.CYAN}[2]{C.RESET} Sedang (50%)")
        print(f"  {C.CYAN}[3]{C.RESET} Seimbang (75%)")
        print(f"  {C.CYAN}[4]{C.RESET} Normal (100%) - [Default]")
        print(f"  {C.CYAN}[5]{C.RESET} Keras (150%)")
        print(f"  {C.CYAN}[K]{C.RESET} Masukkan Angka Persentase Kustom (0 - 200%)")
        print(f"  {C.CYAN}[0]{C.RESET} Kembali ke Menu Utama\n")

        choice = input(f"{C.YELLOW}Pilih opsi: {C.RESET}").strip().upper()
        presets = {"1": 25, "2": 50, "3": 75, "4": 100, "5": 150}
        if choice in presets:
            new_pct = presets[choice]
            new_vol = percent_to_volume_str(new_pct)
            cfg["MUSIC_VOLUME"] = new_vol
            save_config({"MUSIC_VOLUME": new_vol})
            print(f"{C.GREEN}[✓] Volume musik diatur ke: {new_pct}% ({new_vol}){C.RESET}")
            time.sleep(1)
        elif choice == "K":
            raw = input("Masukkan persentase volume musik (0-200): ").strip().replace("%", "")
            try:
                val = int(raw)
                val = max(0, min(200, val))
                new_vol = percent_to_volume_str(val)
                cfg["MUSIC_VOLUME"] = new_vol
                save_config({"MUSIC_VOLUME": new_vol})
                print(f"{C.GREEN}[✓] Volume musik berhasil diatur ke: {val}% ({new_vol}){C.RESET}")
                time.sleep(1)
            except ValueError:
                print(f"{C.RED}[!] Input angka tidak valid!{C.RESET}")
                time.sleep(1)
        elif choice == "0":
            break


def menu_custom_playlist(cfg: dict):
    p_file = cfg.get("PLAYLIST_FILE", "playlist.txt")
    m_dir = cfg.get("MUSIC_DIR", "music")
    tracks = load_playlist_file(p_file, m_dir)

    while True:
        print_header("📋 KELOLA URUTAN LAGU KUSTOM (PLAYLIST)")
        mode = cfg.get("PLAYLIST_MODE", "shuffle")
        status_note = f"{C.GREEN}AKTIF{C.RESET}" if mode == "custom" else f"{C.YELLOW}Nonaktif (Mode saat ini: {mode}){C.RESET}"
        print(f"  • File Playlist : {C.CYAN}{p_file}{C.RESET}")
        print(f"  • Status Mode   : {status_note}")
        print(f"  • Total Lagu    : {C.BOLD}{len(tracks)} lagu{C.RESET}\n")

        print(f"{C.BOLD}Daftar Urutan Lagu Saat Ini:{C.RESET}")
        if not tracks:
            print(f"  {C.RED}(Tidak ada lagu di playlist atau folder musik){C.RESET}")
        else:
            for i, t in enumerate(tracks, 1):
                print(f"  {C.CYAN}{i:2d}.{C.RESET} {t}")

        print(f"\n{C.BOLD}Menu Pengaturan Urutan:{C.RESET}")
        print(f"  {C.CYAN}[T]{C.RESET} Tukar / Pindah Posisi Lagu (misal: pindahkan lagu #3 ke #1)")
        print(f"  {C.CYAN}[N]{C.RESET} Geser Naik (Move Up)")
        print(f"  {C.CYAN}[D]{C.RESET} Geser Turun (Move Down)")
        print(f"  {C.CYAN}[A]{C.RESET} Acak Urutan Sekarang (One-time Shuffle)")
        print(f"  {C.CYAN}[Z]{C.RESET} Urutkan Berdasarkan Abjad (A - Z)")
        print(f"  {C.CYAN}[R]{C.RESET} Reset Ulang dari Folder Musik")
        print(f"  {C.CYAN}[S]{C.RESET} Simpan Playlist & Aktifkan Mode Kustom")
        print(f"  {C.CYAN}[0]{C.RESET} Kembali ke Menu Utama\n")

        choice = input(f"{C.YELLOW}Pilih opsi: {C.RESET}").strip().upper()
        if choice == "T":
            if len(tracks) < 2:
                print(f"{C.YELLOW}[!] Minimal 2 lagu untuk menukar posisi.{C.RESET}")
                time.sleep(1)
                continue
            src = input(f"Masukkan nomor lagu yang ingin dipindah (1-{len(tracks)}): ").strip()
            dst = input(f"Pindahkan ke posisi nomor berapa (1-{len(tracks)}): ").strip()
            if src.isdigit() and dst.isdigit():
                s = int(src) - 1
                d = int(dst) - 1
                if 0 <= s < len(tracks) and 0 <= d < len(tracks):
                    item = tracks.pop(s)
                    tracks.insert(d, item)
                    save_playlist_file(p_file, tracks)
                    print(f"{C.GREEN}[✓] Lagu '{item}' dipindahkan ke posisi #{d+1}!{C.RESET}")
                    time.sleep(1)
        elif choice == "N":
            num = input(f"Nomor lagu yang ingin digeser NAIK (1-{len(tracks)}): ").strip()
            if num.isdigit():
                idx = int(num) - 1
                if 1 <= idx < len(tracks):
                    tracks[idx], tracks[idx - 1] = tracks[idx - 1], tracks[idx]
                    save_playlist_file(p_file, tracks)
                    print(f"{C.GREEN}[✓] Lagu dinaikkan ke posisi #{idx}!{C.RESET}")
                    time.sleep(0.7)
                elif idx == 0:
                    print(f"{C.YELLOW}[!] Lagu sudah berada di paling atas.{C.RESET}")
                    time.sleep(1)
        elif choice == "D":
            num = input(f"Nomor lagu yang ingin digeser TURUN (1-{len(tracks)}): ").strip()
            if num.isdigit():
                idx = int(num) - 1
                if 0 <= idx < len(tracks) - 1:
                    tracks[idx], tracks[idx + 1] = tracks[idx + 1], tracks[idx]
                    save_playlist_file(p_file, tracks)
                    print(f"{C.GREEN}[✓] Lagu diturunkan ke posisi #{idx+2}!{C.RESET}")
                    time.sleep(0.7)
                elif idx == len(tracks) - 1:
                    print(f"{C.YELLOW}[!] Lagu sudah berada di paling bawah.{C.RESET}")
                    time.sleep(1)
        elif choice == "A":
            random.shuffle(tracks)
            save_playlist_file(p_file, tracks)
            print(f"{C.GREEN}[✓] Urutan lagu berhasil diacak!{C.RESET}")
            time.sleep(1)
        elif choice == "Z":
            tracks.sort()
            save_playlist_file(p_file, tracks)
            print(f"{C.GREEN}[✓] Lagu berhasil diurutkan A-Z!{C.RESET}")
            time.sleep(1)
        elif choice == "R":
            tracks = scan_music_files(m_dir)
            save_playlist_file(p_file, tracks)
            print(f"{C.GREEN}[✓] Playlist direset ulang dari folder '{m_dir}'!{C.RESET}")
            time.sleep(1)
        elif choice == "S":
            save_playlist_file(p_file, tracks)
            cfg["PLAYLIST_MODE"] = "custom"
            save_config({"PLAYLIST_MODE": "custom"})
            print(f"{C.GREEN}[✓] Playlist disimpan & Mode Kustom diaktifkan!{C.RESET}")
            time.sleep(1.2)
            break
        elif choice == "0":
            break


def main_cli():
    while True:
        cfg = load_config()
        cur_v = cfg.get("VIDEO_FILE", "")
        v_info = probe_video(cur_v)
        m_dir = cfg.get("MUSIC_DIR", "music")
        m_tracks = scan_music_files(m_dir)
        p_mode = cfg.get("PLAYLIST_MODE", "shuffle")
        v_vol_pct = volume_to_percent(cfg.get("VIDEO_VOLUME", "0.0"))
        m_vol_pct = volume_to_percent(cfg.get("MUSIC_VOLUME", "1.0"))
        s_key = cfg.get("STREAM_KEY", "")

        clear_screen()
        print(f"{C.CYAN}╔══════════════════════════════════════════════════════════════════╗{C.RESET}")
        print(f"{C.CYAN}║{C.BOLD}{C.WHITE}       🎬  PENGATURAN LIVE STREAMING 24/7 (TERMUX / LINUX)        {C.RESET}{C.CYAN}║{C.RESET}")
        print(f"{C.CYAN}╚══════════════════════════════════════════════════════════════════╝{C.RESET}")

        # Tampilan Ringkasan Status
        video_display = cur_v if cur_v else "Auto (video/)"
        if v_info.get("exists") and v_info.get("width"):
            v_spec = f"{v_info.get('width')}x{v_info.get('height')} @ {v_info.get('fps')}fps"
        else:
            v_spec = "File Siap" if v_info.get("exists") else "Tidak Ditemukan"

        print(f"\n{C.BOLD}STATUS KONFIGURASI SAAT INI:{C.RESET}")
        print(f" • Stream Key      : {mask_stream_key(s_key)}")
        print(f" • Video Looping   : {C.CYAN}{video_display}{C.RESET} {C.DIM}({v_spec}){C.RESET}")
        v_vol_desc = f"{v_vol_pct}% (Muted)" if v_vol_pct == 0 else f"{v_vol_pct}% (Dimix)"
        print(f" • Volume Video    : {C.BOLD}{v_vol_desc}{C.RESET} {C.GREEN if v_info.get('has_audio') else C.YELLOW}(Audio Video: {'Ada' if v_info.get('has_audio') else 'Tanpa Audio'}){C.RESET}")
        print(f" • Folder Musik    : {C.CYAN}{m_dir}/{C.RESET} {C.DIM}({len(m_tracks)} lagu ditemukan){C.RESET}")
        print(f" • Urutan Musik    : {C.BOLD}{p_mode.upper()}{C.RESET} {C.DIM}{'(playlist.txt)' if p_mode == 'custom' else ''}{C.RESET}")
        print(f" • Volume Musik    : {C.BOLD}{m_vol_pct}%{C.RESET}")

        print(f"\n{C.CYAN}──────────────────────────────────────────────────────────────────{C.RESET}")
        print(f"{C.BOLD}MENU PENGATURAN:{C.RESET}")
        print(f"  {C.CYAN}[1]{C.RESET} 🔑 Atur Stream Key & Server RTMP")
        print(f"  {C.CYAN}[2]{C.RESET} 📹 Pilih Lokasi Video Background")
        print(f"  {C.CYAN}[3]{C.RESET} 🔊 Atur Volume Audio Video (0% - 200%)")
        print(f"  {C.CYAN}[4]{C.RESET} 📂 Pilih Lokasi Folder Musik")
        print(f"  {C.CYAN}[5]{C.RESET} 🎵 Atur Mode Urutan Musik (Acak / A-Z / Z-A / Kustom)")
        print(f"  {C.CYAN}[6]{C.RESET} 🔉 Atur Volume Playlist Musik (0% - 200%)")
        print(f"  {C.CYAN}[7]{C.RESET} 📋 Kelola Urutan Lagu Kustom (Geser/Tukar Lagu di Playlist)")
        print(f"{C.CYAN}──────────────────────────────────────────────────────────────────{C.RESET}")
        print(f"  {C.GREEN}{C.BOLD}[8] 🚀 Jalankan Live Stream Sekarang (./stream.sh){C.RESET}")
        print(f"  {C.YELLOW}{C.BOLD}[9] 🧪 Tes Streaming (Preview 15 Detik Tanpa Live){C.RESET}")
        print(f"  {C.MAGENTA}{C.BOLD}[W] 🌐 Buka Web Dashboard di Browser (Mobile Friendly UI){C.RESET}")
        print(f"  {C.RED}[0] 🚪 Keluar{C.RESET}\n")

        cmd = input(f"{C.YELLOW}Pilih nomor menu [0-9 atau W]: {C.RESET}").strip().upper()
        if cmd == "1":
            menu_stream_key(cfg)
        elif cmd == "2":
            menu_video_location(cfg)
        elif cmd == "3":
            menu_video_volume(cfg)
        elif cmd == "4":
            menu_music_location(cfg)
        elif cmd == "5":
            menu_playlist_mode(cfg)
        elif cmd == "6":
            menu_music_volume(cfg)
        elif cmd == "7":
            menu_custom_playlist(cfg)
        elif cmd == "8":
            # Mulai Live Stream
            if not cfg.get("STREAM_KEY"):
                print(f"\n{C.RED}[!] Stream Key belum diisi! Silakan isi di menu [1] terlebih dahulu.{C.RESET}")
                time.sleep(2)
                continue
            clear_screen()
            print(f"{C.GREEN}[*] Menjalankan Live Streaming ke YouTube...{C.RESET}")
            subprocess.run([str(STREAM_SH)], cwd=str(BASE_DIR))
            input(f"\n{C.DIM}Tekan Enter untuk kembali ke menu...{C.RESET}")
        elif cmd == "9":
            # Mode Uji Coba 15 Detik
            clear_screen()
            print(f"{C.YELLOW}[*] Menjalankan Uji Coba Preview 15 Detik...{C.RESET}")
            subprocess.run([str(STREAM_SH), "--test"], cwd=str(BASE_DIR))
            input(f"\n{C.DIM}Tekan Enter untuk kembali ke menu...{C.RESET}")
        elif cmd == "W":
            run_web_server()
            break
        elif cmd == "0":
            print(f"\n{C.GREEN}Sampai jumpa! Selamat streaming!{C.RESET}\n")
            sys.exit(0)


# ==============================================================================
# MODE WEB UI DASHBOARD (FLASK EMBEDDED)
# ==============================================================================

WEB_HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Stream Configurator - Live 24/7</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --accent: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background-color: var(--bg-color); color: var(--text-main); padding: 12px; padding-bottom: 80px; }
        .container { max-width: 680px; margin: 0 auto; }
        .header { text-align: center; padding: 16px 0; border-bottom: 1px solid var(--card-border); margin-bottom: 20px; }
        .header h1 { font-size: 1.4rem; color: #fff; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .header p { font-size: 0.85rem; color: var(--text-dim); margin-top: 4px; }
        .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); }
        .card-title { font-size: 1.05rem; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
        .badge { font-size: 0.72rem; padding: 3px 8px; border-radius: 9999px; background: #334155; color: #e2e8f0; font-weight: normal; }
        .badge.green { background: #065f46; color: #6ee7b7; }
        .badge.yellow { background: #78350f; color: #fde68a; }
        .badge.blue { background: #1e3a8a; color: #93c5fd; }
        .form-group { margin-bottom: 14px; }
        label { display: block; font-size: 0.85rem; color: var(--text-dim); margin-bottom: 6px; font-weight: 500; }
        input[type="text"], input[type="password"], select { width: 100%; padding: 10px 12px; background: #0f172a; border: 1px solid var(--card-border); border-radius: 8px; color: #fff; font-size: 0.95rem; outline: none; transition: border-color 0.2s; }
        input[type="text"]:focus, input[type="password"]:focus, select:focus { border-color: var(--primary); }
        .input-row { display: flex; gap: 8px; }
        .slider-container { display: flex; align-items: center; gap: 12px; }
        input[type="range"] { flex: 1; accent-color: var(--primary); height: 6px; border-radius: 4px; }
        .slider-val { min-width: 52px; font-weight: bold; color: var(--accent); text-align: right; font-size: 1rem; }
        .radio-group { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 6px; }
        .radio-btn { border: 1px solid var(--card-border); padding: 10px; border-radius: 8px; font-size: 0.85rem; text-align: center; cursor: pointer; transition: all 0.2s; background: #0f172a; }
        .radio-btn.active { border-color: var(--primary); background: rgba(59, 130, 246, 0.15); color: #93c5fd; font-weight: 600; }
        .playlist-list { list-style: none; max-height: 280px; overflow-y: auto; border: 1px solid var(--card-border); border-radius: 8px; background: #0f172a; }
        .playlist-item { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }
        .playlist-item:last-child { border-bottom: none; }
        .item-actions { display: flex; gap: 4px; }
        .btn-mini { padding: 4px 8px; font-size: 0.8rem; background: #334155; border: none; border-radius: 4px; color: #fff; cursor: pointer; }
        .btn-mini:hover { background: #475569; }
        .btn-group { display: flex; gap: 8px; margin-top: 10px; }
        .btn { flex: 1; padding: 12px; border-radius: 8px; font-size: 0.95rem; font-weight: 600; border: none; cursor: pointer; text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 6px; transition: 0.2s; }
        .btn-primary { background: var(--primary); color: #fff; }
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-success { background: var(--accent); color: #fff; }
        .btn-warning { background: var(--warning); color: #000; }
        .btn-danger { background: var(--danger); color: #fff; }
        .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #10b981; color: #fff; padding: 10px 20px; border-radius: 30px; font-size: 0.9rem; font-weight: 500; display: none; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.5); z-index: 1000; }
        .terminal-box { background: #050811; border: 1px solid #1e293b; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 0.75rem; color: #10b981; height: 160px; overflow-y: auto; white-space: pre-wrap; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎬 Stream Configurator</h1>
            <p>Konfigurasi YouTube Live Looping 24/7 (Termux & Linux)</p>
        </div>

        <!-- STREAM KEY CARD -->
        <div class="card">
            <div class="card-title">
                <span>🔑 Stream Key & RTMP Server</span>
                <span class="badge blue">YouTube</span>
            </div>
            <div class="form-group">
                <label>YouTube Stream Key:</label>
                <div class="input-row">
                    <input type="password" id="streamKey" placeholder="tempel stream key di sini">
                    <button class="btn-mini" onclick="toggleStreamKey()" style="padding:0 14px;">👁️</button>
                </div>
            </div>
            <div class="form-group">
                <label>RTMP Target URL:</label>
                <select id="rtmpUrl">
                    <option value="rtmp://a.rtmp.youtube.com/live2">YouTube RTMP (Standar)</option>
                    <option value="rtmps://a.rtmp.youtube.com/live2">YouTube RTMPS (Aman SSL)</option>
                    <option value="rtmps://live-api-s.facebook.com:443/rtmp/">Facebook Live</option>
                    <option value="rtmp://live.twitch.tv/app/">Twitch</option>
                </select>
            </div>
        </div>

        <!-- VIDEO SETTINGS CARD -->
        <div class="card">
            <div class="card-title">
                <span>📹 Video Background</span>
                <span id="videoAudioBadge" class="badge">Mengecek...</span>
            </div>
            <div class="form-group">
                <label>Lokasi File Video:</label>
                <div class="input-row">
                    <input type="text" id="videoFile" placeholder="misal: video/sample_background.mp4">
                </div>
                <small id="videoMeta" style="color:var(--text-dim); display:block; margin-top:4px; font-size:0.75rem;">-</small>
            </div>
            <div class="form-group">
                <label>Volume Audio Video: <span id="videoVolLabel" style="color:var(--accent); font-weight:bold;">0%</span></label>
                <div class="slider-container">
                    <input type="range" id="videoVolRange" min="0" max="200" value="0" oninput="updateVideoVol(this.value)">
                    <div class="slider-val" id="videoVolVal">0%</div>
                </div>
                <small style="color:var(--text-dim); font-size:0.75rem;">0% = Mute/Senyap (Suara murni dari musik). Di atas 0% akan di-mix dengan playlist.</small>
            </div>
        </div>

        <!-- MUSIC SETTINGS CARD -->
        <div class="card">
            <div class="card-title">
                <span>📂 Folder & Volume Musik</span>
                <span id="trackCountBadge" class="badge green">0 Lagu</span>
            </div>
            <div class="form-group">
                <label>Lokasi Folder Musik:</label>
                <input type="text" id="musicDir" placeholder="misal: music atau /sdcard/Music" onchange="loadMusicTracks()">
            </div>
            <div class="form-group">
                <label>Volume Playlist Musik: <span id="musicVolLabel" style="color:var(--accent); font-weight:bold;">100%</span></label>
                <div class="slider-container">
                    <input type="range" id="musicVolRange" min="0" max="200" value="100" oninput="updateMusicVol(this.value)">
                    <div class="slider-val" id="musicVolVal">100%</div>
                </div>
            </div>
            <div class="form-group">
                <label>Mode Urutan Musik:</label>
                <div class="radio-group">
                    <div class="radio-btn" id="mode-shuffle" onclick="selectMode('shuffle')">🔁 Acak (Shuffle)</div>
                    <div class="radio-btn" id="mode-alphabetical" onclick="selectMode('alphabetical')">🔤 Abjad (A - Z)</div>
                    <div class="radio-btn" id="mode-reverse" onclick="selectMode('reverse')">🔃 Terbalik (Z - A)</div>
                    <div class="radio-btn" id="mode-custom" onclick="selectMode('custom')">📋 Kustom (Urutkan)</div>
                </div>
            </div>
        </div>

        <!-- PLAYLIST REORDER CARD (VISIBLE IN CUSTOM MODE) -->
        <div class="card" id="playlistCard">
            <div class="card-title">
                <span>📋 Urutan Lagu Kustom</span>
                <button class="btn-mini" onclick="shufflePlaylist()">🎲 Acak Urutan</button>
            </div>
            <ul class="playlist-list" id="playlistItems">
                <li style="padding:15px; text-align:center; color:var(--text-dim);">Memuat lagu...</li>
            </ul>
        </div>

        <!-- ACTION BUTTONS -->
        <div style="position: sticky; bottom: 12px; z-index: 100;">
            <button class="btn btn-primary" onclick="saveAllConfig()" style="width:100%; box-shadow: 0 4px 14px rgba(59,130,246,0.4);">
                💾 Simpan Semua Konfigurasi
            </button>
        </div>

        <!-- CONTROL & TERMINAL CARD -->
        <div class="card" style="margin-top:20px;">
            <div class="card-title">
                <span>🚀 Kontrol Live Streaming</span>
                <span id="streamStatusBadge" class="badge">Idle / Siap</span>
            </div>
            <div class="btn-group">
                <button class="btn btn-success" onclick="startStream(false)">▶️ Mulai Live</button>
                <button class="btn btn-warning" onclick="startStream(true)">🧪 Tes 15s</button>
                <button class="btn btn-danger" onclick="stopStream()">⏹️ Stop</button>
            </div>
            <div class="terminal-box" id="terminalBox">Log siaran akan tampil di sini...</div>
        </div>
    </div>

    <div class="toast" id="toast">Konfigurasi Disimpan!</div>

    <script>
        let playlistData = [];
        let currentMode = "shuffle";

        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 2500);
        }

        function toggleStreamKey() {
            const el = document.getElementById('streamKey');
            el.type = el.type === 'password' ? 'text' : 'password';
        }

        function updateVideoVol(val) {
            document.getElementById('videoVolLabel').innerText = val + '%';
            document.getElementById('videoVolVal').innerText = val + '%';
        }

        function updateMusicVol(val) {
            document.getElementById('musicVolLabel').innerText = val + '%';
            document.getElementById('musicVolVal').innerText = val + '%';
        }

        function selectMode(mode) {
            currentMode = mode;
            document.querySelectorAll('.radio-btn').forEach(b => b.classList.remove('active'));
            const activeBtn = document.getElementById('mode-' + mode);
            if (activeBtn) activeBtn.classList.add('active');
        }

        async function loadData() {
            try {
                const res = await fetch('/api/config');
                const data = await res.json();
                
                document.getElementById('streamKey').value = data.config.STREAM_KEY || '';
                document.getElementById('rtmpUrl').value = data.config.RTMP_URL || 'rtmp://a.rtmp.youtube.com/live2';
                document.getElementById('videoFile').value = data.config.VIDEO_FILE || '';
                document.getElementById('musicDir').value = data.config.MUSIC_DIR || 'music';

                const vVol = Math.round(parseFloat(data.config.VIDEO_VOLUME || '0.0') * 100);
                document.getElementById('videoVolRange').value = vVol;
                updateVideoVol(vVol);

                const mVol = Math.round(parseFloat(data.config.MUSIC_VOLUME || '1.0') * 100);
                document.getElementById('musicVolRange').value = mVol;
                updateMusicVol(mVol);

                selectMode(data.config.PLAYLIST_MODE || 'shuffle');

                // Video metadata badge
                const vm = data.video_info;
                const vBadge = document.getElementById('videoAudioBadge');
                const vMeta = document.getElementById('videoMeta');
                if (vm && vm.exists) {
                    vBadge.className = vm.has_audio ? 'badge green' : 'badge yellow';
                    vBadge.innerText = vm.has_audio ? 'Audio: ' + (vm.audio_codec || 'Ada') : 'Tanpa Audio';
                    vMeta.innerText = `${vm.width || '?'}x${vm.height || '?'} @ ${vm.fps || '?'}fps | ${vm.size_mb || '?'} MB`;
                } else {
                    vBadge.className = 'badge';
                    vBadge.innerText = 'Video Belum Dipilih';
                }

                // Playlist
                playlistData = data.playlist || [];
                renderPlaylist();
                document.getElementById('trackCountBadge').innerText = playlistData.length + ' Lagu';
            } catch (e) {
                console.error(e);
            }
        }

        function renderPlaylist() {
            const list = document.getElementById('playlistItems');
            if (playlistData.length === 0) {
                list.innerHTML = '<li style="padding:15px; text-align:center; color:var(--text-dim);">Folder musik kosong.</li>';
                return;
            }
            list.innerHTML = '';
            playlistData.forEach((item, idx) => {
                const li = document.createElement('li');
                li.className = 'playlist-item';
                li.innerHTML = `
                    <span><strong>${idx + 1}.</strong> ${item}</span>
                    <div class="item-actions">
                        <button class="btn-mini" onclick="moveItem(${idx}, -1)">▲</button>
                        <button class="btn-mini" onclick="moveItem(${idx}, 1)">▼</button>
                    </div>
                `;
                list.appendChild(li);
            });
        }

        function moveItem(idx, dir) {
            const newIdx = idx + dir;
            if (newIdx < 0 || newIdx >= playlistData.length) return;
            const temp = playlistData[idx];
            playlistData[idx] = playlistData[newIdx];
            playlistData[newIdx] = temp;
            renderPlaylist();
        }

        function shufflePlaylist() {
            for (let i = playlistData.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [playlistData[i], playlistData[j]] = [playlistData[j], playlistData[i]];
            }
            renderPlaylist();
            showToast("Urutan diacak!");
        }

        async function saveAllConfig() {
            const payload = {
                STREAM_KEY: document.getElementById('streamKey').value.trim(),
                RTMP_URL: document.getElementById('rtmpUrl').value.trim(),
                VIDEO_FILE: document.getElementById('videoFile').value.trim(),
                VIDEO_VOLUME: (parseInt(document.getElementById('videoVolRange').value) / 100).toFixed(2),
                MUSIC_DIR: document.getElementById('musicDir').value.trim(),
                MUSIC_VOLUME: (parseInt(document.getElementById('musicVolRange').value) / 100).toFixed(2),
                PLAYLIST_MODE: currentMode,
                playlist: playlistData
            };

            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await res.json();
            if (result.success) {
                showToast("✅ Konfigurasi Berhasil Disimpan!");
            } else {
                alert("Gagal menyimpan: " + result.message);
            }
        }

        async function startStream(isTest) {
            await saveAllConfig();
            const res = await fetch('/api/stream/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ test: isTest })
            });
            const r = await res.json();
            showToast(r.message);
        }

        async function stopStream() {
            const res = await fetch('/api/stream/stop', { method: 'POST' });
            const r = await res.json();
            showToast(r.message);
        }

        async function pollLogs() {
            try {
                const res = await fetch('/api/stream/logs');
                const data = await res.json();
                const box = document.getElementById('terminalBox');
                const badge = document.getElementById('streamStatusBadge');

                if (data.running) {
                    badge.className = 'badge green';
                    badge.innerText = '🔴 LIVE BERJALAN';
                } else {
                    badge.className = 'badge';
                    badge.innerText = 'Standby / Idle';
                }

                if (data.logs && data.logs.length > 0) {
                    box.innerText = data.logs.join('\n');
                    box.scrollTop = box.scrollHeight;
                }
            } catch (e) {}
        }

        window.onload = () => {
            loadData();
            setInterval(pollLogs, 2000);
        };
    </script>
</body>
</html>
"""


def run_web_server(port: int = 5000):
    try:
        from flask import Flask, jsonify, request, render_template_string
    except ImportError:
        print(f"{C.RED}[ERROR] Flask belum terpasang. Jalankan: pip install flask{C.RESET}")
        return

    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(WEB_HTML)

    @app.route("/api/config", methods=["GET"])
    def get_config():
        cfg = load_config()
        v_info = probe_video(cfg.get("VIDEO_FILE", ""))
        tracks = load_playlist_file(cfg.get("PLAYLIST_FILE", "playlist.txt"), cfg.get("MUSIC_DIR", "music"))
        return jsonify({
            "config": cfg,
            "video_info": v_info,
            "playlist": tracks
        })

    @app.route("/api/config", methods=["POST"])
    def post_config():
        data = request.json or {}
        updates = {}
        keys = ["STREAM_KEY", "RTMP_URL", "VIDEO_FILE", "VIDEO_VOLUME", "MUSIC_DIR", "MUSIC_VOLUME", "PLAYLIST_MODE"]
        for k in keys:
            if k in data:
                updates[k] = str(data[k])

        ok = save_config(updates)
        if "playlist" in data and isinstance(data["playlist"], list):
            save_playlist_file(load_config().get("PLAYLIST_FILE", "playlist.txt"), data["playlist"])

        return jsonify({"success": ok, "message": "Konfigurasi disimpan"})

    @app.route("/api/stream/start", methods=["POST"])
    def api_start_stream():
        data = request.json or {}
        is_test = data.get("test", False)
        args = ["--test"] if is_test else []
        ok, msg = run_stream_process(args)
        return jsonify({"success": ok, "message": msg})

    @app.route("/api/stream/stop", methods=["POST"])
    def api_stop_stream():
        ok, msg = stop_stream_process()
        return jsonify({"success": ok, "message": msg})

    @app.route("/api/stream/logs", methods=["GET"])
    def api_stream_logs():
        global STREAM_PROCESS, STREAM_LOGS
        is_running = STREAM_PROCESS is not None and STREAM_PROCESS.poll() is None
        return jsonify({
            "running": is_running,
            "logs": STREAM_LOGS[-50:]
        })

    print(f"\n{C.CYAN}╔══════════════════════════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.CYAN}║{C.BOLD}{C.GREEN}         🌐 WEB DASHBOARD STREAMING AKTIF BERJALAN                {C.RESET}{C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}╚══════════════════════════════════════════════════════════════════╝{C.RESET}")
    print(f"\n{C.BOLD}Buka browser di HP Anda dan kunjungi salah satu URL ini:{C.RESET}")
    print(f"  👉 {C.CYAN}{C.BOLD}http://localhost:{port}{C.RESET}")
    print(f"  👉 {C.CYAN}{C.BOLD}http://127.0.0.1:{port}{C.RESET}\n")
    print(f"{C.DIM}Tekan Ctrl + C untuk keluar dari mode Web Dashboard.{C.RESET}\n")

    app.run(host="0.0.0.0", port=port, debug=False)


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--web", "-w"):
        port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 5000
        run_web_server(port)
    else:
        main_cli()
