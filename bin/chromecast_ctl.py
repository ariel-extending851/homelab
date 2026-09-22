#!/usr/bin/env python3
"""Chromecast Living Room Automation Controller.

Provides voice notifications (TTS) and control for Google Chromecast / TV.
Uses gTTS for local Portuguese (PT-BR) speech generation and pychromecast for CastV2 streaming.
"""

import argparse
import http.server
import os
import socket
import sys
import tempfile
import threading
import time
from typing import Optional

try:
    from gtts import gTTS
    import pychromecast
except ImportError:
    print("❌ Error: Missing required dependencies. Run: pip install pychromecast gtts")
    sys.exit(1)

DEFAULT_CHROMECAST_IP = "192.168.8.206"
DEFAULT_CHROMECAST_NAME = "Living room TV"


def get_local_ip() -> str:
    """Detect local IP on the 192.168.8.0/24 LAN."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Route to Opal Gateway to determine outbound interface IP
        s.connect(("192.168.8.1", 80))
        return s.getsockname()[0]
    except Exception:
        return "192.168.8.120"
    finally:
        s.close()


class EphemeralAudioHandler(http.server.SimpleHTTPRequestHandler):
    """Serve single audio file and log minimally."""
    audio_data = b""

    def do_GET(self):
        if self.path.endswith(".mp3") or self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(self.audio_data)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(self.audio_data)
        else:
            self.send_error(404, "File Not Found")

    def log_message(self, format, *args):
        # Silence HTTP server logs to keep CLI clean
        pass


class EphemeralAudioServer:
    """Lightweight single-purpose HTTP server to stream TTS audio to Chromecast."""

    def __init__(self, audio_bytes: bytes, port: int = 8088):
        self.port = port
        EphemeralAudioHandler.audio_data = audio_bytes
        self.server = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), EphemeralAudioHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def connect_chromecast(ip: str, name: str = DEFAULT_CHROMECAST_NAME, timeout: float = 3.0) -> pychromecast.Chromecast:
    """Connect to Chromecast by friendly name or direct 5-tuple host fallback."""
    try:
        chromecasts, browser = pychromecast.get_listed_chromecasts(friendly_names=[name], timeout=timeout)
        if chromecasts:
            cast = chromecasts[0]
            cast.wait(timeout=timeout)
            pychromecast.discovery.stop_discovery(browser)
            return cast
    except Exception:
        pass

    # Direct fallback using 5-tuple
    cast = pychromecast.get_chromecast_from_host((ip, 8009, None, "Chromecast", name))
    cast.wait(timeout=timeout)
    return cast


def send_voice_notification(message: str, chromecast_ip: str = DEFAULT_CHROMECAST_IP, port: int = 8088):
    """Generate TTS MP3 and cast to TV."""
    print(f"🎙️  Gerando áudio TTS: \"{message}\"...")
    tts = gTTS(text=message, lang="pt", tld="com.br")
    
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
        tts.save(tmp_path)

    with open(tmp_path, "rb") as f:
        audio_bytes = f.read()

    os.unlink(tmp_path)

    local_ip = get_local_ip()
    stream_url = f"http://{local_ip}:{port}/notify.mp3"
    print(f"📡 Iniciando servidor efêmero de áudio em {stream_url}...")
    server = EphemeralAudioServer(audio_bytes, port=port)
    server.start()

    try:
        print(f"📺 Conectando ao Chromecast em {chromecast_ip}...")
        cast = connect_chromecast(chromecast_ip)
        print(f"✓ Conectado a: {cast.name} ({cast.model_name})")

        mc = cast.media_controller
        print("📢 Transmitindo áudio para a TV...")
        mc.play_media(stream_url, "audio/mp3", title="Homelab Notificação", thumb=None)
        mc.block_until_active(timeout=10)

        # Wait for playback to complete
        start_time = time.time()
        timeout = 20  # Max 20s for notification
        while time.time() - start_time < timeout:
            status = mc.status
            if status.player_state in ["IDLE"]:
                # Check if it finished playing
                if time.time() - start_time > 2.0:
                    break
            time.sleep(0.5)

        print("✓ Reprodução de voz concluída com sucesso!")
    finally:
        server.stop()
        print("🧹 Servidor temporário de áudio desligado.")


def show_status(chromecast_ip: str = DEFAULT_CHROMECAST_IP):
    """Display current TV and Chromecast status."""
    print(f"📺 Consultando status do Chromecast em {chromecast_ip}...")
    cast = connect_chromecast(chromecast_ip)
    status = cast.status
    mc = cast.media_controller
    mc_status = mc.status

    print("\n==================================================")
    print(f"  Dispositivo:    {cast.name} ({cast.model_name})")
    print(f"  Endereço IP:    {chromecast_ip}")
    print(f"  App Ativo:      {status.display_name or 'Nenhum (Standby / Backdrop)'}")
    print(f"  Volume:         {round(status.volume_level * 100)}% (Mutado: {status.volume_muted})")
    print(f"  Estado Player:  {mc_status.player_state}")
    print("==================================================")


def main():
    parser = argparse.ArgumentParser(description="Chromecast Living Room Automation Controller")
    parser.add_argument("--notify", type=str, help="Mensagem de texto para falar na TV (TTS em PT-BR)")
    parser.add_argument("--status", action="store_true", help="Exibe o status atual do Chromecast")
    parser.add_argument("--ip", type=str, default=DEFAULT_CHROMECAST_IP, help="IP do Chromecast")
    parser.add_argument("--port", type=int, default=8088, help="Porta para servidor HTTP temporário")

    args = parser.parse_args()

    if args.notify:
        send_voice_notification(args.notify, chromecast_ip=args.ip, port=args.port)
    elif args.status:
        show_status(chromecast_ip=args.ip)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
