#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# YouTube 24/7 Live Stream Script (1080p Looping Video + Looping Music Playlist)
# Dibuat khusus & dioptimasi untuk Linux / Android Termux
# ==============================================================================

set -o pipefail

# ANSI Color Codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 1. Muat Konfigurasi dari config.env
CONFIG_FILE="$DIR/config.env"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$CONFIG_FILE"
else
  echo -e "${YELLOW}[!] File config.env tidak ditemukan, menggunakan nilai default.${NC}"
fi

# Nilai Default jika belum diatur di config.env
RTMP_URL="${RTMP_URL:-"rtmp://a.rtmp.youtube.com/live2"}"
STREAM_KEY="${STREAM_KEY:-""}"
VIDEO_FILE="${VIDEO_FILE:-""}"
VIDEO_VOLUME="${VIDEO_VOLUME:-"0.0"}"
MUSIC_DIR="${MUSIC_DIR:-"music"}"
MUSIC_VOLUME="${MUSIC_VOLUME:-"1.0"}"
PLAYLIST_MODE="${PLAYLIST_MODE:-""}"
PLAYLIST_FILE="${PLAYLIST_FILE:-"playlist.txt"}"
SHUFFLE_PLAYLIST="${SHUFFLE_PLAYLIST:-"true"}"

# Kompatibilitas mundur untuk SHUFFLE_PLAYLIST
if [[ -z "$PLAYLIST_MODE" ]]; then
  if [[ "$SHUFFLE_PLAYLIST" == "false" ]]; then
    PLAYLIST_MODE="alphabetical"
  else
    PLAYLIST_MODE="shuffle"
  fi
fi

VIDEO_WIDTH="${VIDEO_WIDTH:-"1920"}"
VIDEO_HEIGHT="${VIDEO_HEIGHT:-"1080"}"
VIDEO_FPS="${VIDEO_FPS:-"30"}"
VIDEO_BITRATE="${VIDEO_BITRATE:-"3500k"}"
VIDEO_MAXRATE="${VIDEO_MAXRATE:-"4000k"}"
VIDEO_BUFSIZE="${VIDEO_BUFSIZE:-"7000k"}"
ENCODER_PRESET="${ENCODER_PRESET:-"ultrafast"}"
AUDIO_BITRATE="${AUDIO_BITRATE:-"128k"}"
AUDIO_SAMPLERATE="${AUDIO_SAMPLERATE:-"44100"}"
AUTO_RECONNECT="${AUTO_RECONNECT:-"true"}"
RECONNECT_DELAY="${RECONNECT_DELAY:-"5"}"

TEST_MODE="false"

# 2. Parse Parameter Argumen
show_help() {
  echo -e "${BOLD}Panduan Penggunaan:${NC}"
  echo -e "  ${CYAN}./stream.sh${NC}          : Menjalankan live streaming langsung ke YouTube"
  echo -e "  ${CYAN}./stream.sh --test${NC}   : Mode uji coba lokal (15 detik tanpa stream ke YouTube)"
  echo -e "  ${CYAN}./stream.sh --help${NC}   : Menampilkan bantuan ini"
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --test|-t)
      TEST_MODE="true"
      ;;
    --help|-h)
      show_help
      ;;
    *)
      ;;
  esac
done

# Banner Tampilan
print_banner() {
  clear 2>/dev/null || true
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║${BOLD}          🔴 YOUTUBE LIVE STREAMING 1080p 24/7 LOOPING           ${NC}${CYAN}║${NC}"
  echo -e "${CYAN}║${NC}             Video Looping  +  Playlist Musik Looping             ${CYAN}║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
}

print_banner

# 3. Cek Ketersediaan FFmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo -e "${RED}[ERROR] FFmpeg belum terpasang!${NC}"
  echo -e "Di Termux, silakan pasang dengan perintah: ${BOLD}pkg install ffmpeg -y${NC}"
  exit 1
fi

