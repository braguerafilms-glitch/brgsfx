"""
CineSound AI — CLI
Uso: python cinesound.py input.mp4 --style cinematic --output output.mp4

Variáveis de ambiente (opcionais para produção):
  GEMINI_API_KEY      → usa Gemini Vision (mais preciso que mock)
  OPENAI_API_KEY      → usa GPT-4 Vision como fallback
  FREESOUND_API_KEY   → busca SFX reais no Freesound.org
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Garante que o diretório do script está no path
sys.path.insert(0, str(Path(__file__).parent))

from scene_analyzer import analyze_video, MockVisionAPI
from mixer import CineSoundMixer, STYLE_PRESETS


BANNER = """
╔═══════════════════════════════════════╗
║        CineSound AI  v0.1.0           ║
║   sound design automático com IA      ║
╚═══════════════════════════════════════╝
"""


def get_vision_api():
    """Detecta qual Vision API usar baseado nas env vars disponíveis."""
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from scene_analyzer import GeminiVisionAPI
            print("→ Vision: Gemini 1.5 Pro")
            return GeminiVisionAPI(gemini_key)
        except ImportError:
            print("  [warn] google-generativeai não instalado, usando mock")
    
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from scene_analyzer import OpenAIVisionAPI
            print("→ Vision: GPT-4o Vision")
            return OpenAIVisionAPI(openai_key)
        except ImportError:
            print("  [warn] openai não instalado, usando mock")
    
    print("→ Vision: Mock (desenvolvimento)")
    print("  ℹ  Configure GEMINI_API_KEY ou OPENAI_API_KEY para análise real")
    return MockVisionAPI()


def main():
    print(BANNER)
    
    parser = argparse.ArgumentParser(
        description="CineSound AI — adiciona sound design automático ao seu vídeo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python cinesound.py meu_video.mp4
  python cinesound.py meu_video.mp4 --style thriller --output resultado.mp4
  python cinesound.py meu_video.mp4 --style documentary --dump-scene
  python cinesound.py meu_video.mp4 --list-styles

Estilos disponíveis: cinematic, thriller, drama, documentary, action
        """
    )
    
    parser.add_argument("input", nargs="?", help="Vídeo de entrada (mp4, mov, mkv...)")
    parser.add_argument("--style", "-s", default="cinematic",
                        choices=list(STYLE_PRESETS.keys()),
                        help="Estilo de sound design (default: cinematic)")
    parser.add_argument("--output", "-o", default=None,
                        help="Caminho do vídeo de saída (default: input_cinesound.mp4)")
    parser.add_argument("--dump-scene", action="store_true",
                        help="Salva o JSON da análise de cena em .json")
    parser.add_argument("--list-styles", action="store_true",
                        help="Lista todos os estilos disponíveis e seus parâmetros")
    parser.add_argument("--real-sfx", action="store_true",
                        help="Usa Freesound API para SFX reais (requer FREESOUND_API_KEY)")
    parser.add_argument("--frame-interval", type=float, default=1.0,
                        help="Intervalo em segundos entre frames analisados (default: 1.0)")
    parser.add_argument("--scene", default=None,
                        help='Descreve a cena em português. Ex: --scene "sala, comemora, bebe copo, palma"')
    parser.add_argument("--events", default=None,
                        help='Define eventos com timing exato. Ex: --events "1.2:applause:0.8, 3.5:glass_clink:0.9, 6.0:liquid_pour:0.6"')
    
    args = parser.parse_args()
    
    # ── list-styles ──────────────────────────────────────────────────────────
    if args.list_styles:
        print("Estilos disponíveis:\n")
        for name, preset in STYLE_PRESETS.items():
            print(f"  {name:15s}")
            print(f"    ambience: {preset['ambience_vol']:.0%} · sfx: {preset['sfx_vol']:.0%}")
            print(f"    reverb: {preset['reverb_wet']:.0%} · target: {preset['output_lufs']} LUFS")
            print()
        return
    
    # ── Validação de input ───────────────────────────────────────────────────
    if not args.input:
        parser.print_help()
        sys.exit(1)
    
    if not os.path.exists(args.input):
        print(f"✗ Arquivo não encontrado: {args.input}")
        sys.exit(1)
    
    # ── Output path ──────────────────────────────────────────────────────────
    input_path = Path(args.input)
    if args.output:
        output_path = args.output
    else:
        output_path = str(input_path.parent / f"{input_path.stem}_cinesound{input_path.suffix}")
    
    print(f"Input:  {args.input}")
    print(f"Output: {output_path}")
    print(f"Estilo: {args.style}")
    if args.real_sfx:
        print("SFX:    Freesound API (real)")
    else:
        print("SFX:    Síntese local")
    print()
    
    # ── Pipeline ─────────────────────────────────────────────────────────────
    t_start = time.time()
    
    if args.events:
        from scene_analyzer import TextDescriptionAPI
        vision_api = TextDescriptionAPI(args.scene or "sala")
        print(f"→ Vision: Timing manual")
    elif args.scene:
        from scene_analyzer import TextDescriptionAPI
        vision_api = TextDescriptionAPI(args.scene)
        print(f"→ Vision: Descrição manual: '{args.scene}'")
    else:
        vision_api = get_vision_api()
    
    print("\n━━ FASE 1: Análise Visual ━━")
    scene = analyze_video(args.input, vision_api, args.frame_interval)
    
    # Injeta eventos manuais se --events foi passado
    if args.events:
        from scene_analyzer import SoundEvent
        scene.events = []
        for entry in args.events.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) < 2:
                continue
            try:
                t = float(parts[0])
                etype = parts[1].strip()
                intensity = float(parts[2]) if len(parts) > 2 else 0.7
                # Duração padrão por tipo
                dur_map = {"applause":1.5,"glass_clink":0.5,"liquid_pour":0.8,
                           "laugh":1.0,"crowd_cheer":1.0,"impact":0.4,
                           "footstep":0.12,"door_close":0.5,"wind_gust":1.2,
                           "chair_scrape":0.5,"car_pass":1.8}
                dur = dur_map.get(etype, 0.5)
                scene.events.append(SoundEvent(
                    time=t, type=etype, intensity=intensity,
                    duration=dur, surface="", distance="near"
                ))
                print(f"  + {t:.1f}s → {etype} ({intensity})")
            except Exception as e:
                print(f"  [warn] evento inválido '{entry}': {e}")
        print(f"✓ {len(scene.events)} eventos manuais carregados")

    if args.dump_scene:
        from dataclasses import asdict
        scene_json_path = str(input_path.parent / f"{input_path.stem}_scene.json")
        with open(scene_json_path, "w") as f:
            json.dump(asdict(scene), f, indent=2)
        print(f"\n✓ Scene JSON salvo: {scene_json_path}")
    
    print("\n━━ FASE 2: Sound Design ━━")
    mixer = CineSoundMixer(style=args.style, prefer_real_sfx=args.real_sfx)
    stats = mixer.mix(args.input, scene, output_path)
    
    elapsed = time.time() - t_start
    
    # ── Resultado ────────────────────────────────────────────────────────────
    print("\n" + "━" * 45)
    print("✓ CONCLUÍDO")
    print(f"  Tempo total:  {elapsed:.1f}s")
    print(f"  Ambiente:     {scene.environment}")
    print(f"  Eventos:      {stats['events_placed']} sincronizados")
    print(f"  Output:       {output_path} ({stats['output_size_mb']} MB)")
    print("━" * 45)
    
    return output_path


if __name__ == "__main__":
    main()
