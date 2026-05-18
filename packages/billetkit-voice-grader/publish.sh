#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "==> Building package..."
python3 -m pip install --upgrade build twine 2>/dev/null || true
python3 -m build

echo ""
echo "==> Publishing to PyPI..."
if [ -z "$PYPI_API_TOKEN" ]; then
    echo "ERROR: PYPI_API_TOKEN not set"
    echo "Set it with: export PYPI_API_TOKEN=pypi-..."
    exit 1
fi

python3 -m twine upload dist/* --username __token__ --password "$PYPI_API_TOKEN"

echo ""
echo "==> Published successfully!"
echo "Install with: pip install billetkit-voice-grader"
