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
import socket
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
# Full Featured: Upload, Ganti, Atur Video & Musik, Akses Perangkat Lain (LAN/Wi-Fi)
# ==============================================================================

def get_local_ip_addresses() -> list:
    """Mendeteksi IP lokal perangkat (Wi-Fi, Hotspot, LAN) untuk akses perangkat lain."""
    ips = []
    # 1. Socket UDP dummy
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith('127.'):
            ips.append(ip)
    except Exception:
        pass
    # 2. Perintah ip route / ip addr show
    try:
        out = subprocess.check_output(['ip', '-4', 'addr', 'show'], text=True, stderr=subprocess.DEVNULL)
        for match in re.finditer(r'inet\s+(\d+\.\d+\.\d+\.\d+)', out):
            ip = match.group(1)
            if not ip.startswith('127.') and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips if ips else ['127.0.0.1']


def get_all_videos(cur_v: str = "") -> list:
    """Mengumpulkan semua video dari folder video/, video aktif, dan direktori proyek."""
    cur_v_clean = cur_v.strip() if cur_v else ""
    v_dir = BASE_DIR / "video"
    v_dir.mkdir(parents=True, exist_ok=True)
    videos = []
    seen = set()

    # 1. Video aktif yang sedang disetel di config.env
    if cur_v_clean:
        p_cur = Path(cur_v_clean)
        if not p_cur.is_absolute():
            p_cur = BASE_DIR / p_cur
        if p_cur.exists() and p_cur.is_file():
            seen.add(str(p_cur.resolve()))
            size_mb = round(p_cur.stat().st_size / (1024 * 1024), 1)
            videos.append({
                "filename": p_cur.name,
                "path": cur_v_clean,
                "full_path": str(p_cur),
                "is_active": True,
                "size_mb": size_mb,
                "is_project_folder": str(v_dir.resolve()) in str(p_cur.resolve().parent)
            })

    # 2. Video di dalam folder video/
    for p in sorted(v_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            res = str(p.resolve())
            if res in seen:
                continue
            seen.add(res)
            rel = f"video/{p.name}"
            is_active = (cur_v_clean == rel or cur_v_clean == str(p) or (not cur_v_clean and len(videos) == 0))
            size_mb = round(p.stat().st_size / (1024 * 1024), 1)
            videos.append({
                "filename": p.name,
                "path": rel,
                "full_path": str(p),
                "is_active": is_active,
                "size_mb": size_mb,
                "is_project_folder": True
            })

    # 3. Video di root proyek
    for p in sorted(BASE_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            res = str(p.resolve())
            if res in seen:
                continue
            seen.add(res)
            rel = p.name
            is_active = (cur_v_clean == rel or cur_v_clean == str(p))
            size_mb = round(p.stat().st_size / (1024 * 1024), 1)
            videos.append({
                "filename": p.name,
                "path": rel,
                "full_path": str(p),
                "is_active": is_active,
                "size_mb": size_mb,
                "is_project_folder": False
            })

    return videos


def get_all_music(m_dir_str: str, playlist_tracks: list) -> list:
    """Mengumpulkan semua file musik dari folder musik aktif dan folder music/ proyek."""
    m_path = Path(m_dir_str)
    if not m_path.is_absolute():
        m_path = BASE_DIR / m_dir_str

    tracks = []
    seen = set()

    if m_path.exists() and m_path.is_dir():
        for p in sorted(m_path.iterdir()):
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                seen.add(p.name)
                tracks.append({
                    "filename": p.name,
                    "path": str(p),
                    "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                    "in_playlist": p.name in playlist_tracks,
                    "folder": str(m_path)
                })

    # Juga periksa folder music/ bawaan jika berbeda dari MUSIC_DIR
    proj_music = BASE_DIR / "music"
    if proj_music.exists() and proj_music != m_path:
        for p in sorted(proj_music.iterdir()):
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS and p.name not in seen:
                tracks.append({
                    "filename": p.name,
                    "path": f"music/{p.name}",
                    "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                    "in_playlist": p.name in playlist_tracks,
                    "folder": "music"
                })

    return tracks


WEB_HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Stream Studio - Live 24/7 Dashboard</title>
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: #151e2e;
            --card-sub: #1a2436;
            --card-border: #233044;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --accent: #10b981;
            --accent-hover: #059669;
            --danger: #ef4444;
            --danger-hover: #dc2626;
            --warning: #f59e0b;
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
            --text-muted: #64748b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        body { background-color: var(--bg-color); color: var(--text-main); padding: 12px; padding-bottom: 120px; }
        .container { max-width: 820px; margin: 0 auto; }
        
        /* HEADER */
        .header { text-align: center; padding: 16px 0 12px 0; border-bottom: 1px solid var(--card-border); margin-bottom: 16px; }
        .header h1 { font-size: 1.45rem; color: #fff; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .header p { font-size: 0.85rem; color: var(--text-dim); margin-top: 4px; }
        
        /* NETWORK CARD */
        .network-card {
            background: linear-gradient(135deg, rgba(30, 58, 138, 0.4) 0%, rgba(15, 23, 42, 0.9) 100%);
            border: 1px solid #3b82f6;
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 18px;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.15);
        }
        .network-title { display: flex; align-items: center; justify-content: space-between; font-size: 0.92rem; font-weight: 600; color: #93c5fd; margin-bottom: 8px; }
        .network-row { display: flex; gap: 8px; align-items: center; }
        .network-input { flex: 1; padding: 9px 12px; background: #080d1a; border: 1px solid #1e3a8a; border-radius: 8px; color: #60a5fa; font-family: monospace; font-size: 0.95rem; font-weight: bold; outline: none; }
        .network-hint { font-size: 0.76rem; color: #94a3b8; margin-top: 6px; line-height: 1.4; }
        
        /* NAVIGATION TABS */
        .tabs { display: flex; gap: 6px; overflow-x: auto; margin-bottom: 16px; padding-bottom: 4px; scrollbar-width: none; }
        .tabs::-webkit-scrollbar { display: none; }
        .tab-btn {
            flex: 1; min-width: 100px; padding: 10px 8px; background: var(--card-bg); border: 1px solid var(--card-border);
            border-radius: 10px; color: var(--text-dim); font-size: 0.85rem; font-weight: 600; cursor: pointer;
            text-align: center; white-space: nowrap; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px;
        }
        .tab-btn:hover { background: var(--card-sub); color: #fff; }
        .tab-btn.active { background: var(--primary); color: #fff; border-color: var(--primary); box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3); }
        
        /* TAB PANES */
        .tab-pane { display: none; }
        .tab-pane.active { display: block; animation: fadeIn 0.25s ease-in-out; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        
        /* CARDS */
        .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.25); }
        .card-title { font-size: 1.05rem; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
        
        /* BADGES */
        .badge { font-size: 0.72rem; padding: 3px 8px; border-radius: 9999px; background: #334155; color: #e2e8f0; font-weight: 500; display: inline-flex; align-items: center; gap: 4px; }
        .badge.green { background: #065f46; color: #6ee7b7; border: 1px solid #059669; }
        .badge.yellow { background: #78350f; color: #fde68a; border: 1px solid #d97706; }
        .badge.blue { background: #1e3a8a; color: #93c5fd; border: 1px solid #2563eb; }
        .badge.red { background: #7f1d1d; color: #fca5a5; border: 1px solid #dc2626; }
        
        /* FORM ELEMENTS */
        .form-group { margin-bottom: 14px; }
        label { display: block; font-size: 0.85rem; color: var(--text-dim); margin-bottom: 6px; font-weight: 500; }
        input[type="text"], input[type="password"], select {
            width: 100%; padding: 10px 12px; background: #0b0f19; border: 1px solid var(--card-border);
            border-radius: 8px; color: #fff; font-size: 0.92rem; outline: none; transition: border-color 0.2s;
        }
        input[type="text"]:focus, input[type="password"]:focus, select:focus { border-color: var(--primary); }
        .input-row { display: flex; gap: 8px; }
        
        /* BUTTONS */
        .btn {
            padding: 10px 16px; border-radius: 8px; font-size: 0.88rem; font-weight: 600; border: none; cursor: pointer;
            text-align: center; display: inline-flex; align-items: center; justify-content: center; gap: 6px; transition: 0.2s;
        }
        .btn-primary { background: var(--primary); color: #fff; }
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-success { background: var(--accent); color: #fff; }
        .btn-success:hover { background: var(--accent-hover); }
        .btn-danger { background: var(--danger); color: #fff; }
        .btn-danger:hover { background: var(--danger-hover); }
        .btn-warning { background: var(--warning); color: #000; }
        .btn-sub { background: #334155; color: #f1f5f9; }
        .btn-sub:hover { background: #475569; }
        .btn-mini { padding: 4px 10px; font-size: 0.78rem; border-radius: 6px; }
        .btn-group { display: flex; gap: 8px; }
        
        /* SLIDERS */
        .slider-container { display: flex; align-items: center; gap: 12px; }
        input[type="range"] { flex: 1; accent-color: var(--primary); height: 6px; border-radius: 4px; }
        .slider-val { min-width: 52px; font-weight: bold; color: var(--accent); text-align: right; font-size: 1rem; }
        
        /* RADIO GRID */
        .radio-group { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 6px; }
        .radio-btn { border: 1px solid var(--card-border); padding: 10px; border-radius: 8px; font-size: 0.84rem; text-align: center; cursor: pointer; transition: all 0.2s; background: #0b0f19; }
        .radio-btn.active { border-color: var(--primary); background: rgba(59, 130, 246, 0.15); color: #93c5fd; font-weight: 600; }
        
        /* UPLOAD DROP ZONE */
        .dropzone {
            border: 2px dashed #334155; border-radius: 12px; padding: 22px 16px; text-align: center;
            background: #0d1322; cursor: pointer; transition: all 0.2s; margin-bottom: 12px;
        }
        .dropzone:hover, .dropzone.dragover { border-color: var(--primary); background: rgba(59, 130, 246, 0.08); }
        .dropzone-icon { font-size: 2.2rem; margin-bottom: 8px; }
        .dropzone-text { font-size: 0.9rem; font-weight: 600; color: #e2e8f0; }
        .dropzone-sub { font-size: 0.76rem; color: var(--text-dim); margin-top: 4px; }
        .file-chosen-box { font-size: 0.82rem; color: #93c5fd; margin-top: 8px; padding: 6px; background: rgba(59,130,246,0.1); border-radius: 6px; display: none; }
        
        /* PROGRESS BAR */
        .progress-box { margin-top: 10px; display: none; }
        .progress-bar-bg { width: 100%; height: 8px; background: #1e293b; border-radius: 9999px; overflow: hidden; }
        .progress-bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, #3b82f6, #10b981); transition: width 0.15s ease; }
        .progress-text { font-size: 0.78rem; color: var(--text-dim); margin-top: 4px; display: flex; justify-content: space-between; }
        
        /* MEDIA LIST ITEMS */
        .media-list { list-style: none; max-height: 340px; overflow-y: auto; border: 1px solid var(--card-border); border-radius: 8px; background: #0b0f19; }
        .media-item { display: flex; align-items: center; justify-content: space-between; padding: 11px 12px; border-bottom: 1px solid #1a2436; font-size: 0.85rem; gap: 8px; }
        .media-item:last-child { border-bottom: none; }
        .media-item.active-item { background: rgba(16, 185, 129, 0.08); border-left: 3px solid var(--accent); }
        .media-info { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .media-title { font-weight: 500; color: #f8fafc; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .media-meta { font-size: 0.72rem; color: var(--text-dim); margin-top: 2px; }
        .media-actions { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
        
        /* VIDEO PREVIEW PLAYER */
        .video-player-wrap { width: 100%; border-radius: 8px; overflow: hidden; background: #000; margin-bottom: 12px; border: 1px solid var(--card-border); }
        video { width: 100%; max-height: 280px; display: block; }
        .meta-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
        .chip { background: #0f172a; border: 1px solid #1e293b; font-size: 0.74rem; padding: 4px 8px; border-radius: 6px; color: #cbd5e1; }
        
        /* BOTTOM FLOATING AUDIO PLAYER */
        .bottom-audio-bar {
            position: fixed; bottom: 0; left: 0; right: 0; background: rgba(15, 23, 42, 0.96);
            backdrop-filter: blur(12px); border-top: 1px solid #334155; padding: 10px 16px;
            display: none; z-index: 999; box-shadow: 0 -4px 16px rgba(0,0,0,0.5);
        }
        .audio-bar-inner { max-width: 820px; margin: 0 auto; display: flex; align-items: center; gap: 12px; }
        .audio-track-info { flex: 1; min-width: 0; }
        .audio-track-title { font-size: 0.85rem; font-weight: 600; color: #fff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .audio-track-time { font-size: 0.72rem; color: var(--text-dim); }
        
        /* TERMINAL LOG BOX */
        .terminal-box { background: #050811; border: 1px solid #1e293b; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 0.75rem; color: #10b981; height: 180px; overflow-y: auto; white-space: pre-wrap; margin-top: 10px; line-height: 1.4; }
        
        /* TOAST NOTIFICATION */
        .toast {
            position: fixed; bottom: 85px; left: 50%; transform: translateX(-50%); background: #10b981;
            color: #fff; padding: 10px 22px; border-radius: 30px; font-size: 0.88rem; font-weight: 500;
            display: none; box-shadow: 0 10px 25px -3px rgba(0,0,0,0.6); z-index: 10000; text-align: center;
        }
        .toast.error { background: #ef4444; }
    </style>
</head>
<body>
    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <h1>🎬 Stream Studio 24/7</h1>
            <p>Pusat Kontrol Live Streaming, Upload & Pengelolaan Media</p>
        </div>

        <!-- NETWORK ACCESS BANNER -->
        <div class="network-card">
            <div class="network-title">
                <span>🌐 Akses Dari Perangkat Lain (Laptop / HP di Wi-Fi yang sama)</span>
                <span class="badge blue">Port 5000</span>
            </div>
            <div class="network-row">
                <input type="text" id="networkUrlInput" class="network-input" readonly value="Memuat alamat IP...">
                <button class="btn btn-primary" onclick="copyNetworkUrl()">📋 Salin Link</button>
            </div>
            <div class="network-hint">
                💡 <strong>Tips:</strong> Pastikan laptop, PC, atau HP lain terhubung ke Wi-Fi atau Hotspot HP yang sama, lalu buka alamat link di atas di browser (Chrome / Safari / Edge).
            </div>
        </div>

        <!-- NAVIGATION TABS -->
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('video')">📹 Video</button>
            <button class="tab-btn" onclick="switchTab('music')">🎵 Musik</button>
            <button class="tab-btn" onclick="switchTab('playlist')">📋 Playlist</button>
            <button class="tab-btn" onclick="switchTab('mixer')">🎛️ Mixer & Audio</button>
            <button class="tab-btn" onclick="switchTab('stream')">🚀 Siaran Langsung</button>
        </div>

        <!-- ========================================== -->
        <!-- TAB 1: KELOLA VIDEO                        -->
        <!-- ========================================== -->
        <div class="tab-pane active" id="tab-video">
            <!-- ACTIVE VIDEO PREVIEW CARD -->
            <div class="card">
                <div class="card-title">
                    <span>📹 Video Background Aktif</span>
                    <span id="activeVideoBadge" class="badge green">Aktif</span>
                </div>
                <div class="video-player-wrap">
                    <video id="videoPreviewPlayer" controls playsinline preload="metadata">
                        Browser Anda tidak mendukung tag video HTML5.
                    </video>
                </div>
                <div class="meta-chips" id="videoMetaChips">
                    <span class="chip" id="vchip-file">File: -</span>
                    <span class="chip" id="vchip-res">Resolusi: -</span>
                    <span class="chip" id="vchip-fps">FPS: -</span>
                    <span class="chip" id="vchip-dur">Durasi: -</span>
                    <span class="chip" id="vchip-size">Ukuran: -</span>
                    <span class="chip" id="vchip-audio">Audio: -</span>
                </div>
            </div>

            <!-- UPLOAD VIDEO CARD -->
            <div class="card">
                <div class="card-title">
                    <span>⬆️ Upload Video Baru</span>
                    <span class="badge">MP4, MKV, MOV, WEBM</span>
                </div>
                <div class="dropzone" id="videoDropZone" onclick="document.getElementById('videoFileInput').click()">
                    <div class="dropzone-icon">📁</div>
                    <div class="dropzone-text">Tarik file video ke sini, atau klik untuk memilih</div>
                    <div class="dropzone-sub">Mendukung file video resolusi 1080p, 720p (Otomatis auto-scale ke 1080p)</div>
                    <div class="file-chosen-box" id="videoChosenText"></div>
                </div>
                <input type="file" id="videoFileInput" accept=".mp4,.mkv,.mov,.webm,.ts" style="display:none;" onchange="onVideoFileSelected(this)">
                
                <div style="margin: 10px 0;">
                    <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
                        <input type="checkbox" id="videoSetActiveCheckbox" checked style="accent-color:var(--primary); width:18px; height:18px;">
                        <span>Langsung jadikan video ini sebagai video aktif setelah selesai diupload</span>
                    </label>
                </div>

                <div class="progress-box" id="videoProgressBox">
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" id="videoProgressBar"></div>
                    </div>
                    <div class="progress-text">
                        <span id="videoProgressPct">0%</span>
                        <span id="videoProgressSize">0 MB / 0 MB</span>
                    </div>
                </div>

                <button class="btn btn-primary" id="btnUploadVideo" onclick="submitVideoUpload()" style="width:100%; margin-top:8px;" disabled>
                    ⬆️ Unggah Video Sekarang
                </button>
            </div>

            <!-- GALLERY / AVAILABLE VIDEOS CARD -->
            <div class="card">
                <div class="card-title">
                    <span>🎬 Daftar Koleksi Video</span>
                    <button class="btn btn-sub btn-mini" onclick="loadMedia()">🔄 Refresh</button>
                </div>
                <ul class="media-list" id="videoListItems">
                    <li style="padding:15px; text-align:center; color:var(--text-dim);">Memuat video...</li>
                </ul>
            </div>
        </div>

        <!-- ========================================== -->
        <!-- TAB 2: KELOLA MUSIK                        -->
        <!-- ========================================== -->
        <div class="tab-pane" id="tab-music">
            <!-- UPLOAD MUSIC CARD -->
            <div class="card">
                <div class="card-title">
                    <span>⬆️ Upload Lagu / Musik Baru</span>
                    <span class="badge">Multi-Upload (Bisa Banyak)</span>
                </div>
                <div class="dropzone" id="musicDropZone" onclick="document.getElementById('musicFileInput').click()">
                    <div class="dropzone-icon">🎵</div>
                    <div class="dropzone-text">Tarik file audio ke sini, atau klik untuk memilih lagu</div>
                    <div class="dropzone-sub">Mendukung MP3, M4A, WAV, FLAC, AAC, OGG, OPUS (Bisa pilih sekaligus banyak)</div>
                    <div class="file-chosen-box" id="musicChosenText"></div>
                </div>
                <input type="file" id="musicFileInput" accept=".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus" multiple style="display:none;" onchange="onMusicFilesSelected(this)">
                
                <div style="margin: 10px 0;">
                    <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
                        <input type="checkbox" id="musicAddToPlaylistCheckbox" checked style="accent-color:var(--primary); width:18px; height:18px;">
                        <span>Otomatis tambahkan lagu yang diunggah ke dalam Playlist</span>
                    </label>
                </div>

                <div class="progress-box" id="musicProgressBox">
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" id="musicProgressBar"></div>
                    </div>
                    <div class="progress-text">
                        <span id="musicProgressPct">0%</span>
                        <span id="musicProgressSize">Mengunggah...</span>
                    </div>
                </div>

                <button class="btn btn-success" id="btnUploadMusic" onclick="submitMusicUpload()" style="width:100%; margin-top:8px;" disabled>
                    ⬆️ Unggah Lagu Sekarang
                </button>
            </div>

            <!-- MUSIC LIBRARY CARD -->
            <div class="card">
                <div class="card-title">
                    <span>📂 Koleksi File Musik</span>
                    <span id="musicCountBadge" class="badge green">0 Lagu</span>
                </div>
                <div class="form-group" style="margin-bottom:10px;">
                    <input type="text" id="musicSearchInput" placeholder="🔍 Cari nama lagu..." oninput="filterMusicList()">
                </div>
                <ul class="media-list" id="musicListItems">
                    <li style="padding:15px; text-align:center; color:var(--text-dim);">Memuat musik...</li>
                </ul>
            </div>
        </div>

        <!-- ========================================== -->
        <!-- TAB 3: URUTAN PLAYLIST                    -->
        <!-- ========================================== -->
        <div class="tab-pane" id="tab-playlist">
            <div class="card">
                <div class="card-title">
                    <span>📋 Urutan Putar Playlist</span>
                    <span id="playlistCountBadge" class="badge blue">0 Lagu</span>
                </div>
                <div class="btn-group" style="margin-bottom:12px;">
                    <button class="btn btn-sub btn-mini" onclick="shufflePlaylistOrder()">🎲 Acak (Shuffle)</button>
                    <button class="btn btn-sub btn-mini" onclick="sortPlaylistOrder('asc')">🔤 Urut A-Z</button>
                    <button class="btn btn-sub btn-mini" onclick="sortPlaylistOrder('desc')">🔃 Urut Z-A</button>
                    <button class="btn btn-sub btn-mini" onclick="syncPlaylistFromFolder()">🔄 Muat Semua</button>
                </div>
                <ul class="media-list" id="playlistListItems" style="max-height: 420px;">
                    <li style="padding:15px; text-align:center; color:var(--text-dim);">Memuat urutan playlist...</li>
                </ul>
                <button class="btn btn-primary" onclick="savePlaylistOrder()" style="width:100%; margin-top:14px;">
                    💾 Simpan Urutan Playlist (playlist.txt)
                </button>
            </div>
        </div>

        <!-- ========================================== -->
        <!-- TAB 4: MIXER & AUDIO                      -->
        <!-- ========================================== -->
        <div class="tab-pane" id="tab-mixer">
            <div class="card">
                <div class="card-title">
                    <span>🔊 Pengaturan Volume & Mixer</span>
                    <span class="badge">Live Mixer</span>
                </div>
                <!-- VIDEO VOLUME -->
                <div class="form-group">
                    <label>Volume Audio Video Background: <span id="mixVideoVolLabel" style="color:var(--accent); font-weight:bold;">0%</span></label>
                    <div class="slider-container">
                        <input type="range" id="mixVideoVolRange" min="0" max="200" value="0" oninput="updateMixVideoVol(this.value)">
                        <div class="slider-val" id="mixVideoVolVal">0%</div>
                    </div>
                    <small style="color:var(--text-dim); font-size:0.75rem;">0% = Mute/Senyap (Suara murni dari lagu). Jika video memiliki suara, naikkan slider ini untuk me-mix dengan musik.</small>
                </div>

                <!-- MUSIC VOLUME -->
                <div class="form-group" style="margin-top:18px;">
                    <label>Volume Playlist Musik: <span id="mixMusicVolLabel" style="color:var(--accent); font-weight:bold;">100%</span></label>
                    <div class="slider-container">
                        <input type="range" id="mixMusicVolRange" min="0" max="200" value="100" oninput="updateMixMusicVol(this.value)">
                        <div class="slider-val" id="mixMusicVolVal">100%</div>
                    </div>
                </div>

                <!-- PLAYLIST MODE -->
                <div class="form-group" style="margin-top:18px;">
                    <label>Mode Pemutaran Playlist Musik:</label>
                    <div class="radio-group">
                        <div class="radio-btn" id="pmode-shuffle" onclick="selectPlaylistMode('shuffle')">🔁 Acak Setiap Putaran</div>
                        <div class="radio-btn" id="pmode-alphabetical" onclick="selectPlaylistMode('alphabetical')">🔤 Abjad (A - Z)</div>
                        <div class="radio-btn" id="pmode-reverse" onclick="selectPlaylistMode('reverse')">🔃 Terbalik (Z - A)</div>
                        <div class="radio-btn" id="pmode-custom" onclick="selectPlaylistMode('custom')">📋 Urutan Kustom (playlist.txt)</div>
                    </div>
                </div>

                <!-- FOLDER LOCATION EDIT -->
                <div class="form-group" style="margin-top:18px;">
                    <label>Path Lokasi Folder Musik di HP:</label>
                    <input type="text" id="mixMusicDirInput" placeholder="music atau /storage/emulated/0/Download/Suno">
                </div>

                <button class="btn btn-primary" onclick="saveMixerConfig()" style="width:100%; margin-top:12px;">
                    💾 Simpan Pengaturan Mixer
                </button>
            </div>
        </div>

        <!-- ========================================== -->
        <!-- TAB 5: KONTROL SIARAN & LOG               -->
        <!-- ========================================== -->
        <div class="tab-pane" id="tab-stream">
            <div class="card">
                <div class="card-title">
                    <span>🔑 Kunci Siaran & Server RTMP</span>
                    <span class="badge blue">YouTube / RTMP</span>
                </div>
                <div class="form-group">
                    <label>YouTube Stream Key:</label>
                    <div class="input-row">
                        <input type="password" id="cfgStreamKey" placeholder="tempel stream key YouTube di sini">
                        <button class="btn btn-sub btn-mini" onclick="toggleStreamKeyVisibility()" style="padding:0 14px;">👁️</button>
                    </div>
                </div>
                <div class="form-group">
                    <label>RTMP Target URL Server:</label>
                    <select id="cfgRtmpUrl">
                        <option value="rtmp://a.rtmp.youtube.com/live2">YouTube RTMP (Standar)</option>
                        <option value="rtmps://a.rtmp.youtube.com/live2">YouTube RTMPS (Aman SSL)</option>
                        <option value="rtmps://live-api-s.facebook.com:443/rtmp/">Facebook Live</option>
                        <option value="rtmp://live.twitch.tv/app/">Twitch</option>
                    </select>
                </div>
                <button class="btn btn-sub" onclick="saveStreamKeyConfig()" style="width:100%;">
                    💾 Simpan Stream Key & RTMP
                </button>
            </div>

            <!-- LIVE CONTROL CARD -->
            <div class="card">
                <div class="card-title">
                    <span>🚀 Kontrol Siaran Langsung</span>
                    <span id="streamLiveBadge" class="badge">Standby</span>
                </div>
                <div class="btn-group">
                    <button class="btn btn-success" style="flex:1;" onclick="startLiveStream(false)">▶️ Mulai Live</button>
                    <button class="btn btn-warning" style="flex:1;" onclick="startLiveStream(true)">🧪 Tes 15s</button>
                    <button class="btn btn-danger" style="flex:1;" onclick="stopLiveStream()">⏹️ Stop</button>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:14px;">
                    <label style="margin:0;">Log Konsol FFmpeg / Terminal:</label>
                    <button class="btn btn-sub btn-mini" onclick="pollStreamLogs()">🔄 Segarkan</button>
                </div>
                <div class="terminal-box" id="streamLogTerminal">Menunggu informasi siaran...</div>
            </div>
        </div>
    </div>

    <!-- FLOATING BOTTOM AUDIO PLAYER BAR -->
    <div class="bottom-audio-bar" id="bottomAudioBar">
        <div class="audio-bar-inner">
            <button class="btn btn-primary btn-mini" id="btnAudioPlayPause" onclick="toggleAudioPlayback()" style="width:36px; height:36px; border-radius:50%; padding:0;">
                ▶️
            </button>
            <div class="audio-track-info">
                <div class="audio-track-title" id="audioPlayerTitle">Judul Lagu</div>
                <div class="audio-track-time" id="audioPlayerTime">00:00 / 00:00</div>
            </div>
            <audio id="globalHtmlAudio" ontimeupdate="onAudioTimeUpdate()" onended="onAudioEnded()"></audio>
            <button class="btn btn-sub btn-mini" onclick="closeAudioPlayer()" style="border-radius:50%; width:30px; height:30px; padding:0;">✕</button>
        </div>
    </div>

    <!-- TOAST NOTIFICATION -->
    <div class="toast" id="toastBox">Notifikasi</div>

    <script>
        let currentConfig = {};
        let allVideos = [];
        let allMusic = [];
        let playlistData = [];
        let activePlaylistMode = "shuffle";
        let activePlayingPath = "";

        // TABS
        function switchTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            
            const btn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick').includes(tabId));
            if (btn) btn.classList.add('active');
            
            const pane = document.getElementById('tab-' + tabId);
            if (pane) pane.classList.add('active');
        }

        // TOAST
        function showToast(msg, type = "success") {
            const t = document.getElementById('toastBox');
            t.innerText = msg;
            t.className = type === "error" ? "toast error" : "toast";
            t.style.display = "block";
            setTimeout(() => { t.style.display = "none"; }, 3000);
        }

        // COPY NETWORK URL
        function copyNetworkUrl() {
            const inp = document.getElementById('networkUrlInput');
            inp.select();
            inp.setSelectionRange(0, 99999);
            if (navigator.clipboard) {
                navigator.clipboard.writeText(inp.value).then(() => {
                    showToast("✅ Link berhasil disalin!");
                }).catch(() => {
                    document.execCommand("copy");
                    showToast("✅ Link berhasil disalin!");
                });
            } else {
                document.execCommand("copy");
                showToast("✅ Link berhasil disalin!");
            }
        }

        // TOGGLE STREAM KEY
        function toggleStreamKeyVisibility() {
            const el = document.getElementById('cfgStreamKey');
            el.type = el.type === 'password' ? 'text' : 'password';
        }

        // SLIDER UPDATE FUNCTIONS
        function updateMixVideoVol(val) {
            document.getElementById('mixVideoVolLabel').innerText = val + '%';
            document.getElementById('mixVideoVolVal').innerText = val + '%';
        }
        function updateMixMusicVol(val) {
            document.getElementById('mixMusicVolLabel').innerText = val + '%';
            document.getElementById('mixMusicVolVal').innerText = val + '%';
        }
        function selectPlaylistMode(mode) {
            activePlaylistMode = mode;
            document.querySelectorAll('.radio-btn').forEach(b => b.classList.remove('active'));
            const b = document.getElementById('pmode-' + mode);
            if (b) b.classList.add('active');
        }

        // LOAD NETWORK INFO
        async function loadNetworkInfo() {
            try {
                const res = await fetch('/api/network_info');
                const data = await res.json();
                if (data.urls && data.urls.length > 0) {
                    document.getElementById('networkUrlInput').value = data.urls[0];
                } else {
                    document.getElementById('networkUrlInput').value = data.local_url;
                }
            } catch (e) {
                console.error(e);
            }
        }

        // LOAD DATA & MEDIA
        async function loadData() {
            try {
                const res = await fetch('/api/config');
                const data = await res.json();
                currentConfig = data.config || {};
                
                document.getElementById('cfgStreamKey').value = currentConfig.STREAM_KEY || '';
                document.getElementById('cfgRtmpUrl').value = currentConfig.RTMP_URL || 'rtmp://a.rtmp.youtube.com/live2';
                document.getElementById('mixMusicDirInput').value = currentConfig.MUSIC_DIR || 'music';

                const vVol = Math.round(parseFloat(currentConfig.VIDEO_VOLUME || '0.0') * 100);
                document.getElementById('mixVideoVolRange').value = vVol;
                updateMixVideoVol(vVol);

                const mVol = Math.round(parseFloat(currentConfig.MUSIC_VOLUME || '1.0') * 100);
                document.getElementById('mixMusicVolRange').value = mVol;
                updateMixMusicVol(mVol);

                selectPlaylistMode(currentConfig.PLAYLIST_MODE || 'shuffle');
                
                // Update active video player & chips
                updateActiveVideoDisplay(data.video_info, currentConfig.VIDEO_FILE);

                await loadMedia();
            } catch (e) {
                console.error(e);
            }
        }

        function updateActiveVideoDisplay(vinfo, vpath) {
            const player = document.getElementById('videoPreviewPlayer');
            const badge = document.getElementById('activeVideoBadge');
            
            if (vinfo && vinfo.exists) {
                const videoSrc = '/api/media/stream/video?path=' + encodeURIComponent(vinfo.path || vpath);
                if (player.src !== window.location.origin + videoSrc) {
                    player.src = videoSrc;
                }
                badge.className = "badge green";
                badge.innerText = "✓ Siap Live";

                document.getElementById('vchip-file').innerText = "File: " + (vinfo.filename || vpath);
                document.getElementById('vchip-res').innerText = "Resolusi: " + (vinfo.width ? `${vinfo.width}x${vinfo.height}` : "1080p Target");
                document.getElementById('vchip-fps').innerText = "FPS: " + (vinfo.fps || "30");
                document.getElementById('vchip-dur').innerText = "Durasi: " + (vinfo.duration ? `${vinfo.duration}s` : "-");
                document.getElementById('vchip-size').innerText = "Ukuran: " + (vinfo.size_mb ? `${vinfo.size_mb} MB` : "-");
                document.getElementById('vchip-audio').innerText = "Audio: " + (vinfo.has_audio ? (vinfo.audio_codec || "Ada") : "Bisu");
            } else {
                badge.className = "badge yellow";
                badge.innerText = "Pilih Video";
                document.getElementById('vchip-file').innerText = "File: Belum Dipilih";
            }
        }

        // LOAD MEDIA (VIDEOS, MUSIC, PLAYLIST)
        async function loadMedia() {
            try {
                const res = await fetch('/api/media/list');
                const data = await res.json();
                allVideos = data.videos || [];
                allMusic = data.music || [];
                playlistData = data.playlist || [];

                renderVideoList();
                renderMusicList();
                renderPlaylistList();
                
                if (data.active_video_info) {
                    updateActiveVideoDisplay(data.active_video_info, data.active_video);
                }
            } catch (e) {
                console.error(e);
            }
        }

        // RENDER VIDEO LIST
        function renderVideoList() {
            const ul = document.getElementById('videoListItems');
            if (!allVideos || allVideos.length === 0) {
                ul.innerHTML = '<li style="padding:15px; text-align:center; color:var(--text-dim);">Belum ada file video. Silakan upload video di atas.</li>';
                return;
            }
            ul.innerHTML = '';
            allVideos.forEach(v => {
                const li = document.createElement('li');
                li.className = 'media-item' + (v.is_active ? ' active-item' : '');
                
                let activeBtn = v.is_active 
                    ? '<span class="badge green">✓ AKTIF</span>' 
                    : `<button class="btn btn-primary btn-mini" onclick="selectActiveVideo('${encodeURIComponent(v.path)}')">⭐ Jadikan Aktif</button>`;
                
                li.innerHTML = `
                    <div class="media-info">
                        <div class="media-title">🎬 ${v.filename}</div>
                        <div class="media-meta">${v.size_mb} MB • ${v.path}</div>
                    </div>
                    <div class="media-actions">
                        ${activeBtn}
                        <button class="btn btn-sub btn-mini" onclick="previewVideoFile('${encodeURIComponent(v.path)}')">👁️ Tonton</button>
                        <button class="btn btn-danger btn-mini" onclick="deleteVideoFile('${encodeURIComponent(v.path)}', '${v.filename}')">🗑️</button>
                    </div>
                `;
                ul.appendChild(li);
            });
        }

        // RENDER MUSIC LIST
        function renderMusicList(filterQuery = "") {
            const ul = document.getElementById('musicListItems');
            document.getElementById('musicCountBadge').innerText = allMusic.length + " Lagu";
            
            const filtered = filterQuery 
                ? allMusic.filter(m => m.filename.toLowerCase().includes(filterQuery.toLowerCase()))
                : allMusic;

            if (!filtered || filtered.length === 0) {
                ul.innerHTML = '<li style="padding:15px; text-align:center; color:var(--text-dim);">' + 
                    (filterQuery ? 'Tidak ada lagu yang cocok dengan pencarian.' : 'Belum ada file lagu. Silakan upload lagu di atas.') + '</li>';
                return;
            }
            
            ul.innerHTML = '';
            filtered.forEach(m => {
                const li = document.createElement('li');
                li.className = 'media-item';
                
                const isPlaying = activePlayingPath === m.path;
                const playBtnText = isPlaying ? "⏸️" : "▶️";
                const inPlBadge = m.in_playlist 
                    ? '<span class="badge blue">Di Playlist</span>'
                    : '<span class="badge">Belum Masuk</span>';
                    
                const togglePlBtn = m.in_playlist
                    ? `<button class="btn btn-sub btn-mini" onclick="togglePlaylistItem('${encodeURIComponent(m.filename)}', 'remove')">➖ Keluarkan</button>`
                    : `<button class="btn btn-success btn-mini" onclick="togglePlaylistItem('${encodeURIComponent(m.filename)}', 'add')">➕ Tambah</button>`;

                li.innerHTML = `
                    <button class="btn btn-sub btn-mini" onclick="playAudioTrack('${encodeURIComponent(m.path)}', '${m.filename}')" style="border-radius:50%; width:32px; height:32px; padding:0;">
                        ${playBtnText}
                    </button>
                    <div class="media-info">
                        <div class="media-title">🎵 ${m.filename}</div>
                        <div class="media-meta">${m.size_mb} MB • ${inPlBadge}</div>
                    </div>
                    <div class="media-actions">
                        ${togglePlBtn}
                        <button class="btn btn-danger btn-mini" onclick="deleteMusicFile('${encodeURIComponent(m.filename)}')">🗑️</button>
                    </div>
                `;
                ul.appendChild(li);
            });
        }

        function filterMusicList() {
            const q = document.getElementById('musicSearchInput').value.trim();
            renderMusicList(q);
        }

        // RENDER PLAYLIST LIST
        function renderPlaylistList() {
            const ul = document.getElementById('playlistListItems');
            document.getElementById('playlistCountBadge').innerText = playlistData.length + " Lagu";
            
            if (!playlistData || playlistData.length === 0) {
                ul.innerHTML = '<li style="padding:15px; text-align:center; color:var(--text-dim);">Playlist masih kosong. Tambahkan lagu dari tab Musik.</li>';
                return;
            }

            ul.innerHTML = '';
            playlistData.forEach((track, idx) => {
                const li = document.createElement('li');
                li.className = 'media-item';
                li.innerHTML = `
                    <span style="font-weight:bold; color:var(--primary); width:28px;">${idx + 1}.</span>
                    <div class="media-info">
                        <div class="media-title">🎵 ${track}</div>
                    </div>
                    <div class="media-actions">
                        <button class="btn btn-sub btn-mini" onclick="movePlaylistItem(${idx}, -1)" ${idx === 0 ? 'disabled' : ''}>▲</button>
                        <button class="btn btn-sub btn-mini" onclick="movePlaylistItem(${idx}, 1)" ${idx === playlistData.length - 1 ? 'disabled' : ''}>▼</button>
                        <button class="btn btn-danger btn-mini" onclick="removeFromPlaylistByIndex(${idx})">➖</button>
                    </div>
                `;
                ul.appendChild(li);
            });
        }

        function movePlaylistItem(idx, dir) {
            const newIdx = idx + dir;
            if (newIdx < 0 || newIdx >= playlistData.length) return;
            const temp = playlistData[idx];
            playlistData[idx] = playlistData[newIdx];
            playlistData[newIdx] = temp;
            renderPlaylistList();
        }

        function removeFromPlaylistByIndex(idx) {
            playlistData.splice(idx, 1);
            renderPlaylistList();
            renderMusicList();
        }

        function shufflePlaylistOrder() {
            for (let i = playlistData.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [playlistData[i], playlistData[j]] = [playlistData[j], playlistData[i]];
            }
            renderPlaylistList();
            showToast("Urutan playlist diacak!");
        }

        function sortPlaylistOrder(dir = 'asc') {
            playlistData.sort((a, b) => dir === 'asc' ? a.localeCompare(b) : b.localeCompare(a));
            renderPlaylistList();
            showToast("Playlist diurutkan!");
        }

        function syncPlaylistFromFolder() {
            playlistData = allMusic.map(m => m.filename);
            renderPlaylistList();
            renderMusicList();
            showToast("Semua lagu dari folder dimasukkan ke playlist!");
        }

        async function savePlaylistOrder() {
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ playlist: playlistData })
                });
                const r = await res.json();
                if (r.success) {
                    showToast("✅ Urutan Playlist Berhasil Disimpan!");
                    loadMedia();
                } else {
                    showToast("Gagal menyimpan: " + r.message, "error");
                }
            } catch (e) {
                showToast("Error koneksi", "error");
            }
        }

        // SELECT ACTIVE VIDEO
        async function selectActiveVideo(pathEncoded) {
            const path = decodeURIComponent(pathEncoded);
            try {
                const res = await fetch('/api/video/select', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: path })
                });
                const r = await res.json();
                if (r.success) {
                    showToast("✅ " + r.message);
                    loadMedia();
                } else {
                    showToast("Gagal: " + r.message, "error");
                }
            } catch (e) {
                showToast("Error koneksi", "error");
            }
        }

        function previewVideoFile(pathEncoded) {
            const path = decodeURIComponent(pathEncoded);
            const player = document.getElementById('videoPreviewPlayer');
            player.src = '/api/media/stream/video?path=' + encodeURIComponent(path);
            player.play();
            showToast("Memutar preview video...");
        }

        // DELETE VIDEO
        async function deleteVideoFile(pathEncoded, filename) {
            const path = decodeURIComponent(pathEncoded);
            if (!confirm(`Hapus file video '${filename}' secara permanen?`)) return;
            try {
                const res = await fetch('/api/video/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: path })
                });
                const r = await res.json();
                if (r.success) {
                    showToast("🗑️ " + r.message);
                    loadMedia();
                } else {
                    showToast("Gagal: " + r.message, "error");
                }
            } catch (e) {
                showToast("Error koneksi", "error");
            }
        }

        // TOGGLE PLAYLIST ITEM
        async function togglePlaylistItem(filenameEncoded, action) {
            const filename = decodeURIComponent(filenameEncoded);
            try {
                const res = await fetch('/api/music/playlist/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: filename, action: action })
                });
                const r = await res.json();
                if (r.success) {
                    showToast(r.message);
                    loadMedia();
                }
            } catch (e) {
                showToast("Error koneksi", "error");
            }
        }

        // DELETE MUSIC
        async function deleteMusicFile(filenameEncoded) {
            const filename = decodeURIComponent(filenameEncoded);
            if (!confirm(`Hapus file lagu '${filename}' secara permanen?`)) return;
            try {
                const res = await fetch('/api/music/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: filename })
                });
                const r = await res.json();
                if (r.success) {
                    showToast("🗑️ " + r.message);
                    loadMedia();
                } else {
                    showToast("Gagal: " + r.message, "error");
                }
            } catch (e) {
                showToast("Error koneksi", "error");
            }
        }

        // UPLOAD VIDEO
        function onVideoFileSelected(input) {
            const file = input.files[0];
            const textEl = document.getElementById('videoChosenText');
            const btn = document.getElementById('btnUploadVideo');
            if (file) {
                const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
                textEl.innerText = `📄 ${file.name} (${sizeMB} MB)`;
                textEl.style.display = 'block';
                btn.disabled = false;
            } else {
                textEl.style.display = 'none';
                btn.disabled = true;
            }
        }

        function submitVideoUpload() {
            const fileInput = document.getElementById('videoFileInput');
            const file = fileInput.files[0];
            if (!file) return;

            const setActive = document.getElementById('videoSetActiveCheckbox').checked;
            const formData = new FormData();
            formData.append('video_file', file);
            formData.append('set_active', setActive ? 'true' : 'false');

            const pBox = document.getElementById('videoProgressBox');
            const pBar = document.getElementById('videoProgressBar');
            const pPct = document.getElementById('videoProgressPct');
            const pSize = document.getElementById('videoProgressSize');
            const btn = document.getElementById('btnUploadVideo');

            pBox.style.display = 'block';
            pBar.style.width = '0%';
            btn.disabled = true;

            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/upload/video', true);

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const pct = Math.round((e.loaded / e.total) * 100);
                    pBar.style.width = pct + '%';
                    pPct.innerText = pct + '%';
                    pSize.innerText = `${(e.loaded / (1024 * 1024)).toFixed(1)} MB / ${(e.total / (1024 * 1024)).toFixed(1)} MB`;
                }
            };

            xhr.onload = () => {
                pBox.style.display = 'none';
                btn.disabled = false;
                fileInput.value = '';
                document.getElementById('videoChosenText').style.display = 'none';
                
                try {
                    const r = JSON.parse(xhr.responseText);
                    if (r.success) {
                        showToast("✅ " + r.message);
                        loadMedia();
                    } else {
                        showToast("Gagal: " + r.message, "error");
                    }
                } catch (e) {
                    showToast("Upload selesai!", "success");
                    loadMedia();
                }
            };

            xhr.onerror = () => {
                pBox.style.display = 'none';
                btn.disabled = false;
                showToast("Terjadi kesalahan jaringan saat upload video", "error");
            };

            xhr.send(formData);
        }

        // UPLOAD MUSIC (MULTI-FILE)
        function onMusicFilesSelected(input) {
            const files = input.files;
            const textEl = document.getElementById('musicChosenText');
            const btn = document.getElementById('btnUploadMusic');
            if (files && files.length > 0) {
                let totalSize = 0;
                for (let f of files) totalSize += f.size;
                const totalMB = (totalSize / (1024 * 1024)).toFixed(1);
                textEl.innerText = `🎵 ${files.length} lagu dipilih (Total: ${totalMB} MB)`;
                textEl.style.display = 'block';
                btn.disabled = false;
            } else {
                textEl.style.display = 'none';
                btn.disabled = true;
            }
        }

        function submitMusicUpload() {
            const fileInput = document.getElementById('musicFileInput');
            const files = fileInput.files;
            if (!files || files.length === 0) return;

            const addToPl = document.getElementById('musicAddToPlaylistCheckbox').checked;
            const formData = new FormData();
            for (let f of files) {
                formData.append('music_files', f);
            }
            formData.append('add_to_playlist', addToPl ? 'true' : 'false');

            const pBox = document.getElementById('musicProgressBox');
            const pBar = document.getElementById('musicProgressBar');
            const pPct = document.getElementById('musicProgressPct');
            const pSize = document.getElementById('musicProgressSize');
            const btn = document.getElementById('btnUploadMusic');

            pBox.style.display = 'block';
            pBar.style.width = '0%';
            btn.disabled = true;

            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/upload/music', true);

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const pct = Math.round((e.loaded / e.total) * 100);
                    pBar.style.width = pct + '%';
                    pPct.innerText = pct + '%';
                    pSize.innerText = `${(e.loaded / (1024 * 1024)).toFixed(1)} MB / ${(e.total / (1024 * 1024)).toFixed(1)} MB`;
                }
            };

            xhr.onload = () => {
                pBox.style.display = 'none';
                btn.disabled = false;
                fileInput.value = '';
                document.getElementById('musicChosenText').style.display = 'none';
                
                try {
                    const r = JSON.parse(xhr.responseText);
                    if (r.success) {
                        showToast("✅ " + r.message);
                        loadMedia();
                    } else {
                        showToast("Gagal: " + r.message, "error");
                    }
                } catch (e) {
                    showToast("Upload lagu selesai!", "success");
                    loadMedia();
                }
            };

            xhr.onerror = () => {
                pBox.style.display = 'none';
                btn.disabled = false;
                showToast("Terjadi kesalahan jaringan saat upload musik", "error");
            };

            xhr.send(formData);
        }

        // DRAG AND DROP SETUP
        function setupDropZones() {
            const vz = document.getElementById('videoDropZone');
            const mz = document.getElementById('musicDropZone');

            ['dragenter', 'dragover'].forEach(name => {
                vz.addEventListener(name, (e) => { e.preventDefault(); vz.classList.add('dragover'); });
                mz.addEventListener(name, (e) => { e.preventDefault(); mz.classList.add('dragover'); });
            });
            ['dragleave', 'drop'].forEach(name => {
                vz.addEventListener(name, (e) => { e.preventDefault(); vz.classList.remove('dragover'); });
                mz.addEventListener(name, (e) => { e.preventDefault(); mz.classList.remove('dragover'); });
            });

            vz.addEventListener('drop', (e) => {
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    document.getElementById('videoFileInput').files = e.dataTransfer.files;
                    onVideoFileSelected(document.getElementById('videoFileInput'));
                }
            });
            mz.addEventListener('drop', (e) => {
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    document.getElementById('musicFileInput').files = e.dataTransfer.files;
                    onMusicFilesSelected(document.getElementById('musicFileInput'));
                }
            });
        }

        // AUDIO PREVIEW PLAYER
        function playAudioTrack(pathEncoded, filename) {
            const path = decodeURIComponent(pathEncoded);
            const audio = document.getElementById('globalHtmlAudio');
            const bar = document.getElementById('bottomAudioBar');
            const btn = document.getElementById('btnAudioPlayPause');

            if (activePlayingPath === path && !audio.paused) {
                audio.pause();
                btn.innerText = "▶️";
                renderMusicList();
                return;
            }

            activePlayingPath = path;
            audio.src = '/api/media/stream/audio?path=' + encodeURIComponent(path);
            audio.play();
            document.getElementById('audioPlayerTitle').innerText = filename;
            bar.style.display = 'block';
            btn.innerText = "⏸️";
            renderMusicList();
        }

        function toggleAudioPlayback() {
            const audio = document.getElementById('globalHtmlAudio');
            const btn = document.getElementById('btnAudioPlayPause');
            if (audio.paused) {
                audio.play();
                btn.innerText = "⏸️";
            } else {
                audio.pause();
                btn.innerText = "▶️";
            }
            renderMusicList();
        }

        function onAudioTimeUpdate() {
            const audio = document.getElementById('globalHtmlAudio');
            if (!audio.duration) return;
            const cur = formatTime(audio.currentTime);
            const dur = formatTime(audio.duration);
            document.getElementById('audioPlayerTime').innerText = `${cur} / ${dur}`;
        }

        function onAudioEnded() {
            document.getElementById('btnAudioPlayPause').innerText = "▶️";
            activePlayingPath = "";
            renderMusicList();
        }

        function closeAudioPlayer() {
            const audio = document.getElementById('globalHtmlAudio');
            audio.pause();
            audio.src = "";
            activePlayingPath = "";
            document.getElementById('bottomAudioBar').style.display = 'none';
            renderMusicList();
        }

        function formatTime(secs) {
            secs = Math.floor(secs || 0);
            const m = Math.floor(secs / 60);
            const s = secs % 60;
            return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
        }

        // SAVE MIXER
        async function saveMixerConfig() {
            const payload = {
                VIDEO_VOLUME: (parseInt(document.getElementById('mixVideoVolRange').value) / 100).toFixed(2),
                MUSIC_VOLUME: (parseInt(document.getElementById('mixMusicVolRange').value) / 100).toFixed(2),
                PLAYLIST_MODE: activePlaylistMode,
                MUSIC_DIR: document.getElementById('mixMusicDirInput').value.trim()
            };
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const r = await res.json();
            if (r.success) {
                showToast("✅ Pengaturan Mixer Berhasil Disimpan!");
                loadData();
            } else {
                showToast("Gagal menyimpan: " + r.message, "error");
            }
        }

        // SAVE STREAM KEY
        async function saveStreamKeyConfig() {
            const payload = {
                STREAM_KEY: document.getElementById('cfgStreamKey').value.trim(),
                RTMP_URL: document.getElementById('cfgRtmpUrl').value.trim()
            };
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const r = await res.json();
            if (r.success) {
                showToast("✅ Stream Key & RTMP Berhasil Disimpan!");
            } else {
                showToast("Gagal: " + r.message, "error");
            }
        }

        // LIVE STREAM CONTROLS
        async function startLiveStream(isTest = false) {
            const res = await fetch('/api/stream/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ test: isTest })
            });
            const r = await res.json();
            showToast(r.message, r.success ? "success" : "error");
            pollStreamLogs();
        }

        async function stopLiveStream() {
            const res = await fetch('/api/stream/stop', { method: 'POST' });
            const r = await res.json();
            showToast(r.message);
            pollStreamLogs();
        }

        async function pollStreamLogs() {
            try {
                const res = await fetch('/api/stream/logs');
                const data = await res.json();
                const badge = document.getElementById('streamLiveBadge');
                const box = document.getElementById('streamLogTerminal');

                if (data.running) {
                    badge.className = 'badge green';
                    badge.innerText = '🔴 SEDANG LIVE';
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
            loadNetworkInfo();
            loadData();
            setupDropZones();
            setInterval(pollStreamLogs, 2500);
        };
    </script>
</body>
</html>
"""


def create_app(port: int = 5000):
    """Membuat dan mengonfigurasi aplikasi Flask Web Dashboard."""
    from flask import Flask, jsonify, request, render_template_string, send_file
    from werkzeug.utils import secure_filename

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # Maksimal upload 4 GB

    @app.route("/")
    def index():
        return render_template_string(WEB_HTML)

    @app.route("/api/network_info")
    def api_network():
        ips = get_local_ip_addresses()
        urls = [f"http://{ip}:{port}" for ip in ips]
        return jsonify({
            "port": port,
            "ips": ips,
            "primary_ip": ips[0] if ips else "127.0.0.1",
            "urls": urls,
            "local_url": f"http://localhost:{port}"
        })

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
            cfg = load_config()
            save_playlist_file(cfg.get("PLAYLIST_FILE", "playlist.txt"), data["playlist"])

        return jsonify({"success": ok, "message": "Konfigurasi berhasil disimpan"})

    @app.route("/api/media/list", methods=["GET"])
    def api_media_list():
        cfg = load_config()
        cur_v = cfg.get("VIDEO_FILE", "")
        m_dir = cfg.get("MUSIC_DIR", "music")
        p_file = cfg.get("PLAYLIST_FILE", "playlist.txt")

        videos = get_all_videos(cur_v)
        playlist_tracks = load_playlist_file(p_file, m_dir)
        music_tracks = get_all_music(m_dir, playlist_tracks)
        v_info = probe_video(cur_v)

        return jsonify({
            "active_video": cur_v,
            "active_video_info": v_info,
            "videos": videos,
            "music": music_tracks,
            "playlist": playlist_tracks,
            "music_dir": m_dir
        })

    @app.route("/api/media/stream/video")
    def stream_video():
        path_param = request.args.get("path", "").strip()
        if not path_param:
            return "Path parameter diperlukan", 400

        full_path = Path(path_param)
        if not full_path.is_absolute():
            full_path = BASE_DIR / path_param

        if not full_path.exists() or not full_path.is_file():
            return "File video tidak ditemukan", 404

        if full_path.suffix.lower() not in VIDEO_EXTS:
            return "Format bukan video", 400

        return send_file(str(full_path), conditional=True)

    @app.route("/api/media/stream/audio")
    def stream_audio():
        fn = request.args.get("filename", "").strip()
        path_param = request.args.get("path", "").strip()

        cfg = load_config()
        m_dir_str = cfg.get("MUSIC_DIR", "music")
        m_path = Path(m_dir_str)
        if not m_path.is_absolute():
            m_path = BASE_DIR / m_dir_str

        full_path = None
        if path_param:
            p = Path(path_param)
            if not p.is_absolute():
                p = BASE_DIR / path_param
            if p.exists() and p.is_file():
                full_path = p

        if not full_path and fn:
            p = m_path / fn
            if p.exists() and p.is_file():
                full_path = p
            else:
                p_fallback = BASE_DIR / "music" / fn
                if p_fallback.exists() and p_fallback.is_file():
                    full_path = p_fallback

        if not full_path or not full_path.exists() or not full_path.is_file():
            return "File audio tidak ditemukan", 404

        if full_path.suffix.lower() not in AUDIO_EXTS:
            return "Format bukan audio", 400

        return send_file(str(full_path), conditional=True)

    @app.route("/api/upload/video", methods=["POST"])
    def upload_video():
        if "video_file" not in request.files:
            return jsonify({"success": False, "message": "Tidak ada file video yang dikirim"}), 400

        f = request.files["video_file"]
        if not f or f.filename == "":
            return jsonify({"success": False, "message": "File video kosong"}), 400

        fname = secure_filename(f.filename)
        if not fname:
            fname = f.filename.replace("/", "_").replace("\\", "_")

        ext = Path(fname).suffix.lower()
        if ext not in VIDEO_EXTS:
            return jsonify({"success": False, "message": f"Format video {ext} tidak didukung. Gunakan MP4, MKV, MOV, WEBM, atau TS."}), 400

        v_dir = BASE_DIR / "video"
        v_dir.mkdir(parents=True, exist_ok=True)
        target = v_dir / fname
        f.save(str(target))

        set_active = request.form.get("set_active", "false").lower() in ("true", "1", "yes")
        rel_path = f"video/{fname}"
        if set_active:
            save_config({"VIDEO_FILE": rel_path})

        return jsonify({
            "success": True,
            "message": f"Video '{fname}' berhasil diunggah" + (" dan dijadikan video aktif!" if set_active else "!"),
            "filename": fname,
            "path": rel_path,
            "set_active": set_active
        })

    @app.route("/api/upload/music", methods=["POST"])
    def upload_music():
        files = request.files.getlist("music_files")
        if not files and "music_file" in request.files:
            files = [request.files["music_file"]]

        if not files or len(files) == 0:
            return jsonify({"success": False, "message": "Tidak ada file musik yang dipilih"}), 400

        cfg = load_config()
        m_dir_str = cfg.get("MUSIC_DIR", "music")
        m_path = Path(m_dir_str)
        if not m_path.is_absolute():
            m_path = BASE_DIR / m_dir_str

        try:
            m_path.mkdir(parents=True, exist_ok=True)
            test_f = m_path / ".perm_check"
            test_f.touch()
            test_f.unlink()
        except Exception:
            m_path = BASE_DIR / "music"
            m_path.mkdir(parents=True, exist_ok=True)

        add_to_playlist = request.form.get("add_to_playlist", "true").lower() in ("true", "1", "yes")
        p_file = cfg.get("PLAYLIST_FILE", "playlist.txt")
        cur_playlist = load_playlist_file(p_file, str(m_path))

        uploaded = []
        skipped = []

        for f in files:
            if not f or f.filename == "":
                continue
            fname = secure_filename(f.filename)
            if not fname:
                fname = f.filename.replace("/", "_").replace("\\", "_")

            ext = Path(fname).suffix.lower()
            if ext not in AUDIO_EXTS:
                skipped.append(fname)
                continue

            target = m_path / fname
            f.save(str(target))
            uploaded.append(fname)

            if add_to_playlist and fname not in cur_playlist:
                cur_playlist.append(fname)

        if add_to_playlist and uploaded:
            save_playlist_file(p_file, cur_playlist)

        msg = f"Berhasil mengunggah {len(uploaded)} lagu!"
        if skipped:
            msg += f" ({len(skipped)} dilewati karena bukan file audio)."

        return jsonify({
            "success": True,
            "message": msg,
            "uploaded_count": len(uploaded),
            "uploaded_files": uploaded
        })

    @app.route("/api/video/select", methods=["POST"])
    def select_video():
        data = request.json or {}
        path_val = data.get("path", "").strip()
        if not path_val:
            return jsonify({"success": False, "message": "Path video tidak boleh kosong"}), 400

        full_path = Path(path_val)
        if not full_path.is_absolute():
            full_path = BASE_DIR / path_val

        if not full_path.exists():
            return jsonify({"success": False, "message": f"File video '{path_val}' tidak ditemukan"}), 404

        ok = save_config({"VIDEO_FILE": path_val})
        info = probe_video(path_val)
        return jsonify({
            "success": ok,
            "message": f"Video aktif berhasil diubah ke '{full_path.name}'",
            "video_file": path_val,
            "video_info": info
        })

    @app.route("/api/video/delete", methods=["POST"])
    def delete_video():
        data = request.json or {}
        path_val = data.get("path", "").strip()
        if not path_val:
            return jsonify({"success": False, "message": "Path tidak boleh kosong"}), 400

        full_path = Path(path_val)
        if not full_path.is_absolute():
            full_path = BASE_DIR / path_val

        if not full_path.exists():
            return jsonify({"success": False, "message": "File tidak ditemukan"}), 404

        try:
            full_path.unlink()
            cfg = load_config()
            if cfg.get("VIDEO_FILE") == path_val or cfg.get("VIDEO_FILE") == str(full_path):
                save_config({"VIDEO_FILE": ""})
            return jsonify({"success": True, "message": f"Video '{full_path.name}' berhasil dihapus."})
        except Exception as e:
            return jsonify({"success": False, "message": f"Gagal menghapus file: {e}"}), 500

    @app.route("/api/music/delete", methods=["POST"])
    def delete_music():
        data = request.json or {}
        fname = data.get("filename", "").strip()
        if not fname:
            return jsonify({"success": False, "message": "Nama file tidak boleh kosong"}), 400

        cfg = load_config()
        m_dir_str = cfg.get("MUSIC_DIR", "music")
        m_path = Path(m_dir_str)
        if not m_path.is_absolute():
            m_path = BASE_DIR / m_dir_str

        target = m_path / fname
        if not target.exists():
            target = BASE_DIR / "music" / fname

        if not target.exists():
            return jsonify({"success": False, "message": "File musik tidak ditemukan"}), 404

        try:
            target.unlink()
            p_file = cfg.get("PLAYLIST_FILE", "playlist.txt")
            tracks = load_playlist_file(p_file, m_dir_str)
            if fname in tracks:
                tracks = [t for t in tracks if t != fname]
                save_playlist_file(p_file, tracks)
            return jsonify({"success": True, "message": f"Lagu '{fname}' berhasil dihapus."})
        except Exception as e:
            return jsonify({"success": False, "message": f"Gagal menghapus lagu: {e}"}), 500

    @app.route("/api/music/playlist/toggle", methods=["POST"])
    def toggle_playlist_item():
        data = request.json or {}
        fname = data.get("filename", "").strip()
        action = data.get("action", "add")
        if not fname:
            return jsonify({"success": False, "message": "Nama lagu kosong"}), 400

        cfg = load_config()
        p_file = cfg.get("PLAYLIST_FILE", "playlist.txt")
        m_dir = cfg.get("MUSIC_DIR", "music")
        tracks = load_playlist_file(p_file, m_dir)

        if action == "add":
            if fname not in tracks:
                tracks.append(fname)
                save_playlist_file(p_file, tracks)
                return jsonify({"success": True, "message": f"'{fname}' ditambahkan ke Playlist", "playlist": tracks})
            return jsonify({"success": True, "message": "Lagu sudah ada di Playlist", "playlist": tracks})
        elif action == "remove":
            if fname in tracks:
                tracks = [t for t in tracks if t != fname]
                save_playlist_file(p_file, tracks)
                return jsonify({"success": True, "message": f"'{fname}' dikeluarkan dari Playlist", "playlist": tracks})
            return jsonify({"success": True, "message": "Lagu tidak ada di Playlist", "playlist": tracks})

        return jsonify({"success": False, "message": "Aksi tidak dikenal"}), 400

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

    return app


def run_web_server(port: int = 5000):
    """Menjalankan Web Server Dashboard interaktif dengan Flask."""
    try:
        import flask
    except ImportError:
        print(f"{C.RED}[ERROR] Modul Flask belum terpasang. Pasang dengan: pip install flask{C.RESET}")
        return

    app = create_app(port)
    ips = get_local_ip_addresses()
    primary_lan_ip = ips[0] if ips else "127.0.0.1"

    print(f"\n{C.CYAN}╔══════════════════════════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.CYAN}║{C.BOLD}{C.GREEN}         🌐 WEB DASHBOARD STREAM STUDIO AKTIF BERJALAN            {C.RESET}{C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}╚══════════════════════════════════════════════════════════════════╝{C.RESET}")
    print(f"\n{C.BOLD}Alamat Akses Web Dashboard:{C.RESET}")
    print(f"  📱 {C.WHITE}Di HP ini (Localhost)  :{C.RESET} {C.CYAN}{C.BOLD}http://localhost:{port}{C.RESET}")
    print(f"  💻 {C.YELLOW}{C.BOLD}Dari Perangkat Lain (Wi-Fi):{C.RESET} {C.GREEN}{C.BOLD}http://{primary_lan_ip}:{port}{C.RESET}")
    if len(ips) > 1:
        for extra_ip in ips[1:]:
            print(f"     Alternatif IP         : {C.CYAN}http://{extra_ip}:{port}{C.RESET}")

    print(f"\n{C.DIM}* Pastikan laptop / HP lain terhubung ke Wi-Fi atau Hotspot HP yang sama.{C.RESET}")
    print(f"{C.DIM}* Tekan Ctrl + C untuk keluar dari mode Web Dashboard.{C.RESET}\n")

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
