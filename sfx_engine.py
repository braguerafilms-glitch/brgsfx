"""
CineSound AI — SFX Engine
Gera sons sintetizados localmente + integra Freesound API + ElevenLabs SFX.
Produção: configure FREESOUND_API_KEY e ELEVENLABS_API_KEY no .env
"""

import os
import math
import wave
import struct
import random
import json
import hashlib
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import requests

from scene_analyzer import SoundEvent, SceneContext


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SFXAsset:
    path: str           # caminho do arquivo WAV
    event_type: str     # tipo de evento
    duration: float     # duração em segundos
    sample_rate: int = 44100
    source: str = "synth"  # synth | freesound | elevenlabs | library


# ---------------------------------------------------------------------------
# Síntese de áudio puro (stdlib — zero dependências externas)
# ---------------------------------------------------------------------------

class AudioSynth:
    """
    Sintetizador de SFX usando apenas stdlib Python + ffmpeg.
    Qualidade suficiente para MVP; substitua por biblioteca real em produção.
    """
    
    SR = 44100  # sample rate
    
    @classmethod
    def _write_wav(cls, samples: list[float], path: str, sr: int = None) -> str:
        sr = sr or cls.SR
        # Normaliza para [-1, 1] → int16
        peak = max(abs(s) for s in samples) if samples else 1.0
        if peak < 0.001:
            peak = 1.0
        scaled = [max(-32767, min(32767, int(s / peak * 32767))) for s in samples]
        
        with wave.open(path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(scaled)}h", *scaled))
        return path
    
    @classmethod
    def _envelope(cls, t: float, attack: float, decay: float, sustain: float,
                  release: float, total: float) -> float:
        if t < attack:
            return t / attack if attack > 0 else 1.0
        t -= attack
        if t < decay:
            return 1.0 - (1.0 - sustain) * (t / decay)
        t -= decay
        hold = total - attack - decay - release
        if t < hold:
            return sustain
        t -= hold
        if t < release:
            return sustain * (1.0 - t / release)
        return 0.0
    
    @classmethod
    def _noise(cls, n: int, color: str = "white") -> list[float]:
        if color == "white":
            return [random.uniform(-1, 1) for _ in range(n)]
        # Pink noise via filtering branco
        samples = [random.uniform(-1, 1) for _ in range(n)]
        b0 = b1 = b2 = b3 = b4 = b5 = b6 = 0.0
        pink = []
        for s in samples:
            b0 = 0.99886 * b0 + s * 0.0555179
            b1 = 0.99332 * b1 + s * 0.0750759
            b2 = 0.96900 * b2 + s * 0.1538520
            b3 = 0.86650 * b3 + s * 0.3104856
            b4 = 0.55000 * b4 + s * 0.5329522
            b5 = -0.7616 * b5 - s * 0.0168980
            pink.append(b0 + b1 + b2 + b3 + b4 + b5 + b6 + s * 0.5362)
            b6 = s * 0.115926
        return pink
    
    @classmethod
    def footstep(cls, surface: str = "concrete", intensity: float = 0.7) -> list[float]:
        dur = 0.12
        n = int(dur * cls.SR)
        
        if surface in ("concrete", "asphalt", "tile"):
            # Impacto seco + reverb curto
            noise = cls._noise(n, "pink")
            freq_low = 80 + intensity * 40
            samples = []
            for i, ns in enumerate(noise):
                t = i / cls.SR
                env = cls._envelope(t, 0.002, 0.03, 0.1, 0.08, dur)
                # Low thump
                thump = math.sin(2 * math.pi * freq_low * t) * math.exp(-t * 25)
                samples.append((ns * 0.4 + thump * 0.6) * env * intensity)
        
        elif surface in ("wood", "hardwood", "floor"):
            noise = cls._noise(n, "white")
            samples = []
            for i, ns in enumerate(noise):
                t = i / cls.SR
                env = cls._envelope(t, 0.001, 0.02, 0.05, 0.09, dur)
                resonance = math.sin(2 * math.pi * 200 * t) * math.exp(-t * 30)
                samples.append((ns * 0.3 + resonance * 0.7) * env * intensity)
        
        elif surface in ("gravel", "dirt"):
            noise = cls._noise(n, "white")
            n2 = int(0.08 * cls.SR)
            samples = []
            for i in range(n):
                t = i / cls.SR
                env = cls._envelope(t, 0.005, 0.04, 0.15, 0.07, dur)
                crush = noise[i] * (1 + 0.5 * math.sin(t * 800))
                samples.append(crush * env * intensity * 0.8)
        
        else:  # carpet, generic
            noise = cls._noise(n, "pink")
            samples = []
            for i, ns in enumerate(noise):
                t = i / cls.SR
                env = cls._envelope(t, 0.005, 0.05, 0.2, 0.1, dur)
                samples.append(ns * env * intensity * 0.5)
        
        return samples
    
    @classmethod
    def impact(cls, intensity: float = 0.8) -> list[float]:
        dur = 0.4
        n = int(dur * cls.SR)
        noise = cls._noise(n, "pink")
        samples = []
        for i, ns in enumerate(noise):
            t = i / cls.SR
            env = cls._envelope(t, 0.001, 0.05, 0.0, 0.35, dur)
            sub = math.sin(2 * math.pi * 55 * t) * math.exp(-t * 8)
            mid = math.sin(2 * math.pi * 180 * t) * math.exp(-t * 15)
            crack = ns * math.exp(-t * 20)
            samples.append((sub * 0.5 + mid * 0.3 + crack * 0.2) * env * intensity)
        return samples
    
    @classmethod
    def door_close(cls, intensity: float = 0.7) -> list[float]:
        dur = 0.5
        n = int(dur * cls.SR)
        samples = []
        for i in range(n):
            t = i / cls.SR
            # Squeak + thud
            squeak_env = math.exp(-t * 40) * (1 if t < 0.05 else 0)
            squeak = math.sin(2 * math.pi * (900 - t * 3000) * t) * squeak_env
            thud_env = cls._envelope(t - 0.04, 0.001, 0.08, 0.0, 0.35, dur - 0.04) if t > 0.04 else 0
            noise = random.uniform(-1, 1)
            thud_low = math.sin(2 * math.pi * 70 * t) * math.exp(-(t - 0.04) * 12) if t > 0.04 else 0
            thud = (noise * 0.3 + thud_low * 0.7) * thud_env
            samples.append((squeak * 0.2 + thud * 0.8) * intensity)
        return samples
    
    @classmethod
    def car_pass(cls, distance: str = "mid", duration: float = 1.8) -> list[float]:
        n = int(duration * cls.SR)
        samples = []
        dist_mult = {"near": 1.0, "mid": 0.5, "far": 0.2}.get(distance, 0.5)
        
        for i in range(n):
            t = i / cls.SR
            # Doppler: freq começa alta, cai no meio, continua baixando
            progress = t / duration
            doppler = 1.0 + 0.3 * math.cos(progress * math.pi)
            base_freq = 80 * doppler
            
            # Engine noise
            engine = 0
            for harmonic in [1, 2, 3, 4, 6, 8]:
                engine += math.sin(2 * math.pi * base_freq * harmonic * t) / harmonic
            
            # Tire noise (white noise filtered)
            tire = random.uniform(-1, 1) * 0.3
            
            # Envelope: fade in → peak no meio → fade out
            env = math.sin(progress * math.pi) ** 0.7
            
            samples.append((engine * 0.6 + tire * 0.4) * env * dist_mult * 0.8)
        return samples
    
    @classmethod
    def wind_gust(cls, intensity: float = 0.4, duration: float = 1.2) -> list[float]:
        n = int(duration * cls.SR)
        noise = cls._noise(n, "pink")
        samples = []
        for i, ns in enumerate(noise):
            t = i / cls.SR
            progress = t / duration
            env = math.sin(progress * math.pi) * (0.5 + 0.5 * math.sin(t * 7))
            # Passa pelo filtro passa-baixa simples (média móvel)
            samples.append(ns * env * intensity)
        
        # Low-pass via média móvel (janela 64 samples)
        window = 64
        filtered = []
        buf = [0.0] * window
        for i, s in enumerate(samples):
            buf[i % window] = s
            filtered.append(sum(buf) / window)
        return filtered
    
    @classmethod
    def keyboard_tap(cls, intensity: float = 0.3) -> list[float]:
        dur = 0.06
        n = int(dur * cls.SR)
        samples = []
        for i in range(n):
            t = i / cls.SR
            click = random.uniform(-1, 1) * math.exp(-t * 120)
            resonance = math.sin(2 * math.pi * 2500 * t) * math.exp(-t * 80)
            env = cls._envelope(t, 0.001, 0.01, 0.0, 0.04, dur)
            samples.append((click * 0.7 + resonance * 0.3) * env * intensity)
        return samples
    
    @classmethod
    def leaves_rustle(cls, intensity: float = 0.3, duration: float = 0.8) -> list[float]:
        n = int(duration * cls.SR)
        noise = cls._noise(n, "white")
        samples = []
        for i, ns in enumerate(noise):
            t = i / cls.SR
            progress = t / duration
            env = math.sin(progress * math.pi) * 0.8
            # High freq rustle
            modulation = 0.5 + 0.5 * math.sin(t * 15 + random.uniform(0, math.pi))
            samples.append(ns * env * modulation * intensity * 0.4)
        return samples
    
    @classmethod
    def branch_snap(cls, intensity: float = 0.5) -> list[float]:
        dur = 0.25
        n = int(dur * cls.SR)
        samples = []
        for i in range(n):
            t = i / cls.SR
            crack = random.uniform(-1, 1) * math.exp(-t * 30)
            resonance = math.sin(2 * math.pi * 350 * t) * math.exp(-t * 20)
            samples.append((crack * 0.6 + resonance * 0.4) * intensity)
        return samples
    
    @classmethod
    def ambience(cls, layer: str, duration: float) -> list[float]:
        """Gera loop de ambiência (noise colorido + modulação)."""
        n = int(duration * cls.SR)
        
        if "city" in layer or "urban" in layer:
            noise = cls._noise(n, "pink")
            # Low rumble urbano
            samples = []
            for i, ns in enumerate(noise):
                t = i / cls.SR
                rumble = math.sin(2 * math.pi * 45 * t) * 0.15
                modulation = 0.85 + 0.15 * math.sin(t * 0.3)
                samples.append((ns * 0.7 + rumble * 0.3) * modulation * 0.25)
            return samples
        
        elif "forest" in layer or "nature" in layer:
            noise = cls._noise(n, "pink")
            samples = []
            for i, ns in enumerate(noise):
                t = i / cls.SR
                birds = math.sin(2 * math.pi * (2800 + 200 * math.sin(t * 2.3)) * t)
                bird_env = max(0, math.sin(t * 0.8)) * max(0, math.sin(t * 1.3 + 1))
                wind = ns * (0.4 + 0.3 * math.sin(t * 0.1))
                samples.append((wind * 0.7 + birds * bird_env * 0.15) * 0.2)
            return samples
        
        elif "room_tone" in layer or "office" in layer:
            noise = cls._noise(n, "pink")
            samples = []
            for i, ns in enumerate(noise):
                t = i / cls.SR
                # AC hum (60hz)
                hum = math.sin(2 * math.pi * 60 * t) * 0.05
                samples.append((ns * 0.3 + hum) * 0.1)
            return samples
        
        else:  # genérico
            noise = cls._noise(n, "pink")
            return [s * 0.15 for s in noise]
    

    @classmethod
    def applause(cls, intensity: float = 0.8, duration: float = 1.5) -> list[float]:
        """Aplausos: múltiplos impactos rápidos sobrepostos."""
        n = int(duration * cls.SR)
        noise = cls._noise(n, "pink")
        samples = []
        for i, ns in enumerate(noise):
            t = i / cls.SR
            progress = t / duration
            # Envelope: cresce, sustenta, cai
            env = math.sin(progress * math.pi) ** 0.5
            # Modulação rápida simulando palmas individuais
            clap_rate = 5.0 + intensity * 3
            clap_mod = 0.5 + 0.5 * abs(math.sin(t * clap_rate * math.pi))
            # Componente de impacto nas mãos
            thump = math.sin(2 * math.pi * 300 * t) * math.exp(-(t % (1/clap_rate)) * 40)
            samples.append((ns * 0.5 + thump * 0.5) * env * clap_mod * intensity)
        return samples

    @classmethod
    def glass_clink(cls, intensity: float = 0.7) -> list[float]:
        """Tinido de copo/brinde."""
        dur = 0.8
        n = int(dur * cls.SR)
        samples = []
        # Frequências fundamentais de vidro
        freqs = [2800, 3500, 4200, 5600]
        for i in range(n):
            t = i / cls.SR
            s = 0
            for j, f in enumerate(freqs):
                decay = 8 + j * 3
                s += math.sin(2 * math.pi * f * t) * math.exp(-t * decay) / (j + 1)
            # Attack transient
            attack = random.uniform(-1, 1) * math.exp(-t * 200)
            samples.append((s * 0.7 + attack * 0.3) * intensity)
        return samples

    @classmethod
    def liquid_pour(cls, intensity: float = 0.5, duration: float = 0.8) -> list[float]:
        """Som de líquido sendo despejado."""
        n = int(duration * cls.SR)
        noise = cls._noise(n, "white")
        samples = []
        for i, ns in enumerate(noise):
            t = i / cls.SR
            progress = t / duration
            env = math.sin(progress * math.pi) * 0.9
            # Frequência do líquido sobe conforme enche
            freq = 400 + progress * 800
            gurgle = math.sin(2 * math.pi * freq * t) * 0.3
            # Modulação borbulhante
            bubble = ns * (0.5 + 0.5 * math.sin(t * 30))
            samples.append((bubble * 0.6 + gurgle * 0.4) * env * intensity * 0.5)
        return samples

    @classmethod
    def laugh(cls, intensity: float = 0.7) -> list[float]:
        """Risada."""
        dur = 1.0
        n = int(dur * cls.SR)
        samples = []
        for i in range(n):
            t = i / cls.SR
            progress = t / dur
            env = math.sin(progress * math.pi) ** 0.6
            # Modulação de risada (ha-ha-ha)
            laugh_mod = max(0, math.sin(t * 7 * math.pi)) ** 2
            # Componente de voz
            voice_freq = 250 + 50 * math.sin(t * 3)
            voice = math.sin(2 * math.pi * voice_freq * t) * 0.4
            noise = random.uniform(-1, 1) * 0.6
            samples.append((voice + noise) * laugh_mod * env * intensity * 0.6)
        return samples

    @classmethod
    def chair_scrape(cls, intensity: float = 0.5) -> list[float]:
        """Cadeira arrastando."""
        dur = 0.5
        n = int(dur * cls.SR)
        samples = []
        for i in range(n):
            t = i / cls.SR
            progress = t / dur
            env = 1.0 - progress * 0.7
            freq = 200 + progress * 400
            scrape = math.sin(2 * math.pi * freq * t) * 0.4
            noise = random.uniform(-1, 1) * math.exp(-progress * 2)
            samples.append((scrape * 0.5 + noise * 0.5) * env * intensity * 0.6)
        return samples

    @classmethod
    def crowd_cheer(cls, intensity: float = 0.9, duration: float = 1.0) -> list[float]:
        """Grito de multidão/torcida."""
        n = int(duration * cls.SR)
        noise = cls._noise(n, "pink")
        samples = []
        for i, ns in enumerate(noise):
            t = i / cls.SR
            progress = t / duration
            env = math.sin(progress * math.pi) ** 0.4
            mod = 0.7 + 0.3 * math.sin(t * 2.5)
            samples.append(ns * env * mod * intensity * 0.7)
        return samples

    @classmethod
    def generate_event(cls, event: SoundEvent, tmpdir: str) -> Optional[SFXAsset]:
        """Gera um arquivo WAV para o evento e retorna SFXAsset."""
        
        fn_map = {
            "footstep":     lambda: cls.footstep(event.surface, event.intensity),
            "impact":       lambda: cls.impact(event.intensity),
            "door_close":   lambda: cls.door_close(event.intensity),
            "door_open":    lambda: cls.door_close(event.intensity * 0.8),
            "car_pass":     lambda: cls.car_pass(event.distance, event.duration),
            "wind_gust":    lambda: cls.wind_gust(event.intensity, event.duration),
            "keyboard_tap": lambda: cls.keyboard_tap(event.intensity),
            "leaves_rustle":lambda: cls.leaves_rustle(event.intensity, event.duration),
            "branch_snap":  lambda: cls.branch_snap(event.intensity),
            "applause":     lambda: cls.applause(event.intensity, event.duration),
            "glass_clink":  lambda: cls.glass_clink(event.intensity),
            "liquid_pour":  lambda: cls.liquid_pour(event.intensity, event.duration),
            "laugh":        lambda: cls.laugh(event.intensity),
            "chair_scrape": lambda: cls.chair_scrape(event.intensity),
            "crowd_cheer":  lambda: cls.crowd_cheer(event.intensity, event.duration),
            "paper_rustle": lambda: cls.leaves_rustle(event.intensity, event.duration),
            "music_distant":lambda: cls.wind_gust(event.intensity * 0.3, event.duration),
        }
        
        fn = fn_map.get(event.type)
        if fn is None:
            print(f"  [warn] tipo '{event.type}' não suportado, pulando")
            return None
        
        samples = fn()
        h = hashlib.md5(f"{event.type}{event.time}{event.intensity}".encode()).hexdigest()[:8]
        path = os.path.join(tmpdir, f"sfx_{event.type}_{h}.wav")
        cls._write_wav(samples, path)
        
        return SFXAsset(
            path=path,
            event_type=event.type,
            duration=len(samples) / cls.SR,
            source="synth"
        )


