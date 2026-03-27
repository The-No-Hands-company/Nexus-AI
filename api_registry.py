import json
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="API Registry", version="1.0.0")

# In-memory storage for API registrations
registered_apis: Dict[str, Dict[str, Any]] = {}

@app.post("/register")
async def register_api(api_name: str, api_url: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Register a new API endpoint.
    
    Args:
        api_name: Unique name for the API
        api_url: URL endpoint of the API
        metadata: Optional additional metadata (description, version, etc.)
    
    Returns:
        Confirmation message with registered API details
    """
    if api_name in registered_apis:
        raise HTTPException(status_code=400, detail=f"API '{api_name}' already registered")
    
    registered_apis[api_name] = {
        "api_url": api_url,
        "metadata": metadata or {},
        "registered_at": "now",
        "status": "active"
    }
    
    return {
        "message": f"API '{api_name}' registered successfully",
        "api": registered_apis[api_name]
    }

@app.get("/registry")
async def get_registry():
    """
    Retrieve the entire API registry.
    
    Returns:
        JSON response with all registered APIs
    """
    return JSONResponse(content=registered_apis)

@app.get("/registry/{api_name}")
async def get_api(api_name: str):
    """
    Retrieve details for a specific registered API.
    
    Args:
        api_name: Name of the API to retrieve
    
    Returns:
        JSON response with API details
    """
    if api_name not in registered_apis:
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not found")
    
    return JSONResponse(content={api_name: registered_apis[api_name]})

@app.delete("/registry/{api_name}")
async def deregister_api(api_name: str):
    """
    Remove an API from the registry.
    
    Args:
        api_name: Name of the API to remove
    
    Returns:
        Confirmation message
    """
    if api_name not in registered_apis:
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not found")
    
    del registered_apis[api_name]
    return {"message": f"API '{api_name}' deregistered successfully"}

@app.put("/registry/{api_name}/status")
async def update_api_status(api_name: str, status: str):
    """
    Update the status of a registered API.
    
    Args:
        api_name: Name of the API to update
        status: New status (active, inactive, deprecated, etc.)
    
    Returns:
        Confirmation message with updated status
    """
    if api_name not in registered_apis:
        raise HTTPException(status_code=404, detail=f"API '{api_name}' not found")
    
    registered_apis[api_name]["status"] = status
    return {
        "message": f"API '{api_name}' status updated to '{status}'",
        "api": registered_apis[api_name]
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)