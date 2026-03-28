# Contributing to Inebotten

Thank you for considering contributing to this project! This document provides guidelines for contributing.

## Code of Conduct

Be respectful, constructive, and helpful. We're all here to learn and improve the project.

## How to Contribute

### Reporting Bugs

1. Check if the issue already exists
2. Open a new issue using the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md)
3. Include:
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Python version)
   - Relevant logs

### Suggesting Features

1. Open an issue using the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md)
2. Describe the use case clearly
3. Provide example interactions if applicable

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Test locally
5. Commit with clear messages
6. Push to your fork
7. Open a Pull Request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/inebotten-discord.git
cd inebotten-discord

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your Discord token

# Run tests
python3 tests/test_selfbot.py
```

## Code Style

- Follow PEP 8
- Use descriptive variable names
- Add docstrings for functions
- Keep functions focused and small
- Comment complex logic

## Adding New Features

When adding a new feature:

1. **Follow the pattern** - Look at existing features in `features/`
2. **Add to message_monitor.py** - Route the command
3. **Update documentation** - Add to README and relevant docs
4. **Add tests** - If applicable
5. **Update QUICK_REFERENCE.md** - Add the new command

Example feature structure:

```python
# features/my_feature.py

class MyFeature:
    def __init__(self):
        pass
    
    async def handle(self, query: str) -> str:
        """Handle the feature command"""
        # Implementation
        return response
```

## Testing

Before submitting a PR:

```bash
# Syntax check
python3 -m py_compile *.py

# Run tests
python3 tests/test_selfbot.py

# Check imports work
python3 -c "from features import weather_api; print('OK')"
```

## Commit Message Format

Use clear, descriptive commit messages:

```
Add aurora forecast feature

- Fetches aurora data from NOAA
- Supports location-based queries
- Added to feature router
```

## Security

**NEVER** commit:
- Discord tokens
- Passwords
- User data from `data/` folder
- Google client secrets

The CI will reject PRs containing potential secrets.

## Questions?

Open a [Discussion](https://github.com/Reedtrullz/inebotten-discord/discussions) for questions.

## Attribution

Contributors will be acknowledged in the README.
