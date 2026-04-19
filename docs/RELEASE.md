# Creating Releases

This guide explains how to create releases with pre-built executables for macOS and Windows.

## Automated Builds

Inebotten uses GitHub Actions to automatically build desktop apps when you create a release tag.

### How It Works

1. You create a git tag (e.g., `v2.0.0`)
2. GitHub Actions triggers automatically
3. Builds macOS app on macOS runner
4. Builds Windows app on Windows runner
5. Creates GitHub release
6. Uploads executables to the release

### Creating a Release

#### Option 1: Using the Release Script (Recommended)

**macOS/Linux:**
```bash
./create-release.sh v2.0.0
```

**Windows:**
```cmd
create-release.bat v2.0.0
```

The script will:
- Check for uncommitted changes
- Show recent commits
- Ask for confirmation
- Create and push the tag
- Show the GitHub Actions URL

#### Option 2: Manual Git Commands

```bash
# Create and push a tag
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin v2.0.0
```

#### Option 3: Using GitHub UI

1. Go to GitHub → Releases
2. Click "Create a new release"
3. Enter tag version (e.g., `v2.0.0`)
4. Click "Publish release"

### Monitoring the Build

After creating a tag, monitor the build at:
```
https://github.com/Reedtrullz/inebotten-discord/actions
```

The workflow will:
1. Build macOS app (~5-10 minutes)
2. Build Windows app (~5-10 minutes)
3. Create release and upload files (~1 minute)

Total time: ~15-20 minutes

### Downloading the Release

Once the build completes, download from:
```
https://github.com/Reedtrullz/inebotten-discord/releases/tag/v2.0.0
```

Files available:
- `Inebotten-macos.zip` - macOS app
- `Inebotten.exe` - Windows executable

## Versioning

Use semantic versioning: `vMAJOR.MINOR.PATCH`

- **MAJOR** - Breaking changes
- **MINOR** - New features
- **PATCH** - Bug fixes

Examples:
- `v2.0.0` - Major release
- `v2.1.0` - New features
- `v2.1.1` - Bug fix

## Pre-releases

For beta or pre-release versions:

```bash
git tag -a v2.0.0-beta.1 -m "Beta release v2.0.0-beta.1"
git push origin v2.0.0-beta.1
```

Or modify the workflow to mark as pre-release:
```yaml
prerelease: true
```

## Manual Build (For Testing)

If you want to test builds locally before releasing:

### macOS
```bash
cd mac_app
./build.sh
```

### Windows
```bash
cd windows_app
python build.py
```

## Troubleshooting

### Build Fails

1. Check the Actions tab for error logs
2. Common issues:
   - Missing dependencies in `requirements.txt`
   - Build script errors
   - Timeout on runners

### Tag Already Exists

```bash
# Delete local tag
git tag -d v2.0.0

# Delete remote tag
git push origin :refs/tags/v2.0.0

# Recreate
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin v2.0.0
```

### Release Not Created

Check that:
- GitHub Actions has permission to create releases
- The workflow completed successfully
- No errors in the build logs

## Workflow Configuration

The workflow is defined in `.github/workflows/build-desktop-apps.yml`

Key settings:
- Triggers on tag push (`v*`)
- Runs on macOS and Windows runners
- Uses Python 3.11
- Builds with PyInstaller
- Uploads artifacts to release

To modify:
1. Edit `.github/workflows/build-desktop-apps.yml`
2. Commit and push changes
3. Test with a new tag

## Best Practices

1. **Test locally first** - Build and test executables locally
2. **Update CHANGELOG** - Document changes before releasing
3. **Use semantic versioning** - Follow versioning conventions
4. **Review commits** - Ensure all changes are committed
5. **Monitor build** - Watch the Actions tab for progress
6. **Test release** - Download and test the executables

## Next Steps

After creating a release:

1. **Announce** - Share the release with users
2. **Update docs** - Update version numbers in documentation
3. **Monitor issues** - Watch for bug reports
4. **Plan next release** - Start working on the next version

## Support

If you encounter issues:
- Check the [GitHub Actions documentation](https://docs.github.com/en/actions)
- Review the workflow logs
- Open an issue on GitHub

---

**Need help?** Check the main [README.md](README.md) or open an issue.
