#!/usr/bin/env python3
"""
Word of the Day (Dagens Ord) for Inebotten
Norwegian words and phrases with explanations
Supports bilingual display
"""

import random
from datetime import datetime


class WordOfTheDay:
    """
    Provides Norwegian word of the day with definitions and usage
    """
    
    def __init__(self):
        self.words_no = [
            {
                'word': 'Koselig',
                'type': 'adjektiv',
                'meaning': 'Hyggelig, trivelig, varm og behagelig atmosfære',
                'examples': [
                    'Det var så koselig hos deg i går!',
                    'Koselig å se deg igjen!',
                ],
                'fun_fact': 'Nordmenn bruker "koselig" mye oftere enn andre nasjoner bruker sine tilsvarende ord!',
            },
            {
                'word': 'Dugnad',
                'type': 'substantiv',
                'meaning': 'Frivillig, ulønnet felles innsats for fellesskapet',
                'examples': [
                    'Vi har dugnad i borettslaget på lørdag.',
                    'Dugnadsånden er sterk i Norge.',
                ],
                'fun_fact': 'Ordet "dugnad" ble kåret til Norges nasjonalord i 2004!',
            },
            {
                'word': 'Skjerpings',
                'type': 'interjeksjon',
                'meaning': 'Uttrykk for at noen må ta seg sammen, bli mer fokusert',
                'examples': [
                    'Skjerpings, gutter! Vi må vinne denne kampen.',
                    'Hørte du rektor si "skjerpings" i dag?',
                ],
                'fun_fact': 'Ofte brukt i sportssammenheng eller når noen er ufocused.',
            },
            {
                'word': 'Takk for sist',
                'type': 'uttrykk',
                'meaning': 'Hilsen som betyr "takk for sist vi møttes"',
                'examples': [
                    'Hei! Takk for sist!',
                    'Takk for sist, det var kjempehyggelig!',
                ],
                'fun_fact': 'Typisk norsk måte å anerkjenne forrige møte på før man fortsetter samtalen.',
            },
            {
                'word': 'Utepils',
                'type': 'substantiv',
                'meaning': 'Å drikke øl ute i solen (spesielt første gangen våren)',
                'examples': [
                    'Endelig første utepilsen i år!',
                    'Ingenting slår en utepils etter jobb.',
                ],
                'fun_fact': 'Nordmenn er nesten religiøse om å få med seg den første utepilsen når sola titter frem!',
            },
            {
                'word': 'Pålegg',
                'type': 'substantiv',
                'meaning': 'Det man legger på brødskiva (ikke bare syltetøy, men alt!)',
                'examples': [
                    'Hva har du på pålegg i dag?',
                    'Brunost er favorittpålegget mitt.',
                ],
                'fun_fact': 'Nordmenn har utrolig mange påleggsalternativer!',
            },
            {
                'word': 'Russ',
                'type': 'substantiv',
                'meaning': 'Avgangselever som feirer siste semester med røde/blå busser og fest',
                'examples': [
                    'Russetiden er den beste tiden i livet!',
                    'Se på den røde russbussen!',
                ],
                'fun_fact': 'Russetradisjonen startet på 1700-tallet som en akademisk feiring!',
            },
            {
                'word': 'Kjæreste',
                'type': 'substantiv',
                'meaning': 'Romantisk partner (ikke nødvendigvis forlovet!)',
                'examples': [
                    'Dette er kjæresten min.',
                    'Har du fått deg kjæreste?',
                ],
                'fun_fact': 'Nordmenn bruker "kjæreste" for alle stadier av forhold!',
            },
            {
                'word': 'Fylla',
                'type': 'substantiv',
                'meaning': 'Å være beruset, full',
                'examples': [
                    'Jeg var på fylla i går.',
                    'Han dro på fylla med kompisene.',
                ],
                'fun_fact': 'Typisk norsk uttrykk som beskriver tilstanden etter å ha drukket alkohol.',
            },
            {
                'word': 'Hygge',
                'type': 'substantiv (dansk)',
                'meaning': 'Trivelig stemning, koselig atmosfære',
                'examples': [
                    'Dette er så hyggelig!',
                    'Vi koser oss med litt hygge.',
                ],
                'fun_fact': 'Selv om det er dansk, bruker mange nordmenn "hygge"!',
            },
        ]
        
        # English "Word of the Day" with interesting English words
        self.words_en = [
            {
                'word': 'Serendipity',
                'type': 'noun',
                'meaning': 'Finding something good without looking for it',
                'examples': [
                    'Meeting you was pure serendipity!',
                    'The discovery was a case of serendipity.',
                ],
                'fun_fact': 'Coined by Horace Walpole in 1754 based on a Persian fairy tale!',
            },
            {
                'word': 'Petrichor',
                'type': 'noun',
                'meaning': 'The pleasant smell of rain on dry earth',
                'examples': [
                    'I love the petrichor after a summer storm.',
                    'The petrichor filled the air.',
                ],
                'fun_fact': 'Coined by Australian scientists in 1964!',
            },
            {
                'word': 'Ephemeral',
                'type': 'adjective',
                'meaning': 'Lasting for a very short time',
                'examples': [
                    'Fame can be ephemeral.',
                    'The beauty of sunset is ephemeral.',
                ],
                'fun_fact': 'From Greek "ephemeros" meaning "lasting only one day"!',
            },
            {
                'word': 'Limerence',
                'type': 'noun',
                'meaning': 'The state of being infatuated with someone',
                'examples': [
                    'His limerence was obvious to everyone.',
                    'She was in a state of limerence.',
                ],
                'fun_fact': 'Coined by psychologist Dorothy Tennov in 1979!',
            },
            {
                'word': 'Sonder',
                'type': 'noun',
                'meaning': 'Realizing everyone has a life as vivid as yours',
                'examples': [
                    'I had a moment of sonder on the subway.',
                    'Sonder hit me while watching the crowd.',
                ],
                'fun_fact': 'Created by The Dictionary of Obscure Sorrows in 2012!',
            },
            {
                'word': 'Defenestration',
                'type': 'noun',
                'meaning': 'The act of throwing someone out a window',
                'examples': [
                    'The defenestration of Prague was a famous event.',
                    'He threatened defenestration jokingly.',
                ],
                'fun_fact': 'There was a famous "Defenestration of Prague" in 1618!',
            },
            {
                'word': 'Mellifluous',
                'type': 'adjective',
                'meaning': 'A sound that is sweet and musical',
                'examples': [
                    'She had a mellifluous voice.',
                    'The mellifluous melody filled the room.',
                ],
                'fun_fact': 'From Latin "mel" (honey) + "fluere" (to flow)!',
            },
            {
                'word': 'Ineffable',
                'type': 'adjective',
                'meaning': 'Too great to be expressed in words',
                'examples': [
                    'The beauty was ineffable.',
                    'Some feelings are simply ineffable.',
                ],
                'fun_fact': 'Often used to describe spiritual experiences!',
            },
        ]
    
    def get_word_of_day(self, lang='no', seed=None):
        """
        Get a word of the day
        Uses date as seed for consistency throughout the day
        """
        words = self.words_no if lang == 'no' else self.words_en
        
        if seed is None:
            seed = datetime.now().strftime('%Y%m%d')
        
        # Use the seed to pick consistently for the day
        random.seed(seed)
        word = random.choice(words)
        random.seed()  # Reset seed
        
        return word
    
    def get_random_word(self, lang='no'):
        """Get a completely random word"""
        words = self.words_no if lang == 'no' else self.words_en
        return random.choice(words)
    
    def format_word(self, word_data, lang='no'):
        """Format word for display in specified language"""
        if lang == 'no':
            header = f"📚 **Dagens ord: {word_data['word']}**"
            meaning_label = "Betydning"
            examples_label = "Eksempler"
            fun_fact_label = "Fun fact"
        else:
            header = f"📚 **Word of the day: {word_data['word']}**"
            meaning_label = "Meaning"
            examples_label = "Examples"
            fun_fact_label = "Fun fact"
        
        lines = [
            header,
            f"*{word_data['type']}*",
            "",
            f"**{meaning_label}:** {word_data['meaning']}",
            "",
            f"**{examples_label}:**",
        ]
        
        for example in word_data['examples'][:2]:
            lines.append(f"• \"{example}\"")
        
        if word_data.get('fun_fact'):
            lines.append(f"\n💡 *{fun_fact_label}:* {word_data['fun_fact']}")
        
        return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    wod = WordOfTheDay()
    
    print("=== Norwegian Word ===\n")
    word = wod.get_word_of_day('no')
    print(wod.format_word(word, 'no'))
    
    print("\n=== English Word ===\n")
    word = wod.get_word_of_day('en')
    print(wod.format_word(word, 'en'))
