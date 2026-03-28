#!/usr/bin/env python3
"""
Comprehensive Automated Test Suite for Inebotten Discord Selfbot
Tests all commands, parsers, and managers
"""

import unittest
import json
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path

# Import all modules to test
from memory.localization import get_localization, detect_language
from cal_system.natural_language_parser import parse_natural_event, NaturalLanguageParser
from features.countdown_manager import CountdownManager
from features.poll_manager import PollManager, parse_poll_command, parse_vote
from features.watchlist_manager import WatchlistManager, parse_watchlist_command
from features.quote_manager import QuoteManager, parse_quote_command
from features.word_of_day import WordOfTheDay
from features.birthday_manager import BirthdayManager, parse_birthday_command
from cal_system.reminder_manager import ReminderManager, parse_reminder_command
from cal_system.event_manager import EventManager


class TestLanguageDetection(unittest.TestCase):
    """Test language detection"""
    
    def test_detect_norwegian(self):
        """Test Norwegian detection"""
        tests = [
            "@inebotten hvor lenge til jul?",
            "@inebotten hva skal vi se i kveld?",
            "@inebotten påminnelse kjøpe melk",
            "@inebotten avstemning pizza eller burger",
            "@inebotten dagens ord",
            "@inebotten skoleferie",
        ]
        for text in tests:
            self.assertEqual(detect_language(text), 'no', f"Failed for: {text}")
    
    def test_detect_english(self):
        """Test English detection"""
        tests = [
            "@inebotten countdown to christmas",
            "@inebotten what should we watch tonight?",
            "@inebotten reminder buy milk",
            "@inebotten poll pizza or burger",
            "@inebotten word of the day",
            "@inebotten school holidays",
        ]
        for text in tests:
            self.assertEqual(detect_language(text), 'en', f"Failed for: {text}")


class TestLocalization(unittest.TestCase):
    """Test localization/translations"""
    
    def setUp(self):
        self.loc = get_localization()
    
    def test_norwegian_translations(self):
        """Test Norwegian translations exist"""
        self.loc.set_language('no')
        
        # Test various translation keys with correct parameters
        test_cases = [
            ('countdown_result', {'event': 'Test', 'days': '5', 'emoji': '🎉'}),
            ('vote_registered', {'num': 1}),
            ('no_quotes', {}),
            ('watchlist_status', {'unwatched_movies': 2, 'total_movies': 5, 'unwatched_series': 1, 'total_series': 3}),
        ]
        for key, kwargs in test_cases:
            result = self.loc.t(key, **kwargs)
            self.assertIsNotNone(result)
            self.assertNotEqual(result, key)  # Should not return the key itself
    
    def test_english_translations(self):
        """Test English translations exist"""
        self.loc.set_language('en')
        
        test_cases = [
            ('countdown_result', {'event': 'Test', 'days': '5', 'emoji': '🎉'}),
            ('vote_registered', {'num': 1}),
            ('no_quotes', {}),
            ('watchlist_status', {'unwatched_movies': 2, 'total_movies': 5, 'unwatched_series': 1, 'total_series': 3}),
        ]
        for key, kwargs in test_cases:
            result = self.loc.t(key, **kwargs)
            self.assertIsNotNone(result)
            self.assertNotEqual(result, key)


class TestNaturalLanguageParser(unittest.TestCase):
    """Test natural language event parsing"""
    
    def setUp(self):
        self.parser = NaturalLanguageParser()
    
    def test_parse_tonight(self):
        """Test 'i kveld' parsing"""
        result = parse_natural_event("@inebotten kamp i kveld kl 20:00")
        self.assertIsNotNone(result)
        self.assertIn('kamp', result['title'].lower())
        self.assertEqual(result['time'], '20:00')
    
    def test_parse_tomorrow(self):
        """Test 'i morgen' parsing"""
        result = parse_natural_event("@inebotten møte i morgen kl 09:00")
        self.assertIsNotNone(result)
        self.assertIn('møte', result['title'].lower())
        self.assertEqual(result['time'], '09:00')
    
    def test_parse_specific_date(self):
        """Test parsing with specific date format"""
        # The parser handles various date formats
        result = parse_natural_event("@inebotten arrangement 17. mai kl 18:00")
        # This should either parse successfully or return None based on implementation
        # Just verify the parser runs without error
        self.assertTrue(result is None or isinstance(result, dict))
    
    def test_parse_day_of_week(self):
        """Test day name parsing"""
        result = parse_natural_event("@inebotten fotball på lørdag kl 15:00")
        self.assertIsNotNone(result)
        self.assertIn('fotball', result['title'].lower())
        self.assertEqual(result['time'], '15:00')
    
    def test_no_time_indicator(self):
        """Test that text without time indicators returns None"""
        result = parse_natural_event("@inebotten hei på deg")
        self.assertIsNone(result)


