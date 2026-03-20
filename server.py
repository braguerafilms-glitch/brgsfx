"""
CineSound AI — Servidor Web
Uso: python3 server.py
Abre: http://localhost:5000
"""

import os
import sys
import json
import hashlib
import tempfile
import subprocess
from pathlib import Path

try:
    from flask import Flask, request, jsonify, send_file, send_from_directory
except ImportError:
    print("Instalando Flask...")
    subprocess.run([sys.executable, "-m", "pip", "install", "flask", "--break-system-packages", "-q"])
    from flask import Flask, request, jsonify, send_file, send_from_directory

try:
    import requests as req
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "--break-system-packages", "-q"])
    import requests as req

app = Flask(__name__)

# Pasta para salvar os sons gerados
SOUNDS_DIR = Path("sounds_gerados")
SOUNDS_DIR.mkdir(exist_ok=True)

TRADUCOES = {
    "tiro de glock": "single glock 9mm pistol gunshot close range indoor",
    "tiro": "gunshot single shot",
    "glock": "glock 9mm pistol gunshot",
    "fuzil": "rifle gunshot single shot loud",
    "explosão": "large explosion outdoor blast rumble",
    "explosao": "large explosion outdoor blast rumble",
    "vidro quebrando": "glass shattering breaking impact",
    "vidro": "glass breaking",
    "passos": "footsteps walking on floor",
    "passos chuva": "footsteps splashing in rain puddles",
    "sirene": "police siren wailing outdoor",
    "sirene policial": "police car siren outdoor",
    "trovão": "thunder crack lightning storm",
    "trovao": "thunder crack lightning storm",
    "soco": "punch impact hit flesh thud",
    "helicóptero": "helicopter flying overhead outdoor blades",
    "helicoptero": "helicopter flying overhead outdoor blades",
    "faca": "knife slash whoosh sharp",
    "palmas": "crowd applause clapping indoor",
    "motor v8": "v8 car engine revving acceleration",
    "motor": "car engine revving",
    "queda corpo": "body falling impact thud ground",
    "queda": "heavy object falling impact",
    "campainha": "doorbell ring indoor",
    "chuva": "rain falling outdoor heavy",
    "vento": "wind blowing outdoor gusty",
    "porta": "wooden door closing shut",
    "carro acelerando": "car engine acceleration tires screeching",
}

def traduzir(desc: str) -> str:
    d = desc.lower().strip()
    if d in TRADUCOES:
        return TRADUCOES[d]
    for pt, en in TRADUCOES.items():
        if pt in d:
            return d.replace(pt, en)
    return f"{d} sound effect cinematic high quality"


@app.route("/")
def index():
    return send_file("index.html")

@app.route("/logo.png")
def logo():
    if os.path.exists("logo.png"):
        return send_file("logo.png")
    return "", 404


@app.route("/sounds/<filename>")
def serve_sound(filename):
    return send_from_directory(SOUNDS_DIR, filename)


@app.route("/gerar", methods=["POST"])
def gerar():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return jsonify({"erro": "ELEVENLABS_API_KEY não configurada"}), 400

    data = request.get_json()
    descricao = data.get("descricao", "").strip()
    duracao = float(data.get("duracao", 2.0))

    if not descricao:
        return jsonify({"erro": "Descrição vazia"}), 400

    prompt = traduzir(descricao)
    duracao = min(max(duracao, 0.5), 22.0)

    # Nome do arquivo baseado na descrição
    variacao = data.get("variacao", 1)
    slug = descricao.lower().replace(" ", "_")
    slug = "".join(c for c in slug if c.isalnum() or c == "_")
    suffix = f"_v{variacao}" if variacao > 1 else ""
    h = hashlib.md5(f"{slug}{duracao}{variacao}".encode()).hexdigest()[:6]
    filename = f"{slug}{suffix}_{h}.wav"
    filepath = SOUNDS_DIR / filename

    # Se já existe em cache, retorna direto
    if filepath.exists():
        return jsonify({
            "arquivo": filename,
            "url": f"/sounds/{filename}",
            "descricao": descricao,
            "prompt": prompt,
            "duracao": duracao,
            "cache": True
        })

    try:
        resp = req.post(
            "https://api.elevenlabs.io/v1/sound-generation",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": prompt,
                "duration_seconds": round(duracao, 1),
                "prompt_influence": round(0.3 + (variacao - 1) * 0.2, 1),
            },
            timeout=30,
        )

        if resp.status_code != 200:
            msg = resp.json().get("detail", {})
            if isinstance(msg, dict):
                msg = msg.get("message", str(resp.status_code))
            return jsonify({"erro": str(msg)}), 400

        # Salva MP3 e converte para WAV
        tmp_mp3 = tempfile.mktemp(suffix=".mp3")
        with open(tmp_mp3, "wb") as f:
            f.write(resp.content)

        subprocess.run([
            "ffmpeg", "-y", "-i", tmp_mp3,
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-ar", "44100", "-ac", "1",
            str(filepath)
        ], capture_output=True)

        os.unlink(tmp_mp3)

        if not filepath.exists():
            return jsonify({"erro": "Falha na conversão de áudio"}), 500

        size_kb = filepath.stat().st_size // 1024

        return jsonify({
            "arquivo": filename,
            "url": f"/sounds/{filename}",
            "descricao": descricao,
            "prompt": prompt,
            "duracao": duracao,
            "tamanho_kb": size_kb,
            "cache": False
        })

    except Exception as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == "__main__":
    key = os.getenv("ELEVENLABS_API_KEY")
    print("\n╔═══════════════════════════════════════╗")
    print("║     CineSound AI — Servidor Web       ║")
    print("╚═══════════════════════════════════════╝\n")

    if key:
        print(f"✓ ElevenLabs: configurado")
    else:
        print("✗ ELEVENLABS_API_KEY não encontrada")
        print("  Rode: export ELEVENLABS_API_KEY='sua_key'")

    print("\n→ Abrindo em: http://localhost:5000\n")
    subprocess.Popen(["open", "http://localhost:5000"])
    app.run(debug=False, port=5000)
