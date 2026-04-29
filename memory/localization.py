#!/usr/bin/env python3
"""
Localization module for Inebotten
Supports both Norwegian (no) and English (en)
"""

import re
from datetime import datetime

class Localization:
    """
    Handles language detection and localized responses
    """
    
    def __init__(self, default_lang='no'):
        self.default_lang = default_lang
        self.current_lang = default_lang
        self.setup_translations()
        self.setup_language_patterns()
    
    def setup_translations(self):
        """Setup all translations"""
        self.translations = {
            # Dashboard / General
            'dashboard_title': {
                'no': '🤖 **{bot_name} Dashboard**',
                'en': '🤖 **{bot_name} Dashboard**'
            },
            'last_update': {
                'no': '— _Sist oppdatert: {time}_',
                'en': '— _Last updated: {time}_'
            },
            'events_section': {
                'no': '📅 **Arrangementer ({count})**',
                'en': '📅 **Events ({count})**'
            },
            'reminders_section': {
                'no': '⏰ **Påminnelser ({count})**',
                'en': '⏰ **Reminders ({count})**'
            },
            'no_events': {
                'no': '*Ingen kommende arrangementer*',
                'en': '*No upcoming events*'
            },
            'no_reminders': {
                'no': '*Ingen aktive påminnelser*',
                'en': '*No active reminders*'
            },
            'birthdays_section': {
                'no': '🎂 **Bursdager**',
                'en': '🎂 **Birthdays**'
            },
            'next_birthday': {
                'no': '🎉 **Neste bursdag:** {name} ({date})',
                'en': '🎉 **Next birthday:** {name} ({date})'
            },
            'no_birthdays': {
                'no': '_Ingen bursdager registrert_',
                'en': '_No birthdays registered_'
            },
            'weather_section': {
                'no': '🌤 **Vær**',
                'en': '🌤 **Weather**'
            },
            'aurora_section': {
                'no': '🌌 **Nordlys-sjanse**',
                'en': '🌌 **Aurora Chance**'
            },
            'school_holidays_section': {
                'no': '🏫 **Skoleferier**',
                'en': '🏫 **School Holidays**'
            },
            'greeting_morning': {
                'no': 'God morgen! ☕',
                'en': 'Good morning! ☕'
            },
            'greeting_afternoon': {
                'no': 'God ettermiddag! ☀️',
                'en': 'Good afternoon! ☀️'
            },
            'greeting_evening': {
                'no': 'God kveld! 🌙',
                'en': 'Good evening! 🌙'
            },
            'help_footer': {
                'no': '💬 **Spør meg om:** arrangementer, bursdager, påminnelser, vær, nordlys, ferier',
                'en': '💬 **Ask me about:** events, birthdays, reminders, weather, aurora, holidays'
            },
            
            # Event commands
            'event_saved': {
                'no': '✅ Lagret: **{title}** {date_time}',
                'en': '✅ Saved: **{title}** {date_time}'
            },
            'event_deleted': {
                'no': '🗑️ Slettet: **{title}**',
                'en': '🗑️ Deleted: **{title}**'
            },
            'event_not_found': {
                'no': '❌ Fant ikke arrangement #{num}',
                'en': '❌ Event #{num} not found'
            },
            'calendar_edit_success': {
                'no': '✅ Oppdatert: **{title}**',
                'en': '✅ Updated: **{title}**'
            },
            'calendar_edit_not_found': {
                'no': '❌ Fant ikke element #{num}',
                'en': '❌ Item #{num} not found'
            },
            'calendar_edit_invalid': {
                'no': '❌ Ugyldig redigeringsformat. Bruk: endre [nummer] [felt]: [verdi]',
                'en': '❌ Invalid edit format. Use: edit [number] [field]: [value]'
            },
            'calendar_search_results': {
                'no': '📅 Søkeresultater:',
                'en': '📅 Search results:'
            },
            'calendar_search_no_results': {
                'no': '❌ Ingen treff for \'{query}\'',
                'en': '❌ No matches for \'{query}\''
            },
            'invalid_event_num': {
                'no': '❌ Ugyldig nummer. Bruk: slett 1',
                'en': '❌ Invalid number. Use: delete 1'
            },
            'upcoming_events': {
                'no': '📋 **Kommende arrangementer**',
                'en': '📋 **Upcoming events**'
            },
            'no_upcoming_events': {
                'no': '📭 Ingen kommende arrangementer',
                'en': '📭 No upcoming events'
            },
            'event_item': {
                'no': '{num}. **{title}** ({date_time})',
                'en': '{num}. **{title}** ({date_time})'
            },
            
            # Reminder commands
            'reminder_saved': {
                'no': '⏰ Påminnelse satt: **{text}**',
                'en': '⏰ Reminder set: **{text}**'
            },
            'reminder_completed': {
                'no': '✅ Ferdig: **{text}**',
                'en': '✅ Done: **{text}**'
            },
            'reminder_not_found': {
                'no': '❌ Fant ikke påminnelse #{num}',
                'en': '❌ Reminder #{num} not found'
            },
            'reminder_edit_success': {
                'no': '✅ Påminnelse oppdatert!',
                'en': '✅ Reminder updated!'
            },
            'reminder_edit_not_found': {
                'no': '❌ Fant ikke påminnelse #{num}',
                'en': '❌ Reminder #{num} not found'
            },
            'reminder_delete_success': {
                'no': '🗑️ Påminnelse slettet!',
                'en': '🗑️ Reminder deleted!'
            },
            'reminder_delete_not_found': {
                'no': '❌ Fant ikke påminnelse #{num}',
                'en': '❌ Reminder #{num} not found'
            },
            'reminder_search_results': {
                'no': '⏰ Søkeresultater:',
                'en': '⏰ Search results:'
            },
            'reminder_search_no_results': {
                'no': "❌ Ingen påminnelser funnet for '{query}'",
                'en': "❌ No reminders found for '{query}'"
            },
            'active_reminders': {
                'no': '📋 **Dine påminnelser**',
                'en': '📋 **Your reminders**'
            },
            'no_active_reminders': {
                'no': '📭 Ingen aktive påminnelser',
                'en': '📭 No active reminders'
            },
            'reminder_item': {
                'no': '• {text}',
                'en': '• {text}'
            },
            
            # Birthday commands
            'birthday_saved': {
                'no': '🎂 Bursdag lagret: **{name}** - {date}',
                'en': '🎂 Birthday saved: **{name}** - {date}'
            },
            'birthday_list': {
                'no': '🎂 **Bursdagsliste**',
                'en': '🎂 **Birthday List**'
            },
            'birthday_item': {
                'no': '• {name}: {date} (om {days} dager)',
                'en': '• {name}: {date} (in {days} days)'
            },
            'no_birthdays_saved': {
                'no': '📭 Ingen bursdager lagret ennå!',
                'en': '📭 No birthdays saved yet!'
            },
            'birthday_today': {
                'no': '🎉🎂 **Gratulerer med dagen, {name}!** 🎂🎉',
                'en': '🎉🎂 **Happy Birthday, {name}!** 🎂🎉'
            },
            'birthday_tomorrow': {
                'no': '🎂 **{name}** har bursdag i morgen!',
                'en': '🎂 **{name}**\'s birthday is tomorrow!'
            },
            'birthday_edit_success': {
                'no': '✅ Bursdag oppdatert!',
                'en': '✅ Birthday updated!'
            },
            'birthday_edit_not_found': {
                'no': '❌ Fant ikke bursdag for {name}',
                'en': '❌ Birthday for {name} not found'
            },
            
            # Countdown
            'countdown_result': {
                'no': '📅 **{event}** om **{days}** dager! {emoji}',
                'en': '📅 **{event}** in **{days}** days! {emoji}'
            },
            'countdown_today': {
                'no': '🎉 **{event}** er i dag! {emoji}',
                'en': '🎉 **{event}** is today! {emoji}'
            },
            'countdown_tomorrow': {
                'no': '📅 **{event}** er i morgen! {emoji}',
                'en': '📅 **{event}** is tomorrow! {emoji}'
            },
            'countdown_past': {
                'no': '📅 **{event}** var for {days} dager siden {emoji}',
                'en': '📅 **{event}** was {days} days ago {emoji}'
            },
            'unknown_event': {
                'no': '🤔 Jeg kjenner ikke til "{event}". Prøv: jul, 17. mai, påske, sommerferie',
                'en': '🤔 I don\'t know "{event}". Try: christmas, 17 may, easter, summer holiday'
            },
            
            # Poll
            'poll_created': {
                'no': '📊 {question}\n\n{options}\n💡 Stem med tall (1-{count})',
                'en': '📊 {question}\n\n{options}\n💡 Vote with numbers (1-{count})'
            },
            'poll_option': {
                'no': '{emoji} {text} {bar} {votes} stemmer ({percent}%)',
                'en': '{emoji} {text} {bar} {votes} votes ({percent}%)'
            },
            'vote_registered': {
                'no': '✅ Stemme registrert! Du valgte alternativ {num}.',
                'en': '✅ Vote registered! You chose option {num}.'
            },
            'vote_error': {
                'no': '❌ Kunne ikke registrere stemme: {error}',
                'en': '❌ Could not register vote: {error}'
            },
            'no_active_polls': {
                'no': '📊 Ingen aktive avstemninger akkurat nå!',
                'en': '📊 No active polls right now!'
            },
            'poll_edited': {
                'no': '✅ Avstemning oppdatert!',
                'en': '✅ Poll updated!'
            },
            'poll_deleted': {
                'no': '🗑️ Avstemning slettet!',
                'en': '🗑️ Poll deleted!'
            },
            'poll_closed': {
                'no': '🔒 Avstemning lukket!',
                'en': '🔒 Poll closed!'
            },
            'poll_not_found': {
                'no': '❌ Fant ikke avstemningen.',
                'en': '❌ Poll not found.'
            },
            'poll_not_owner': {
                'no': '🚫 Du kan bare endre/slette dine egne avstemninger.',
                'en': '🚫 You can only edit/delete your own polls.'
            },
            'poll_closed_already': {
                'no': '🔒 Avstemningen er allerede lukket.',
                'en': '🔒 Poll is already closed.'
            },
            'poll_list_title': {
                'no': '📊 **Aktive avstemninger**',
                'en': '📊 **Active Polls**'
            },
            'poll_list_item': {
                'no': '{num}. {question}',
                'en': '{num}. {question}'
            },
            'poll_list_hint': {
                'no': 'Bruk "@inebotten stem [nummer]" for å stemme',
                'en': 'Use "@inebotten vote [number]" to vote'
            },
            'poll_no_permission': {
                'no': '🚫 Du har ikke tilgang til å gjøre dette.',
                'en': '🚫 You don\'t have permission to do that.'
            },
            
            # Watchlist
            'watchlist_suggestion': {
                'no': '🎬 **{type}forslag!**\n\n**{title}**\n{type_icon} {type_name}\nSjanger: {genre}\nÅr: {year}\n\n💬 {comment}',
                'en': '🎬 **{type} Suggestion!**\n\n**{title}**\n{type_icon} {type_name}\nGenre: {genre}\nYear: {year}\n\n💬 {comment}'
            },
            'watchlist_status': {
                'no': '📋 **Watchlist Status**\n🎬 Filmer: {unwatched_movies} usette ({total_movies} totalt)\n📺 Serier: {unwatched_series} usette ({total_series} totalt)',
                'en': '📋 **Watchlist Status**\n🎬 Movies: {unwatched_movies} unwatched ({total_movies} total)\n📺 Series: {unwatched_series} unwatched ({total_series} total)'
            },
            'watchlist_empty': {
                'no': '🎉 Watchlista er tom! Tid for å legge til mer?',
                'en': '🎉 Watchlist is empty! Time to add more?'
            },
            'no_suggestions': {
                'no': 'Beklager, fant ingen forslag akkurat nå! 🎬',
                'en': 'Sorry, no suggestions found right now! 🎬'
            },
            'watchlist_help': {
                'no': '🎬 Watchlist-kommandoer:\n• "@inebotten hva skal vi se?"\n• "@inebotten filmforslag"\n• "@inebotten watchlist status"',
                'en': '🎬 Watchlist commands:\n• "@inebotten what should we watch?"\n• "@inebotten movie suggestion"\n• "@inebotten watchlist status"'
            },
            
            # Quote
            'quote_saved': {
                'no': '💾 Lagret! "{text}"',
                'en': '💾 Saved! "{text}"'
            },
            'quote_random': {
                'no': '💬 **Sitat fra arkivet**\n\n"{text}"\n— {author}\n_{date}_',
                'en': '💬 **Quote from archive**\n\n"{text}"\n— {author}\n_{date}_'
            },
            'quote_list_title': {
                'no': '📚 **Sitater**',
                'en': '📚 **Quotes**'
            },
            'quote_list_empty': {
                'no': '📚 Ingen sitater ennå!',
                'en': '📚 No quotes yet!'
            },
            'quote_edit_success': {
                'no': '✅ Sitat oppdatert!',
                'en': '✅ Quote updated!'
            },
            'quote_edit_not_found': {
                'no': '❌ Fant ikke sitat #{num}',
                'en': '❌ Quote #{num} not found'
            },
            'quote_delete_success': {
                'no': '🗑️ Sitat slettet!',
                'en': '🗑️ Quote deleted!'
            },
            'quote_delete_not_found': {
                'no': '❌ Fant ikke sitat #{num}',
                'en': '❌ Quote #{num} not found'
            },
            'no_quotes': {
                'no': 'Ingen sitater lagret ennå! 💬\n\nSi "@inebotten husk dette: [noe morsomt]" for å lagre!',
                'en': 'No quotes saved yet! 💬\n\nSay "@inebotten remember this: [something funny]" to save!'
            },
            
            # Word of Day
            'word_of_day': {
                'no': '📚 **Dagens ord: {word}**\n*{type}*\n\n**Betydning:** {meaning}\n\n**Eksempler:**\n{examples}\n\n💡 *{fun_fact}*',
                'en': '📚 **Word of the day: {word}**\n*{type}*\n\n**Meaning:** {meaning}\n\n**Examples:**\n{examples}\n\n💡 *{fun_fact}*'
            },
            
            # Aurora
            'aurora_high': {
                'no': '🌌 **Sterk nordlys-aktivitet!**\nSjanse: {chance}%\n\n🎯 Perfekte forhold i kveld!\n📍 Gå ut av byen for best utsikt\n📸 Husk kameraet!',
                'en': '🌌 **Strong aurora activity!**\nChance: {chance}%\n\n🎯 Perfect conditions tonight!\n📍 Go outside the city for best view\n📸 Don\'t forget your camera!'
            },
            'aurora_medium': {
                'no': '🌌 **Moderat nordlys-aktivitet**\nSjanse: {chance}%\n\n🌤️ Kan være verdt å sjekke himmelen!',
                'en': '🌌 **Moderate aurora activity**\nChance: {chance}%\n\n🌤️ Might be worth checking the sky!'
            },
            'aurora_low': {
                'no': '🌌 **Svak nordlys-aktivitet**\nSjanse: {chance}%\n\n😴 Ikke mye å se i kveld.',
                'en': '🌌 **Weak aurora activity**\nChance: {chance}%\n\n😴 Not much to see tonight.'
            },
            
            # School Holidays
            'holiday_now': {
                'no': '🎉 **{name} nå!**\nTil {end_date} ({days_left} dager igjen)',
                'en': '🎉 **{name} now!**\nUntil {end_date} ({days_left} days left)'
            },
            'holiday_upcoming': {
                'no': '📅 **{name}**: {start_date} (om {days} dager)',
                'en': '📅 **{name}**: {start_date} (in {days} days)'
            },
            'holiday_past': {
                'no': '✅ **{name}**: Var {start_date} - {end_date}',
                'en': '✅ **{name}**: Was {start_date} - {end_date}'
            },
            'no_holidays': {
                'no': '📭 Ingen ferier funnet for dette skoleåret',
                'en': '📭 No holidays found for this school year'
            },
            'holidays_title': {
                'no': '🏫 **Skoleferier**',
                'en': '🏫 **School Holidays**'
            },
            
            # Weather
            'weather_current': {
                'no': '🌡️ **{temp}°C** {condition}\n💨 Vind: {wind} m/s\n💧 Fuktighet: {humidity}%',
                'en': '🌡️ **{temp}°C** {condition}\n💨 Wind: {wind} m/s\n💧 Humidity: {humidity}%'
            },
            'weather_activity_sunny': {
                'no': '☀️ Perfekt vær for en tur ut!',
                'en': '☀️ Perfect weather for a walk outside!'
            },
            'weather_activity_rainy': {
                'no': '🌧️ Inne-kos med film og kakao?',
                'en': '🌧️ Indoor coziness with movies and cocoa?'
            },
            'weather_activity_snowy': {
                'no': '❄️ Tid for aking eller skigåing!',
                'en': '❄️ Time for sledding or skiing!'
            },
            
            # Errors
            'error_generic': {
                'no': '😅 Oisann, noe gikk galt! Prøv igjen?',
                'en': '😅 Oops, something went wrong! Try again?'
            },
            'rate_limited': {
                'no': '⏳ Jeg sender for mange meldinger. Vent litt...',
                'en': '⏳ I\'m sending too many messages. Wait a bit...'
            },
            'unknown_command': {
                'no': '🤔 Jeg forstod ikke helt. Prøv "@inebotten hjelp"',
                'en': '🤔 I didn\'t quite understand. Try "@inebotten help"'
            },
            
            # Help
            'help_title': {
                'no': '🤖 **Inebotten Kommandoer**',
                'en': '🤖 **Inebotten Commands**'
            },
            'help_events': {
                'no': '📅 **Arrangementer:**\n• "@inebotten kamp i kveld kl 20"\n• "@inebotten arrangementer" / "events"\n• "@inebotten slett 1" / "delete 1"',
                'en': '📅 **Events:**\n• "@inebotten match tonight at 8pm"\n• "@inebotten events" / "arrangementer"\n• "@inebotten delete 1" / "slett 1"'
            },
            'help_reminders': {
                'no': '⏰ **Påminnelser:**\n• "@inebotten påminnelse kjøpe melk"\n• "@inebotten ferdig 1" / "done 1"\n• "@inebotten påminnelser" / "reminders"',
                'en': '⏰ **Reminders:**\n• "@inebotten reminder buy milk"\n• "@inebotten done 1" / "ferdig 1"\n• "@inebotten reminders" / "påminnelser"'
            },
            'help_birthdays': {
                'no': '🎂 **Bursdager:**\n• "@inebotten bursdag 15.05"\n• "@inebotten bursdager" / "birthdays"',
                'en': '🎂 **Birthdays:**\n• "@inebotten birthday May 15"\n• "@inebotten birthdays" / "bursdager"'
            },
            'help_fun': {
                'no': '🎉 **Moro:**\n• "@inebotten hvor lenge til jul" / "countdown to christmas"\n• "@inebotten avstemning Pizza eller burger?"\n• "@inebotten filmforslag" / "movie suggestion"\n• "@inebotten sitat" / "quote"\n• "@inebotten dagens ord" / "word of the day"\n• "@inebotten nordlys" / "aurora"\n• "@inebotten skoleferie" / "school holidays"\n• "@inebotten bitcoin pris" / "btc price"\n• "@inebotten kompliment @user" / "compliment @user"\n• "@inebotten horoskop vannmannen" / "horoscope aquarius"\n• "@inebotten regn ut 2+2" / "calculate 2+2"\n• "@inebotten 100 USD til NOK" / "convert 100 USD to NOK"\n• "@inebotten forkort [URL]" / "shorten [URL]"\n• "@inebotten daglig oppsummering" / "daily digest"',
                'en': '🎉 **Fun:**\n• "@inebotten countdown to christmas" / "hvor lenge til jul"\n• "@inebotten poll Pizza or burger?"\n• "@inebotten movie suggestion" / "filmforslag"\n• "@inebotten quote" / "sitat"\n• "@inebotten word of the day" / "dagens ord"\n• "@inebotten aurora" / "nordlys"\n• "@inebotten school holidays" / "skoleferie"\n• "@inebotten btc price" / "bitcoin pris"\n• "@inebotten compliment @user" / "kompliment @user"\n• "@inebotten horoscope aquarius" / "horoskop vannmannen"\n• "@inebotten calculate 2+2" / "regn ut 2+2"\n• "@inebotten convert 100 USD to NOK" / "100 USD til NOK"\n• "@inebotten shorten [URL]" / "forkort [URL]"\n• "@inebotten daily digest" / "daglig oppsummering"'
            },
            'help_profile': {
                'no': '👤 **Profil:**\n• "@inebotten status online/dnd/idle"\n• "@inebotten spiller [spill]" / "ser på [film]"',
                'en': '👤 **Profile:**\n• "@inebotten status online/dnd/idle"\n• "@inebotten playing [game]" / "watching [movie]"'
            },
            'help_footer_tip': {
                'no': '\n💡 Jeg forstår både norsk og engelsk!',
                'en': '\n💡 I understand both Norwegian and English!'
            }
        }
    
    def setup_language_patterns(self):
        """Setup patterns to detect language"""
        self.no_patterns = [
            r'\bhv[oa]\b', r'\bn[åa]r\b', r'\bhva\b', r'\bhvem\b',
            r'\ber\b', r'\bdet\b', r'\bden\b', r'\btil\b',
            r'\bskal\b', r'\bskole\b', r'\bferie\b', r'\bpåminnelse\b',
            r'\barrangement\b', r'\bbursdag\b', r'\bsitat\b',
            r'\bforslag\b', r'\bavstemning\b', r'\bnordlys\b',
            r'\bi kveld\b', r'\bi morgen\b', r'\bi dag\b',
            r'\bslett\b', r'\bferdig\b', r'\bhusk\b',
            r'\blagre\b', r'\bse\b', r'\bfilm\b', r'\bserie\b',
            r'\bbitcoin\b', r'\bpris\b', r'\bverdi\b',
            r'\bkompliment\b', r'\bros\b', r'\bhoroskop\b',
            r'\bregn ut\b', r'\bforkort\b', r'\boppsummering\b',
            r'\bkonverter\b', r'\bhva koster\b',
        ]
        
        self.en_patterns = [
            r'\bwhat\b', r'\bwhen\b', r'\bwhere\b', r'\bwho\b',
            r'\bis\b', r'\bthe\b', r'\bto\b', r'\bof\b',
            r'\bwill\b', r'\bschool\b', r'\bholiday\b', r'\breminder\b',
            r'\bevent\b', r'\bbirthday\b', r'\bquote\b',
            r'\bsuggestion\b', r'\bpoll\b', r'\bcountdown\b',
            r'\btonight\b', r'\btomorrow\b', r'\btoday\b',
            r'\bdelete\b', r'\bdone\b', r'\bremember\b',
            r'\bsave\b', r'\bwatch\b', r'\bmovie\b', r'\bseries\b',
            r'\bbitcoin\b', r'\bbtc\b', r'\bprice\b', r'\bstock\b',
            r'\bcompliment\b', r'\broast\b', r'\bhoroscope\b',
            r'\bcalculate\b', r'\bcompute\b', r'\bconvert\b',
            r'\bshorten\b', r'\bsummary\b', r'\bdigest\b',
        ]
    
    def detect_language(self, text):
        """
        Detect language from text
        Returns 'no' or 'en'
        """
        text_lower = text.lower()
        
        no_score = sum(1 for p in self.no_patterns if re.search(p, text_lower))
        en_score = sum(1 for p in self.en_patterns if re.search(p, text_lower))
        
        if no_score > en_score:
            return 'no'
        elif en_score > no_score:
            return 'en'
        else:
            return self.default_lang
    
    def get(self, key, **kwargs):
        """Get translated text for current language"""
        if key in self.translations:
            translation = self.translations[key].get(self.current_lang) or self.translations[key].get(self.default_lang) or key
            return translation.format(**kwargs) if kwargs else translation
        return key
    
    def set_language(self, lang):
        """Set current language"""
        if lang in ['no', 'en']:
            self.current_lang = lang
    
    def t(self, key, **kwargs):
        """Shorthand for get()"""
        return self.get(key, **kwargs)


# Singleton instance
_localization = None

def get_localization(default_lang='no'):
    """Get or create localization instance"""
    global _localization
    if _localization is None:
        _localization = Localization(default_lang)
    return _localization


def detect_language(text):
    """Convenience function to detect language"""
    return get_localization().detect_language(text)


def t(key, lang=None, **kwargs):
    """Translate a key"""
    loc = get_localization()
    if lang:
        old_lang = loc.current_lang
        loc.set_language(lang)
        result = loc.get(key, **kwargs)
        loc.set_language(old_lang)
        return result
    return loc.get(key, **kwargs)
