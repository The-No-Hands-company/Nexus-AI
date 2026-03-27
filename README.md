# API Registry

A simple API registry service to manage and track API endpoints.

## Features

- Register new APIs with metadata
- Retrieve all registered APIs
- Get details for a specific API
- Update API status
- Deregister APIs

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Start the server

```bash
python api_registry.py
```

The server will start on `http://localhost:8000`.

### API Endpoints

- **POST /register** - Register a new API
  - Parameters: `api_name`, `api_url`, `metadata` (optional)
  
- **GET /registry** - Get all registered APIs
  
- **GET /registry/{api_name}** - Get details for a specific API
  
- **PUT /registry/{api_name}/status** - Update API status
  - Parameters: `status`
  
- **DELETE /registry/{api_name}** - Deregister an API

### Example Usage

```bash
# Register an API
curl -X POST "http://localhost:8000/register" \
  -H "Content-Type: application/json" \
  -d '{"api_name": "weather_api", "api_url": "https://api.weather.com/v1", "metadata": {"description": "Weather data API", "version": "1.0"}}'

# Get all APIs
curl "http://localhost:8000/registry"

# Get specific API
curl "http://localhost:8000/registry/weather_api"

# Update status
curl -X PUT "http://localhost:8000/registry/weather_api/status" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}'

# Deregister
curl -X DELETE "http://localhost:8000/registry/weather_api"
```

## Running Tests

```bash
# Install test dependencies
pip install pytest httpx

# Run tests
pytest tests/
```