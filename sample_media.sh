#!/data/data/com.termux/files/usr/bin/env bash
# ============================================================
# sample_media.sh
# Skrip pembuat media sampel (video 1080p & lagu demo) untuk uji coba
# ============================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

mkdir -p video music

echo "============================================================"
echo "🎬 Membuat Video Demo 1080p Looping (5 Detik)..."
echo "============================================================"
ffmpeg -y -f lavfi \
  -i "testsrc2=size=1920x1080:rate=30:duration=5" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  video/sample_background.mp4 2>/dev/null

echo -e "\033[0;32m[✓] Video berhasil dibuat: video/sample_background.mp4\033[0m\n"

echo "============================================================"
echo "🎵 Membuat 3 File Musik Demo di folder music/..."
echo "============================================================"
# Nada 1 (C4 - 261.63 Hz)
ffmpeg -y -f lavfi -i "sine=frequency=261.63:duration=5" -c:a mp3 music/sample_track_1_C4.mp3 2>/dev/null
# Nada 2 (E4 - 329.63 Hz)
ffmpeg -y -f lavfi -i "sine=frequency=329.63:duration=5" -c:a mp3 music/sample_track_2_E4.mp3 2>/dev/null
# Nada 3 (G4 - 392.00 Hz)
ffmpeg -y -f lavfi -i "sine=frequency=392.00:duration=5" -c:a mp3 music/sample_track_3_G4.mp3 2>/dev/null

echo -e "\033[0;32m[✓] Musik demo berhasil dibuat di folder music/:\033[0m"
ls -lh music/sample_track_*.mp3
echo ""
echo -e "\033[0;36mSekarang Anda bisa menjalankan uji coba dengan:\033[0m"
echo -e "  \033[1m./stream.sh --test\033[0m"
echo "============================================================"
