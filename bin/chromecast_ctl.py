#!/usr/bin/env python3
"""Chromecast Living Room Automation Controller.

Provides family-friendly voice notifications (TTS), morning briefing, and media controls
for Google Chromecast / TV via the native CastV2 protocol (port 8009 / mDNS).
Zero ADB dependency: works 24/7 with USB and Wireless debugging completely disabled.
"""

import argparse
import http.server
import os
import socket
import sys
import tempfile
import threading
import time
from typing import Optional, Tuple

try:
    from gtts import gTTS
    import pychromecast
except ImportError:
    print("❌ Error: Missing required dependencies. Run: pip install pychromecast gtts")
    sys.exit(1)

DEFAULT_CHROMECAST_IP = "192.168.8.206"
DEFAULT_CHROMECAST_NAME = "Living room TV"
GENTLE_VOLUME_LEVEL = 0.22  # 22% volume for soft notifications


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
        print(f"📥 Chromecast conectado buscando áudio: {self.client_address[0]} (caminho: {self.path})", flush=True)
        if self.path.endswith(".mp3") or self.path == "/" or "/notify" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(self.audio_data)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(self.audio_data)
            print("✓ Áudio MP3 transmitido com sucesso para a TV!", flush=True)
        else:
            self.send_error(404, "File Not Found")

    def log_message(self, format, *args):
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


def connect_chromecast(ip: str = DEFAULT_CHROMECAST_IP, name: str = DEFAULT_CHROMECAST_NAME, timeout: float = 3.0) -> pychromecast.Chromecast:
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


def is_tv_busy(cast: pychromecast.Chromecast) -> Tuple[bool, str]:
    """Check if TV is actively being used by family (e.g. watching movie or series).

    Returns:
        (True, reason) if busy with active media/app.
        (False, reason) if idle / standby / backdrop.
    """
    status = cast.status
    mc = cast.media_controller
    mc_status = mc.status

    # 1. Media is actively playing
    if mc_status.player_state == "PLAYING":
        app_name = status.display_name or "Vídeo"
        return True, f"reprodução de mídia ativa ('{app_name}')"

    # 2. An application is active on screen other than ambient backdrop/screensaver
    idle_apps = {"Backdrop", "Ambient", "Default Media Receiver", "Homelab Notificação", None, ""}
    if status.display_name not in idle_apps:
        return True, f"aplicativo aberto ('{status.display_name}')"

    return False, "TV em repouso (Backdrop / Standby)"


def send_voice_notification(
    message: str,
    chromecast_ip: str = DEFAULT_CHROMECAST_IP,
    port: int = 8088,
    force: bool = False,
    volume: Optional[float] = GENTLE_VOLUME_LEVEL,
) -> bool:
    """Generate TTS MP3 and cast to TV safely, respecting family watching TV."""
    print(f"📺 Conectando ao Chromecast em {chromecast_ip}...")
    try:
        cast = connect_chromecast(chromecast_ip)
    except Exception as e:
        print(f"❌ Erro ao conectar ao Chromecast: {e}")
        return False

    # Check if TV is in use by family (Modo Não Perturbe a Mãe)
    busy, reason = is_tv_busy(cast)
    if busy and not force:
        print(f"\n🔇 [Modo Não Perturbe a Família] TV em uso ({reason}).")
        print("   Notificação suprimida para não interromper a programação.")
        print(f"   Mensagem que seria falada: \"{message}\"")
        return False

    print(f"✓ TV livre para notificação ({reason}).")
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
    server = EphemeralAudioServer(audio_bytes, port=port)
    server.start()

    orig_volume = cast.status.volume_level

    try:
        # Set gentle volume if requested
        if volume is not None:
            try:
                cast.set_volume(volume)
            except Exception:
                pass

        mc = cast.media_controller
        print(f"📢 Transmitindo áudio para a TV em volume suave ({round(volume * 100 if volume else 100)}%)...")
        mc.play_media(stream_url, "audio/mpeg", title="Homelab Notificação", thumb=None)
        mc.block_until_active(timeout=10)

        # Wait for playback to complete (track has_started so we don't exit before playing)
        start_time = time.time()
        timeout = 25
        has_started = False
        while time.time() - start_time < timeout:
            status = mc.status
            state = status.player_state
            if state in ["PLAYING", "BUFFERING"]:
                has_started = True
            elif state in ["IDLE"] and has_started:
                # Playback completed!
                break
            time.sleep(0.5)

        print("✓ Notificação de voz concluída com sucesso!")
        return True
    finally:
        # Restore original volume
        if volume is not None and orig_volume is not None:
            try:
                cast.set_volume(orig_volume)
            except Exception:
                pass
        server.stop()


