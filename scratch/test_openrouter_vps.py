import os
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append('/opt/inebotten-discord')

from ai.openrouter_connector import create_openrouter_connector
from core.config import get_config

async def test_openrouter():
    config = get_config()
    print(f"Provider: {config.AI_PROVIDER}")
    print(f"Model: {config.OPENROUTER_MODEL}")
    
    try:
        connector = create_openrouter_connector(config)
        print("Checking health...")
        success, message = await connector.check_health()
        print(f"Health check: {'PASSED' if success else 'FAILED'}")
        print(f"Message: {message}")
        
        if success:
            print("\nTesting response generation...")
            success, response = await connector.generate_response(
                message_content="Hei, hvordan går det?",
                author_name="Tester",
                channel_type="DM"
            )
            print(f"Response success: {success}")
            print(f"Response: {response}")
            
        await connector.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_openrouter())
