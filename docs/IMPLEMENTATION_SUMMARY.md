# Native Image Generation Backend Implementation

## Overview
Added Stable Diffusion diffusers backend to the image generation system, allowing users to generate images locally using the diffusers library when preferred over external APIs.

## Changes Made

### 1. Modified `src/generation.py`:
- Added "diffusers" to `IMAGE_BACKENDS` list
- Implemented `_diffusers_image()` function that:
  - Uses StableDiffusionPipeline from the diffusers library
  - Automatically detects and uses CUDA if available
  - Uses runwayml/stable-diffusion-v1-5 as the default model
  - Disables the safety checker for simplicity
  - Handles errors gracefully by returning None
- Updated `generate_image_local()` to:
  - Include "diffusers" in the auto-backend fallback list
  - Added elif clause to call `_diffusers_image()` when backend="diffusers"

### 2. Modified `src/agent.py`:
- Updated `tool_image_gen()` function to:
  - Accept a new `backend` parameter (defaults to "pollinations" for backward compatibility)
  - Import and use `generate_image_local()` from generation.py
  - Return generated images as base64-encoded data URLs instead of external URLs
  - Handle generation failures gracefully with error messages
- Updated the image_gen action handler in the agent processing loop to:
  - Pass the backend parameter from action data (defaults to "pollinations")

## Features
- **Backward Compatible**: Existing code using tool_image_gen() continues to work unchanged
- **Flexible Backend Selection**: Users can specify backend="diffusers" to use local Stable Diffusion
- **Automatic GPU Usage**: Uses CUDA when available for faster generation
- **Fallback Behavior**: If diffusers dependencies are missing, falls back gracefully
- **Consistent Interface**: Returns images in the same format as other backends (base64 data URLs)

## Usage Examples
```python
# Use diffusers backend (new functionality)
result = tool_image_gen("a beautiful sunset", width=512, height=512, backend="diffusers")

# Use existing pollinations backend (default, unchanged)
result = tool_image_gen("a beautiful sunset", width=512, height=512)

# In action format:
{"action": "image_gen", "prompt": "a beautiful sunset", "width": 512, "height": 512, "backend": "diffusers"}
```

## Dependencies
The diffusers backend requires:
- torch
- diffusers
- transformers (safety checker components, though disabled)

These are optional dependencies - if not installed, the backend will fail gracefully and users can fall back to other backends like pollinations.

## Testing
Verified that:
1. All existing functionality remains unchanged (backward compatibility)
2. New diffusers backend is properly registered in IMAGE_BACKENDS
3. tool_image_gen function accepts and processes the backend parameter correctly
4. generate_image_local function correctly routes to the diffusers backend
5. Diffusers backend successfully generates images when dependencies are available
6. Error handling works appropriately when dependencies are missing