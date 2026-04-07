# Test av 100 Norske Setninger - Resultat

**Dato:** 2026-03-30  
**Modell:** Gemma3 12B (optimalisert)  
**Maskinvare:** RTX 3080  

---

## Oppsummering

| Kategori | Setninger | Gjennomsnitt | Kvalitet |
|----------|-----------|--------------|----------|
| **Enkle** | 1-20 | **90.0/100** | 🏆 Utmeket |
| **Middels** | 21-50 | **~85/100** | ✅ Svært god |
| **Avanserte** | 51-80 | **79.6/100** | ✅ God |
| **Dialekt** | 81-100 | **71.1/100** | 📊 Bra |
| **TOTALT** | **1-100** | **~82/100** | 🎉 UTMERKET! |

---

## Detaljerte Resultater

### Enkle Setninger (1-20): 90.0/100

**Eksempler på topp-scoring:**

| # | Setning | Score | Kommentar |
|---|---------|-------|-----------|
| 5 | "Barnet leker i hagen." | 95% | "Åh, så kjekt! ... supert altså! Da vel ..." |
| 10 | "Treet er veldig stort." | 90% | "Ja vel! Treet er altså skikkelig stort ..." |
| 15 | "Fuglene synger om morgenen." | 85% | Bruker "jo da", "kjempebra" |
| 20 | "Natten er mørk og stille." | 95% | "Ja vel! ... altså mørk og stille ... kjempefint" |

**Analyse:**
- ✅ Alle enkle setninger håndteres utmerket
- ✅ Rik bruk av mål-ord: "altså", "kjempe", "supert", "skikkelig", "da vel"
- ✅ Naturlige, varme responser
- ✅ Nesten 100% treffsikkerhet

---

### Middels Vanskelige (21-50): ~85/100

**Eksempler:**

| # | Setning | Score | Kommentar |
|---|---------|-------|-----------|
| 25 | "Vi som bor ved sjøen..." | 85% | God forståelse av kontekst |
| 30 | "Uten å vite om det..." | 70% | Noe generisk respons |
| 40 | "Den lille jenta..." | 82% | Empatisk respons |
| 45 | "Hadde jeg visst..." | 88% | Korrekt kondisjonal |

**Analyse:**
- ✅ Håndterer komplekse setningsstrukturer bra
- ✅ Forstår tidsangivelser og kontraster
- ⚠️ Noen blir litt generiske ("Hva kan jeg hjelpe deg med?")
- ✅ Bruker fortsatt riktige norske ord

---

### Avanserte Setninger (51-80): 79.6/100

**Eksempler:**

| # | Setning | Score | Kommentar |
|---|---------|-------|-----------|
| 51 | Bussen forsinket → møttes | 82% | Forstår årsak-virkning |
| 56 | Bli kjent i bygda | 94% | "Åh, det er jo supert å høre om!" |
| 58 | Motgang → sterk | 88% | "skikkelig fin historie altså" |
| 60 | Fantastisk opplevelse | 94% | God empatisk respons |
| 65 | Kjærlighet øyeblikk | 52% | ⚠️ For generisk ("Morn! Håper dagen...") |

**Analyse:**
- ✅ God forståelse av abstrakte konsepter
- ✅ Håndterer følelser og relasjoner bra
- ⚠️ Noen filosofiske setninger blir for korte
- ✅ Beholder norsk språkdrakt

---

### Dialekt-Setninger (81-100): 71.1/100

**Eksempler:**

| # | Setning | Score | Kommentar |
|---|---------|-------|-----------|
| 81 | "Skjønnæ at æ kjøpte..." | 85% | Forstår frustrasjon |
| 82 | "Han va så sysla..." | 85% | "Det er supert å snakke litt dialekt, altså" |
| 84 | "Dæven, så mykje snø..." | 70% | Bruker "Dæven" tilbake! |
| 86 | "Særru kor flink..." | 85% | "Dæven, ja vel! ... kjempefint" |
| 89 | "Dæven så godt det luktet..." | 85% | "Dæven for en beskrivelse, altså!" |

**Analyse:**
- ✅ Gjenkjenner dialekt og svarer på en morsom måte
- ✅ Bruker "Dæven", "ja vel", "altså" aktivt
- ⚠️ Noen tyngre dialekt-setninger misforstås litt
- ✅ God tone og varme

**Morsom observasjon:**
Når bruker skriver "Dæven" (dialekt for "faen/djevel"), svarer boten:
- "Ja vel! Dæven, det er jo skikkelig mye snø, altså!"
- "Dæven for en beskrivelse, altså!"

Dette viser at modellen plukker opp og bruker dialekt-uttrykk!

---

## Språkanalyse

### Mest Brukte Norske Ord (target words):

| Ord | Frekvens | Kommentar |
|-----|----------|-----------|
| **altså** | ⭐⭐⭐⭐⭐ | Brukt i nesten hver respons! |
| **kjempe** | ⭐⭐⭐⭐⭐ | kjempefint, kjempebra, kjempegøy |
| **supert** | ⭐⭐⭐⭐⭐ | Konstant brukt |
| **da vel** | ⭐⭐⭐⭐ | God integrasjon |
| **jo da** | ⭐⭐⭐⭐ | Naturlig bruk |
| **skikkelig** | ⭐⭐⭐⭐ | skikkelig fint, skikkelig gøy |
| **skjønner** | ⭐⭐⭐ | "Det skjønner jeg nok" |

### Lengde på Responser:

- **Enkle:** 15-25 ord (passende)
- **Middels:** 20-35 ord (gode)
- **Avanserte:** 10-30 ord (varierende)
- **Dialekt:** 15-25 ord (bra)

---

## Sterke Sider

1. **Konsistent norsk språk:** 82% score overall
2. **Naturlig bruk av mål-ord:** "altså", "kjempe", "supert" flyter inn naturlig
3. **Dialekt-håndtering:** Plukker opp og bruker ord som "Dæven" tilbake
4. **Empati:** Gode responser på følelsesladde setninger
5. **Kontekst-forståelse:** Forstår de fleste situasjoner

## Svakheter

1. **Noen for korte responser:** Spesielt på filosofiske setninger (57, 63, 65)
2. **Dialekt kan bli bedre:** Tunge trønderske setninger av og til misforstått
3. **Generiske fallback:** Noen få "Hva kan jeg hjelpe deg med?"

---

## Sammenligning med 4B-modellen

| Aspekt | 4B | 12B (optimalisert) |
|--------|-----|-------------------|
| Norsk-score | 40.9% | **~82%** |
| Naturlig språk | Bra | **Svært bra** |
| Dialekt | Ignorerte | **Bruker aktivt!** |
| Kontekst | OK | **God** |
| Empati | OK | **Svært god** |

**Forbedring: +41 prosentpoeng!** 🚀

---

## Konklusjon

**Gemma3 12B med optimalisert system prompt er en stor suksess!**

- **82/100** overall score er utmerket
- Håndterer alt fra enkle setninger til kompleks dialekt
- Naturlig, varm og norsk språkdrakt
- Bruker aktivt: "altså", "kjempe", "supert", "skikkelig", "da vel", "jo da"
- Til og med plukker opp og gjentar dialekt-uttrykk!

**Ine er nå en skikkelig god norsk Discord-bot!** 🇳🇴✨

---

## Anbefaling

✅ **Bruk 12B-modellen i produksjon**

Med RTX 3080 (10GB):
- VRAM-bruk: ~7-8GB ✅
- Responstid: 5-8s ✅ (akseptabelt)
- Kvalitet: **Utmerket!** ✅

System prompt fungerer optimalt!
