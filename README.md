# CineSound AI

**Sound design automático com IA contextual.**  
Você manda o vídeo. O pipeline analisa a cena, detecta eventos, sincroniza SFX e exporta já mixado — nível cinematográfico.

---

## Como funciona

```
vídeo → frames → Gemini Vision → SceneContext JSON → SFX Engine → Mixer → vídeo final
```

1. **Scene Analyzer** — extrai frames e identifica: ambiente, personagens, movimentos, eventos  
2. **SFX Engine** — gera sons via síntese local ou busca no Freesound  
3. **Mixer** — sincroniza todos os tracks, aplica EQ + compressão + loudness via FFmpeg  

---

## Instalação

```bash
# Dependências do sistema
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Python (3.10+)
pip install google-generativeai   # Vision real (opcional)
pip install openai                # Alternativa Vision (opcional)
pip install requests              # Freesound API (opcional)

# Clone
git clone https://github.com/braguerafilms/cinesound
cd cinesound
```

---

## Uso rápido

```bash
# Modo desenvolvimento (sem API keys — usa mock inteligente)
python cinesound.py meu_video.mp4

# Com estilo
python cinesound.py meu_video.mp4 --style thriller

# Com análise real (Gemini)
GEMINI_API_KEY=sua_key python cinesound.py meu_video.mp4 --style cinematic

# Com SFX reais (Freesound)
FREESOUND_API_KEY=sua_key python cinesound.py meu_video.mp4 --real-sfx

# Dump do JSON de cena (debug / curadoria)
python cinesound.py meu_video.mp4 --dump-scene

# Ver todos os estilos
python cinesound.py --list-styles
```

---

## Estilos disponíveis

| Estilo         | Ambiência | SFX   | Reverb | LUFS  | Uso              |
|----------------|-----------|-------|--------|-------|------------------|
| `cinematic`    | 18%       | 75%   | 25%    | -16   | Narrativo, drama |
| `thriller`     | 12%       | 90%   | 35%    | -14   | Suspense, tensão |
| `drama`        | 22%       | 65%   | 30%    | -18   | Emocional        |
| `documentary`  | 30%       | 60%   | 15%    | -20   | Real, sóbrio     |
| `action`       | 10%       | 100%  | 20%    | -12   | Alta energia     |

---

## Variáveis de ambiente

```bash
# .env
GEMINI_API_KEY=...       # Google Gemini Vision (análise de cenas)
OPENAI_API_KEY=...       # GPT-4o Vision (fallback)
FREESOUND_API_KEY=...    # SFX reais do Freesound.org (CC0)
ELEVENLABS_API_KEY=...   # Geração de SFX com IA (v2 roadmap)
```

---

## Arquitetura dos módulos

```
cinesound/
├── cinesound.py        ← CLI principal (ponto de entrada)
├── scene_analyzer.py   ← extração de frames + análise Vision
│   ├── MockVisionAPI      (dev/test — zero custo)
│   ├── GeminiVisionAPI    (produção — mais preciso)
│   └── OpenAIVisionAPI    (alternativa)
├── sfx_engine.py       ← síntese + gestão de assets
│   ├── AudioSynth         (síntese stdlib — zero deps)
│   ├── FreesoundEngine    (SFX reais CC0)
│   └── SFXManager         (cache + fallback automático)
└── mixer.py            ← sincronização + mixagem + render
    ├── STYLE_PRESETS      (parâmetros por estilo)
    ├── mix_wavs_to_stereo (mixer puro Python)
    ├── apply_ffmpeg_processing (EQ + comp + loudness)
    └── CineSoundMixer     (orquestrador)
```

---

## Eventos suportados

`footstep` · `impact` · `door_close` · `door_open` · `car_pass` · `wind_gust` · `keyboard_tap` · `leaves_rustle` · `branch_snap`

Surfaces: `concrete` · `wood` · `hardwood` · `gravel` · `carpet` · `plastic` · `metal`

---

## Roadmap

### MVP (semana 1–2) ✅
- [x] Pipeline core funcional
- [x] Síntese de SFX local (zero deps externas)
- [x] Mixagem estéreo com pan e volume
- [x] Post-processing via FFmpeg
- [x] 5 style presets
- [x] CLI completa

### V0.2 (semana 3–4)
- [ ] Interface web Next.js
- [ ] Upload de vídeo + preview de timeline
- [ ] Stripe (free tier + Pro R$47/mês)
- [ ] Integração Freesound API (SFX reais CC0)
- [ ] Gemini Vision em produção

### V1.0 (mês 2)
- [ ] ElevenLabs SFX generation
- [ ] Preset "BRG Custom" — estilo BRG Films
- [ ] Editor de timeline (ajuste fino de sincronização)
- [ ] Export stems separados (ambience / sfx / foley)
- [ ] API REST pública

### V2.0 (mês 3+)
- [ ] Marketplace de presets (outros editores)
- [ ] Plugin Premiere Pro / DaVinci Resolve
- [ ] Batch processing
- [ ] White-label para agências

---

## Tech stack completo

**Backend**  
- Python 3.12 (pipeline core)
- FFmpeg (sync + render + post-processing)
- NestJS + BullMQ + Redis (queue de jobs)
- PostgreSQL + Prisma (dados)

**AI**  
- Google Gemini 1.5 Pro Vision (análise de cenas)
- ElevenLabs SFX (geração de sons — roadmap)
- Meta AudioCraft (alternativa open source)

**Frontend**  
- Next.js 14 + Tailwind
- Vercel (deploy)
- Supabase (auth + storage)
- Stripe (pagamentos)

**SFX Sources**  
- Síntese local (MVP)
- Freesound API — licença CC0 (produção)
- Biblioteca própria curada (BRG Custom)

---

## Créditos

Desenvolvido por **BRG Films / Braguera Films**  
[@braguerafilms](https://instagram.com/braguerafilms) · São Paulo, BR

---

*"o plugin que edita como o Gabriel"*
