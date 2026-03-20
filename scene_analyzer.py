"""
CineSound AI — Scene Analyzer
Extrai frames do vídeo e gera JSON de eventos sonoros.
Produção: troca MockVisionAPI por GeminiVisionAPI ou OpenAIVisionAPI.
"""

import subprocess
import json
import os
import base64
import math
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import tempfile


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SoundEvent:
    time: float          # segundos
    type: str            # footstep | impact | door | car_pass | cloth | breath ...
    intensity: float     # 0.0 – 1.0
    duration: float      # segundos
    surface: str = ""    # concrete | wood | gravel | water ...
    distance: str = "near"  # near | mid | far


@dataclass
class SceneContext:
    environment: str          # urban_exterior | indoor_office | forest | ...
    time_of_day: str          # day | night | golden_hour
    weather: str              # clear | rain | wind | ...
    camera_motion: str        # static | handheld | dolly | drone
    mood: str                 # cinematic | thriller | drama | documentary
    events: list[SoundEvent] = field(default_factory=list)
    ambience_layer: str = ""  # city_night | forest_day | room_tone | ...
    duration: float = 0.0


# ---------------------------------------------------------------------------
# Frame extractor
# ---------------------------------------------------------------------------

def extract_frames(video_path: str, interval: float = 1.0, max_frames: int = 30) -> list[dict]:
    """Extrai frames em intervalos regulares. Retorna lista de {time, path}."""
    
    # Pega duração do vídeo
    probe = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", video_path
    ], capture_output=True, text=True)
    
    info = json.loads(probe.stdout)
    duration = float(info["format"]["duration"])
    
    frames = []
    tmpdir = tempfile.mkdtemp(prefix="cinesound_frames_")
    
    times = [round(t, 2) for t in 
             [i * interval for i in range(int(duration / interval) + 1)]
             if t < duration]
    times = times[:max_frames]
    
    for t in times:
        frame_path = os.path.join(tmpdir, f"frame_{t:.2f}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(t),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "3",
            "-vf", "scale=640:-1",
            frame_path
        ]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and os.path.exists(frame_path):
            frames.append({"time": t, "path": frame_path})
    
    return frames, duration


def frame_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ---------------------------------------------------------------------------
# Vision API — Interface base + implementações
# ---------------------------------------------------------------------------

class VisionAPI:
    """Interface base. Substitua por GeminiVisionAPI ou OpenAIVisionAPI em produção."""
    
    def analyze_frame(self, frame_b64: str, timestamp: float, context: dict) -> dict:
        raise NotImplementedError
    
    def analyze_scene_context(self, frames_b64: list[str], duration: float) -> dict:
        raise NotImplementedError


class MockVisionAPI(VisionAPI):
    """
    Simulação determinística para desenvolvimento e testes.
    Retorna eventos realistas baseados em timestamp.
    """
    
    SCENES = [
        {
            "environment": "urban_exterior",
            "time_of_day": "night",
            "weather": "clear",
            "camera_motion": "handheld",
            "mood": "cinematic",
            "ambience_layer": "city_night_low_traffic",
        },
        {
            "environment": "indoor_office",
            "time_of_day": "day",
            "weather": "clear",
            "camera_motion": "static",
            "mood": "drama",
            "ambience_layer": "room_tone_office",
        },
        {
            "environment": "forest_exterior",
            "time_of_day": "golden_hour",
            "weather": "wind_light",
            "camera_motion": "dolly",
            "mood": "documentary",
            "ambience_layer": "forest_birds_wind",
        },
    ]
    
    def __init__(self, scene_idx: int = 0):
        self.scene = self.SCENES[scene_idx % len(self.SCENES)]
    
    def analyze_scene_context(self, frames_b64: list[str], duration: float) -> dict:
        ctx = dict(self.scene)
        ctx["duration"] = duration
        ctx["events"] = self._generate_events(duration, self.scene["environment"])
        return ctx
    
    def _generate_events(self, duration: float, env: str) -> list[dict]:
        events = []
        
        # Passos periódicos (caminhar)
        if env in ("urban_exterior", "indoor_office"):
            step_interval = 0.55
            surface = "concrete" if env == "urban_exterior" else "hardwood"
            t = 0.8
            while t < duration - 0.5:
                events.append({
                    "time": round(t, 2),
                    "type": "footstep",
                    "intensity": round(0.5 + 0.15 * math.sin(t), 2),
                    "duration": 0.12,
                    "surface": surface,
                    "distance": "near"
                })
                t += step_interval + (0.05 * math.sin(t * 3))
        
        # Eventos pontuais específicos do ambiente
        if env == "urban_exterior":
            # Carro passando
            events.append({"time": 3.2, "type": "car_pass", "intensity": 0.6,
                           "duration": 1.8, "surface": "", "distance": "mid"})
            # Wind gust
            events.append({"time": 6.5, "type": "wind_gust", "intensity": 0.35,
                           "duration": 1.2, "surface": "", "distance": "near"})
        
        elif env == "indoor_office":
            # Porta
            events.append({"time": 2.0, "type": "door_close", "intensity": 0.7,
                           "duration": 0.3, "surface": "wood", "distance": "near"})
            # Teclas de teclado
            for t in [4.1, 4.3, 4.5, 4.7, 5.0, 5.2]:
                if t < duration:
                    events.append({"time": round(t, 1), "type": "keyboard_tap",
                                  "intensity": 0.3, "duration": 0.05,
                                  "surface": "plastic", "distance": "near"})
        
        elif env == "forest_exterior":
            # Galhos
            events.append({"time": 1.5, "type": "branch_snap", "intensity": 0.4,
                           "duration": 0.2, "surface": "wood", "distance": "near"})
            events.append({"time": 5.8, "type": "leaves_rustle", "intensity": 0.3,
                           "duration": 0.8, "surface": "", "distance": "near"})
        
        # Ordena por tempo
        events.sort(key=lambda e: e["time"])
        return events