# ---------------------------------------------------------------------------
# Freesound API (produção)
# ---------------------------------------------------------------------------

class FreesoundEngine:
    """
    Busca SFX no Freesound.org.
    Requer FREESOUND_API_KEY no ambiente.
    """
    
    BASE = "https://freesound.org/apiv2"
    QUERY_MAP = {
        "footstep": "footstep walking",
        "footstep_concrete": "footstep concrete",
        "footstep_wood": "footstep wooden floor",
        "footstep_gravel": "footstep gravel",
        "impact": "impact thud punch",
        "door_close": "door close shut",
        "door_open": "door open creak",
        "car_pass": "car passing road",
        "wind_gust": "wind gust",
        "keyboard_tap": "keyboard typing click",
        "leaves_rustle": "leaves rustle wind",
        "branch_snap": "branch crack wood snap",
        "rain": "rain ambience",
        "city_night": "city night ambience traffic",
        "forest": "forest ambience birds",
        "room_tone_office": "office room tone interior",
    }
    
    def __init__(self):
        self.api_key = os.getenv("FREESOUND_API_KEY")
    
    def search(self, event_type: str, surface: str = "", duration_max: float = 2.0) -> Optional[str]:
        if not self.api_key:
            return None
        
        query_key = f"{event_type}_{surface}" if surface else event_type
        query = self.QUERY_MAP.get(query_key, self.QUERY_MAP.get(event_type, event_type))
        
        try:
            resp = requests.get(f"{self.BASE}/search/text/", params={
                "query": query,
                "token": self.api_key,
                "fields": "id,name,duration,previews,license",
                "filter": f"duration:[0.1 TO {duration_max}] license:(\"Creative Commons 0\")",
                "sort": "rating_desc",
                "page_size": 5,
            }, timeout=8)
            
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None
            
            sound = results[0]
            preview_url = sound["previews"]["preview-hq-mp3"]
            
            # Download preview
            audio_resp = requests.get(preview_url, timeout=15)
            tmppath = tempfile.mktemp(suffix=".mp3")
            with open(tmppath, "wb") as f:
                f.write(audio_resp.content)
            
            # Converte para WAV
            wav_path = tmppath.replace(".mp3", ".wav")
            subprocess.run(["ffmpeg", "-y", "-i", tmppath, "-ac", "1",
                           "-ar", "44100", wav_path], capture_output=True)
            os.unlink(tmppath)
            return wav_path
        
        except Exception as e:
            print(f"  [freesound] erro: {e}")
            return None