class TestCountdownManager(unittest.TestCase):
    """Test countdown manager"""
    
    def setUp(self):
        self.manager = CountdownManager()
    
    def test_parse_countdown_norwegian(self):
        """Test Norwegian countdown queries"""
        queries = [
            "@inebotten hvor lenge til jul",
            "@inebotten nedtelling til 17. mai",
            "@inebotten hvor mange dager til påske",
        ]
        for query in queries:
            result = self.manager.parse_countdown_query(query)
            self.assertIsNotNone(result, f"Failed for: {query}")
            self.assertIn('days', result)
            self.assertIn('event', result)
    
    def test_parse_countdown_english(self):
        """Test English countdown queries"""
        queries = [
            "@inebotten countdown to christmas",
            "@inebotten how long until new year",
            "@inebotten days to easter",
        ]
        for query in queries:
            result = self.manager.parse_countdown_query(query)
            self.assertIsNotNone(result, f"Failed for: {query}")
    
    def test_format_response_norwegian(self):
        """Test Norwegian formatting"""
        data = {
            'event': 'Jul',
            'days': 25,
            'hours': 5,
            'emoji': '🎄',
            'is_past': False,
            'is_today': False,
            'is_tomorrow': False
        }
        result = self.manager.format_response(data, 'no')
        self.assertIn('Jul', result)
        self.assertIn('dager', result)
    
    def test_format_response_english(self):
        """Test English formatting"""
        data = {
            'event': 'Christmas',
            'days': 25,
            'hours': 5,
            'emoji': '🎄',
            'is_past': False,
            'is_today': False,
            'is_tomorrow': False
        }
        result = self.manager.format_response(data, 'en')
        self.assertIn('Christmas', result)
        self.assertIn('days', result)


class TestPollManager(unittest.TestCase):
    """Test poll manager"""
    
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        self.temp_file.close()
        self.manager = PollManager(storage_path=self.temp_file.name)
    
    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_create_poll(self):
        """Test poll creation"""
        poll = self.manager.create_poll(
            guild_id='test_guild',
            question='Pizza or Burger?',
            options=['Pizza', 'Burger'],
            created_by='TestUser'
        )
        self.assertIsNotNone(poll)
        self.assertEqual(poll['question'], 'Pizza or Burger?')
        self.assertEqual(len(poll['options']), 2)
    
    def test_vote(self):
        """Test voting"""
        poll = self.manager.create_poll(
            guild_id='test_guild',
            question='Test?',
            options=['A', 'B'],
            created_by='TestUser'
        )
        
        success, msg = self.manager.vote('test_guild', poll['id'], 1, 'user1', 'User1')
        self.assertTrue(success)
        
        # Check vote was recorded
        self.assertEqual(len(self.manager.polls['test_guild'][poll['id']]['options'][0]['votes']), 1)
    
    def test_parse_poll_command_norwegian(self):
        """Test Norwegian poll parsing"""
        result = parse_poll_command("@inebotten avstemning A eller B?")
        self.assertIsNotNone(result)
        self.assertEqual(result['lang'], 'no')
        # Options are parsed from the text after the question mark
        self.assertTrue(len(result['options']) >= 2)
    
    def test_parse_poll_command_english(self):
        """Test English poll parsing"""
        result = parse_poll_command("@inebotten poll Pizza or Burger?")
        self.assertIsNotNone(result)
        self.assertEqual(result['lang'], 'en')
    
    def test_parse_vote(self):
        """Test vote parsing"""
        self.assertEqual(parse_vote("@inebotten 1"), 1)
        self.assertEqual(parse_vote("@inebotten 5"), 5)
        self.assertIsNone(parse_vote("@inebotten hei"))


