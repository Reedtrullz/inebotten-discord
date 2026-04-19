#!/usr/bin/env python3
"""
Test advanced and dialect sentences (51-100)
"""

import asyncio
from ai.hermes_connector import HermesConnector


async def test_remaining():
    connector = HermesConnector(temperature=0.8, max_tokens=200, model_size="12b")
    
    # Avanserte setninger (51-80)
    avanserte = [
        ("Hadde det ikke vært for at bussen var forsinket, ville vi aldri ha møtt hverandre.", "tilfeldighet"),
        ("Det at han velger å reise sin vei nå, betyr ikke at han ikke bryr seg.", "tolking"),
        ("Uansett hvor mye du prøver å forklare det, vil hun aldri forstå hvor viktig det er for meg.", "misforståelse"),
        ("Det var først etter at stormen hadde lagt seg, at vi forstod hvor heldige vi hadde vært.", "innsikt"),
        ("Siden ingen av oss hadde tenkt over konsekvensene, endte vi opp i en situasjon ingen ønsket.", "konsekvens"),
        ("At hun skulle ende opp som den mest kjente personen i den lille bygda, hadde ingen trodd.", "ironisk"),
        ("Selv om vi hadde vært venner i mange år, visste jeg ikke hva jeg skulle si.", "tausehet"),
        ("Det var nettopp fordi han hadde opplevd så mye motgang at han ble så sterk.", "karakter"),
        ("Uten at noen av oss la merke til det, hadde tiden passert mye fortere enn vi trodde.", "tidsflykt"),
        ("At vi skulle få oppleve noe så fantastisk sammen, var mer enn vi hadde våget å håpe på.", "takknemlighet"),
        ("Siden hun aldri hadde vært flink til å uttrykke følelsene sine, ble det vanskelig å forstå henne.", "kommunikasjon"),
        ("Det at vi alle var enige om å dra, betydde at ingen ble igjen alene.", "solidaritet"),
        ("For å kunne forstå hva som hadde skjedd, måtte vi se tilbake på hele historien.", "forståelse"),
        ("Hadde det ikke vært for hennes stahet, ville vi aldri ha fullført prosjektet.", "utholdenhet"),
        ("Det var i det øyeblikket han så på henne at han forsto hva kjærlighet egentlig betydde.", "kjærlighet"),
    ]
    
    # Dialekt (81-100)
    dialekt = [
        ("Skjønnæ at æ kjøpte den bilen, for den va itj verdt alle pengan.", "trøndersk"),
        ("Han va så sysla at han itj fikk ei flue på veggen.", "trøndersk"),
        ("Æ trur dokker må skjønne at det her itj e no lek lenger.", "nordnorsk"),
        ("Dæven, så mykje snø som ha kome i natt, særru!", "nordnorsk"),
        ("Hørru, æ ska sei dokker en ting – det her va itj så lett, skjønnæ.", "nordnorsk"),
        ("Særru kor flink den guten ha blitt til å fiske, dæven!", "nordnorsk"),
        ("Æ va så ræl i magen at æ itj turde eta noko heile dagen.", "trøndersk"),
        ("Dokker må itj tru at alt bare går rett i dass utan innsats.", "nordnorsk"),
        ("Dæven så godt det luktet når ho baka brød, særru!", "nordnorsk"),
        ("Æ trur æ må dra heim no, for æ kjennæ at æ blir litt elendig.", "nordnorsk"),
    ]
    
    print("="*70)
    print("TEST AV AVANSERTE OG DIALEKT-SETNINGER (51-100)")
    print("="*70)
    
    # Test avanserte
    print("\n--- AVANSERTE SETNINGER ---")
    avanserte_scores = []
    
    for i, (sentence, tag) in enumerate(avanserte, 51):
        success, response = await connector.generate_response(
            message_content=sentence,
            author_name="TestBruker",
            channel_type="GROUP_DM",
            is_mention=True,
        )
        
        if success:
            # Simplified scoring
            target_words = ['kjempe', 'skikkelig', 'supert', 'vel', 'kjekt', 'altså', 'jo', 'da', 'skjønner']
            matches = sum(1 for word in target_words if word in response.lower())
            score = min(100, 40 + matches * 6)
            avanserte_scores.append(score)
            
            status = "✓" if score >= 60 else "⚠"
            print(f"{status} {i}. {sentence[:45]}... → {score}%")
        else:
            print(f"✗ {i}. FEIL")
            avanserte_scores.append(0)
        
        await asyncio.sleep(0.5)
    
    # Test dialekt
    print("\n--- DIALEKT-SETNINGER ---")
    dialekt_scores = []
    
    for i, (sentence, tag) in enumerate(dialekt, 81):
        success, response = await connector.generate_response(
            message_content=sentence,
            author_name="TestBruker",
            channel_type="GROUP_DM",
            is_mention=True,
        )
        
        if success:
            # Check if bot acknowledges dialect or uses Norwegian words
            has_dialect_response = any(word in response.lower() for word in 
                ['dialekt', 'trøndersk', 'nordnorsk', 'morsomt', 'artig', 'kjekt', 'tøft'])
            matches = sum(1 for word in ['kjempe', 'skikkelig', 'supert', 'vel', 'altså'] 
                         if word in response.lower())
            
            if has_dialect_response:
                score = 85
            else:
                score = min(100, 30 + matches * 8)
            
            dialekt_scores.append(score)
            
            status = "✓" if score >= 60 else "⚠"
            print(f"{status} {i}. {sentence[:45]}... → {score}%")
            if i % 3 == 0:
                print(f"    Respons: {response[:70]}...")
        else:
            print(f"✗ {i}. FEIL")
            dialekt_scores.append(0)
        
        await asyncio.sleep(0.5)
    
    await connector.close()
    
    # Summary
    print("\n" + "="*70)
    print("OPPSUMMERING SETNING 51-100")
    print("="*70)
    
    if avanserte_scores:
        avg_avansert = sum(avanserte_scores) / len(avanserte_scores)
        print(f"Avanserte (51-65): {avg_avansert:.1f}/100")
    
    if dialekt_scores:
        avg_dialekt = sum(dialekt_scores) / len(dialekt_scores)
        print(f"Dialekt (81-90):   {avg_dialekt:.1f}/100")
    
    if avanserte_scores and dialekt_scores:
        total_avg = (sum(avanserte_scores) + sum(dialekt_scores)) / (len(avanserte_scores) + len(dialekt_scores))
        print(f"\nGjennomsnitt 51-100: {total_avg:.1f}/100")


if __name__ == "__main__":
    asyncio.run(test_remaining())
