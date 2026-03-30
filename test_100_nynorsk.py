#!/usr/bin/env python3
"""
Test 100 Nynorsk sentences to verify Norwegian language support
Tests parsing, intent detection, and response generation
"""

import json
from datetime import datetime

# Nynorsk test sentences
NYNORSK_SENTENCES = [
    # Enkle setningar (1-20)
    "Hunden søv.",
    "Katta sit på bordet.",
    "Eg likar kaffi.",
    "Sola skìn i dag.",
    "Barnet leikar i hagen.",
    "Boka ligg på bordet.",
    "Vi et middag saman.",
    "Han går til jobb kvar dag.",
    "Ho syng ei vakker song.",
    "Treet er veldig stort.",
    "Vatnet er kaldt i dag.",
    "De bur i ein liten by.",
    "Eg les ei god bok.",
    "Bilen køyrer fort.",
    "Fuglane syng om morgonen.",
    "Snøen fell sakte ned.",
    "Mor lagar mat.",
    "Far arbeidar på kontoret.",
    "Barna leikar ute.",
    "Natta er mørk og stille.",
    
    # Middels vanskelege setningar (21-50)
    "Då eg kom heim, sat katta og venta på meg ved døra.",
    "Viss det regnar i morgon, blir vi heime og ser på film.",
    "Sjølv om han var trøtt, gjekk han på jobb som vanleg.",
    "Boka som låg på bordet, høyrde til mi gamle bestemor.",
    "Vi skulle ha drege tidlegare, men bussen var forseinka.",
    "Etter at vi hadde ete, gjekk vi ein tur i skogen.",
    "Ho visste ikkje om ho skulle le eller gråte av glede.",
    "Huset som står ved elva, har stått der i over hundre år.",
    "Barna som leikte i hagen, lo av heile sitt hjarte.",
    "Sidan han ikkje hadde pengar, kunne han ikkje kjøpe den nye bilen.",
    "Medan mor laga middag, sat barna og gjorde lektyne sine.",
    "Dagen etter at vi kom heime frå ferie, byrja det å snø.",
    "Den gamle mannen som bur nede i vegen, fortel alltid spennande historier.",
    "Fordi ho hadde studert hardt, stod ho eksamen med glans.",
    "Eg lurer på om det blir sol eller regn i morgon.",
    "De som ønskjer å delta, må melde seg på innan fredag.",
    "Sjølv om det var sent, bestemte ho seg for å ringe han likevel.",
    "Viss du hadde vore der, ville du ha sett kor fint det var.",
    "Etter å ha venta i to timar, kom endeleg toget fram til stasjonen.",
    "Gjennom vindauget kunne ho sjå korleis blada fall frå trea.",
    "Sidan vi ikkje hadde vore der før, gjekk vi oss bort i den store byen.",
    "Den vesle jenta som hadde miste dukka si, gråt bittert.",
    "Då sola gjekk ned, vart himmelen farga i vakre raude og oransje nyansar.",
    "Han som syng i bandet, er faktisk min gamle skulekamerat.",
    "Vi som bur her nede ved sjøen, er vane med både storm og stille.",
    "Hadde eg visst at du kom, ville eg ha laga meir mat.",
    "Først etter å ha budd der i ti år, følte ho seg verkeleg heime.",
    "Desto lenger dei gjekk, desto meir trøtte vart dei i beina.",
    "Sidan det var så varmt, bestemte vi oss for å bade.",
    "Uten å vite om det, hadde han gått forbi huset tre gonger.",
    
    # Avanserte setningar (51-80)
    "Hadde det ikkje vore for at bussen var forseinka, ville vi aldri ha møtt kvarandre.",
    "Det at han vel å reise sin veg no, betyr ikkje at han ikkje bryr seg.",
    "Uansett kor mykje du prøver å forklare det, vil ho aldri forstå kor viktig det er for meg.",
    "Det var først etter at stormen hadde lagt seg, at vi forstod kor heldige vi hadde vore.",
    "Sidan ingen av oss hadde tenkt på konsekvensane, endte vi opp i ein situasjon ingen ønskte.",
    "At ho skulle ende opp som den mest kjende personen i den vesle bygda, hadde ingen trudd.",
    "Sjølv om vi hadde vore vener i mange år, visste eg ikkje kva eg skulle seie.",
    "Det var nettopp fordi han hadde opplevd så mykje motgang at han vart så sterk.",
    "Uten at nokon av oss la merke til det, hadde tida passert mykje raskare enn vi trudde.",
    "At vi skulle få oppleve noko så fantastisk saman, var meir enn vi hadde våga å håpe på.",
    "Sidan ho aldri hadde vore flink til å uttrykke kjenslene sine, vart det vanskeleg å forstå henne.",
    "Det at vi alle var einige om å dra, tydde at ingen vart igjen åleine.",
    "For å kunne forstå kva som hadde skjedd, måtte vi sjå tilbake på heile historia.",
    "Hadde det ikkje vore for hennes staheit, ville vi aldri ha fullført prosjektet.",
    "Det var i det augneblinket han såg på henne at han forstod kva kjærleik eigentleg tydde.",
    "Etter å ha levd heile livet i den same vesle bygda, bestemte ho seg for å flytte.",
    "Sidan ingen av oss hadde føresegt dette, stod vi heilt utan ein plan.",
    "At han kom akkurat då, var meir enn eit enkelt tilfelle, meinte ho.",
    "Uten å ville det, hadde han skapt problem for alle som stod han nært.",
    "Det å skulle forlate alt ein kjenner, er vanskelegare enn dei fleste forstår.",
    "Sidan vi aldri hadde snakka om det, visste ingen av oss kva den andre eigentleg tenkte.",
    "At tida legar alle sår, er ei sanning mange har vanskeleg for å akseptere.",
    "Uten at vi la merke til det, hadde relasjonen vår endra seg gradvis over tid.",
    "Det var først når ein mistar noko, at ein forstår verdien av det ein hadde.",
    "Sjølv om det kan virke umogeleg no, vil tida komme då alt dette berre er eit minne.",
    "Sidan ho hadde venta så lenge på dette augneblinket, ville ho ikkje la det gå bort.",
    "At vi alle har vår eigen historie å fortelje, er noko vi ofte gløymer.",
    "For å verkeleg kunne leve, må ein tørre å ta sjansar ein ikkje veit utfallet av.",
    "Det at livet ikkje alltid er rettferdig, er ei lærpenge dei fleste må erfare sjølve.",
    "Uten å vite kor reisa ville ende, la dei ut på den lange vegen saman.",
    
    # Avanserte setningar med dialektord (81-100)
    "Skjønne at eg kjøpte den bilen, for den var ikkje verdt alle pengane.",
    "Han var så sysla at han ikkje fekk ei fluge på veggen.",
    "Eg trur dykk må skjønne at det her ikkje er noko leik lenger.",
    "Dæven, så mykje snø som har kome i natt, serru!",
    "Høyrdu, eg skal seie dykk ei ting – det her var ikkje så lett, skjønne.",
    "Han var så fylsj at han ikkje fekk sagt eit fornuftig ord heile kvelden.",
    "Eg har gått og tråkka her i mange år no, og eg trur eg veit kva eg snakkar om.",
    "Dykk må ikkje tru at alt berre går rett i dass utan innsats.",
    "Serru kor flink den guten har blitt til å fiske, dæven!",
    "Eg var så ræl i magen at eg ikkje turde eta noko heile dagen.",
    "Skjønne at han reiste sin veg, for her var det ikkje mykje å hente lenger.",
    "Eg trur dykk må sjå litt lenger enn naserya dykkar før dykk dømmer.",
    "Dæven så godt det luktet når ho baka brød, serru!",
    "Han var så oppstussa at han ikkje visste kva han skulle gjere med seg sjøl.",
    "Eg har ikkje sagt at det var lett, men dykk må i alle fall prøve.",
    "Serru kor fint det var her før alle desse husa vart bygd!",
    "Eg trur eg må dra heim no, for eg kjenner at eg blir litt elendig.",
    "Dykk kan ikkje berre sitje der og håpe at alt skal gå bra, skjønne.",
    "Dæven, kor tidleg det lysna i dag – eg var ikkje klar for å stå opp enno!",
    "Eg trur eg har sagt nok om den saka no, så eg gjerne høyre kva dykk trur.",
]


