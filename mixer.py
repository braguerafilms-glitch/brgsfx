"""
CineSound AI — Mixer
Sincroniza SFX com o vídeo e faz a mixagem cinematic final via FFmpeg.
"""

import os
import subprocess
import tempfile
import json
import wave
import struct
import math
from pathlib import Path
from dataclasses import dataclass

from scene_analyzer import SceneContext, SoundEvent
from sfx_engine import SFXManager, SFXAsset, AudioSynth


# ---------------------------------------------------------------------------
# Style presets — parâmetros de mixagem por estilo
# ---------------------------------------------------------------------------

STYLE_PRESETS = {
    "cinematic": {
        "ambience_vol": 0.04,
        "sfx_vol": 0.75,
        "reverb_room": 0.3,
        "reverb_wet": 0.25,
        "eq_low_boost": 4,      # dB
        "eq_high_cut": 12000,   # Hz
        "compression_threshold": -18,
        "compression_ratio": 3.5,
        "output_lufs": -16,
    },
    "thriller": {
        "ambience_vol": 0.03,
        "sfx_vol": 0.9,
        "reverb_room": 0.5,
        "reverb_wet": 0.35,
        "eq_low_boost": 6,
        "eq_high_cut": 10000,
        "compression_threshold": -20,
        "compression_ratio": 5.0,
        "output_lufs": -14,
    },
    "drama": {
        "ambience_vol": 0.05,
        "sfx_vol": 0.65,
        "reverb_room": 0.4,
        "reverb_wet": 0.3,
        "eq_low_boost": 2,
        "eq_high_cut": 14000,
        "compression_threshold": -16,
        "compression_ratio": 2.5,
        "output_lufs": -18,
    },
    "documentary": {
        "ambience_vol": 0.06,
        "sfx_vol": 0.6,
        "reverb_room": 0.2,
        "reverb_wet": 0.15,
        "eq_low_boost": 1,
        "eq_high_cut": 16000,
        "compression_threshold": -14,
        "compression_ratio": 2.0,
        "output_lufs": -20,
    },
    "action": {
        "ambience_vol": 0.03,
        "sfx_vol": 1.0,
        "reverb_room": 0.25,
        "reverb_wet": 0.2,
        "eq_low_boost": 8,
        "eq_high_cut": 11000,
        "compression_threshold": -22,
        "compression_ratio": 6.0,
        "output_lufs": -12,
    },
}


# ---------------------------------------------------------------------------
# WAV utilities (stdlib)
# ---------------------------------------------------------------------------

def wav_info(path: str) -> dict:
    with wave.open(path, "r") as wf:
        return {
            "channels": wf.getnchannels(),
            "sr": wf.getframerate(),
            "frames": wf.getnframes(),
            "duration": wf.getnframes() / wf.getframerate(),
        }


def mix_wavs_to_stereo(tracks: list[dict], output_path: str,
                        total_duration: float, sr: int = 44100) -> str:
    """
    Mistura múltiplos tracks WAV em um único arquivo estéreo.
    tracks = [{"path": str, "start": float, "volume": float, "pan": float (-1 a 1)}]
    """
    total_frames = int(total_duration * sr)
    mixed_L = [0.0] * total_frames
    mixed_R = [0.0] * total_frames
    
    for track in tracks:
        if not os.path.exists(track["path"]):
            continue
        
        info = wav_info(track["path"])
        start_frame = int(track.get("start", 0) * sr)
        vol = track.get("volume", 1.0)
        pan = track.get("pan", 0.0)  # -1 = esquerda, 0 = centro, 1 = direita
        
        pan_l = math.cos((pan + 1) * math.pi / 4)
        pan_r = math.sin((pan + 1) * math.pi / 4)
        
        with wave.open(track["path"], "r") as wf:
            raw = wf.readframes(wf.getnframes())
            
        ch = info["channels"]
        fmt = f"<{len(raw)//2}h"
        samples_int = struct.unpack(fmt, raw)
        
        # Converte para mono float se necessário
        if ch == 2:
            mono = [(samples_int[i] + samples_int[i+1]) / 2 / 32767
                    for i in range(0, len(samples_int), 2)]
        else:
            mono = [s / 32767 for s in samples_int]
        
        # Resample simples se SR diferente
        if info["sr"] != sr:
            ratio = info["sr"] / sr
            resampled = []
            for i in range(int(len(mono) / ratio)):
                idx = int(i * ratio)
                if idx < len(mono):
                    resampled.append(mono[idx])
            mono = resampled
        
        # Aplica ao buffer
        for i, s in enumerate(mono):
            frame = start_frame + i
            if frame >= total_frames:
                break
            mixed_L[frame] += s * vol * pan_l
            mixed_R[frame] += s * vol * pan_r
    
    # Soft clip + normaliza
    def soft_clip(x):
        if abs(x) < 0.8:
            return x
        sign = 1 if x > 0 else -1
        return sign * (0.8 + 0.2 * math.tanh((abs(x) - 0.8) / 0.2))
    
    mixed_L = [soft_clip(s) for s in mixed_L]
    mixed_R = [soft_clip(s) for s in mixed_R]
    
    # Normaliza para -3dBFS
    peak = max(max(abs(s) for s in mixed_L), max(abs(s) for s in mixed_R), 0.001)
    target_peak = 0.7
    gain = target_peak / peak
    
    # Escreve estéreo
    interleaved = []
    for l, r in zip(mixed_L, mixed_R):
        interleaved.append(max(-32767, min(32767, int(l * gain * 32767))))
        interleaved.append(max(-32767, min(32767, int(r * gain * 32767))))
    
    with wave.open(output_path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))
    
    return output_path