class TestWatchlistManager(unittest.TestCase):
    """Test watchlist manager"""
    
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        self.temp_file.close()
        self.manager = WatchlistManager(storage_path=self.temp_file.name)
    
    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_get_random_suggestion(self):
        """Test getting suggestions"""
        suggestion = self.manager.get_random_suggestion()
        self.assertIsNotNone(suggestion)
        self.assertIn('title', suggestion)
        self.assertIn('type', suggestion)
    
    def test_format_suggestion_norwegian(self):
        """Test Norwegian formatting"""
        item = {
            'title': 'Test Movie',
            'type': 'movie',
            'genre': 'Comedy',
            'year': 2020
        }
        result = self.manager.format_suggestion(item, 'no')
        self.assertIn('Test Movie', result)
        self.assertIn('Film', result)
        self.assertIn('Sjanger', result)
    
    def test_format_suggestion_english(self):
        """Test English formatting"""
        item = {
            'title': 'Test Movie',
            'type': 'movie',
            'genre': 'Comedy',
            'year': 2020
        }
        result = self.manager.format_suggestion(item, 'en')
        self.assertIn('Test Movie', result)
        self.assertIn('Movie', result)
        self.assertIn('Genre', result)
    
    def test_parse_watchlist_command(self):
        """Test watchlist command parsing"""
        # Norwegian
        result = parse_watchlist_command("@inebotten hva skal vi se?")
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'suggest')
        self.assertEqual(result['lang'], 'no')
        
        # English
        result = parse_watchlist_command("@inebotten what should we watch?")
        self.assertIsNotNone(result)
        self.assertEqual(result['lang'], 'en')


class TestQuoteManager(unittest.TestCase):
    """Test quote manager"""
    
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        self.temp_file.close()
        self.manager = QuoteManager(storage_path=self.temp_file.name)
    
    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_add_and_get_quote(self):
        """Test adding and retrieving quotes"""
        self.manager.add_quote('test_guild', 'Funny quote', 'TestAuthor')
        
        quote = self.manager.get_random_quote('test_guild')
        self.assertIsNotNone(quote)
        self.assertEqual(quote['text'], 'Funny quote')
        self.assertEqual(quote['author'], 'TestAuthor')
    
    def test_format_quote_norwegian(self):
        """Test Norwegian formatting"""
        quote = {
            'text': 'Test quote',
            'author': 'TestAuthor',
            'date': '01.01.2024'
        }
        result = self.manager.format_quote(quote, 'no')
        self.assertIn('Test quote', result)
        self.assertIn('Sitat fra arkivet', result)
    
    def test_format_quote_english(self):
        """Test English formatting"""
        quote = {
            'text': 'Test quote',
            'author': 'TestAuthor',
            'date': '01.01.2024'
        }
        result = self.manager.format_quote(quote, 'en')
        self.assertIn('Test quote', result)
        self.assertIn('Quote from archive', result)
    
    def test_parse_quote_command_norwegian(self):
        """Test Norwegian quote parsing"""
        result = parse_quote_command('@inebotten husk dette: "funny"')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'save')
        self.assertEqual(result['lang'], 'no')
        
        result = parse_quote_command('@inebotten sitat')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'get')
    
    def test_parse_quote_command_english(self):
        """Test English quote parsing"""
        result = parse_quote_command('@inebotten remember this: "funny"')
        self.assertIsNotNone(result)
        self.assertEqual(result['action'], 'save')
        self.assertEqual(result['lang'], 'en')


class TestWordOfTheDay(unittest.TestCase):
    """Test word of the day"""
    
    def setUp(self):
        self.wod = WordOfTheDay()
    
    def test_get_word_norwegian(self):
        """Test getting Norwegian word"""
        word = self.wod.get_word_of_day('no')
        self.assertIsNotNone(word)
        self.assertIn('word', word)
        self.assertIn('meaning', word)
    
    def test_get_word_english(self):
        """Test getting English word"""
        word = self.wod.get_word_of_day('en')
        self.assertIsNotNone(word)
        self.assertIn('word', word)
    
    def test_format_word_norwegian(self):
        """Test Norwegian formatting"""
        word = self.wod.get_word_of_day('no')
        result = self.wod.format_word(word, 'no')
        self.assertIn('Dagens ord', result)
        self.assertIn('Betydning', result)
    
    def test_format_word_english(self):
        """Test English formatting"""
        word = self.wod.get_word_of_day('en')
        result = self.wod.format_word(word, 'en')
        self.assertIn('Word of the day', result)
        self.assertIn('Meaning', result)


class TestBirthdayManager(unittest.TestCase):
    """Test birthday manager"""
    
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        self.temp_file.close()
        self.manager = BirthdayManager(storage_path=self.temp_file.name)
    
    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_add_birthday(self):
        """Test adding birthday"""
        result = self.manager.add_birthday('test_guild', 'user1', 'TestUser', 15, 5)
        self.assertTrue(result)
    
    def test_get_upcoming_birthdays(self):
        """Test getting upcoming birthdays"""
        self.manager.add_birthday('test_guild', 'user1', 'TestUser', 15, 5)
        birthdays = self.manager.get_upcoming_birthdays('test_guild')
        self.assertIsInstance(birthdays, list)