# ---------------------------------------------------------------------------
# SFX Manager — orquestra synth + Freesound + ElevenLabs
# ---------------------------------------------------------------------------


class ElevenLabsEngine:
    """
    Gera SFX reais usando ElevenLabs Sound Effects API.
    Sons profissionais gerados por descrição de texto.
    """
    
    PROMPT_MAP = {
        "applause":     "enthusiastic indoor applause and clapping crowd",
        "glass_clink":  "glass clink champagne toast crystal sound",
        "liquid_pour":  "liquid pouring into glass water sound",
        "laugh":        "person laughing naturally indoors",
        "crowd_cheer":  "crowd cheering celebration indoors",
        "impact":       "heavy impact thud punch hit sound",
        "footstep":     "single footstep on hardwood floor indoor",
        "footstep_concrete": "single footstep on concrete pavement",
        "door_close":   "wooden door closing shut interior",
        "door_open":    "wooden door opening creaking interior",
        "wind_gust":    "wind gust outdoor natural sound",
        "car_pass":     "car passing by on road exterior",
        "keyboard_tap": "keyboard key typing click mechanical",
        "chair_scrape": "chair scraping on floor indoor",
        "paper_rustle": "paper rustling handling sound",
        "rain":         "rain falling outdoor natural ambience",
        "branch_snap":  "branch snapping crack wood outdoor",
        "leaves_rustle":"leaves rustling in wind outdoor",
    }
    
    def __init__(self):
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.base_url = "https://api.elevenlabs.io/v1/sound-generation"
    
    def generate(self, event_type: str, surface: str = "", duration: float = 1.0, tmpdir: str = "") -> Optional[str]:
        if not self.api_key:
            return None
        
        # Monta prompt
        key = f"{event_type}_{surface}" if surface and f"{event_type}_{surface}" in self.PROMPT_MAP else event_type
        prompt = self.PROMPT_MAP.get(key, self.PROMPT_MAP.get(event_type, event_type.replace("_", " ")))
        
        dur = min(max(duration + 0.3, 0.5), 22.0)
        
        try:
            resp = requests.post(
                self.base_url,
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": prompt,
                    "duration_seconds": round(dur, 1),
                    "prompt_influence": 0.3,
                },
                timeout=30,
            )
            
            if resp.status_code != 200:
                print(f"  [elevenlabs] erro {resp.status_code}: {resp.text[:100]}")
                return None
            
            # Salva MP3 e converte para WAV
            h = hashlib.md5(f"{event_type}{surface}".encode()).hexdigest()[:8]
            mp3_path = os.path.join(tmpdir, f"el_{event_type}_{h}.mp3")
            wav_path = mp3_path.replace(".mp3", ".wav")
            
            with open(mp3_path, "wb") as f:
                f.write(resp.content)
            
            subprocess.run([
                "ffmpeg", "-y", "-i", mp3_path,
                "-ac", "1", "-ar", "44100", wav_path
            ], capture_output=True)
            
            if os.path.exists(wav_path):
                os.unlink(mp3_path)
                # Normaliza para -14 LUFS para consistência na mixagem
                norm_path = wav_path.replace(".wav", "_norm.wav")
                subprocess.run([
                    "ffmpeg", "-y", "-i", wav_path,
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-ar", "44100", "-ac", "1", norm_path
                ], capture_output=True)
                if os.path.exists(norm_path):
                    os.unlink(wav_path)
                    wav_path = norm_path
                print(f"  [elevenlabs] ✓ {event_type} gerado ({os.path.getsize(wav_path):,} bytes)")
                return wav_path
            return None
        
        except Exception as e:
            print(f"  [elevenlabs] erro: {e}")
            return None


