# Modell-anbefalinger for Inebotten

> Tester og erfaringer med ulike AI-modeller for norsk språk

## 🏆 TOPP ANBEFALING

### **Gemma 3 12B Instruct** ⭐⭐⭐ (Beste valg for norsk - testet mars 2026)
- **Størrelse:** 12B (krever ~7-8GB VRAM)
- **Norsk:** ⭐⭐⭐⭐⭐ **82/100 poeng** (UTMERKET!)
- **Hastighet:** ~5-8 sekunder per respons
- **Last ned:** `google/gemma-3-12b-it-GGUF`
- **Anbefalt kvantisering:** Q4_K_M
- **Fordeler:** 
  - Følger system prompt utmerket
  - Bruker norske ord aktivt: "altså", "kjempe", "supert", "skikkelig", "da vel"
  - Forstår og bruker dialekt-uttrykk
  - Håndterer komplekse setninger (82% på 100 test-setninger)
- **Ulemper:** Tregere enn 4B-modeller (men verdt det!)
- **Best for:** RTX 3080/4070 eller bedre

---

## Testet og rangert

### 1. **Gemma 3 12B Instruct** 🥇
- **Norsk-score:** 82/100 (UTMERKET)
- **Enkle setninger:** 90/100
- **Middels setninger:** 85/100
- **Avanserte setninger:** 80/100
- **Dialekt:** 71/100
- **VRAM:** ~7-8GB
- **Kommentar:** Vår nye standard etter omfattende testing!

### 2. **Qwen 2.5 4B Instruct** 🥈 (Godt alternativ for lavere VRAM)
- **Størrelse:** 4B (lite nok for de fleste)
- **Norsk:** ⭐⭐⭐⭐⭐ Utmerket
- **Hastighet:** Veldig rask
- **Last ned:** `Qwen/Qwen2.5-4B-Instruct-GGUF`
- **Anbefalt kvantisering:** Q4_K_M
- **Fordeler:** Spesialbygd for multilingual, fantastisk norsk
- **Ulemper:** Litt større enn Llama 3.2

### 3. **Qwen 2.5 7B Instruct**
- **Størrelse:** 7B (krever ~6-8GB VRAM)
- **Norsk:** ⭐⭐⭐⭐⭐ Litt bedre enn 4B
- **Last ned:** `Qwen/Qwen2.5-7B-Instruct-GGUF`
- **Best for:** Hvis du har nok VRAM

### 4. **Mistral 7B Instruct v0.3**
- **Størrelse:** 7B
- **Norsk:** ⭐⭐⭐⭐ Veldig god
- **Personlighet:** Leken og varm
- **Last ned:** `TheBloke/Mistral-7B-Instruct-v0.3-GGUF`

### 5. **Gemma 2 2B Instruct**
- **Størrelse:** 2B (veldig liten!)
- **Norsk:** ⭐⭐⭐⭐ God
- **Hastighet:** Lynrask
- **Last ned:** `bartowski/gemma-2-2b-it-GGUF`
- **Best for:** Hvis VRAM er kritisk lavt

### 6. **Phi-3.5 Mini (3.8B)**
- **Størrelse:** 3.8B
- **Norsk:** ⭐⭐⭐ OK, men ikke like god som Qwen
- **Best for:** Engelsk, programmering

### ❌ Unngå

**Llama 3.2 3B** - Dårlig på norsk, selv med mye prompting
- Fungerer best for engelsk
- Gir gebrokken norsk selv med tydelige instruksjoner

---

## Min anbefaling (Oppdatert 2026)

### Hvis du har RTX 3080/10GB+ VRAM:
→ **Gemma 3 12B** - 🏆 Beste norske resultater noensinne testet!
- 82/100 poeng på norsk språktest
- Naturlig bruk av "altså", "kjempe", "supert", "da vel"
- Forstår og bruker dialekt

### Hvis du har 6GB VRAM:
→ **Qwen 2.5 4B** - God balanse mellom kvalitet og størrelse

### Hvis du har 4GB VRAM:
→ **Gemma 2 2B** - Liten men bra på norsk

### Hvis du har 8GB+ VRAM (alternativ):
→ **Qwen 2.5 7B** - God, men Gemma 12B er bedre

