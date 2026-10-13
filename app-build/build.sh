#!/bin/zsh
# Build, sign and self-test dist/Meikipop.app (steps from BUILD.txt).
set -e
cd "$(dirname "$0")"
PY=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
[ -f ../mining-settings.json ] || cp /Applications/Meikipop.app/Contents/Resources/mining-settings.json ..
xcrun swiftc -O -swift-version 5 -target arm64-apple-macosx13.0 ../native/GameAudio.swift -o ../native/GameAudio
$PY prepare.py >/dev/null
PYTHONPATH=.. $PY -m PyInstaller --noconfirm Meikipop.spec > build/meikipop-build.log 2>&1
xattr -rd com.apple.FinderInfo dist/Meikipop.app 2>/dev/null || true
xattr -rd com.apple.ResourceFork dist/Meikipop.app 2>/dev/null || true
# A stable identity keeps macOS privacy permissions (Screen Recording, Accessibility)
# across rebuilds. Ad hoc signatures change with every build, so macOS treats each
# build as a new app and old permissions silently stop matching.
if security find-identity -p codesigning 2>/dev/null | grep -q "Keiko Dev"; then
    codesign --force --deep --sign "Keiko Dev" dist/Meikipop.app
else
    echo "  'Keiko Dev' not found: ad hoc signing; permissions must be granted again after each build"
    codesign --force --deep --sign - dist/Meikipop.app
fi
codesign --verify --deep --strict dist/Meikipop.app
dist/Meikipop.app/Contents/MacOS/Meikipop --self-test "${TMPDIR:-/tmp}/meikipop-self-test.json"
grep -q '"success": true' "${TMPDIR:-/tmp}/meikipop-self-test.json" && echo "✓ Built and self-tested: $(pwd)/dist/Meikipop.app"
