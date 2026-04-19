#!/bin/bash

# Release script for Inebotten Discord Bot
# Usage: ./create-release.sh [version]
# Example: ./create-release.sh v2.0.0

set -e

VERSION=${1:-"v2.0.0"}

echo "=========================================="
echo "Creating release: $VERSION"
echo "=========================================="
echo ""

# Check if git is clean
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Warning: You have uncommitted changes"
    echo "   Please commit or stash them before creating a release"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if tag already exists
if git rev-parse "$VERSION" >/dev/null 2>&1; then
    echo "⚠️  Warning: Tag $VERSION already exists"
    read -p "Delete and recreate? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git tag -d "$VERSION"
        git push origin ":refs/tags/$VERSION" || true
    else
        exit 1
    fi
fi

# Get current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "Current branch: $BRANCH"
echo ""

# Show recent commits
echo "Recent commits:"
git log --oneline -5
echo ""

# Confirm
read -p "Create release $VERSION on branch $BRANCH? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Create and push tag
echo ""
echo "Creating tag..."
git tag -a "$VERSION" -m "Release $VERSION"

echo "Pushing tag to GitHub..."
git push origin "$VERSION"

echo ""
echo "=========================================="
echo "✅ Release $VERSION created!"
echo "=========================================="
echo ""
echo "GitHub Actions will now:"
echo "  1. Build macOS app"
echo "  2. Build Windows app"
echo "  3. Create GitHub release"
echo "  4. Upload executables"
echo ""
echo "Monitor progress at:"
echo "  https://github.com/Reedtrullz/inebotten-discord/actions"
echo ""
echo "Release will be available at:"
echo "  https://github.com/Reedtrullz/inebotten-discord/releases/tag/$VERSION"
echo ""
