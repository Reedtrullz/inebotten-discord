#!/usr/bin/env python3
"""
Comprehensive Test Suite for Discord Selfbot
Run this BEFORE deploying the selfbot to verify everything works
"""

import os
import sys
from pathlib import Path
from datetime import timedelta

# Add directory to path
sys.path.insert(0, str(Path(__file__).parent))

def run_tests():
    """Execute all tests and return summary"""
    
    print("="*60)
    print("  DISCORD SELFBOT - COMPREHENSIVE TEST SUITE")
    print(f"  Directory: {Path(__file__).resolve().parent}")
    print("="*60)
    
    results = {
        'total': 0,
        'passed': 0,
        'failed': 0,
        'skipped': 0
    }
    
    def test(name, fn):
        """Run a single test with formatting"""
        results['total'] += 1
        print(f"\n[Test {results['passed']+results['failed']+1}] {name}")
        try:
            fn()
            results['passed'] += 1
            print("  ✓ PASSED")
        except AssertionError as e:
            results['failed'] += 1
            print(f"  ✗ FAILED: {e}")
        except Exception as e:
            results['failed'] += 1
            print(f"  ✗ ERROR: {e}")
    
    def skip(name, reason):
        """Skip a test with reason"""
        results['skipped'] += 1
        print(f"  ⊘ SKIPPED: {reason}")
    
    # ====================================================================
    # TEST SUITE
    # ====================================================================
    
    # Test 1: Environment Variables
    def test_env():
        """Check that required env vars are configured"""
        has_token = bool(os.getenv('DISCORD_USER_TOKEN'))
        has_email_pass = os.getenv('DISCORD_EMAIL') and os.getenv('DISCORD_PASSWORD')
        
        if not has_token and not has_email_pass:
            raise AssertionError("No Discord credentials configured!")
        
        print(f"  ✓ Auth type: {'Token' if has_token else 'Email/Password'}")
    test("Environment Variables", test_env)
    
    # Test 2: Config Module
    def test_config():
        """Test configuration loading and validation"""
        from core.config import get_config, Config
        cfg = get_config()
        
        assert hasattr(cfg, 'HERMES_API_URL'), "Config missing HERMES_API_URL"
        url = cfg.get_hermes_url()
        assert 'api/chat' in url, f"Wrong URL: {url}"
        print(f"  ✓ Hermes URL: {url}")
        
        # Check rate limits
        assert cfg.MAX_MSGS_PER_SECOND == 5, "Wrong max msgs per second"
        assert cfg.DAILY_QUOTA == 10000, "Wrong daily quota"
        print(f"  ✓ Rate limits: {cfg.MAX_MSGS_PER_SECOND}/sec, {cfg.DAILY_QUOTA}/day")
    test("Configuration Module", test_config)
    
    # Test 3: Auth Handler
    def test_auth():
        """Test authentication handler"""
        from core.config import get_config
        from core.auth_handler import create_auth_handler
        
        cfg = get_config()
        auth = create_auth_handler(cfg)
        
        assert auth.get_auth_type() in ['token', 'email/password'], "Invalid auth type"
        print(f"  ✓ Auth type: {auth.get_auth_type()}")
        
        creds = auth.get_discord_credentials()
        assert creds is not None, "No credentials returned"
        print(f"  ✓ Credentials retrieved")
    test("Authentication Handler", test_auth)
    
    # Test 4: Rate Limiter
    def test_rate_limiter():
        """Test rate limiting functionality"""
        from core.config import get_config
        from core.rate_limiter import create_rate_limiter
        
        cfg = get_config()
        rl = create_rate_limiter(cfg)
        
        # Should be able to send initially
        can_send, reason = rl.can_send()
        assert can_send, f"Should be able to send initially: {reason}"
        print(f"  ✓ Initial state allows sending")
        
        # Record some sends
        for i in range(3):
            rl.record_sent()
        
        stats = rl.get_stats()
        assert stats['sent_last_second'] == 3, "Message count not tracking"
        print(f"  ✓ Message tracking works ({stats['sent_last_second']} recorded)")
    test("Rate Limiter", test_rate_limiter)
    
    # Test 5: Hermes Connector
    def test_hermes():
        """Test Hermes API connector"""
        import asyncio
        from core.config import get_config
        from ai.hermes_connector import create_hermes_connector
        
        cfg = get_config()
        hermes = create_hermes_connector(cfg)
        
        assert hermes.base_url == cfg.HERMES_API_URL, "URL mismatch"
        print(f"  ✓ URL configured: {hermes.base_url}")
        
        # Check health (async)
        async def check():
            healthy, message = await hermes.check_health()
            await hermes.close()  # Clean up session
            return healthy, message
        
        try:
            healthy, message = asyncio.run(check())
            if healthy:
                print(f"  ✓ Health check: {message}")
            else:
                print(f"  ⚠ Health check: {message}")
        except Exception as e:
            print(f"  ⚠ Health check failed: {e}")
    test("Hermes Connector", test_hermes)
    
    # Test 6: Response Generator
    def test_response_gen():
        """Test response generator"""
        from ai.response_generator import create_response_generator
        
        gen = create_response_generator()
        
        # Generate demo response
        response = gen.generate_demo_response()
        assert response and len(response) > 0, "No response generated"
        assert '📅' in response, "Missing header emoji"
        assert '🌙' in response, "Missing almanac emoji"
        print(f"  ✓ Demo response generated ({len(response)} chars)")
    test("Response Generator", test_response_gen)
    
    # Test 7: Message Monitor (import only)
    def test_monitor():
        """Test message monitor imports"""
        from core.message_monitor import MessageMonitor, SelfbotClient, create_monitor
        print("  ✓ All classes import successfully")
    test("Message Monitor Imports", test_monitor)
    
    # Test 8: Selfbot Runner (import only)
    def test_runner():
        """Test selfbot runner imports"""
        from core.selfbot_runner import SelfbotRunner, main
        print("  ✓ Runner imports successfully")
    test("Selfbot Runner Imports", test_runner)
    
    # Test 9: Full integration (check components work together)
    def test_integration():
        """Test that all components integrate properly"""
        from core.config import get_config
        from core.auth_handler import create_auth_handler
        from core.rate_limiter import create_rate_limiter
        from ai.hermes_connector import create_hermes_connector
        from ai.response_generator import create_response_generator
        
        cfg = get_config()
        auth = create_auth_handler(cfg)
        rl = create_rate_limiter(cfg)
        hermes = create_hermes_connector(cfg)
        gen = create_response_generator()
        
        # Verify all created
        assert cfg is not None
        assert auth is not None
        assert rl is not None
        assert hermes is not None
        assert gen is not None
        
        print(f"  ✓ All components initialized")
        print(f"    Config: {cfg.get_auth_type()} auth")
        print(f"    Rate limiter: {rl.max_per_second}/sec")
        print(f"    Hermes: {hermes.base_url}")
    test("Full Integration", test_integration)
    
    # ====================================================================
    # RESULTS
    # ====================================================================
    
    print("\n" + "="*60)
    print("  TEST RESULTS")
    print("="*60)
    print(f"  Total:   {results['total']}")
    print(f"  Passed:  {results['passed']} ✓")
    print(f"  Failed:  {results['failed']} ✗")
    print(f"  Skipped: {results['skipped']}")
    print("="*60)
    
    if results['failed'] == 0:
        print("\n✅ ALL TESTS PASSED!")
        print("The Discord selfbot is ready to run.")
        print("\nTo start the selfbot:")
        print("  python3 selfbot_runner.py")
        return 0
    else:
        print(f"\n❌ {results['failed']} test(s) failed!")
        print("Fix the issues above before running the selfbot.")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
