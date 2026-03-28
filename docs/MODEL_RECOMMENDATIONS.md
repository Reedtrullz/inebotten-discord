# Modell-anbefalinger for Inebotten

> Tester og erfaringer med ulike AI-modeller for norsk språk

## Testet og rangert

### 1. **Qwen 2.5 4B Instruct** ⭐ (Beste valg for norsk)
- **Størrelse:** 4B (lite nok for de fleste)
- **Norsk:** ⭐⭐⭐⭐⭐ Utmerket
- **Hastighet:** Veldig rask
- **Last ned:** `Qwen/Qwen2.5-4B-Instruct-GGUF`
- **Anbefalt kvantisering:** Q4_K_M
- **Fordeler:** Spesialbygd for multilingual, fantastisk norsk
- **Ulemper:** Litt større enn Llama 3.2

### 2. **Qwen 2.5 7B Instruct**
- **Størrelse:** 7B (krever ~6-8GB VRAM)
- **Norsk:** ⭐⭐⭐⭐⭐ Litt bedre enn 4B
- **Last ned:** `Qwen/Qwen2.5-7B-Instruct-GGUF`
- **Best for:** Hvis du har nok VRAM

### 3. **Mistral 7B Instruct v0.3**
- **Størrelse:** 7B
- **Norsk:** ⭐⭐⭐⭐ Veldig god
- **Personlighet:** Leken og varm
- **Last ned:** `TheBloke/Mistral-7B-Instruct-v0.3-GGUF`

### 4. **Gemma 2 2B Instruct**
- **Størrelse:** 2B (veldig liten!)
- **Norsk:** ⭐⭐⭐⭐ God
- **Hastighet:** Lynrask
- **Last ned:** `bartowski/gemma-2-2b-it-GGUF`
- **Best for:** Hvis VRAM er kritisk lavt

### 5. **Phi-3.5 Mini (3.8B)**
- **Størrelse:** 3.8B
- **Norsk:** ⭐⭐⭐ OK, men ikke like god som Qwen
- **Best for:** Engelsk, programmering

### ❌ Unngå

**Llama 3.2 3B** - Dårlig på norsk, selv med mye prompting
- Fungerer best for engelsk
- Gir gebrokken norsk selv med tydelige instruksjoner

## Min anbefaling

### Hvis du har 6GB+ VRAM:
→ **Qwen 2.5 4B** - Beste balanse mellom kvalitet og størrelse

### Hvis du har 4GB VRAM:
→ **Gemma 2 2B** - Liten men bra på norsk

### Hvis du har 8GB+ VRAM:
→ **Qwen 2.5 7B** - Beste norske resultater

## Hvordan bytte modell

1. Last ned ny modell i LM Studio
2. Endre i `ai/hermes_bridge_server.py`:
   ```python
   LM_STUDIO_MODEL = "qwen-2.5-4b"  # eller din valgte modell
   ```
3. Restart bot: `python3 run_both.py`

## Erfaringer

| Modell | Norsk | Personlighet | VRAM |
|--------|-------|--------------|------|
| Qwen 2.5 4B | ⭐⭐⭐⭐⭐ | Varm, naturlig | ~3GB |
| Gemma 2 2B | ⭐⭐⭐⭐ | Vennlig | ~1.5GB |
| Mistral 7B | ⭐⭐⭐⭐ | Leken | ~5GB |
| Llama 3.2 3B | ⭐⭐ | Stiv | ~2GB |
