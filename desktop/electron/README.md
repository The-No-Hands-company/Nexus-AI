# Nexus AI Desktop Application

## Overview

Nexus AI Desktop is a cross-platform desktop application built with Electron, providing full access to the Nexus AI assistant through a native desktop interface.

## Features

- Native desktop window management
- System tray integration
- Native application menus
- Power management (prevents screen sleep when plugged in)
- Secure IPC communication for native APIs
- File dialog support

## Building from Source

### Prerequisites

- Node.js 20+
- npm

### Development Setup

```bash
# Install dependencies
npm install

# Start in development mode
npm start

# Build for distribution
npm run dist:linux
```

### Available Build Targets

| Platform | Target | Command |
|----------|--------|---------|
| Linux (universal) | AppImage | `npm run dist:linux` |
| Linux (portable) | tar.gz | Included in `dist:linux` |
| macOS | dmg, zip | `npm run dist:mac` |
| Windows | nsis, zip | `npm run dist:win` |

## Installation

### Fedora / RHEL / CentOS Stream

1. Download the AppImage from the releases page
2. Make it executable:
   ```bash
   chmod +x "Nexus AI-0.1.0-linux-x86_64.AppImage"
   ```
3. Run it:
   ```bash
   ./Nexus AI-0.1.0-linux-x86_64.AppImage
   ```

Alternative: Extract the tar.gz and run the `nexus-ai-desktop` executable.

### Other Linux Distributions

The AppImage should work on most modern Linux distributions without additional dependencies.

### macOS

Download the `.dmg` file, open it, and drag the Nexus AI app to your Applications folder.

### Windows

Run the installer `.exe` and follow the prompts.

## Building Locally

```bash
# Clone the repository
git cloneuí clone https://github.com/your-repo/nexus-ai.git

# Navigate to the desktop app directory
cd nexus-ai/desktop/electron

# Install dependencies
npm install

# Build for current platform
npm run dist

# Or build for a specific platform
npm run dist:linux
npm run dist:mac
npm run dist:win
```

## Development

### Run in development mode

```bash
npm start
```

This starts the Electron app with hot reloading enabled.

### Project Structure

```
desktop/electron/
├── main.js          # Main Electron process (entry point)
├── preload.js       # Preload script for secure IPC
├── package.json     # Project configuration and dependencies
├── start.sh         # Helper script to run the AppImage
└── dist/            # Production builds
    └── Nexus AI-0.1.0-linux-x86_64.AppImage
```

## Security

- **Context Isolation**: Renderer process is isolated from Node.js APIs
- **Sandbox**: Chromium sandbox is enabled
- **Secure IPC**: Only whitelisted APIs are exposed to the renderer via preload script
- **No Node Integration**: Node.js integration is disabled in the renderer

## Troubleshooting

### AppImage won't run

Make sure the AppImage is executable:
```bash
chmod +x "Nexus AI-0.1.0-linux-x86_64.AppImage"
```

If you're on Fedora 43+, you might need to install FUSE:
```bash
sudo dnf install fuse
```

### Development mode fails

If you see `Cannot find module 'electron-squirrel-startup'`:
- This dependency has been removed from the code
- Make sure you're using the latest version of `main.js`
- Run `npm install` again if needed

### Build fails with missing dependencies

For RPM builds, you need `rpmbuild` installed:
```bash
sudo dnf install rpm-build
```

For DEB builds, you need `dpkg-deb`:
```bash
sudo apt-get install dpkg-dev
```

## Platform-Specific Notes

### Fedora

- Recommended build target: `AppImage` or `tar.gz`
- RPM builds require `rpmbuild` (see above)
- AppImages are fully self-contained and portable

### Ubuntu/Debian

- Recommended build target: `AppImage` or `deb`
- DEB builds require `dpkg-deb` (see above)

### macOS

- Build target: `dmg`, `zip`
- Requires Xcode Command Line Tools
- Code signing recommended for distribution

### Windows

- Build target: `nsis`, `zip`
- Requires VS Build Tools or Visual Studio
- Code signing required for distribution

## Configuration

The application can be configured via environment variables:

- `NEXUS_AI_URL`: URL of the Nexus AI backend (default: `http://127.0.0.1:8000`)
- `NODE_ENV`: Set to `development` for development mode

## License

MIT