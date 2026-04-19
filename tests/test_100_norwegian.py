#!/usr/bin/env python3
"""
Test 12B model with 100 Norwegian sentences
Evaluates response quality from simple to advanced
"""

import asyncio
from ai.hermes_connector import HermesConnector


class NorwegianEvaluator:
    """Evaluate Norwegian language responses"""

    def __init__(self):
        self.results = []
        
    # All 100 sentences organized by difficulty
    SENTENCES = {
        "enkle": [
            ("Hunden sover.", "simpel_utsagn"),
            ("Katten sitter på bordet.", "spatial_relasjon"),
            ("Jeg liker kaffe.", "preferanse"),
            ("Solen skinner i dag.", "observasjon"),
            ("Barnet leker i hagen.", "aktivitet"),
            ("Boken ligger på bordet.", "posisjon"),
            ("Vi spiser middag sammen.", "sosial"),
            ("Han går til jobb hver dag.", "rutine"),
            ("Hun synger en vakker sang.", "beskrivelse"),
            ("Treet er veldig stort.", "egenskap"),
            ("Vannet er kaldt i dag.", "sanse"),
            ("De bor i en liten by.", "lokasjon"),
            ("Jeg leser en god bok.", "aktivitet"),
            ("Bilen kjører fort.", "hastighet"),
            ("Fuglene synger om morgenen.", "natur"),
            ("Snøen faller sakte ned.", "vær"),
            ("Moren lager mat.", "hverdag"),
            ("Faren arbeider på kontoret.", "arbeid"),
            ("Barna leker ute.", "lek"),
            ("Natten er mørk og stille.", "atmosfære"),
        ],
        "middels": [
            ("Da jeg kom hjem, satt katten og ventet på meg ved døren.", "tidsrekkefølge"),
            ("Hvis det regner i morgen, blir vi hjemme og ser på film.", "betingelse"),
            ("Selv om han var trøtt, gikk han på jobb som vanlig.", "kontrast"),
            ("Boken som lå på bordet, tilhørte min gamle bestemor.", "relativ_setning"),
            ("Vi skulle ha dratt tidligere, men bussen var forsinket.", "fortid"),
            ("Etter at vi hadde spist, gikk vi en tur i skogen.", "sekvens"),
            ("Hun visste ikke om hun skulle le eller gråte av glede.", "følelser"),
            ("Huset som står ved elven, har stått der i over hundre år.", "historie"),
            ("Barna som lekte i hagen, lo av hele sine hjertet.", "beskrivelse"),
            ("Siden han ikke hadde penger, kunne han ikke kjøpe den nye bilen.", "årsak"),
            ("Mens moren laget middag, satt barna og gjorde leksene sine.", "samtidig"),
            ("Dagen etter at vi kom hjem fra ferie, begynte det å snø.", "tidsangivelse"),
            ("Den gamle mannen som bor nede i veien, forteller alltid spennende historier.", "karakter"),
            ("Fordi hun hadde studert hardt, besto hun eksamen med glans.", "konsekvens"),
            ("Jeg lurer på om det blir sol eller regn i morgen.", "usikkerhet"),
            ("De som ønsker å delta, må melde seg på innen fredag.", "betingelse"),
            ("Selv om det var sent, bestemte hun seg for å ringe ham likevel.", "beslutning"),
            ("Hvis du hadde vært der, ville du ha sett hvor fint det var.", "hypotetisk"),
            ("Etter å ha ventet i to timer, endelig kom toget frem til stasjonen.", "venting"),
            ("Gjennom vinduet kunne hun se hvordan bladene falt fra trærne.", "observasjon"),
            ("Siden vi ikke hadde vært der før, gikk vi oss bort i den store byen.", "orientering"),
            ("Den lille jenta som hadde mistet dokken sin, gråt bittert.", "sorg"),
            ("Da solen gikk ned, ble himmelen farget i vakre røde og oransje nyanser.", "natur"),
            ("Han som synger i bandet, er faktisk min gamle skolekamerat.", "gjenkjennelse"),
            ("Vi som bor her nede ved sjøen, er vant til både storm og stille.", "tilpasning"),
            ("Hadde jeg visst at du kom, ville jeg ha laget mer mat.", "fortid_kondisjonal"),
            ("Først etter å ha bodd der i ti år, følte hun seg virkelig hjemme.", "tilhørighet"),
            ("Desto lenger de gikk, desto mer trøtte ble de i beina.", "gradvis"),
            ("Siden det var så varmt, bestemte vi oss for å bade.", "beslutning"),
            ("Uten å vite om det, hadde han gått forbi huset tre ganger.", "uvitenhet"),
        ],
        "avanserte": [
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
            ("Etter å ha levd hele livet i den samme lille bygda, bestemte hun seg for å flytte.", "forandring"),
            ("Siden ingen av oss hadde forutsett dette, sto vi helt uten en plan.", "uforberedt"),
            ("At han kom akkurat da, var mer enn et enkelt tilfelle, mente hun.", "skjebne"),
            ("Uten å ville det, hadde han skapt problemer for alle som sto ham nært.", "utilsiktet"),
            ("Det å skulle forlate alt man kjenner, er vanskeligere enn de fleste forstår.", "avskjed"),
            ("Siden vi aldri hadde snakket om det, visste ingen av oss hva den andre egentlig tenkte.", "mangel_kommunikasjon"),
            ("At tiden leger alle sår, er en sannhet mange har vanskelig for å akseptere.", "tilgivelse"),
            ("Uten at vi la merke til det, hadde relasjonen vår forandret seg gradvis over tid.", "utvikling"),
            ("Det var først når man mister noe, at man forstår verdien av det man hadde.", "verdsetting"),
            ("Selv om det kan virke umulig nå, vil tiden komme da alt dette bare er et minne.", "håp"),
            ("Siden hun hadde ventet så lenge på dette øyeblikket, ville hun ikke la det gå bort.", "besluttsomhet"),
            ("At vi alle har vår egen historie å fortelle, er noe vi ofte glemmer.", "historiefortelling"),
            ("For å virkelig kunne leve, må man tørre å ta sjanser man ikke vet utfallet av.", "mot"),
            ("Det at livet ikke alltid er rettferdig, er en lærepenge de fleste må erfare selv.", "livsvisdom"),
            ("Uten å vite hvor reisen ville ende, la de ut på den lange veien sammen.", "eventyr"),
        ],
        "dialekt": [
            ("Skjønnæ at æ kjøpte den bilen, for den va itj verdt alle pengan.", "trøndersk"),
            ("Han va så sysla at han itj fikk ei flue på veggen.", "trøndersk"),
            ("Æ trur dokker må skjønne at det her itj e no lek lenger.", "nordnorsk"),
            ("Dæven, så mykje snø som ha kome i natt, særru!", "nordnorsk"),
            ("Hørru, æ ska sei dokker en ting – det her va itj så lett, skjønnæ.", "nordnorsk"),
            ("Han va så fylsj at han itj fikk sagt et fornuftig ord heile kvelden.", "trøndersk"),
            ("Æ ha gått og tråkka her i mange år no, og æ trur æ veit ka æ snakke om.", "nordnorsk"),
            ("Dokker må itj tru at alt bare går rett i dass utan innsats.", "nordnorsk"),
            ("Særru kor flink den guten ha blitt til å fiske, dæven!", "nordnorsk"),
            ("Æ va så ræl i magen at æ itj turde eta noko heile dagen.", "trøndersk"),
            ("Skjønnæ at han reiste sin veg, for her va det itj mye å hente lenger.", "trøndersk"),
            ("Æ trur dokker må sjå litt lenger enn naserya deres før dokker dømmer.", "nordnorsk"),
            ("Dæven så godt det luktet når ho baka brød, særru!", "nordnorsk"),
            ("Han va så oppstussa at han itj visste kva han sku gjere med seg sjøl.", "trøndersk"),
            ("Æ ha itj sagt at det va lett, men dokker må i hvert fall prøve.", "nordnorsk"),
            ("Særru kor fint det va her før alle desse husan vart bygd!", "nordnorsk"),
            ("Æ trur æ må dra heim no, for æ kjennæ at æ blir litt elendig.", "nordnorsk"),
            ("Dokker kan itj bare sitte der og håpe at alt ska gå bra, skjønnæ.", "nordnorsk"),
            ("Dæven, kor tidlig det lysna i dag – æ va itj klar for å stå opp ennå!", "nordnorsk"),
            ("Æ trur æ ha sagt nokk om den saka no, så æ gærn høre kva dokker trur.", "nordnorsk"),
        ],
    }

    def evaluate_response(self, prompt, response, category):
        """Evaluate the quality of a Norwegian response"""
        score = 0
        feedback = []
        
        # 1. Check if response is in Norwegian (basic)
        norwegian_words = ['jeg', 'du', 'det', 'er', 'og', 'på', 'å', 'med', 'for', 'ikke']
        if any(word in response.lower() for word in norwegian_words):
            score += 20
        else:
            feedback.append("Ikke norsk")
        
        # 2. Check for target Norwegian words
        target_words = ['kjempe', 'skikkelig', 'supert', 'vel', 'kjekt', 'tøft', 'rått', 
                       'skjønner', 'jo', 'da', 'altså', 'nok', 'kanskje', 'egentlig']
        target_matches = sum(1 for word in target_words if word in response.lower())
        score += min(30, target_matches * 3)
        
        # 3. Check for natural flow (sentence length)
        word_count = len(response.split())
        if 5 <= word_count <= 50:
            score += 15
        elif word_count > 50:
            score += 10  # A bit long but OK
        else:
            feedback.append("For kort")
        
        # 4. Context relevance
        prompt_lower = prompt.lower()
        response_lower = response.lower()
        
        # Check if response addresses the topic
        if category == "dialekt":
            # For dialect, check if bot acknowledges or mirrors
            if any(word in response_lower for word in ['dialekt', 'trøndersk', 'nordnorsk', 'morsomt', 'artig']):
                score += 20
            elif target_matches >= 3:
                score += 15  # Uses Norwegian words even if not mentioning dialect
        elif any(word in prompt_lower for word in ['jeg', 'min', 'mitt']):
            # Personal statements should get personal response
            if any(word in response_lower for word in ['du', 'din', 'ditt', 'deg']):
                score += 20
            else:
                score += 10
        else:
            score += 20  # General relevance
        
        # 5. Grammar and coherence (simplified check)
        if response[0].isupper() and response[-1] in '.!?':
            score += 15
        else:
            score += 5
        
        return min(100, score), feedback

    async def run_tests(self):
        """Run all 100 tests"""
        connector = HermesConnector(temperature=0.8, max_tokens=200, model_size="12b")
        
        print("="*70)
        print("TEST AV 100 NORSKE SETNINGER - 12B MODELL")
        print("="*70)
        
        for category, sentences in self.SENTENCES.items():
            print(f"\n{'='*70}")
            print(f"KATEGORI: {category.upper()} ({len(sentences)} setninger)")
            print(f"{'='*70}")
            
            category_scores = []
            
            for i, (sentence, tag) in enumerate(sentences, 1):
                success, response = await connector.generate_response(
                    message_content=sentence,
                    author_name="TestBruker",
                    channel_type="GROUP_DM",
                    is_mention=True,
                )
                
                if success:
                    score, feedback = self.evaluate_response(sentence, response, category)
                    category_scores.append(score)
                    
                    # Print every 5th example
                    if i % 5 == 0 or score < 40:
                        status = "✓" if score >= 50 else "⚠" if score >= 30 else "✗"
                        print(f"\n{status} {i}. {sentence[:50]}...")
                        print(f"   Respons: {response[:70]}...")
                        print(f"   Score: {score}/100")
                else:
                    print(f"\n✗ {i}. {sentence[:50]}...")
                    print(f"   FEIL: {response}")
                    category_scores.append(0)
                
                await asyncio.sleep(0.3)
            
            # Category summary
            if category_scores:
                avg = sum(category_scores) / len(category_scores)
                print(f"\n--- {category.upper()} SNITT: {avg:.1f}/100 ---")
                self.results.append((category, avg, category_scores))
        
        await connector.close()
        
        # Final summary
        print("\n" + "="*70)
        print("ENDELIG OPPSUMMERING")
        print("="*70)
        
        for category, avg, scores in self.results:
            print(f"{category:15s}: {avg:5.1f}/100")
        
        overall = sum(avg for _, avg, _ in self.results) / len(self.results)
        print(f"\n{'TOTALT':15s}: {overall:5.1f}/100")
        
        # Quality assessment
        print("\n" + "="*70)
        if overall >= 70:
            print("🎉🎉🎉 UTMERKET! Modellen håndterer norsk svært bra!")
        elif overall >= 60:
            print("✅ GOD! Modellen håndterer norsk bra!")
        elif overall >= 50:
            print("📊 AKSEPTABEL. Modellen håndterer norsk OK.")
        else:
            print("⚠️  TRENGER FORBEDRING. Modellen sliter med noen setninger.")
        print("="*70)


async def main():
    evaluator = NorwegianEvaluator()
    await evaluator.run_tests()


if __name__ == "__main__":
    asyncio.run(main())
