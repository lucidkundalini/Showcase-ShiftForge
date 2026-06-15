from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

from core.env_bootstrap import bootstrap_env


AI_CODER_DIR = Path(__file__).resolve().parents[1]
_ENV_CALL_RE = re.compile(r"os\.(?:getenv|environ\.get)\(\s*[\"']([A-Z0-9_]+)[\"']")


def build_mcp_provider_introspection(user_id: str = "") -> dict[str, Any]:
    """Return safe provider and MCP metadata without making network calls."""
    bootstrap_env()
    return {
        "mode": "read_only",
        "providers": _provider_introspection(user_id=user_id),
        "mcp": _mcp_introspection(),
        "security_policy": {
            "external_schema_introspection": "disabled_by_default",
            "raw_tool_schemas_exposed": False,
            "raw_provider_secrets_exposed": False,
            "token_values_exposed": False,
            "rfc7662_token_introspection": _token_introspection_status(),
            "normal_user_detail": "provider and MCP names only; raw schemas require gated developer access",
        },
    }


def _provider_introspection(user_id: str = "") -> dict[str, Any]:
    registered: list[str] = []
    env_status: dict[str, dict[str, Any]] = {}
    supported: dict[str, dict[str, Any]] = {}
    user_status_by_name: dict[str, dict[str, Any]] = {}
    provider_priority: list[str] = []
    budget: dict[str, dict[str, Any]] = {}
    teacher_fallback_enabled = False

    try:
        from providers.factory import registered_providers

        registered = sorted(registered_providers())
    except Exception:
        registered = []

    try:
        from services.provider_service import SUPPORTED_PROVIDERS, provider_env_status

        supported = dict(SUPPORTED_PROVIDERS)
        env_status = provider_env_status()
    except Exception:
        supported = {}
        env_status = {}

    if user_id:
        try:
            from services.provider_service import list_providers

            user_status_by_name = {
                str(item.get("provider_name") or ""): item
                for item in list_providers(user_id)
                if item.get("provider_name")
            }
        except Exception:
            user_status_by_name = {}

    try:
        from core.token_budget import budget_status, provider_priority_from_env

        provider_priority = provider_priority_from_env()
        budget = budget_status()
    except Exception:
        provider_priority = []
        budget = {}

    try:
        from lowus_brain.brain_config import BrainConfig

        teacher_fallback_enabled = BrainConfig.from_env().is_teacher_allowed()
    except Exception:
        teacher_fallback_enabled = False

    provider_names = sorted(set(registered) | set(supported) | set(env_status))
    providers: list[dict[str, Any]] = []
    configured_provider_names: list[str] = []
    configured_routable_provider_names: list[str] = []
    enabled_user_provider_names: list[str] = []
    for name in provider_names:
        info = supported.get(name, {})
        env = env_status.get(name, {})
        user = user_status_by_name.get(name, {})
        env_configured = bool(env.get("env_configured", False))
        user_key_configured = bool(user.get("has_key", False))
        user_enabled = bool(user.get("enabled", False))
        requires_key = bool(info.get("has_key", True))
        provider_record = {
            "name": name,
            "display": str(info.get("display") or name),
            "registered": name in registered,
            "routable": bool(env.get("routable", name in registered)),
            "requires_secret": requires_key,
            "env_configured": env_configured,
            "env_secret_count": len(list(env.get("env_key_names") or [])),
            "user_key_configured": user_key_configured,
            "user_enabled": user_enabled,
            "default_model": str(
                user.get("default_model")
                or env.get("default_model")
                or ""
            ),
            "budget": budget.get(name, {}),
            "auth_validation": {
                "env_secret_presence_checked": True,
                "encrypted_user_secret_presence_checked": bool(user_id),
                "oauth_token_introspection": "not_configured",
            },
        }
        providers.append(provider_record)
        if env_configured or user_key_configured or not requires_key:
            configured_provider_names.append(name)
            if provider_record["routable"]:
                configured_routable_provider_names.append(name)
        if user_enabled:
            enabled_user_provider_names.append(name)

    return {
        "registered": registered,
        "provider_priority": provider_priority,
        "teacher_fallback_enabled": teacher_fallback_enabled,
        "configured_provider_names": sorted(configured_provider_names),
        "configured_routable_provider_names": sorted(configured_routable_provider_names),
        "enabled_user_provider_names": sorted(enabled_user_provider_names),
        "providers": providers,
    }


def _mcp_introspection() -> dict[str, Any]:
    servers = _dedupe_servers(_discover_mcp_servers())
    return {
        "discovery": "local_static_ast_scan",
        "network_calls_made": False,
        "schema_exposure": "tool_names_only",
        "raw_schemas_exposed": False,
        "external_introspection": "disabled_by_default",
        "server_count": len(servers),
        "servers": servers,
    }


def _dedupe_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for server in servers:
        name = str(server.get("server_name") or "")
        if name in seen:
            continue
        seen.add(name)
        out.append(server)
    return out


def _discover_mcp_servers() -> list[dict[str, Any]]:
    roots = [
        AI_CODER_DIR / "mcp_server",
        AI_CODER_DIR / "memory" / "mcp" / "factory",
    ]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        paths.extend(sorted(root.glob("*_mcp.py")))
        paths.extend(sorted(root.glob("*.py")))

    seen: set[Path] = set()
    servers: list[dict[str, Any]] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen or path.name.startswith("__"):
            continue
        seen.add(resolved)
        server = _parse_mcp_module(path)
        if server:
            servers.append(server)
    return sorted(servers, key=lambda item: item["server_name"])


def _parse_mcp_module(path: Path) -> dict[str, Any] | None:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return None

    constants: dict[str, Any] = {}
    tool_names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id in {"SERVER_NAME", "SERVER_VERSION", "SERVER_DESCRIPTION"}:
                constants[target.id] = _literal_string(node.value)
            if target.id == "TOOLS":
                tool_names = _extract_tool_names(node.value)

    server_name = str(constants.get("SERVER_NAME") or "").strip()
    if not server_name and not tool_names:
        return None

    env_names = sorted(set(_ENV_CALL_RE.findall(source)))
    return {
        "server_name": server_name or path.stem,
        "version": str(constants.get("SERVER_VERSION") or "unknown"),
        "description": str(constants.get("SERVER_DESCRIPTION") or "")[:180],
        "module": _relative_module_path(path),
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "schema_detail": "redacted",
        "env_requirements": [
            {"name": env_name, "configured": bool(os.environ.get(env_name, "").strip())}
            for env_name in env_names
        ],
        "status": "discovered_not_health_checked",
    }


def _literal_string(node: ast.AST) -> str:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _extract_tool_names(node: ast.AST) -> list[str]:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return names


def _relative_module_path(path: Path) -> str:
    try:
        return path.relative_to(AI_CODER_DIR).as_posix()
    except ValueError:
        return path.name


def _token_introspection_status() -> dict[str, Any]:
    endpoint_configured = bool(os.environ.get("MCP_TOKEN_INTROSPECTION_URL", "").strip())
    return {
        "configured": endpoint_configured,
        "standard": "RFC 7662",
        "mode": "not_called_by_snapshot",
        "reason": (
            "MCP_TOKEN_INTROSPECTION_URL is configured"
            if endpoint_configured
            else "No OAuth token introspection endpoint is configured"
        ),
    }