---

## Hvordan sette opp Gemma 3 12B

1. **Last ned i LM Studio:**
   - Søk etter `google/gemma-3-12b-it`
   - Velg Q4_K_M kvantisering
   - Last ned (~7-8GB)

2. **System prompt er automatisk:**
   - Fil: `ai/system_prompt_12b.txt`
   - Inneholder optimaliserte instruksjoner for norsk
   - Bruker ord: kjempe, skikkelig, supert, vel, altså, jo, da

3. **Konfigurasjon:**
   ```python
   # I koden (gjøres automatisk)
   connector = HermesConnector(
       temperature=0.8,  # Høyere for 12B
       max_tokens=200,
       model_size="12b"  # Laster 12B-optimized prompt
   )
   ```

4. **Start bot:**
   ```bash
   python3 run_both.py
   ```

---

## Testresultater (Gemma 3 12B)

| Kategori | Score | Eksempel |
|----------|-------|----------|
| **Enkle setninger** | 90/100 | "Barnet leker i hagen" → "Åh, så kjekt! ... supert altså!" |
| **Middels** | 85/100 | "Bussen var forsinket" → "Åh, ja vel! ... skikkelig fin historie" |
| **Avanserte** | 80/100 | "Motgang gjør sterk" → "... skikkelig fin historie altså" |
| **Dialekt** | 71/100 | "Dæven, så mye snø!" → "Ja vel! Dæven, det er jo skikkelig mye snø, altså!" |
| **TOTALT** | **82/100** | 🎉 UTMERKET! |

### Språkanalyse (100 setninger)

**Mest brukte norske ord:**
- **altså** - Brukt i nesten hver respons!
- **kjempe** - kjempefint, kjempebra, kjempegøy
- **supert** - Konstant brukt
- **da vel** - God integrasjon
- **jo da** - Naturlig bruk
- **skikkelig** - skikkelig fint, skikkelig gøy

---

## Sammenligning: Før vs Etter

| Metrikk | 4B (før) | 12B (etter) | Forbedring |
|---------|----------|-------------|------------|
| Norsk-score | 40.9% | **82%** | **+41pp** 🚀 |
| Naturlig språk | Bra | **Svært bra** | ✅ |
| Dialekt | Ignorerte | **Bruker aktivt!** | ✅ |
| Responslengde | Kort | **Passende** | ✅ |
| Responstid | 3s | **5-8s** | Acceptabelt |

---

## Erfaringer (Oppdatert)

| Modell | Norsk | Personlighet | VRAM | Anbefaling |
|--------|-------|--------------|------|------------|
| **Gemma 3 12B** | ⭐⭐⭐⭐⭐ | Varm, naturlig | ~7-8GB | 🏆 **TOPP VALG** |
| Qwen 2.5 4B | ⭐⭐⭐⭐⭐ | Varm, naturlig | ~3GB | 🥈 Godt alternativ |
| Gemma 2 2B | ⭐⭐⭐⭐ | Vennlig | ~1.5GB | Lav VRAM |
| Mistral 7B | ⭐⭐⭐⭐ | Leken | ~5GB | Bra |
| Llama 3.2 3B | ⭐⭐ | Stiv | ~2GB | ❌ Unngå |

---

## Oppsett-tips

### For best norsk kvalitet (12B):
- **Temperature:** 0.8 (høyere enn 4B)
- **Max tokens:** 200
- **System prompt:** `ai/system_prompt_12b.txt` (automatisk)
- **Kontekst:** 4096 tokens

### Dialekt-håndtering:
Bruker `respond_to_dialect()` i `ai/personality.py` som sjekker for:
- "kjekt" → "Det var kjekt å høre!"
- "tøft" → "Skikkelig tøft! 👍"
- "rått" → "Helt rått! 🎉"
- "skikkelig" → "Skikkelig bra!"

---

## Konklusjon

**Gemma 3 12B er vår nye standard for norsk språk!**

Med 82/100 poeng, naturlig bruk av norske uttrykk, og evne til å håndtere alt fra enkle setninger til kompleks dialekt, er dette den beste modellen vi har testet.

**Anbefaling:** Hvis du har RTX 3080 eller bedre, bruk Gemma 3 12B!