# 4. Validasi Video Background
find_video_file() {
  if [[ -n "$VIDEO_FILE" && -f "$VIDEO_FILE" ]]; then
    echo "$VIDEO_FILE"
    return 0
  fi

  # Cari di folder video/
  local found=""
  if [[ -d "video" ]]; then
    found=$(find video/ -maxdepth 2 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.ts" \) 2>/dev/null | head -n 1)
  fi

  # Jika belum ditemukan, cari di folder saat ini
  if [[ -z "$found" ]]; then
    found=$(find . -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" \) 2>/dev/null | head -n 1)
  fi

  echo "$found"
}

DAY_VIDEO="$DIR/video/day_seamless.mp4"
NIGHT_VIDEO="$DIR/video/night_seamless.mp4"
STEAM_VIDEO="$DIR/video/perfect_steam_loop.mov"

DAY_NIGHT_MODE="false"
if [[ -f "$DAY_VIDEO" && -f "$NIGHT_VIDEO" ]]; then
  DAY_NIGHT_MODE="true"
  ACTIVE_VIDEO="$DAY_VIDEO"
else
  ACTIVE_VIDEO="$(find_video_file)"
fi

if [[ -z "$ACTIVE_VIDEO" || ! -f "$ACTIVE_VIDEO" ]]; then
  echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${RED}║ [ERROR] File video background tidak ditemukan!                   ║${NC}"
  echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
  echo -e "${YELLOW}Cara mengatasi:${NC}"
  echo -e " 1. Letakkan file video Anda di folder ${BOLD}video/${NC} (misal: ${BOLD}video/background.mp4${NC})"
  echo -e "    Contoh salin dari HP: ${CYAN}cp /sdcard/Download/video.mp4 video/${NC}"
  echo -e " 2. Atau buat video demo otomatis dengan menjalankan:"
  echo -e "    ${BOLD}./sample_media.sh${NC}"
  exit 1
fi

# Cek apakah video memiliki stream audio
HAS_VIDEO_AUDIO="false"
if ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$ACTIVE_VIDEO" 2>/dev/null | grep -q "audio"; then
  HAS_VIDEO_AUDIO="true"
fi

MIX_VIDEO_AUDIO="false"
if [[ "$HAS_VIDEO_AUDIO" == "true" && -n "$VIDEO_VOLUME" && "$VIDEO_VOLUME" != "0" && "$VIDEO_VOLUME" != "0.0" && "$VIDEO_VOLUME" != "0%" ]]; then
  MIX_VIDEO_AUDIO="true"
fi

# 5. Validasi Playlist Musik
if [[ ! -d "$MUSIC_DIR" ]]; then
  mkdir -p "$MUSIC_DIR"
fi

count_music_files() {
  find "$MUSIC_DIR" -type f \( -iname "*.mp3" -o -iname "*.wav" -o -iname "*.flac" -o -iname "*.m4a" -o -iname "*.aac" -o -iname "*.ogg" -o -iname "*.opus" \) 2>/dev/null | wc -l
}

TOTAL_TRACKS="$(count_music_files)"
if [[ "$TOTAL_TRACKS" -eq 0 ]]; then
  echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${RED}║ [ERROR] Folder musik kosong: '$MUSIC_DIR'                        ║${NC}"
  echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
  echo -e "${YELLOW}Cara mengatasi:${NC}"
  echo -e " 1. Masukkan lagu-lagu Anda (.mp3, .m4a, .wav, dsb) ke folder ${BOLD}$MUSIC_DIR/${NC}"
  echo -e "    Contoh salin dari HP: ${CYAN}cp /sdcard/Music/*.mp3 $MUSIC_DIR/${NC}"
  echo -e " 2. Atau buat musik demo otomatis dengan menjalankan:"
  echo -e "    ${BOLD}./sample_media.sh${NC}"
  exit 1
fi

# 6. Validasi Stream Key (Jika bukan mode test)
if [[ "$TEST_MODE" != "true" ]]; then
  if [[ -z "$STREAM_KEY" || "$STREAM_KEY" == *"xxxx"* ]]; then
    echo -e "${YELLOW}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║ [PERHATIAN] Stream Key YouTube belum diatur!                     ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo -e "Dapatkan Stream Key di: ${CYAN}https://studio.youtube.com/channel/live/livestreaming${NC}"
    echo ""
    read -r -p "Masukkan YouTube Stream Key Anda: " INPUT_KEY
    if [[ -z "$INPUT_KEY" ]]; then
      echo -e "${RED}[ERROR] Stream Key tidak boleh kosong! Batal.${NC}"
      exit 1
    fi
    STREAM_KEY="$INPUT_KEY"
    # Simpan ke config.env agar tidak perlu mengisi berulang kali
    sed -i "s|^STREAM_KEY=.*|STREAM_KEY=\"$STREAM_KEY\"|" "$CONFIG_FILE" 2>/dev/null || true
    echo -e "${GREEN}[✓] Stream Key disimpan ke config.env${NC}\n"
  fi
fi

# 7. Aktifkan Wake-Lock Termux (Mencegah Android mematikan proses saat layar mati)
if command -v termux-wake-lock &>/dev/null; then
  termux-wake-lock
  echo -e "${BLUE}[INFO] Termux Wake-Lock diaktifkan (layar mati streaming tetap jalan).${NC}"
fi

# 8. Buat FIFO Pipe untuk Audio Streaming Seamless
FIFO_DIR="$(mktemp -d /data/data/com.termux/files/usr/tmp/ytlive.XXXXXX 2>/dev/null || mktemp -d /tmp/ytlive.XXXXXX 2>/dev/null || mktemp -d)"
AUDIO_FIFO="$FIFO_DIR/audio.pcm"
mkfifo "$AUDIO_FIFO"

FEEDER_PID=""
MAIN_FFMPEG_PID=""

# Cleanup Trap saat skrip dihentikan (Ctrl + C / Selesai)
cleanup() {
  echo -e "\n${YELLOW}[!] Menghentikan streaming & membersihkan proses...${NC}"
  
  if [[ -n "$FEEDER_PID" ]]; then
    kill -TERM "$FEEDER_PID" 2>/dev/null || true
    pkill -P "$FEEDER_PID" 2>/dev/null || true
  fi

  if [[ -n "$MAIN_FFMPEG_PID" ]]; then
    kill -TERM "$MAIN_FFMPEG_PID" 2>/dev/null || true
  fi

  if [[ -d "$FIFO_DIR" ]]; then
    rm -rf "$FIFO_DIR" 2>/dev/null || true
  fi

  if command -v termux-wake-unlock &>/dev/null; then
    termux-wake-unlock
  fi

  echo -e "${GREEN}[✓] Selesai. Live stream telah ditutup dengan aman.${NC}"
}
trap cleanup EXIT INT TERM

# 9. Fungsi Audio Feeder Background (Looping Playlist Musik)
start_audio_feeder() {
  (
    trap "exit 0" INT TERM
    # Buka deskriptor file 3 ke FIFO agar tidak terjadi premature EOF saat ganti lagu
    exec 3> "$AUDIO_FIFO"

    cycle=1
    while true; do
      playlist=()

      # Cek apakah mode kustom dan ada file playlist
      if [[ "$PLAYLIST_MODE" == "custom" && -f "$PLAYLIST_FILE" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
          line="$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
          [[ -z "$line" || "$line" =~ ^# ]] && continue
          if [[ -f "$line" ]]; then
            playlist+=("$line")
          elif [[ -f "$MUSIC_DIR/$line" ]]; then
            playlist+=("$MUSIC_DIR/$line")
          fi
        done < "$PLAYLIST_FILE"
      fi

      # Jika playlist masih kosong (belum mode custom atau file custom kosong), scan folder musik
      if [[ ${#playlist[@]} -eq 0 ]]; then
        while IFS= read -r -d $'\0' track; do
          playlist+=("$track")
        done < <(find "$MUSIC_DIR" -type f \( -iname "*.mp3" -o -iname "*.wav" -o -iname "*.flac" -o -iname "*.m4a" -o -iname "*.aac" -o -iname "*.ogg" -o -iname "*.opus" \) -print0 | sort -z)

        if [[ "$PLAYLIST_MODE" == "shuffle" || ("$SHUFFLE_PLAYLIST" == "true" && "$PLAYLIST_MODE" != "alphabetical" && "$PLAYLIST_MODE" != "reverse" && "$PLAYLIST_MODE" != "custom") ]]; then
          shuffled=()
          while IFS= read -r line; do
            shuffled+=("$line")
          done < <(printf '%s\n' "${playlist[@]}" | shuf)
          playlist=("${shuffled[@]}")
        elif [[ "$PLAYLIST_MODE" == "reverse" ]]; then
          reversed=()
          for (( i=${#playlist[@]}-1; i>=0; i-- )); do
            reversed+=("${playlist[i]}")
          done
          playlist=("${reversed[@]}")
        fi
      elif [[ "$PLAYLIST_MODE" == "shuffle" ]]; then
        shuffled=()
        while IFS= read -r line; do
          shuffled+=("$line")
        done < <(printf '%s\n' "${playlist[@]}" | shuf)
        playlist=("${shuffled[@]}")
      fi

      total=${#playlist[@]}
      if [[ $total -eq 0 ]]; then
        echo -e "${RED}[AUDIO] File musik tidak ditemukan di $MUSIC_DIR!${NC}" >&2
        sleep 3
        continue
      fi

      echo -e "\n${CYAN}══════════════════════════════════════════════════════════════════${NC}" >&2
      echo -e "${PURPLE}🔁 [PLAYLIST] Putaran Musik #$cycle (${total} Lagu) | Mode: $PLAYLIST_MODE | Vol Musik: $MUSIC_VOLUME${NC}" >&2
      echo -e "${CYAN}══════════════════════════════════════════════════════════════════${NC}" >&2

      idx=1
      for song in "${playlist[@]}"; do
        song_title="$(basename "$song")"
        echo -e "\n${GREEN}🎵 [NOW PLAYING ($idx/$total)]:${NC} ${BOLD}$song_title${NC}" >&2
        
        # Decode audio menjadi PCM stereo 16-bit 44.1kHz langsung ke FIFO pipe
        # Terapkan volume musik jika diset
        if [[ -n "$MUSIC_VOLUME" && "$MUSIC_VOLUME" != "1" && "$MUSIC_VOLUME" != "1.0" && "$MUSIC_VOLUME" != "100%" ]]; then
          ffmpeg -v error -i "$song" -vn -filter:a "volume=$MUSIC_VOLUME" -f s16le -acodec pcm_s16le -ar "$AUDIO_SAMPLERATE" -ac 2 pipe:1 >&3 || true
        else
          ffmpeg -v error -i "$song" -vn -f s16le -acodec pcm_s16le -ar "$AUDIO_SAMPLERATE" -ac 2 pipe:1 >&3 || true
        fi
        
        idx=$((idx + 1))
      done

      cycle=$((cycle + 1))
    done
    exec 3>&-
  ) &
  FEEDER_PID=$!
}

stop_audio_feeder() {
  if [[ -n "$FEEDER_PID" ]]; then
    kill -TERM "$FEEDER_PID" 2>/dev/null || true
    pkill -P "$FEEDER_PID" 2>/dev/null || true
    wait "$FEEDER_PID" 2>/dev/null || true
    FEEDER_PID=""
  fi
}

# 10. Tampilkan Rincian Siaran
echo -e "${BOLD}⚙️  RINCIAN KONFIGURASI LIVE:${NC}"
echo -e " • Mode Siaran     : $(if [[ "$TEST_MODE" == "true" ]]; then echo -e "${YELLOW}TEST / UJI COBA LOKAL (15s)${NC}"; else echo -e "${GREEN}YOUTUBE LIVE 24/7${NC}"; fi)"
if [[ "$DAY_NIGHT_MODE" == "true" ]]; then
  echo -e " • Mode Video      : ${GREEN}🌤️/🌙 Siklus Siang-Malam Dinamis Real-Time (WIB)${NC}"
  echo -e " • Video Siang     : ${CYAN}$DAY_VIDEO${NC}"
  echo -e " • Video Malam     : ${CYAN}$NIGHT_VIDEO${NC}"
  if [[ -f "$STEAM_VIDEO" ]]; then
    echo -e " • Asap Kopi Meja  : ${GREEN}Aktif (Perpetual Seamless Loop)${NC}"
  fi
else
  echo -e " • File Video      : ${CYAN}$ACTIVE_VIDEO${NC}"
fi
if [[ "$HAS_VIDEO_AUDIO" == "true" ]]; then
  if [[ "$MIX_VIDEO_AUDIO" == "true" ]]; then
    echo -e " • Audio Video     : ${GREEN}Aktif (Volume: $VIDEO_VOLUME - Dimix dengan musik)${NC}"
  else
    echo -e " • Audio Video     : ${YELLOW}Muted / Hening (Volume: $VIDEO_VOLUME)${NC}"
  fi
else
  echo -e " • Audio Video     : ${BLUE}Tanpa Track Audio (Murni Playlist Musik)${NC}"
fi
echo -e " • Folder Musik    : ${CYAN}$MUSIC_DIR/ ($TOTAL_TRACKS lagu ditemukan)${NC}"
echo -e " • Urutan Musik    : ${BOLD}$PLAYLIST_MODE${NC} $(if [[ "$PLAYLIST_MODE" == "custom" ]]; then echo "($PLAYLIST_FILE)"; fi)"
echo -e " • Volume Musik    : ${BOLD}$MUSIC_VOLUME${NC}"
echo -e " • Resolusi        : ${BOLD}${VIDEO_WIDTH}x${VIDEO_HEIGHT} (${VIDEO_FPS} fps) - Full HD${NC}"
echo -e " • Bitrate Video   : ${BOLD}$VIDEO_BITRATE${NC} (Preset: $ENCODER_PRESET)"
echo -e " • Bitrate Audio   : ${BOLD}$AUDIO_BITRATE${NC} (${AUDIO_SAMPLERATE} Hz AAC)"
if [[ "$TEST_MODE" != "true" ]]; then
  echo -e " • RTMP Server     : ${CYAN}$RTMP_URL${NC}"
  echo -e " • Stream Key      : ${CYAN}${STREAM_KEY:0:4}****${STREAM_KEY: -4}${NC}"
fi
echo -e "${CYAN}══════════════════════════════════════════════════════════════════${NC}"
echo ""

# Filter Skala & Pipeline Generator
VIDEO_FILTER="scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,pad=${VIDEO_WIDTH}:${VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${VIDEO_FPS}"
GOP_SIZE=$((VIDEO_FPS * 2))

prepare_pipeline() {
  if [[ "$DAY_NIGHT_MODE" == "true" ]]; then
    # Hitung bobot siang & malam berdasarkan waktu lokal Android (WIB)
    read -r W_DAY W_NIGHT PHASE <<< $(python3 -c "
import datetime
now = datetime.datetime.now()
m = now.hour * 60 + now.minute
if 375 <= m < 1035:
    print('1.000 0.000 siang')
elif 1035 <= m < 1065:
    print('1.000 0.000 sore')
elif 1065 <= m < 1125:
    p = (m - 1065) / 60.0
    sp = p * p * (3 - 2 * p)
    print(f'{1-sp:.3f} {sp:.3f} senja')
elif m >= 1125 or m < 300:
    print('0.000 1.000 malam')
else:
    p = (m - 300) / 75.0
    sp = p * p * (3 - 2 * p)
    print(f'{sp:.3f} {1-sp:.3f} fajar')
")

    local STEAM_W STEAM_H STEAM_X STEAM_Y
    if [[ "$VIDEO_WIDTH" -ge 1920 ]]; then
      STEAM_W=210; STEAM_H=390; STEAM_X=1476; STEAM_Y=298
    else
      STEAM_W=140; STEAM_H=260; STEAM_X=984; STEAM_Y=199
    fi

    # Pilih video atau blend berdasarkan fase waktu
    if (( $(echo "$W_DAY >= 0.999" | bc -l 2>/dev/null || awk -v d="$W_DAY" 'BEGIN {print (d>=0.999)}') )); then
      # Murni Siang
      BASE_INPUTS=(-thread_queue_size 1024 -stream_loop -1 -re -i "$DAY_VIDEO")
      if [[ "$PHASE" == "sore" ]]; then
        FILTER_BASE="[0:v]colorbalance=rh=0.12:gh=0.06:bh=-0.08,scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}:flags=fast_bilinear,fps=${VIDEO_FPS}[base_scaled]"
      else
        FILTER_BASE="[0:v]scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}:flags=fast_bilinear,fps=${VIDEO_FPS}[base_scaled]"
      fi
      STEAM_INPUT_IDX=1
      AUDIO_FIFO_IDX=2
      AUDIO_V_SRC="[0:a]"

    elif (( $(echo "$W_NIGHT >= 0.999" | bc -l 2>/dev/null || awk -v n="$W_NIGHT" 'BEGIN {print (n>=0.999)}') )); then
      # Murni Malam
      BASE_INPUTS=(-thread_queue_size 1024 -stream_loop -1 -re -i "$NIGHT_VIDEO")
      FILTER_BASE="[0:v]scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}:flags=fast_bilinear,fps=${VIDEO_FPS}[base_scaled]"
      STEAM_INPUT_IDX=1
      AUDIO_FIFO_IDX=2
      AUDIO_V_SRC="[0:a]"

    else
      # Senja atau Fajar: Blend halus Siang & Malam
      BASE_INPUTS=(-thread_queue_size 1024 -stream_loop -1 -re -i "$DAY_VIDEO" -thread_queue_size 1024 -stream_loop -1 -re -i "$NIGHT_VIDEO")
      FILTER_BASE="[0:v][1:v]blend=all_expr='A*${W_DAY}+B*${W_NIGHT}'[base_v];[base_v]scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT}:flags=fast_bilinear,fps=${VIDEO_FPS}[base_scaled]"
      STEAM_INPUT_IDX=2
      AUDIO_FIFO_IDX=3
      AUDIO_V_SRC="[v_mixed_a]"
    fi

    # Tambahkan overlay asap kopi jika tersedia
    if [[ -f "$STEAM_VIDEO" ]]; then
      PIPELINE_INPUTS=("${BASE_INPUTS[@]}" -thread_queue_size 1024 -stream_loop -1 -re -i "$STEAM_VIDEO" -thread_queue_size 1024 -f s16le -ar "$AUDIO_SAMPLERATE" -ac 2 -i "$AUDIO_FIFO")
      local FILTER_V="${FILTER_BASE};[${STEAM_INPUT_IDX}:v]scale=${STEAM_W}:${STEAM_H},fps=${VIDEO_FPS}[steam];[base_scaled][steam]overlay=${STEAM_X}:${STEAM_Y}:format=rgb,format=yuv420p[vout]"
      local FIFO_IN_IDX=$((AUDIO_FIFO_IDX))
    else
      PIPELINE_INPUTS=("${BASE_INPUTS[@]}" -thread_queue_size 1024 -f s16le -ar "$AUDIO_SAMPLERATE" -ac 2 -i "$AUDIO_FIFO")
      local FILTER_V="${FILTER_BASE};[base_scaled]format=yuv420p[vout]"
      local FIFO_IN_IDX=$((AUDIO_FIFO_IDX - 1))
    fi

    # Audio handling
    if [[ "$MIX_VIDEO_AUDIO" == "true" ]]; then
      if [[ "$AUDIO_V_SRC" == "[v_mixed_a]" ]]; then
        local FILTER_A="[0:a]volume=${W_DAY}[va0];[1:a]volume=${W_NIGHT}[va1];[va0][va1]amix=inputs=2[v_mixed_a];${AUDIO_V_SRC}volume=${VIDEO_VOLUME},aresample=${AUDIO_SAMPLERATE}[va_resamp];[${FIFO_IN_IDX}:a]aresample=${AUDIO_SAMPLERATE}[ma];[va_resamp][ma]amix=inputs=2:duration=first:dropout_transition=0[aout]"
      else
        local FILTER_A="${AUDIO_V_SRC}volume=${VIDEO_VOLUME},aresample=${AUDIO_SAMPLERATE}[va_resamp];[${FIFO_IN_IDX}:a]aresample=${AUDIO_SAMPLERATE}[ma];[va_resamp][ma]amix=inputs=2:duration=first:dropout_transition=0[aout]"
      fi
    else
      local FILTER_A="[${FIFO_IN_IDX}:a]aresample=${AUDIO_SAMPLERATE}[aout]"
    fi

    PIPELINE_FILTER="${FILTER_V};${FILTER_A}"
  else
    PIPELINE_INPUTS=(-stream_loop -1 -re -i "$ACTIVE_VIDEO" -f s16le -ar "$AUDIO_SAMPLERATE" -ac 2 -i "$AUDIO_FIFO")
    if [[ "$MIX_VIDEO_AUDIO" == "true" ]]; then
      PIPELINE_FILTER="[0:v]${VIDEO_FILTER}[vout];[0:a]volume=${VIDEO_VOLUME},aresample=${AUDIO_SAMPLERATE}[va];[1:a]aresample=${AUDIO_SAMPLERATE}[ma];[va][ma]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    else
      PIPELINE_FILTER="[0:v]${VIDEO_FILTER}[vout];[1:a]aresample=${AUDIO_SAMPLERATE}[aout]"
    fi
  fi
}

# 11. Eksekusi Mode Uji Coba (--test)
if [[ "$TEST_MODE" == "true" ]]; then
  TEST_OUTPUT="test_preview_1080p.mp4"
  echo -e "${YELLOW}[*] Menjalankan uji coba encode 15 detik ke file: $TEST_OUTPUT...${NC}"
  start_audio_feeder
  prepare_pipeline

  ffmpeg -hide_banner \
    "${PIPELINE_INPUTS[@]}" \
    -filter_complex "$PIPELINE_FILTER" \
    -map "[vout]" -map "[aout]" \
    -c:v libx264 -preset "$ENCODER_PRESET" -tune zerolatency \
    -b:v "$VIDEO_BITRATE" -maxrate "$VIDEO_MAXRATE" -bufsize "$VIDEO_BUFSIZE" \
    -pix_fmt yuv420p -g "$GOP_SIZE" -keyint_min "$GOP_SIZE" -sc_threshold 0 \
    -c:a aac -b:a "$AUDIO_BITRATE" -ar "$AUDIO_SAMPLERATE" \
    -max_muxing_queue_size 4096 \
    -t 15 -y "$TEST_OUTPUT"

  stop_audio_feeder
  
  # Salin otomatis ke Movies Android
  cp "$TEST_OUTPUT" "/storage/emulated/0/Movies/live_test_preview.mp4" 2>/dev/null || true

  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║ [✓] UJI COBA BERHASIL! File disimpan ke:                         ║${NC}"
  echo -e "${GREEN}║     $TEST_OUTPUT                                     ║${NC}"
  echo -e "${GREEN}║     /storage/emulated/0/Movies/live_test_preview.mp4             ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"
  echo -e "${CYAN}Video dan playlist musik berjalan normal. Anda siap live streaming!${NC}"
  echo -e "Jalankan live sesungguhnya dengan perintah: ${BOLD}./stream.sh${NC}"
  exit 0
fi

# 12. Eksekusi Live Streaming Utama ke YouTube dengan Auto-Reconnect
FULL_RTMP_TARGET="${RTMP_URL}/${STREAM_KEY}"

echo -e "${GREEN}[*] Memulai Live Streaming ke YouTube...${NC}"
echo -e "${YELLOW}[i] Tekan Ctrl + C kapan saja untuk menghentikan siaran.${NC}\n"

reconnect_count=0

while true; do
  start_audio_feeder
  prepare_pipeline

  # Jalankan FFmpeg siaran langsung
  ffmpeg -hide_banner \
    "${PIPELINE_INPUTS[@]}" \
    -filter_complex "$PIPELINE_FILTER" \
    -map "[vout]" -map "[aout]" \
    -c:v libx264 -preset "$ENCODER_PRESET" -tune zerolatency \
    -b:v "$VIDEO_BITRATE" -maxrate "$VIDEO_MAXRATE" -bufsize "$VIDEO_BUFSIZE" \
    -pix_fmt yuv420p -g "$GOP_SIZE" -keyint_min "$GOP_SIZE" -sc_threshold 0 \
    -c:a aac -b:a "$AUDIO_BITRATE" -ar "$AUDIO_SAMPLERATE" \
    -max_muxing_queue_size 4096 \
    -flvflags no_duration_filesize \
    -rtmp_live live -rtmp_buffer 1000 \
    -f flv "$FULL_RTMP_TARGET" &
  
  MAIN_FFMPEG_PID=$!
  wait "$MAIN_FFMPEG_PID" 2>/dev/null
  EXIT_STATUS=$?
  MAIN_FFMPEG_PID=""

  stop_audio_feeder

  if [[ $EXIT_STATUS -eq 0 ]]; then
    echo -e "${GREEN}[✓] Siaran dihentikan secara normal.${NC}"
    break
  fi

  if [[ "$AUTO_RECONNECT" != "true" ]]; then
    echo -e "${RED}[✗] Streaming terputus (Kode Error: $EXIT_STATUS). Auto-reconnect nonaktif.${NC}"
    break
  fi

  reconnect_count=$((reconnect_count + 1))
  echo -e "\n${YELLOW}[!] Koneksi terputus (Kode: $EXIT_STATUS). Menghubungkan ulang ke YouTube (#$reconnect_count)...${NC}"
  echo -e "${YELLOW}    Menunggu $RECONNECT_DELAY detik... (Tekan Ctrl + C untuk keluar)${NC}"
  sleep "$RECONNECT_DELAY"
done
