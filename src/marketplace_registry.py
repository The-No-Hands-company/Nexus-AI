"""Custom tool registry and marketplace connectors for Nexus AI.

Allows third parties and users to:
- Register custom tools with validated schemas
- Discover and invoke registered tools
- Publish agent templates to a local marketplace
- Contribute personas to the community library
- Load model provider plugins
"""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Custom tool registry ──────────────────────────────────────────────────────

@dataclass
class ToolRegistration:
    tool_id: str
    name: str
    description: str
    author: str
    schema: dict                   # JSON Schema for arguments
    handler_module: str = ""       # dotted module path to callable
    handler_code:   str = ""       # inline Python (sandbox-only)
    endpoint_url:   str = ""       # remote HTTP endpoint for external tools
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    downloads: int = 0

    def to_dict(self) -> dict:
        return {
            "tool_id":        self.tool_id,
            "name":           self.name,
            "description":    self.description,
            "author":         self.author,
            "schema":         self.schema,
            "tags":           self.tags,
            "version":        self.version,
            "is_active":      self.is_active,
            "created_at":     self.created_at,
            "downloads":      self.downloads,
            "endpoint_url":   self.endpoint_url,
            "has_handler":    bool(self.handler_module or self.handler_code),
        }


_tool_registry: dict[str, ToolRegistration] = {}


def register_tool(name: str, description: str, author: str, schema: dict,
                  handler_module: str = "", endpoint_url: str = "",
                  tags: list[str] | None = None, version: str = "1.0.0") -> ToolRegistration:
    """Register a new custom tool."""
    # Basic schema validation
    if not isinstance(schema, dict):
        raise ValueError("schema must be a JSON object")
    if not name.strip():
        raise ValueError("name is required")

    tool_id = hashlib.sha256(f"{author}:{name}:{version}".encode()).hexdigest()[:16]
    reg = ToolRegistration(
        tool_id=tool_id,
        name=name,
        description=description,
        author=author,
        schema=schema,
        handler_module=handler_module,
        endpoint_url=endpoint_url,
        tags=tags or [],
        version=version,
    )
    _tool_registry[tool_id] = reg
    logger.info("Registered custom tool: %s v%s by %s", name, version, author)
    return reg


def get_tool(tool_id: str) -> ToolRegistration | None:
    return _tool_registry.get(tool_id)


def list_tools(tag: str | None = None, author: str | None = None,
               active_only: bool = True) -> list[dict]:
    items = list(_tool_registry.values())
    if active_only:
        items = [t for t in items if t.is_active]
    if tag:
        items = [t for t in items if tag in t.tags]
    if author:
        items = [t for t in items if t.author == author]
    return [t.to_dict() for t in items]


def deactivate_tool(tool_id: str) -> bool:
    tool = _tool_registry.get(tool_id)
    if not tool:
        return False
    tool.is_active = False
    return True