class GeminiVisionAPI(VisionAPI):
    """
    Implementação real com Google Gemini Vision.
    Requer: pip install google-genai
    """
    
    SYSTEM_PROMPT = """You are a professional sound designer analyzing video frames.
For the given video frames, analyze and return ONLY a JSON object with this exact structure:
{
  "environment": "urban_exterior|indoor_office|forest_exterior|beach|interior_home|living_room|kitchen|...",
  "time_of_day": "day|night|golden_hour|dusk",
  "weather": "clear|rain|wind_light|wind_strong|snow",
  "camera_motion": "static|handheld|dolly|crane|drone",
  "mood": "cinematic|thriller|drama|documentary|action|romance",
  "ambience_layer": "descriptive name for background ambience",
  "events": [
    {
      "time": <float seconds>,
      "type": "footstep|impact|door_close|door_open|car_pass|wind_gust|keyboard_tap|cloth_rustle|breath|glass_clink|liquid_pour|chair_scrape|...",
      "intensity": <0.0-1.0>,
      "duration": <float seconds>,
      "surface": "concrete|wood|gravel|carpet|metal|water|plastic|glass|",
      "distance": "near|mid|far"
    }
  ]
}
Be very precise about what you actually see. If it's an indoor scene, say interior. Only include events clearly visible."""
    
    def __init__(self, api_key: str):
        from google import genai
        self.client = genai.Client(api_key=api_key)
    
    def analyze_scene_context(self, frames_b64: list[str], duration: float) -> dict:
        from google import genai
        from google.genai import types
        
        # Usa subset de frames para economizar tokens
        sample = frames_b64[::max(1, len(frames_b64)//8)][:8]
        
        parts = [
            types.Part.from_text(text=self.SYSTEM_PROMPT + f"\n\nVideo duration: {duration:.1f}s. Analyze these {len(sample)} frames and return ONLY the JSON:"),
        ]
        for b64 in sample:
            parts.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/jpeg"))
        
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=parts,
        )
        
        raw = response.text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        
        result = json.loads(raw.strip())
        result["duration"] = duration
        return result


class OpenAIVisionAPI(VisionAPI):
    """
    Implementação real com OpenAI GPT-4 Vision.
    Requer: pip install openai
    """
    
    def __init__(self, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
    
    def analyze_scene_context(self, frames_b64: list[str], duration: float) -> dict:
        sample = frames_b64[::max(1, len(frames_b64)//6)][:6]
        
        content = [
            {"type": "text", "text": f"Video {duration:.1f}s. Analyze and return JSON only (no markdown): environment, time_of_day, weather, camera_motion, mood, ambience_layer, events[] with time/type/intensity/duration/surface/distance."}
        ]
        for b64 in sample:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}
            })
        
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            max_tokens=1500,
        )
        
        raw = response.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        
        result = json.loads(raw)
        result["duration"] = duration
        return result


# ---------------------------------------------------------------------------
# Analyzer principal
# ---------------------------------------------------------------------------

def analyze_video(
    video_path: str,
    vision_api: Optional[VisionAPI] = None,
    frame_interval: float = 1.0,
) -> SceneContext:
    """
    Pipeline completo de análise.
    Retorna SceneContext com todos os eventos identificados.
    """
    
    print(f"[1/3] Extraindo frames de '{Path(video_path).name}'...")
    frames, duration = extract_frames(video_path, frame_interval)
    print(f"      {len(frames)} frames extraídos · duração: {duration:.1f}s")
    
    if vision_api is None:
        vision_api = MockVisionAPI()
    
    print(f"[2/3] Analisando cena com {type(vision_api).__name__}...")
    frames_b64 = [frame_to_base64(f["path"]) for f in frames]
    raw = vision_api.analyze_scene_context(frames_b64, duration)
    
    print(f"[3/3] Construindo SceneContext...")
    events = [SoundEvent(**e) for e in raw.get("events", [])]
    
    ctx = SceneContext(
        environment=raw.get("environment", "unknown"),
        time_of_day=raw.get("time_of_day", "day"),
        weather=raw.get("weather", "clear"),
        camera_motion=raw.get("camera_motion", "static"),
        mood=raw.get("mood", "cinematic"),
        ambience_layer=raw.get("ambience_layer", "room_tone"),
        events=events,
        duration=duration,
    )
    
    print(f"\n✓ Cena: {ctx.environment} · {ctx.time_of_day} · {ctx.mood}")
    print(f"✓ {len(ctx.events)} eventos detectados")
    print(f"✓ Ambiência: {ctx.ambience_layer}")
    
    return ctx