def speak_morning_briefing(
    chromecast_ip: str = DEFAULT_CHROMECAST_IP,
    port: int = 8088,
    force: bool = False,
) -> bool:
    """Compose and speak friendly morning briefing."""
    briefing_msg = (
        "Bom dia, Ariel! Cluster Homelab operacional, "
        "roteador seguro e backups em dia. Tenha um ótimo dia de trabalho!"
    )
    return send_voice_notification(
        message=briefing_msg,
        chromecast_ip=chromecast_ip,
        port=port,
        force=force,
        volume=GENTLE_VOLUME_LEVEL,
    )


def set_volume(level: int, chromecast_ip: str = DEFAULT_CHROMECAST_IP):
    """Set volume between 0 and 100."""
    cast = connect_chromecast(chromecast_ip)
    vol_float = max(0.0, min(1.0, level / 100.0))
    cast.set_volume(vol_float)
    print(f"✓ Volume da TV ajustado para {level}%")


def media_pause(chromecast_ip: str = DEFAULT_CHROMECAST_IP):
    """Pause media playback on Chromecast."""
    cast = connect_chromecast(chromecast_ip)
    cast.media_controller.pause()
    print("✓ Mídia pausada no Chromecast")


def media_play(chromecast_ip: str = DEFAULT_CHROMECAST_IP):
    """Resume media playback on Chromecast."""
    cast = connect_chromecast(chromecast_ip)
    cast.media_controller.play()
    print("✓ Mídia despausada no Chromecast")


def media_mute(chromecast_ip: str = DEFAULT_CHROMECAST_IP):
    """Toggle mute on Chromecast."""
    cast = connect_chromecast(chromecast_ip)
    curr = cast.status.volume_muted
    cast.set_volume_muted(not curr)
    state_str = "mutado" if not curr else "desmutado"
    print(f"✓ Chromecast {state_str}")


def show_status(chromecast_ip: str = DEFAULT_CHROMECAST_IP):
    """Display current TV and Chromecast status."""
    print(f"📺 Consultando status do Chromecast em {chromecast_ip}...")
    cast = connect_chromecast(chromecast_ip)
    status = cast.status
    mc = cast.media_controller
    mc_status = mc.status
    busy, reason = is_tv_busy(cast)

    print("\n==================================================")
    print(f"  Dispositivo:    {cast.name} ({cast.model_name})")
    print(f"  Endereço IP:    {chromecast_ip}")
    print(f"  App Ativo:      {status.display_name or 'Nenhum (Standby / Backdrop)'}")
    print(f"  Volume:         {round(status.volume_level * 100)}% (Mutado: {status.volume_muted})")
    print(f"  Estado Player:  {mc_status.player_state}")
    print(f"  Uso Família:    {'EM USO (' + reason + ')' if busy else 'LIVRE (Pode notificar)'}")
    print("==================================================")


def main():
    parser = argparse.ArgumentParser(description="Chromecast Living Room Automation Controller")
    parser.add_argument("--notify", type=str, help="Mensagem de texto para falar na TV (TTS em PT-BR)")
    parser.add_argument("--briefing", action="store_true", help="Executa o Morning Briefing matinal falado na TV")
    parser.add_argument("--force", action="store_true", help="Força a notificação mesmo se a TV estiver em reprodução ativa")
    parser.add_argument("--vol", type=int, metavar="0-100", help="Ajusta o volume do Chromecast (0 a 100)")
    parser.add_argument("--pause", action="store_true", help="Pausa a reprodução no Chromecast")
    parser.add_argument("--play", action="store_true", help="Despausa a reprodução no Chromecast")
    parser.add_argument("--mute", action="store_true", help="Alterna o mudo no Chromecast")
    parser.add_argument("--status", action="store_true", help="Exibe o status atual do Chromecast e detecção de uso")
    parser.add_argument("--ip", type=str, default=DEFAULT_CHROMECAST_IP, help="IP do Chromecast")
    parser.add_argument("--port", type=int, default=8088, help="Porta para servidor HTTP temporário")

    args = parser.parse_args()

    if args.notify:
        send_voice_notification(args.notify, chromecast_ip=args.ip, port=args.port, force=args.force)
    elif args.briefing:
        speak_morning_briefing(chromecast_ip=args.ip, port=args.port, force=args.force)
    elif args.vol is not None:
        set_volume(args.vol, chromecast_ip=args.ip)
    elif args.pause:
        media_pause(chromecast_ip=args.ip)
    elif args.play:
        media_play(chromecast_ip=args.ip)
    elif args.mute:
        media_mute(chromecast_ip=args.ip)
    elif args.status:
        show_status(chromecast_ip=args.ip)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