class SFXManager:
    
    def __init__(self, prefer_real: bool = False):
        self.synth = AudioSynth()
        self.freesound = FreesoundEngine()
        self.elevenlabs = ElevenLabsEngine()
        self.use_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY"))
        self.prefer_real = prefer_real and bool(os.getenv("FREESOUND_API_KEY"))
        self._cache: dict[str, SFXAsset] = {}
        self.tmpdir = tempfile.mkdtemp(prefix="cinesound_sfx_")
        if self.use_elevenlabs:
            print("  → SFX: ElevenLabs (sons reais por IA)")
        elif self.prefer_real:
            print("  → SFX: Freesound API")
        else:
            print("  → SFX: Síntese local")
    
    def get_sfx(self, event: SoundEvent) -> Optional[SFXAsset]:
        cache_key = f"{event.type}_{event.surface}_{round(event.intensity, 1)}"
        
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        asset = None
        
        # ElevenLabs tem prioridade máxima — sons reais por IA
        if self.use_elevenlabs:
            wav_path = self.elevenlabs.generate(
                event.type, event.surface, event.duration, self.tmpdir
            )
            if wav_path:
                asset = SFXAsset(
                    path=wav_path,
                    event_type=event.type,
                    duration=event.duration,
                    source="elevenlabs"
                )
        
        # Fallback: Freesound
        if asset is None and self.prefer_real:
            wav_path = self.freesound.search(event.type, event.surface, event.duration + 0.5)
            if wav_path:
                asset = SFXAsset(
                    path=wav_path,
                    event_type=event.type,
                    duration=event.duration,
                    source="freesound"
                )
        
        # Fallback final: síntese local
        if asset is None:
            asset = self.synth.generate_event(event, self.tmpdir)
        
        if asset:
            self._cache[cache_key] = asset
        
        return asset
    
    def get_ambience(self, layer: str, duration: float) -> str:
        """Gera ou busca ambiência e retorna path do WAV."""
        path = os.path.join(self.tmpdir, f"ambience_{layer.replace(' ', '_')}.wav")
        
        if not os.path.exists(path):
            samples = AudioSynth.ambience(layer, duration)
            AudioSynth._write_wav(samples, path)
        
        return path