class TextDescriptionAPI(VisionAPI):
    """
    Modo sem câmera: você descreve a cena em português.
    O sistema interpreta e gera os eventos certos.
    Exemplo: "sala de estar, pessoa comemorando, bate palma, bebe copo"
    """

    SCENE_MAP = {
        "sala": ("interior_living_room", "room_tone_home"),
        "quarto": ("interior_bedroom", "room_tone_quiet"),
        "cozinha": ("interior_kitchen", "room_tone_kitchen"),
        "escritorio": ("indoor_office", "room_tone_office"),
        "rua": ("urban_exterior", "city_day_traffic"),
        "noite": ("urban_exterior", "city_night_low_traffic"),
        "floresta": ("forest_exterior", "forest_birds_wind"),
        "praia": ("beach_exterior", "beach_waves"),
        "restaurante": ("indoor_restaurant", "restaurant_ambience"),
        "bar": ("indoor_bar", "bar_ambience"),
        "igreja": ("indoor_church", "church_reverb"),
    }

    EVENT_MAP = {
        "palma":     ("applause",      "",       0.8, 1.5),
        "aplauso":   ("applause",      "",       0.8, 2.0),
        "comemora":  ("applause",      "",       0.7, 1.5),
        "grito":     ("crowd_cheer",   "",       0.9, 1.0),
        "bebe":      ("liquid_pour",   "glass",  0.5, 0.8),
        "copo":      ("glass_clink",   "glass",  0.7, 0.3),
        "brinde":    ("glass_clink",   "glass",  0.8, 0.3),
        "porta":     ("door_close",    "wood",   0.6, 0.4),
        "cadeira":   ("chair_scrape",  "wood",   0.5, 0.5),
        "passos":    ("footstep",      "wood",   0.6, 0.12),
        "teclado":   ("keyboard_tap",  "plastic",0.3, 0.05),
        "papel":     ("paper_rustle",  "",       0.3, 0.4),
        "risada":    ("laugh",         "",       0.7, 1.0),
        "telefone":  ("phone_ring",    "",       0.8, 1.5),
        "carro":     ("car_pass",      "",       0.6, 1.8),
        "vento":     ("wind_gust",     "",       0.4, 1.2),
        "chuva":     ("rain",          "",       0.5, 3.0),
        "impacto":   ("impact",        "",       0.8, 0.4),
        "batida":    ("impact",        "wood",   0.7, 0.3),
        "musica":    ("music_distant", "",       0.3, 3.0),
    }

    def __init__(self, description: str):
        self.description = description.lower()

    def analyze_scene_context(self, frames_b64: list, duration: float) -> dict:
        desc = self.description

        environment = "interior_living_room"
        ambience = "room_tone_home"
        for keyword, (env, amb) in self.SCENE_MAP.items():
            if keyword in desc:
                environment = env
                ambience = amb
                break

        time_of_day = "night" if "noite" in desc else "day"
        weather = "rain" if "chuva" in desc else "clear"

        events = []
        step = duration / 6
        t = step * 0.5

        for keyword, (etype, surface, intensity, dur) in self.EVENT_MAP.items():
            if keyword in desc:
                if keyword in ("palma", "aplauso", "comemora"):
                    for i in range(3):
                        et = round(t + i * (duration / 4), 2)
                        if et < duration - 0.5:
                            events.append({
                                "time": et,
                                "type": etype,
                                "intensity": intensity,
                                "duration": dur,
                                "surface": surface,
                                "distance": "near"
                            })
                else:
                    et = round(min(t, duration - dur - 0.2), 2)
                    events.append({
                        "time": et,
                        "type": etype,
                        "intensity": intensity,
                        "duration": dur,
                        "surface": surface,
                        "distance": "near"
                    })
                    t += step

        events.sort(key=lambda e: e["time"])

        return {
            "environment": environment,
            "time_of_day": time_of_day,
            "weather": weather,
            "camera_motion": "handheld",
            "mood": "cinematic",
            "ambience_layer": ambience,
            "events": events,
            "duration": duration,
        }


if __name__ == "__main__":
    ctx = analyze_video("/tmp/test_input.mp4")
    print("\n--- JSON output ---")
    print(json.dumps(asdict(ctx), indent=2))
