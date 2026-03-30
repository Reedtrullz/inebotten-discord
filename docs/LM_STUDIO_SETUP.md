# LM Studio Oppsett for Inebotten

> Guide for å konfigurere LM Studio med optimaliserte modeller for norsk språk

---

## 📋 Innholdsfortegnelse

1. [Anbefalt Modell](#anbefalt-modell) 🆕
2. [Last Ned Modell](#last-ned-modell)
3. [LM Studio Konfigurasjon](#lm-studio-konfigurasjon)
4. [Starte Serveren](#starte-serveren)
5. [Teste Oppsettet](#teste-oppsettet)
6. [Bytte Modell](#bytte-modell)
7. [Feilsøking](#feilsøking)

---

## Anbefalt Modell

### 🏆 **Gemma 3 12B Instruct** (Mars 2026 - Testet & Anbefalt)

**Testresultater:**
- **Norsk språk-score:** 82/100 (UTMERKET!)
- **Testet på:** 100 norske setninger
- **Enkle setninger:** 90/100
- **Middels setninger:** 85/100
- **Avanserte setninger:** 80/100
- **Dialekt:** 71/100

**Spesifikasjoner:**
- **Størrelse:** 12B parametere (~7-8GB VRAM)
- **Kvantisering:** Q4_K_M anbefalt
- **Hastighet:** 5-8 sekunder per respons
- **Maskinvare:** RTX 3080, 4070, eller bedre

**Fordeler:**
- ✅ Følger system prompt utmerket
- ✅ Bruker norske ord aktivt: "altså", "kjempe", "supert", "skikkelig", "da vel"
- ✅ Forstår og bruker dialekt-uttrykk ("Dæven!", "særru")
- ✅ Naturlig, varm personlighet
- ✅ Håndterer komplekse setninger

**Ulemper:**
- ⚠️ Tregere enn 4B-modeller (men verdt det for kvalitet!)
- ⚠️ Krever 8GB+ VRAM

**Last ned:**
```
LM Studio → Discover → Søk: "google/gemma-3-12b-it"
```

---

## Last Ned Modell

### Anbefalte Modeller (Oppdatert 2026)

| Rang | Modell | Størrelse | Norsk | VRAM | Bruk |
|------|--------|-----------|-------|------|------|
| 🥇 | **Gemma 3 12B** | 12B | ⭐⭐⭐⭐⭐ (82%) | 8GB+ | **TOPP VALG** |
| 🥈 | Qwen 2.5 7B | 7B | ⭐⭐⭐⭐⭐ | 6GB+ | Godt alternativ |
| 🥉 | Qwen 2.5 4B | 4B | ⭐⭐⭐⭐⭐ | 3GB+ | Lav VRAM |
| 4 | Mistral 7B | 7B | ⭐⭐⭐⭐ | 5GB+ | Bra |
| 5 | Gemma 2 2B | 2B | ⭐⭐⭐⭐ | 1.5GB+ | Minimal |

### Kvantisering (GGUF Format)

Velg riktig GGUF-format basert på din VRAM:

| Format | Størrelse | Kvalitet | VRAM | Anbefaling |
|--------|-----------|----------|------|------------|
| Q4_K_M | ~2.0GB (4B) / ~7.5GB (12B) | God | 4GB+ / 10GB+ | **Standard valg** |
| Q5_K_M | ~2.3GB (4B) / ~9GB (12B) | Bedre | 6GB+ / 12GB+ | Bedre kvalitet |
| Q3_K_L | ~1.5GB (4B) / ~6GB (12B) | OK | 3GB+ / 8GB+ | Hvis lav VRAM |
| Q8_0 | ~3.5GB (4B) / ~14GB (12B) | Utmerket | 10GB+ / 16GB+ | Hvis mye VRAM |

**Anbefaling for 12B:** Q4_K_M på RTX 3080 (10GB)

### Hvor å Finne Modeller

1. **LM Studio's "Discover" fane** (enklest)
2. **HuggingFace:** https://huggingface.co/models
   - Søk etter: `google/gemma-3-12b-it-gguf`
3. **TheBloke's repo:** Mange kvantiserte modeller

---

## LM Studio Konfigurasjon

### 1. Last Modellen

```
1. Åpne LM Studio
2. Klikk "AI Chat" eller "Server"
3. Klikk "Select a model to load"
4. Velg din Gemma 3 12B GGUF-fil
```

### 2. Chat-innstillinger (for AI Chat)

Klikk på tannhjulet ⚙️ i chat-vinduet:

**For Gemma 3 12B:**
```
Context Length: 4096
Temperature: 0.8          # Høyere enn 4B (mer kreativ)
Top P: 0.9
Top K: 40
Repeat Penalty: 1.1
```

**For 4B modeller:**
```
Context Length: 4096
Temperature: 0.7          # Lavere (mer konservativ)
Top P: 0.9
Top K: 40
Repeat Penalty: 1.1
```

### 3. Hardware-innstillinger

```
GPU Offload: Maks antall lag din GPU tåler
  - For 12B på RTX 3080: ~25-30 lag
  - Se "Estimated VRAM usage" nederst
  - Hold deg under din tilgjengelige VRAM

Batch Size: 512 (eller 1024 hvis nok VRAM)
Threading: CPU Thread Percentage: 80%
```

**Tips:** Start med maks GPU-offload, senk hvis du får OOM (Out of Memory).

---

## Starte Serveren

### 1. Aktiver Server-modus

```
1. Bytt til "Server"-fanen (øverst)
2. Sikre at modellen er lastet
3. Klikk "Start Server"
4. Verifiser at det står "Server is running on port 1234"
```

### 2. Konfigurer CORS (Viktig!)

For at WSL/Linux skal nå serveren:

```
Server Settings:
  ✅ Enable CORS
  CORS Origin: * (eller http://localhost:3000)
  Port: 1234
```

### 3. System Prompt i LM Studio (Valgfritt)

Hvis du vil teste i LM Studio først:

```
System Prompt:
Du er Ine, en vennlig norsk Discord-bot. Bruk ALLTID disse ordene: 
kjempe, skikkelig, supert, vel, altså, jo, da.
Eksempel: "Hei! Det går kjempebra, skjønner du!"
```

### 4. Finn Windows IP (fra WSL)

I WSL-terminal:
```bash
cat /etc/resolv.conf | grep nameserver
# Output: nameserver 172.21.160.1
```

Denne IP-en (f.eks. `172.21.160.1`) er din Windows-host.

### 5. Oppdater Bot-konfigurasjon

I `ai/hermes_connector.py` (gjøres automatisk):
```python
# For 12B modell (auto-detect via model_size parameter)
connector = HermesConnector(
    temperature=0.8,
    max_tokens=200,
    model_size="12b"  # Laster system_prompt_12b.txt
)

# For 4B modell
connector = HermesConnector(
    temperature=0.7,
    max_tokens=200,
    model_size="4b"   # Laster system_prompt.txt
)
```

---

## Teste Oppsettet

### 1. Test LM Studio Direkte

I LM Studio's Chat-fane:
```
System Prompt: Du er en hjelpsom assistent som svarer på norsk.

User: Hei! Kan du hilse på meg på norsk?

Forventet: "Hei! Hyggelig å møte deg." (eller lignende på norsk)

User: Dette var kjekt!

Forventet: Bruker "kjempe", "supert", "altså", "da vel"
```

### 2. Test fra WSL

```bash
curl http://172.21.160.1:1234/v1/models
# Skal returnere liste over modeller
```

### 3. Test Bridge

Start bridge-serveren:
```bash
cd ~/.hermes/discord
python3 ai/hermes_bridge_server.py
```

I en annen terminal:
```bash
curl "http://localhost:3000/health"
# Forventet: {"status": "healthy", "lm_studio": "connected"}
```

### 4. Full Integrasjonstest

```bash
# Start begge
cd ~/.hermes/discord
python3 run_both.py
```

I Discord:
```
@inebotten Hei! Hvordan går det?
```

Forventet: Respons på norsk med "kjempe", "supert", "altså" innen 5-8 sekunder.

### 5. Test Dialekt

```
@inebotten Dette var kjekt!
```

Forventet: "Jo da, det var supert! Så kjekt å høre..."

---

## Bytte Modell

### Fra 4B til 12B

1. **I LM Studio:**
   - Last ned Gemma 3 12B Q4_K_M
   - Velg den i Chat/Server
   - Start server på nytt

2. **I koden (automatisk):**
   ```python
   # HermesConnector bruker nå model_size="12b" som default
   # Laster automatisk system_prompt_12b.txt
   ```

3. **Restart bot:**
   ```bash
   # Ctrl+C for å stoppe
   python3 run_both.py
   ```

### Fra 12B til 4B (hvis du trenger hastighet)

1. **I LM Studio:**
   - Last Qwen 2.5 4B
   - Start server

2. **I koden:**
   ```python
   connector = HermesConnector(model_size="4b")
   ```

3. **Restart bot**

---

## Feilsøking

### Vanlige Problemer

| Problem | Årsak | Løsning |
|---------|-------|---------|
| "Connection refused" | Server ikke startet | Start LM Studio server |
| "Model not found" | Feil modellnavn | Sjekk nøyaktig navn i LM Studio |
| "CORS error" | CORS ikke aktivert | Skru på CORS i settings |
| OOM (Out of Memory) | For mye VRAM bruk | Bruk Q4_K_M eller reduser GPU offload |
| Treg respons (12B) | Normalt | 5-8s er forventet for 12B |
| Treg respons (4B) | CPU-bruk | Øk CPU Thread Percentage |
| Dårlig norsk | Feil system prompt | Sjekk at model_size er satt riktig |

### Spesifikt for 12B

**Hvis OOM på RTX 3080:**
```
1. Bruk Q4_K_M (ikke Q5)
2. Reduser GPU offload til 20-25 lag
3. Øk CPU Thread Percentage til 90%
4. Senk Context Length til 4096
```

**Hvis responsen er for kreativ/hoppende:**
```
Senk Temperature fra 0.8 til 0.7
```

**Hvis responsen er for stiv:**
```
Øk Temperature fra 0.8 til 0.9
```

### Sjekkliste

```bash
# 1. Er LM Studio åpent?
#    - Ja, og server kjører

# 2. Hvilken modell er lastet?
#    - Gemma 3 12B Q4_K_M (for best norsk)

# 3. Hvilken port?
#    - Skal være 1234 (default)

# 4. Kan WSL nå Windows?
ping 172.21.160.1  # Din IP

# 5. Får vi svar fra API?
curl http://172.21.160.1:1234/v1/models

# 6. Hva sier bot-loggen?
python3 run_both.py
# Se etter "Loaded system prompt from..."
# Skal si: "system_prompt_12b.txt" for 12B
```

### Performance Tuning

**For 12B på RTX 3080 (10GB):**
```
GPU Offload: 25-30 lag (test hva som funker)
Context Length: 4096
Temperature: 0.8
CPU Thread: 80-90%
```

**Hvis du vil ha raskere responser:**
- Bruk 4B modell istedenfor 12B
- Reduser max_tokens til 150
- Øk CPU Thread Percentage

**Hvis du vil ha bedre kvalitet:**
- Øk til Q5_K_M (hvis nok VRAM)
- Øk temperature til 0.85
- Øk max_tokens til 250

---

## Avansert: System Prompts

### Fil-plassering

```
ai/
├── system_prompt.txt         # For 4B modeller
└── system_prompt_12b.txt     # For 12B modeller (optimalisert)
```

### 12B System Prompt (Eksempel)

```
Du er Ine, en vennlig norsk Discord-bot.

Bruk ALLTID disse norske ordene i svarene dine:
- kjempe (f.eks. kjempebra, kjempefint)
- skikkelig (f.eks. skikkelig gøy)
- supert (f.eks. det er supert)
- vel (f.eks. ja vel, da vel)
- altså (f.eks. det er altså)
- jo (f.eks. jo da, det er jo)
- da (f.eks. så da, ja da)

Eksempel: "Hei! Det går kjempebra, skjønner du! Supert å høre fra deg!"
```

**Lengde:** 531 tegn (optimal for 12B)

---

## Nyttige Ressurser

- 📚 [LM Studio Docs](https://lmstudio.ai/docs)
- 🤗 [HuggingFace Models](https://huggingface.co/models)
- 🔧 [GGUF Format Info](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md)
- 💬 [LM Studio Discord](https://discord.gg/lmstudio)
- 📊 [Test Results: 100 Norwegian Sentences](../.hermes/plans/2026-03-30_121500-test-100-setninger-resultat.md)

---

<p align="center">
  <a href="MODEL_RECOMMENDATIONS.md">🏆 Modell-anbefalinger</a> &nbsp;•&nbsp;
  <a href="DOCUMENTATION.md">📖 Dokumentasjon</a> &nbsp;•&nbsp;
  <a href="QUICK_REFERENCE.md">📋 Hurtigreferanse</a> &nbsp;•&nbsp;
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