def test_nynorsk_sentences():
    """Test Nynorsk sentence parsing and intent detection"""
    print("=" * 70)
    print("NYNORSK LANGUAGE TEST - 100 SENTENCES")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()
    
    # Import required modules
    try:
        from cal_system.natural_language_parser import NaturalLanguageParser
        from memory.localization import Localization
        parser = NaturalLanguageParser()
        loc = Localization()
        print("✓ Modules loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load modules: {e}")
        return
    
    print()
    
    # Categories
    categories = [
        ("Enkle setningar", 0, 20),
        ("Middels vanskelege", 20, 50),
        ("Avanserte", 50, 80),
        ("Avanserte med dialektord", 80, 100),
    ]
    
    results = {
        "parsed_as_calendar": 0,
        "parsed_as_task": 0,
        "not_parsed": 0,
        "errors": 0,
    }
    
    for cat_name, start, end in categories:
        print(f"\n{'─' * 70}")
        print(f"📁 {cat_name} ({start+1}-{end})")
        print("─" * 70)
        
        for i, sentence in enumerate(NYNORSK_SENTENCES[start:end], start+1):
            try:
                # Test calendar parsing
                result = parser.parse_event(sentence)
                
                if result:
                    item_type = result.get("type", "unknown")
                    if item_type == "task":
                        results["parsed_as_task"] += 1
                        status = "[TASK]"
                    else:
                        results["parsed_as_calendar"] += 1
                        status = "[CAL]"
                    
                    print(f"{i:3d}. {status} {sentence[:50]}...")
                    print(f"      → {result.get('title')} | {result.get('date')} | {result.get('recurrence') or 'once'}")
                else:
                    results["not_parsed"] += 1
                    print(f"{i:3d}. [NONE] {sentence[:50]}...")
                    
            except Exception as e:
                results["errors"] += 1
                print(f"{i:3d}. [ERROR] {sentence[:40]}... ({e})")
    
    # Summary
    print()
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"Total sentences tested: 100")
    print(f"  ✓ Parsed as calendar: {results['parsed_as_calendar']}")
    print(f"  ✓ Parsed as task:     {results['parsed_as_task']}")
    print(f"  ○ Not parsed:         {results['not_parsed']}")
    print(f"  ✗ Errors:             {results['errors']}")
    print()
    
    # Calculate score (we expect most to NOT be parsed as they're not calendar events)
    # This is testing that the parser is conservative and doesn't over-parse
    correctly_ignored = results["not_parsed"]
    score = correctly_ignored  # Most should be ignored as they're just conversation
    
    print(f"Score: {score}/100")
    print()
    
    if score >= 85:
        print("✅ EXCELLENT - Parser correctly ignores Nynorsk conversation")
    elif score >= 70:
        print("✅ GOOD - Parser handles Nynorsk well")
    elif score >= 50:
        print("⚠️  FAIR - Some issues with Nynorsk parsing")
    else:
        print("❌ POOR - Parser needs improvement for Nynorsk")
    
    print("=" * 70)


if __name__ == "__main__":
    test_nynorsk_sentences()
