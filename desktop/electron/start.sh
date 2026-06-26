#!/bin/bash
# Nexus AI Desktop - Start Script
# This script makes the AppImage executable and runs it

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPIMAGE="$SCRIPT_DIR/dist/Nexus AI-0.1.0-linux-x86_64.AppImage"

# Check if AppImage exists
if [ ! -f "$APPIMAGE" ]; then
    echo "Error: AppImage not found at $APPIMAGE"
    echo "Please run 'npm run dist:linux' first to build the AppImage"
    exit 1
fi

# Make sure it's executable
chmod +x "$APPIMAGE"

# Run the AppImage
echo "Starting Nexus AI Desktop..."
exec "$APPIMAGE" "$@"