async def invoke_custom_tool(tool_id: str, args: dict) -> dict:
    """Invoke a registered custom tool (remote endpoint or module handler)."""
    tool = _tool_registry.get(tool_id)
    if not tool:
        return {"ok": False, "error": f"Tool '{tool_id}' not found"}
    if not tool.is_active:
        return {"ok": False, "error": "Tool is deactivated"}

    tool.downloads += 1

    # Remote endpoint invocation
    if tool.endpoint_url:
        try:
            import httpx  # type: ignore
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(tool.endpoint_url, json=args)
                resp.raise_for_status()
                return {"ok": True, "result": resp.json()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # Module handler
    if tool.handler_module:
        try:
            parts  = tool.handler_module.rsplit(".", 1)
            mod    = importlib.import_module(parts[0])
            fn     = getattr(mod, parts[1])
            result = fn(**args) if not _is_async(fn) else await fn(**args)  # type: ignore
            return {"ok": True, "result": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": "Tool has no invocation handler"}


def _is_async(fn: Any) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(fn)


# ── Marketplace connectors ────────────────────────────────────────────────────

@dataclass
class MarketplaceConnector:
    connector_id: str
    name: str
    description: str
    type: str          # tool | data_source | notification | storage | auth
    config_schema: dict
    author: str = ""
    version: str = "1.0.0"
    homepage: str = ""
    icon_url: str = ""
    install_count: int = 0
    is_installed: bool = False
    installed_at: str | None = None
    config: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "connector_id":   self.connector_id,
            "name":           self.name,
            "description":    self.description,
            "type":           self.type,
            "config_schema":  self.config_schema,
            "author":         self.author,
            "version":        self.version,
            "homepage":       self.homepage,
            "install_count":  self.install_count,
            "is_installed":   self.is_installed,
            "installed_at":   self.installed_at,
            "created_at":     self.created_at,
        }


_connectors: dict[str, MarketplaceConnector] = {}

# Seed built-in connectors
_BUILTIN_CONNECTORS = [
    {"id": "slack",        "name": "Slack",           "type": "notification", "desc": "Send messages and receive commands from Slack"},
    {"id": "discord",      "name": "Discord",          "type": "notification", "desc": "Discord bot integration"},
    {"id": "notion",       "name": "Notion",           "type": "storage",      "desc": "Export chats and knowledge to Notion"},
    {"id": "obsidian",     "name": "Obsidian",         "type": "storage",      "desc": "Export chats to Obsidian vault"},
    {"id": "github",       "name": "GitHub",           "type": "data_source",  "desc": "Read repos, issues, PRs and trigger Actions"},
    {"id": "jira",         "name": "Jira",             "type": "tool",         "desc": "Create/update Jira tickets from agent tasks"},
    {"id": "linear",       "name": "Linear",           "type": "tool",         "desc": "Create Linear issues from tasks"},
    {"id": "zapier",       "name": "Zapier",           "type": "tool",         "desc": "Trigger Zapier zaps from agent events"},
    {"id": "google_drive", "name": "Google Drive",     "type": "storage",      "desc": "Read/write documents in Google Drive"},
    {"id": "confluence",   "name": "Confluence",       "type": "storage",      "desc": "Publish agent outputs to Confluence pages"},
]


def _seed_connectors() -> None:
    for c in _BUILTIN_CONNECTORS:
        cid = c["id"]
        _connectors[cid] = MarketplaceConnector(
            connector_id=cid,
            name=c["name"],
            description=c["desc"],
            type=c["type"],
            config_schema={"type": "object", "properties": {}},
            author="nexus-ai",
        )


_seed_connectors()


def list_connectors(connector_type: str | None = None, installed_only: bool = False) -> list[dict]:
    items = list(_connectors.values())
    if connector_type:
        items = [c for c in items if c.type == connector_type]
    if installed_only:
        items = [c for c in items if c.is_installed]
    return [c.to_dict() for c in items]


def get_connector(connector_id: str) -> MarketplaceConnector | None:
    return _connectors.get(connector_id)


def install_connector(connector_id: str, config: dict) -> dict:
    conn = _connectors.get(connector_id)
    if not conn:
        return {"ok": False, "error": "Connector not found"}
    conn.is_installed = True
    conn.installed_at = datetime.now(timezone.utc).isoformat()
    conn.config       = config
    conn.install_count += 1
    logger.info("Installed connector: %s", connector_id)
    return {"ok": True, "connector": conn.to_dict()}


def uninstall_connector(connector_id: str) -> bool:
    conn = _connectors.get(connector_id)
    if not conn:
        return False
    conn.is_installed = False
    conn.installed_at = None
    conn.config       = {}
    return True


# ── Agent templates ───────────────────────────────────────────────────────────

@dataclass
class AgentTemplate:
    template_id: str
    name: str
    description: str
    author: str
    blueprint: dict           # the agent blueprint JSON
    tags: list[str] = field(default_factory=list)
    use_case: str = ""
    downloads: int = 0
    rating: float = 0.0
    review_count: int = 0
    version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "template_id":  self.template_id,
            "name":         self.name,
            "description":  self.description,
            "author":       self.author,
            "tags":         self.tags,
            "use_case":     self.use_case,
            "downloads":    self.downloads,
            "rating":       self.rating,
            "review_count": self.review_count,
            "version":      self.version,
            "created_at":   self.created_at,
        }


_templates: dict[str, AgentTemplate] = {}


def publish_template(name: str, description: str, author: str,
                     blueprint: dict, tags: list[str] | None = None,
                     use_case: str = "") -> AgentTemplate:
    tid = str(uuid.uuid4())[:12]
    tmpl = AgentTemplate(
        template_id=tid, name=name, description=description,
        author=author, blueprint=blueprint, tags=tags or [], use_case=use_case,
    )
    _templates[tid] = tmpl
    logger.info("Published template: %s by %s", name, author)
    return tmpl


