# LM Studio Oppsett for Inebotten

> Guide for å konfigurere LM Studio med Llama 3.2 (eller andre modeller)

---

## 📋 Innholdsfortegnelse

1. [Last Ned Modell](#last-ned-modell)
2. [LM Studio Konfigurasjon](#lm-studio-konfigurasjon)
3. [Starte Serveren](#starte-serveren)
4. [Teste Oppsettet](#teste-oppsettet)
5. [Bytte Modell](#bytte-modell)
6. [Feilsøking](#feilsøking)

---

## Last Ned Modell

### Anbefalte Modeller

| Modell | Størrelse | Norsk | Hastighet | Bruk |
|--------|-----------|-------|-----------|------|
| **Llama 3.2 3B Instruct** | 3B | ⭐⭐⭐⭐ | Veldig rask | Standard valg |
| Llama 3.1 8B Instruct | 8B | ⭐⭐⭐⭐⭐ | Rask | Bedre kvalitet |
| Qwen 2.5 7B Instruct | 7B | ⭐⭐⭐⭐ | Rask | God instruksjonsfølging |
| Mistral 7B Instruct | 7B | ⭐⭐⭐⭐ | Rask | God personlighet |

### Kvantisering (GGUF Format)

Velg riktig GGUF-format basert på din VRAM:

| Format | Størrelse | Kvalitet | VRAM |
|--------|-----------|----------|------|
| Q4_K_M | ~2.0GB | God | 4GB+ |
| Q5_K_M | ~2.3GB | Bedre | 6GB+ |
| Q6_K | ~2.7GB | Best | 8GB+ |
| Q8_0 | ~3.5GB | Utmerket | 10GB+ |

**Anbefaling:** Start med **Q4_K_M** - best balanse mellom kvalitet og hastighet.

### Hvor å Finne Modeller

1. **LM Studio's "Discover" fane** (enklest)
2. **HuggingFace:** https://huggingface.co/models
   - Søk etter: `llama-3.2-3b-instruct-gguf`
3. **TheBloke's repo:** Mange kvantiserte modeller

---

## LM Studio Konfigurasjon

### 1. Last Modellen

```
1. Åpne LM Studio
2. Klikk "AI Chat" eller "Server"
3. Klikk "Select a model to load"
4. Velg din Llama 3.2 GGUF-fil
```

### 2. Chat-innstillinger (for AI Chat)

Klikk på tannhjulet ⚙️ i chat-vinduet:

```
Context Length: 4096
Temperature: 0.75
Top P: 0.9
Top K: 40
Repeat Penalty: 1.1
```

### 3. Hardware-innstillinger

```
GPU Offload: Maks antall lag din GPU tåler
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

### 3. Finn Windows IP (fra WSL)

I WSL-terminal:
```bash
cat /etc/resolv.conf | grep nameserver
# Output: nameserver 172.21.160.1
```

Denne IP-en (f.eks. `172.21.160.1`) er din Windows-host.

### 4. Oppdater Bot-konfigurasjon

I `ai/hermes_bridge_server.py`:
```python
LM_STUDIO_URL = "http://172.21.160.1:1234/v1"  # Din IP her
LM_STUDIO_MODEL = "llama-3.2-3b"
```

---

## Teste Oppsettet

### 1. Test LM Studio Direkte

I LM Studio's Chat-fane:
```
System Prompt: Du er en hjelpsom assistent som svarer på norsk.

User: Hei! Kan du hilse på meg på norsk?

Forventet: "Hei! Hyggelig å møte deg." (eller lignende på norsk)
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

Forventet: Respons på norsk innen 2-3 sekunder.

---

## Bytte Modell

### Fra Gemma til Llama 3.2

1. **I LM Studio:**
   - Last ned Llama 3.2 3B
   - Velg den i Chat/Server
   - Start server på nytt

2. **I bot-konfigurasjon:**
   ```python
   # ai/hermes_bridge_server.py
   LM_STUDIO_MODEL = "llama-3.2-3b"
   ```

3. **Restart bot:**
   ```bash
   # Ctrl+C for å stoppe
   python3 run_both.py
   ```

### Tilbake til Gemma

```python
LM_STUDIO_MODEL = "gemma-3-4b"
```

Og restart.

---

## Feilsøking

### Vanlige Problemer

| Problem | Årsak | Løsning |
|---------|-------|---------|
| "Connection refused" | Server ikke startet | Start LM Studio server |
| "Model not found" | Feil modellnavn | Sjekk nøyaktig navn i LM Studio |
| "CORS error" | CORS ikke aktivert | Skru på CORS i settings |
| Timeout | For tung modell | Senk batch size, øk CPU % |
| OOM (Out of Memory) | For mye VRAM bruk | Reduser GPU offload layers |
| Treg respons | CPU-bruk | Øk CPU Thread Percentage |
| Dårlig norsk | Feil modell | Bruk Llama 3.2 eller nyere |

### Sjekkliste

```bash
# 1. Er LM Studio åpent?
#    - Ja, og server kjører

# 2. Hvilken port?
#    - Skal være 1234 (default)

# 3. Kan WSL nå Windows?
ping 172.21.160.1  # Din IP

# 4. Får vi svar fra API?
curl http://172.21.160.1:1234/v1/models

# 5. Hva sier bridge-loggen?
python3 ai/hermes_bridge_server.py
# Se etter "LM Studio connected!"
```

### Performance Tuning

**Hvis treg:**
- Senk Context Length til 2048
- Bruk Q4_K_M istedenfor Q5_K_M
- Øk CPU Thread Percentage til 90%

**Hvis OOM:**
- Reduser GPU offload med 5-10 lag
- Bruk lavere kvantisering (Q4 istedenfor Q5)
- Senk Batch Size til 256

**Hvis dårlig kvalitet:**
- Øk temperature til 0.8
- Bruk høyere kvantisering (Q5_K_M eller Q6_K)
- Øk max_tokens til 600

---

## Avansert: Koble til Ekstern LM Studio

Hvis du vil kjøre LM Studio på en annen maskin:

### 1. Finn IP-adresse

På Windows-maskinen (der LM Studio kjører):
```cmd
ipconfig
# Ser etter IPv4 Address, f.eks. 192.168.1.100
```

### 2. Oppdater Bot-konfigurasjon

```python
LM_STUDIO_URL = "http://192.168.1.100:1234/v1"
```

### 3. Sørg for Nettverkstilgang

- Begge maskiner på samme nettverk
- Ingen brannmur blokkerer port 1234
- CORS aktivert i LM Studio

---

## Nyttige Ressurser

- 📚 [LM Studio Docs](https://lmstudio.ai/docs)
- 🤗 [HuggingFace Models](https://huggingface.co/models)
- 🔧 [GGUF Format Info](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md)
- 💬 [LM Studio Discord](https://discord.gg/lmstudio)

---

<p align="center">
  <a href="DOCUMENTATION.md">📖 Dokumentasjon</a> &nbsp;•&nbsp;
  <a href="QUICK_REFERENCE.md">📋 Hurtigreferanse</a> &nbsp;•&nbsp;
  <a href="../README.md">⬅️ Tilbake til README</a>
</p>
