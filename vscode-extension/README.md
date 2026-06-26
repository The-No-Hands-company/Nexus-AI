# Nexus AI VS Code Extension

A VS Code extension that integrates with the Nexus AI assistant to provide AI-powered coding assistance directly within your editor.

## Features
- Chat with Nexus AI assistant from within VS Code
- Generate images using AI models (displays results in preview panel)
- Voice input simulation for hands-free coding (uses text input as fallback)
- Configuration for API endpoint and API key

## Extension Settings
This extension contributes the following settings:

* `nexusAI.apiEndpoint`: The Nexus AI backend API endpoint (default: http://localhost:8000)
* `nexusAI.apiKey`: API key for authenticating with the Nexus AI backend

## Known Issues
- Voice input uses text input as a fallback since direct microphone access requires additional permissions and webview implementation
- Requires Nexus AI backend to be running and accessible

## Release Notes
### 0.0.2
- Implemented actual functionality for chat, image generation, and voice input features
- Added proper error handling and loading indicators
- Image generation results displayed in a preview panel when base64 image data is returned

### 0.0.1
- Initial release - basic skeleton created.

## Requirements
- VS Code 1.70.0 or higher
- Nexus AI backend running and accessible