def list_templates(tag: str | None = None, use_case: str | None = None) -> list[dict]:
    items = list(_templates.values())
    if tag:
        items = [t for t in items if tag in t.tags]
    if use_case:
        items = [t for t in items if t.use_case == use_case]
    return sorted([t.to_dict() for t in items], key=lambda x: x["downloads"], reverse=True)


def get_template(template_id: str) -> AgentTemplate | None:
    return _templates.get(template_id)


def deploy_template(template_id: str) -> dict:
    """Increment download counter and return blueprint for deployment."""
    tmpl = _templates.get(template_id)
    if not tmpl:
        return {"ok": False, "error": "Template not found"}
    tmpl.downloads += 1
    return {"ok": True, "blueprint": tmpl.blueprint, "template": tmpl.to_dict()}


# ── Community personas ────────────────────────────────────────────────────────

@dataclass
class CommunityPersona:
    persona_id: str
    name: str
    description: str
    author: str
    system_prompt: str
    temperature: float = 0.7
    tags: list[str] = field(default_factory=list)
    downloads: int = 0
    rating: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "persona_id":    self.persona_id,
            "name":          self.name,
            "description":   self.description,
            "author":        self.author,
            "tags":          self.tags,
            "temperature":   self.temperature,
            "downloads":     self.downloads,
            "rating":        self.rating,
            "created_at":    self.created_at,
        }


_community_personas: dict[str, CommunityPersona] = {}


def publish_persona(name: str, description: str, author: str,
                    system_prompt: str, temperature: float = 0.7,
                    tags: list[str] | None = None) -> CommunityPersona:
    pid = str(uuid.uuid4())[:12]
    persona = CommunityPersona(
        persona_id=pid, name=name, description=description,
        author=author, system_prompt=system_prompt,
        temperature=temperature, tags=tags or [],
    )
    _community_personas[pid] = persona
    return persona


def list_community_personas(tag: str | None = None) -> list[dict]:
    items = list(_community_personas.values())
    if tag:
        items = [p for p in items if tag in p.tags]
    return sorted([p.to_dict() for p in items], key=lambda x: x["downloads"], reverse=True)


def get_community_persona(persona_id: str) -> CommunityPersona | None:
    return _community_personas.get(persona_id)


# ── Model provider plugins ────────────────────────────────────────────────────

@dataclass
class ProviderPlugin:
    plugin_id: str
    name: str
    description: str
    base_url: str
    api_key_env: str
    models: list[str]
    supports_streaming: bool = True
    supports_vision:    bool = False
    is_openai_compat:   bool = True
    author: str = ""
    version: str = "1.0.0"
    is_active: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "plugin_id":           self.plugin_id,
            "name":                self.name,
            "description":         self.description,
            "base_url":            self.base_url,
            "api_key_env":         self.api_key_env,
            "models":              self.models,
            "supports_streaming":  self.supports_streaming,
            "supports_vision":     self.supports_vision,
            "is_openai_compat":    self.is_openai_compat,
            "author":              self.author,
            "version":             self.version,
            "is_active":           self.is_active,
            "created_at":          self.created_at,
        }


_provider_plugins: dict[str, ProviderPlugin] = {}


def register_provider_plugin(plugin_id: str, name: str, description: str,
                              base_url: str, api_key_env: str,
                              models: list[str], **kwargs) -> ProviderPlugin:
    plugin = ProviderPlugin(
        plugin_id=plugin_id, name=name, description=description,
        base_url=base_url, api_key_env=api_key_env, models=models, **kwargs,
    )
    _provider_plugins[plugin_id] = plugin
    logger.info("Registered provider plugin: %s", name)
    return plugin


def list_provider_plugins(active_only: bool = False) -> list[dict]:
    items = list(_provider_plugins.values())
    if active_only:
        items = [p for p in items if p.is_active]
    return [p.to_dict() for p in items]


def activate_provider_plugin(plugin_id: str) -> bool:
    plugin = _provider_plugins.get(plugin_id)
    if not plugin:
        return False
    plugin.is_active = True
    return True