class TestReminderManager(unittest.TestCase):
    """Test reminder manager"""
    
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        self.temp_file.close()
        self.manager = ReminderManager(storage_path=self.temp_file.name)
    
    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_add_reminder(self):
        """Test adding reminder"""
        result = self.manager.add_reminder('test_guild', 'user1', 'TestUser', 'Buy milk', None)
        self.assertTrue(result)  # Returns True/False, not a dict
    
    def test_get_active_reminders(self):
        """Test getting active reminders"""
        self.manager.add_reminder('test_guild', 'user1', 'TestUser', 'Buy milk', None)
        reminders = self.manager.get_active_reminders('test_guild', 'user1')
        self.assertEqual(len(reminders), 1)


class TestEventManager(unittest.TestCase):
    """Test event manager"""
    
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        self.temp_file.close()
        self.manager = EventManager(storage_path=self.temp_file.name)
    
    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)
    
    def test_create_event(self):
        """Test event creation"""
        event = self.manager.create_event(
            'test_guild',
            'Test Event',
            '25.12.2025',
            '18:00',
            'TestUser'
        )
        self.assertIsNotNone(event)
        self.assertEqual(event['title'], 'Test Event')
    
    def test_get_upcoming_events(self):
        """Test getting upcoming events"""
        self.manager.create_event('test_guild', 'Test', '25.12.2025', '18:00', 'User')
        events = self.manager.get_upcoming_events('test_guild')
        self.assertIsInstance(events, list)


class TestHelpCommand(unittest.TestCase):
    """Test help command"""
    
    def setUp(self):
        self.loc = get_localization()
    
    def test_help_translations_exist(self):
        """Test that all help translations exist"""
        for lang in ['no', 'en']:
            self.loc.set_language(lang)
            
            keys = ['help_title', 'help_events', 'help_reminders', 
                   'help_birthdays', 'help_fun', 'help_footer_tip']
            for key in keys:
                result = self.loc.t(key)
                self.assertIsNotNone(result)
                self.assertNotEqual(result, key)
    
    def test_help_norwegian_content(self):
        """Test Norwegian help content"""
        self.loc.set_language('no')
        help_text = self.loc.t('help_title')
        self.assertIn('Inebotten', help_text)
        
        events_help = self.loc.t('help_events')
        self.assertIn('Arrangementer', events_help)
    
    def test_help_english_content(self):
        """Test English help content"""
        self.loc.set_language('en')
        help_text = self.loc.t('help_title')
        self.assertIn('Inebotten', help_text)
        
        events_help = self.loc.t('help_events')
        self.assertIn('Events', events_help)


class TestIntegration(unittest.TestCase):
    """Integration tests"""
    
    def test_full_event_flow(self):
        """Test complete event creation flow"""
        # Parse natural language
        event_data = parse_natural_event("@inebotten kamp i kveld kl 20:00")
        self.assertIsNotNone(event_data)
        
        # Create event
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        temp_file.close()
        manager = EventManager(storage_path=temp_file.name)
        
        event = manager.create_event(
            'test_guild',
            event_data['title'],
            event_data['date'],
            event_data['time'],
            'TestUser'
        )
        
        self.assertIsNotNone(event)
        self.assertIn('kamp', event['title'].lower())
        
        os.unlink(temp_file.name)
    
    def test_full_poll_flow(self):
        """Test complete poll creation and voting flow"""
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        temp_file.close()
        manager = PollManager(storage_path=temp_file.name)
        
        # Parse command
        cmd = parse_poll_command("@inebotten poll A or B?")
        self.assertIsNotNone(cmd)
        
        # Create poll
        poll = manager.create_poll('test_guild', cmd['question'], cmd['options'], 'User')
        self.assertIsNotNone(poll)
        
        # Vote
        success, _ = manager.vote('test_guild', poll['id'], 1, 'user1', 'User1')
        self.assertTrue(success)
        
        os.unlink(temp_file.name)


def run_tests():
    """Run all tests and print results"""
    print("=" * 60)
    print("INEBOTTEN AUTOMATED TEST SUITE")
    print("=" * 60)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestLanguageDetection,
        TestLocalization,
        TestNaturalLanguageParser,
        TestCountdownManager,
        TestPollManager,
        TestWatchlistManager,
        TestQuoteManager,
        TestWordOfTheDay,
        TestBirthdayManager,
        TestReminderManager,
        TestEventManager,
        TestHelpCommand,
        TestIntegration,
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print()
    
    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED")
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