if __name__ == "__main__":
    from scene_analyzer import SoundEvent
    import tempfile
    
    tmpdir = tempfile.mkdtemp()
    synth = AudioSynth()
    
    print("Testando síntese de SFX...")
    
    tests = [
        SoundEvent(1.2, "footstep", 0.7, 0.12, "concrete", "near"),
        SoundEvent(2.0, "footstep", 0.65, 0.12, "wood", "near"),
        SoundEvent(3.5, "impact", 0.9, 0.4, "", "near"),
        SoundEvent(5.0, "door_close", 0.7, 0.5, "wood", "near"),
        SoundEvent(6.0, "car_pass", 0.6, 1.8, "", "mid"),
        SoundEvent(8.0, "wind_gust", 0.4, 1.2, "", "near"),
    ]
    
    manager = SFXManager()
    for ev in tests:
        asset = manager.get_sfx(ev)
        size = os.path.getsize(asset.path) if asset else 0
        print(f"  ✓ {ev.type:15s} ({ev.surface:10s}) → {size:,} bytes  [{asset.source}]")
    
    amb = manager.get_ambience("city_night_low_traffic", 5.0)
    print(f"  ✓ ambience            (city_night) → {os.path.getsize(amb):,} bytes")
    print("\nSFX Engine OK")
