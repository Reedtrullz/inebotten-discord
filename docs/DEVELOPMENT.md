# Inebotten Development Guide

## Adding a New Feature

### Step 1: Create Feature Manager

Create `feature_manager.py`:

```python
#!/usr/bin/env python3
"""
Feature Manager - [Description of your feature]
"""

import json
from pathlib import Path
from datetime import datetime


class FeatureManager:
    """
    Manages [feature] functionality
    """
    
    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / '.hermes' / 'discord' / 'feature_data.json'
        
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_data()
    
    def _load_data(self):
        """Load data from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_data(self):
        """Save data to storage"""
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def do_something(self, guild_id, user_id, param):
        """
        Main feature logic
        
        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID
            param: Some parameter
        
        Returns:
            (success: bool, result: str)
        """
        guild_key = str(guild_id)
        
        if guild_key not in self.data:
            self.data[guild_key] = []
        
        # Your logic here
        
        self._save_data()
        return True, "Success message"
    
    def format_output(self, guild_id):
        """Format data for display"""
        guild_key = str(guild_id)
        
        if guild_key not in self.data or not self.data[guild_key]:
            return "Ingen data funnet."
        
        lines = ["📋 **Feature Header:**"]
        for i, item in enumerate(self.data[guild_key][:10], 1):
            lines.append(f"{i}. {item}")
        
        return "\n".join(lines)


def parse_feature_command(content: str):
    """
    Parse feature command from message
    
    Args:
        content: Message content (without bot mention)
    
    Returns:
        (action: str, params: dict) or None if not a match
    """
    content_lower = content.lower().strip()
    
    # Match patterns like "feature add ...", "feature list", etc.
    if content_lower.startswith('feature '):
        parts = content_lower.split(maxsplit=2)
        
        if len(parts) < 2:
            return None
        
        action = parts[1]  # "add", "list", "remove", etc.
        rest = parts[2] if len(parts) > 2 else ""
        
        return action, {"content": rest}
    
    return None


# Singleton instance
_feature_manager = None

def get_feature_manager():
    """Get or create singleton FeatureManager instance"""
    global _feature_manager
    if _feature_manager is None:
        _feature_manager = FeatureManager()
    return _feature_manager
```

### Step 2: Add to Message Monitor

In `message_monitor.py`:

**1. Add import (around line 50):**

```python
from feature_manager import FeatureManager, parse_feature_command
```

**2. Initialize in `__init__` (around line 70):**

```python
self.feature = FeatureManager()
self.parse_feature_command = parse_feature_command
```

**3. Add command matcher in `process_message()`:**

Find the section with other command matchers (around line 250) and add:

```python
# Check for feature command
parsed = self.parse_feature_command(content)
if parsed:
    print(f"[MONITOR] Matched: feature command")
    await self._handle_feature_command(message, parsed)
    return
```

**4. Add handler method:**

Add a new method to the class:

```python
async def _handle_feature_command(self, message, parsed):
    """
    Handle feature commands
    
    Args:
        message: Discord message object
        parsed: (action, params) tuple from parser
    """
    try:
        action, params = parsed
        guild_id = message.guild.id if message.guild else message.channel.id
        
        if action == 'add':
            success, result = self.feature.do_something(
                guild_id, 
                message.author.id,
                params['content']
            )
            
            if success:
                await message.reply(f"✅ {result}", mention_author=False)
            else:
                await message.reply(f"❌ {result}", mention_author=False)
        
        elif action == 'list':
            output = self.feature.format_output(guild_id)
            await message.reply(output, mention_author=False)
        
        else:
            await message.reply(
                "❌ Ukjent kommando. Bruk: `@inebotten feature [add/list/remove]`",
                mention_author=False
            )
    
    except Exception as e:
        print(f"[MONITOR] Feature command error: {e}")
        await message.reply(
            "❌ Noe gikk galt. Prøv igjen senere.",
            mention_author=False
        )
```

### Step 3: Update Documentation

Add to `DOCUMENTATION.md` in the features table:

```markdown
| **Your Feature** | `feature_manager.py` | `@inebotten feature [action]` |
```

Add usage examples to `QUICK_REFERENCE.md`:

```markdown
| Your Feature | `@inebotten feature add [data]` |
```

### Step 4: Test

```bash
# Syntax check
python3 -m py_compile feature_manager.py
python3 -m py_compile message_monitor.py

# Run tests
python3 -c "from feature_manager import FeatureManager; fm = FeatureManager('/tmp/test.json'); print('OK')"
```