# ---------------------------------------------------------------------------
# FFmpeg post-processing
# ---------------------------------------------------------------------------

def apply_ffmpeg_processing(audio_in: str, audio_out: str, preset: dict) -> str:
    """
    Aplica EQ, compressão e normalização via FFmpeg.
    """
    
    low_boost = preset.get("eq_low_boost", 3)
    high_cut = preset.get("eq_high_cut", 14000)
    comp_thresh = preset.get("compression_threshold", -18)
    comp_ratio = preset.get("compression_ratio", 3.0)
    target_lufs = preset.get("output_lufs", -16)
    
    # Filtros FFmpeg em chain
    filters = [
        # EQ: boost graves, corta altas
        f"equalizer=f=80:width_type=o:width=2:g={low_boost}",
        f"lowpass=f={high_cut}",
        # Compressão
        f"acompressor=threshold={comp_thresh}dB:ratio={comp_ratio}:attack=20:release=200:makeup=3dB",
        # Normalização loudness
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
    ]
    
    cmd = [
        "ffmpeg", "-y",
        "-i", audio_in,
        "-af", ",".join(filters),
        "-ar", "48000",
        "-c:a", "pcm_s24le",
        audio_out
    ]
    
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [warn] FFmpeg processing: {r.stderr[-200:]}")
        # Fallback: copia sem processar
        subprocess.run(["ffmpeg", "-y", "-i", audio_in, audio_out], capture_output=True)
    
    return audio_out


def render_final_video(video_in: str, audio_in: str, video_out: str) -> str:
    """
    Combina vídeo original (sem áudio) com novo áudio processado.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_in,
        "-i", audio_in,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-map_metadata", "0",
        "-movflags", "use_metadata_tags",
        "-shortest",
        video_out
    ]
    
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg render falhou:\n{r.stderr[-500:]}")
    
    return video_out


# ---------------------------------------------------------------------------
# Mixer principal
# ---------------------------------------------------------------------------

class CineSoundMixer:
    
    def __init__(self, style: str = "cinematic", prefer_real_sfx: bool = False):
        self.style = style
        self.preset = STYLE_PRESETS.get(style, STYLE_PRESETS["cinematic"])
        self.sfx_manager = SFXManager(prefer_real=prefer_real_sfx)
        self.tmpdir = tempfile.mkdtemp(prefix="cinesound_mix_")
    
    def mix(self, video_path: str, scene: SceneContext, output_path: str) -> dict:
        """
        Pipeline completo de mixagem.
        Retorna dict com stats do render.
        """
        
        print(f"\n[MIXER] Estilo: {self.style} · {len(scene.events)} eventos")
        
        tracks = []
        
        # ── Track 1: Ambiência de fundo ──────────────────────────────────────
        print("  [1/4] Gerando ambiência...")
        amb_path = self.sfx_manager.get_ambience(scene.ambience_layer, scene.duration)
        tracks.append({
            "path": amb_path,
            "start": 0.0,
            "volume": self.preset["ambience_vol"],
            "pan": 0.0
        })
        
        # ── Tracks 2+: Eventos sincronizados ─────────────────────────────────
        print(f"  [2/4] Sintetizando {len(scene.events)} SFX...")
        events_placed = 0
        
        for event in scene.events:
            asset = self.sfx_manager.get_sfx(event)
            if asset is None:
                continue
            
            # Pan baseado em posição temporal (simula movimento no frame)
            pan = 0.0
            if event.type in ("car_pass", "wind_gust"):
                # Movimento esquerda → direita
                progress = event.time / scene.duration
                pan = -0.6 + progress * 1.2
            
            # Aplicar fade-in nos passos para não cortar
            vol = self.preset["sfx_vol"] * event.intensity
            
            tracks.append({
                "path": asset.path,
                "start": event.time,
                "volume": vol,
                "pan": pan,
                "event_type": event.type,
            })
            events_placed += 1
        
        print(f"  [3/4] Mixando {len(tracks)} tracks → estéreo...")
        raw_mix_path = os.path.join(self.tmpdir, "raw_mix.wav")
        mix_wavs_to_stereo(tracks, raw_mix_path, scene.duration)
        
        size_before = os.path.getsize(raw_mix_path)
        
        # ── Post-processing FFmpeg ───────────────────────────────────────────
        processed_path = os.path.join(self.tmpdir, "processed.wav")
        apply_ffmpeg_processing(raw_mix_path, processed_path, self.preset)
        
        # ── Render final ─────────────────────────────────────────────────────
        print(f"  [4/4] Renderizando vídeo final...")
        render_final_video(video_path, processed_path, output_path)
        
        size_out = os.path.getsize(output_path)
        
        stats = {
            "style": self.style,
            "duration": scene.duration,
            "environment": scene.environment,
            "events_placed": events_placed,
            "tracks_total": len(tracks),
            "output_path": output_path,
            "output_size_mb": round(size_out / 1024 / 1024, 2),
            "preset": self.preset,
        }
        
        print(f"\n✓ Render concluído: {output_path}")
        print(f"  {events_placed} eventos · {len(tracks)} tracks · {stats['output_size_mb']} MB")
        
        return stats


if __name__ == "__main__":
    from scene_analyzer import analyze_video
    
    mixer = CineSoundMixer(style="cinematic")
    scene = analyze_video("/tmp/test_input.mp4")
    
    output = "/tmp/test_output_cinematic.mp4"
    stats = mixer.mix("/tmp/test_input.mp4", scene, output)
    
    print("\n--- Stats ---")
    print(json.dumps({k: v for k, v in stats.items() if k != "preset"}, indent=2))