## Code Style Guidelines

### 1. Naming

- **Classes:** `PascalCase` (e.g., `CalendarManager`)
- **Functions:** `snake_case` (e.g., `parse_event`)
- **Constants:** `UPPER_CASE` (e.g., `MAX_ITEMS`)
- **Private:** `_leading_underscore` (e.g., `_load_data`)

### 2. Documentation

```python
def method_name(self, param1, param2):
    """
    Brief description of what this does
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value
    
    Example:
        >>> method_name("test", 123)
        "result"
    """
```

### 3. Error Handling

```python
try:
    result = risky_operation()
except SpecificError as e:
    print(f"[FEATURE] Specific error: {e}")
    return False, "User-friendly error message"
except Exception as e:
    print(f"[FEATURE] Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    return False, "Noe gikk galt"
```

### 4. Norwegian Text

Bot speaks Norwegian to users, but code is in English:

```python
# Good
error_message = "Fant ikke noe med det nummeret."  # User sees Norwegian

# Bad
error_message = "Item not found with that number."  # Mixing languages
```

## Testing

### Unit Test Template

```python
#!/usr/bin/env python3
"""Tests for feature_manager.py"""

import sys
import os
import tempfile

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_manager import FeatureManager, parse_feature_command


def test_parse_feature_command():
    """Test command parsing"""
    # Should match
    result = parse_feature_command("feature add test data")
    assert result is not None
    assert result[0] == "add"
    assert result[1]["content"] == "test data"
    
    # Should not match
    result = parse_feature_command("something else")
    assert result is None
    
    print("✓ parse_feature_command tests passed")


def test_feature_manager():
    """Test feature manager operations"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name
    
    try:
        fm = FeatureManager(temp_path)
        
        # Test add
        success, result = fm.do_something("guild1", "user1", "test")
        assert success is True
        
        # Test format
        output = fm.format_output("guild1")
        assert "test" in output
        
        print("✓ FeatureManager tests passed")
    
    finally:
        os.remove(temp_path)


if __name__ == "__main__":
    test_parse_feature_command()
    test_feature_manager()
    print("\nAll tests passed!")
```

## Common Patterns

### Singleton Pattern

```python
_manager = None

def get_manager():
    global _manager
    if _manager is None:
        _manager = Manager()
    return _manager
```

### Storage Pattern

```python
def _load(self):
    if self.path.exists():
        with open(self.path, 'r') as f:
            return json.load(f)
    return {}

def _save(self):
    with open(self.path, 'w') as f:
        json.dump(self.data, f, indent=2)
```

### Command Handler Pattern

```python
async def _handle_command(self, message):
    try:
        guild_id = message.guild.id if message.guild else message.channel.id
        content = message.content
        
        # Parse command
        parsed = parse_command(content)
        if not parsed:
            return
        
        # Execute
        success, result = self.manager.action(guild_id, parsed)
        
        # Respond
        if success:
            await message.reply(f"✅ {result}")
        else:
            await message.reply(f"❌ {result}")
    
    except Exception as e:
        print(f"[ERROR] {e}")
        await message.reply("❌ Feil")
```

## Debugging Tips

### 1. Enable Debug Logging

Add to your feature:

```python
print(f"[FEATURE] Debug: variable={value}")
```

### 2. Test in Isolation

```python
# Test just your feature
python3 -c "
from feature_manager import FeatureManager
fm = FeatureManager('/tmp/test.json')
print(fm.do_something('g1', 'u1', 'test'))
"
```

### 3. Check Storage

```bash
# View stored data
cat ~/.hermes/discord/feature_data.json | python3 -m json.tool
```

### 4. Trace Message Flow

Watch the console output:
```
[MONITOR] Mention detected...
[MONITOR] Matched: feature command
[MONITOR] Feature command error: ...
```

## Git Workflow

```bash
# Before making changes
git status
git diff

# Make changes to feature_manager.py

# Test
python3 -m py_compile feature_manager.py
python3 test_feature.py

# Commit
git add feature_manager.py message_monitor.py
git commit -m "Add feature: description"
```

## Useful Commands

```bash
# Find all TODOs
grep -r "TODO" *.py

# Check file sizes
ls -lh *.py

# Count lines of code
wc -l *.py

# Find imports
grep "^import\|^from" message_monitor.py

# Test all syntax
for f in *.py; do python3 -m py_compile "$f" && echo "✓ $f"; done
```
