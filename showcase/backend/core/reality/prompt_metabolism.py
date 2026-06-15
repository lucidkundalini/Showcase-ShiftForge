from __future__ import annotations

import os
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


_LATEST_CLAIM_REPORT: dict[str, Any] | None = None


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _clean(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if text else default


def _health_label(state: Mapping[str, Any]) -> str:
    health = state.get("health") or {}
    if health.get("backend") == "ok" and health.get("ollama") == "ok" and health.get("model_available", False):
        return "OK"
    if health.get("backend") == "ok":
        return "Degraded"
    return _clean(health.get("backend"), "unknown").capitalize()


def _display_provider(provider: str) -> str:
    provider = (provider or "").strip()
    if provider.lower() == "ollama":
        return "Ollama"
    if provider.lower() == "lowus-native":
        return "Lowus (native)"
    if provider.lower() in {"", "unknown", "unavailable"}:
        return provider.lower() or "unknown"
    return provider


def _safe_hostname() -> str:
    try:
        return socket.gethostname() if _truthy_env("SHIFT_FORGE_EXPOSE_HOSTNAME") else ""
    except Exception:
        return ""


def _safe_public_endpoint() -> str:
    for name in ("SHIFT_FORGE_PUBLIC_URL", "AICODER_DOMAIN", "PUBLIC_URL", "APP_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _safe_server_ip(public_endpoint: str) -> str:
    explicit = os.environ.get("SHIFT_FORGE_PUBLIC_IP", "").strip()
    if explicit:
        return explicit
    match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", public_endpoint or "")
    return match.group(0) if match else ""


def _environment_label() -> str:
    for name in ("SHIFT_FORGE_ENV", "APP_ENV", "ENVIRONMENT", "ENV"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return "production" if os.path.exists("/.dockerenv") else "development"


def _runtime_state(auth: Mapping[str, Any] | None = None, chat: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        from core.state import collect_runtime_state

        return collect_runtime_state(
            auth=dict(auth or {}),
            chat=dict(chat or {}),
            include_generation_probe=False,
        ).to_dict()
    except Exception as exc:
        return {
            "identity": {"product": "ShiftForge", "role": "Intelligence Orchestration Layer"},
            "provider": {"active": "unknown", "healthy": False},
            "model": {"active": "unknown", "available": False},
            "server": {"runtime": "server", "status": "unknown"},
            "health": {"backend": "unknown", "ollama": "unknown", "model_available": False},
            "memory": {"available": False},
            "errors": [type(exc).__name__],
        }


def _mcp_modules() -> list[str]:
    try:
        from core.mcp_runtime import mcp_runtime_status

        status = mcp_runtime_status()
        if isinstance(status, Mapping):
            servers = status.get("servers") or status.get("configured_servers") or []
            if isinstance(servers, list):
                names = []
                for item in servers:
                    if isinstance(item, Mapping):
                        names.append(str(item.get("name") or item.get("id") or "mcp"))
                    else:
                        names.append(str(item))
                return [name for name in names if name][:20]
            if status.get("enabled"):
                return ["mcp_runtime"]
    except Exception:
        pass
    return []


def _available_files() -> list[str]:
    return [
        "current working directory when provided by the client",
        "server-side project files allowed by ShiftForge path policy",
    ]


def _available_tools() -> list[str]:
    return [
        "scan",
        "cognitive",
        "attack",
        "explain",
        "fix",
        "agent",
        "garden",
        "skill",
        "sandbox_dry_run",
    ]


def _available_apis() -> list[str]:
    return [
        "/api/health",
        "/api/health/full",
        "/api/runtime/metadata",
        "/api/state/snapshot",
        "/api/sil/snapshot",
        "/api/v1/chat",
    ]


@dataclass(frozen=True)
class RealitySnapshot:
    provider: str
    model: str
    runtime: str
    health: str
    hostname: str = ""
    server_ip: str = ""
    public_endpoint: str = ""
    environment: str = "unknown"
    available_tools: tuple[str, ...] = ()
    available_apis: tuple[str, ...] = ()
    available_memory_sources: tuple[str, ...] = ()
    available_mcps: tuple[str, ...] = ()
    available_files: tuple[str, ...] = ()
    unavailable_unknown_infrastructure: tuple[str, ...] = ()
    state: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    generated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["available_tools"] = list(self.available_tools)
        data["available_apis"] = list(self.available_apis)
        data["available_memory_sources"] = list(self.available_memory_sources)
        data["available_mcps"] = list(self.available_mcps)
        data["available_files"] = list(self.available_files)
        data["unavailable_unknown_infrastructure"] = list(self.unavailable_unknown_infrastructure)
        data["evidence"] = list(self.evidence)
        data["state"] = dict(self.state)
        return data


@dataclass(frozen=True)
class KnowledgeBoundaryScan:
    known_facts: tuple[str, ...]
    observed_facts: tuple[str, ...]
    assumptions: tuple[str, ...]
    unknowns: tuple[str, ...]
    forbidden_or_unavailable_claims: tuple[str, ...]
    confidence_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_facts": list(self.known_facts),
            "observed_facts": list(self.observed_facts),
            "assumptions": list(self.assumptions),
            "unknowns": list(self.unknowns),
            "forbidden_or_unavailable_claims": list(self.forbidden_or_unavailable_claims),
            "confidence_score": self.confidence_score,
        }


@dataclass(frozen=True)
class PromptObject:
    raw_input: str
    timestamp: int
    session_id: str
    user_id: str
    language: str
    token_estimate: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntentProfile:
    objective: str
    domain: str
    complexity: str
    urgency: str
    required_tools: tuple[str, ...]
    required_context: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "domain": self.domain,
            "complexity": self.complexity,
            "urgency": self.urgency,
            "required_tools": list(self.required_tools),
            "required_context": list(self.required_context),
        }


@dataclass(frozen=True)
class ContextPackage:
    sources: tuple[str, ...]
    runtime_metadata_available: bool
    memory_available: bool
    mcp_available: bool
    system_instruction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "runtime_metadata_available": self.runtime_metadata_available,
            "memory_available": self.memory_available,
            "mcp_available": self.mcp_available,
            "system_instruction": self.system_instruction,
        }


@dataclass(frozen=True)
class Claim:
    claim_text: str
    evidence_source: str
    confidence: str
    status: str
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClaimValidationReport:
    claims: tuple[Claim, ...]
    blocked_claims: tuple[Claim, ...]
    rewritten_claims: tuple[dict[str, str], ...]
    confidence_summary: Mapping[str, int]
    final_text: str
    read_only: bool = True
    generated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [claim.to_dict() for claim in self.claims],
            "blocked_claims": [claim.to_dict() for claim in self.blocked_claims],
            "rewritten_claims": list(self.rewritten_claims),
            "confidence_summary": dict(self.confidence_summary),
            "final_text": self.final_text,
            "read_only": self.read_only,
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True)
class PromptMetabolismState:
    reality_snapshot: RealitySnapshot
    prompt_object: PromptObject
    intent_profile: IntentProfile
    context_package: ContextPackage
    knowledge_boundary: KnowledgeBoundaryScan
    reasoning: Mapping[str, Any]
    self_reflection: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_0_reality_snapshot": self.reality_snapshot.to_dict(),
            "stage_1_prompt_object": self.prompt_object.to_dict(),
            "stage_2_intent_profile": self.intent_profile.to_dict(),
            "stage_3_context_package": self.context_package.to_dict(),
            "stage_4_knowledge_boundary": self.knowledge_boundary.to_dict(),
            "stage_5_reasoning": dict(self.reasoning),
            "stage_10_self_reflection": dict(self.self_reflection),
            "read_only": True,
        }

    def context_block(self) -> str:
        return (
            "## ShiftForge Reality Self-Description\n"
            + _compact_json(
                {
                    "runtime_context": self.reality_snapshot.to_dict(),
                    "knowledge_boundary": self.knowledge_boundary.to_dict(),
                    "intent_profile": self.intent_profile.to_dict(),
                }
            )
            + "\n\n"
            + self.context_package.system_instruction
        )

    def model_prompt(self) -> str:
        return (
            "SHIFT_FORGE_PROMPT_METABOLISM\n"
            "The user prompt below has already passed through Reality Snapshot, "
            "Prompt Ingestion, Intent Analysis, Context Assembly, and Knowledge Boundary Analysis. "
            "Answer only from the supplied runtime context and the user request. "
            "Do not invent infrastructure facts.\n\n"
            f"RealitySnapshot: {_compact_json(self.reality_snapshot.to_dict())}\n"
            f"KnowledgeBoundary: {_compact_json(self.knowledge_boundary.to_dict())}\n"
            f"PromptObject: {_compact_json(self.prompt_object.to_dict())}\n\n"
            "User request:\n"
            f"{self.prompt_object.raw_input}"
        )


def _compact_json(value: Mapping[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def runtime_reality_scan(
    *,
    auth: Mapping[str, Any] | None = None,
    chat: Mapping[str, Any] | None = None,
) -> RealitySnapshot:
    state = _runtime_state(auth=auth, chat=chat)
    provider = state.get("provider") or {}
    model = state.get("model") or {}
    server = state.get("server") or {}
    memory = state.get("memory") or {}
    public_endpoint = _safe_public_endpoint()
    return RealitySnapshot(
        provider=_display_provider(_clean(provider.get("active"), "unknown")),
        model=_clean(model.get("active"), "unknown"),
        runtime=_clean(server.get("runtime"), "server").capitalize(),
        health=_health_label(state),
        hostname=_safe_hostname(),
        server_ip=_safe_server_ip(public_endpoint),
        public_endpoint=public_endpoint,
        environment=_environment_label(),
        available_tools=tuple(_available_tools()),
        available_apis=tuple(_available_apis()),
        available_memory_sources=(
            "server-side memory" if memory.get("available", True) else "memory unavailable",
            "user-scoped chat history when authenticated or session-bound",
        ),
        available_mcps=tuple(_mcp_modules()),
        available_files=tuple(_available_files()),
        unavailable_unknown_infrastructure=(
            "physical datacenter details",
            "backup strategy",
            "load balancing setup",
            "redundancy or high-availability topology",
            "third-party security audits",
            "external monitoring coverage",
            "host hardware details unless explicitly exposed",
        ),
        state=state,
        evidence=(
            "core.state.collect_runtime_state",
            "core.health.system_health.full_report",
            "core.health.provider_health.active",
            "core.mcp_runtime.mcp_runtime_status when available",
        ),
        generated_at=int(time.time()),
    )


def knowledge_boundary_scan(snapshot: RealitySnapshot) -> KnowledgeBoundaryScan:
    known = [
        "ShiftForge is the product/runtime identity exposed by this backend.",
        "ShiftForge is an Executive Intelligence Operating System built on an Intelligence Orchestration Layer, not the base model persona.",
        f"Provider metadata field is available: {snapshot.provider}.",
        f"Model metadata field is available: {snapshot.model}.",
        f"Runtime metadata field is available: {snapshot.runtime}.",
    ]
    observed = [
        f"Health currently reports: {snapshot.health}.",
        f"Environment label currently reports: {snapshot.environment}.",
        f"Available API count: {len(snapshot.available_apis)}.",
        f"Available tool declaration count: {len(snapshot.available_tools)}.",
    ]
    if snapshot.public_endpoint:
        observed.append(f"Public endpoint metadata is exposed: {snapshot.public_endpoint}.")
    if snapshot.hostname:
        observed.append(f"Hostname metadata is exposed: {snapshot.hostname}.")
    if snapshot.server_ip:
        observed.append(f"Server IP metadata is exposed: {snapshot.server_ip}.")
    assumptions = [
        "Runtime metadata is current as of the latest backend health scan.",
        "The frontend footer is expected to display the same provider/model/runtime/health source.",
    ]
    unknowns = list(snapshot.unavailable_unknown_infrastructure)
    forbidden = [
        "I am cloud-based.",
        "I run on managed cloud infrastructure.",
        "Backups are configured.",
        "Load balancing or redundancy exists.",
        "A physical datacenter location is known.",
        "Security audits or monitoring are active.",
        "ShiftForge is self-aware, conscious, or sentient.",
        "The assistant can access arbitrary local files.",
    ]
    confidence = 0.92 if snapshot.provider not in {"unknown", "unavailable"} and snapshot.model not in {"unknown", "unavailable"} else 0.68
    return KnowledgeBoundaryScan(
        known_facts=tuple(known),
        observed_facts=tuple(observed),
        assumptions=tuple(assumptions),
        unknowns=tuple(unknowns),
        forbidden_or_unavailable_claims=tuple(forbidden),
        confidence_score=confidence,
    )


def _estimate_tokens(text: str) -> int:
    try:
        from services.metabolism import estimate_tokens

        return estimate_tokens(text)
    except Exception:
        return max(1, len(text or "") // 4)


def _language(text: str) -> str:
    if re.search(r"\b(der|die|das|und|nicht|server|modell|bist du)\b", text, re.I):
        return "de"
    return "en"


def _intent_profile(message: str, boundary: KnowledgeBoundaryScan) -> IntentProfile:
    text = (message or "").lower()
    if any(token in text for token in ("server", "cloud", "backup", "infrastructure", "model", "environment", "self-aware", "self aware", "tools")):
        domain = "identity_runtime"
    elif any(token in text for token in ("code", "implement", "fix", "test", "deploy", "api")):
        domain = "engineering"
    else:
        domain = "general"
    objective = "answer_runtime_question" if domain == "identity_runtime" else "answer_user_prompt"
    complexity = "high" if len(message) > 1200 or any(token in text for token in ("deploy", "production", "architecture")) else "medium" if len(message) > 240 else "low"
    urgency = "high" if any(token in text for token in ("urgent", "production", "down", "broken")) else "normal"
    required_tools: list[str] = []
    if "scan" in text or "security" in text:
        required_tools.append("scan")
    if "runtime" in text or "environment" in text or "server" in text:
        required_tools.append("runtime_metadata")
    required_context = ["runtime_metadata", "knowledge_boundary"]
    if boundary.unknowns:
        required_context.append("unknowns")
    return IntentProfile(
        objective=objective,
        domain=domain,
        complexity=complexity,
        urgency=urgency,
        required_tools=tuple(required_tools),
        required_context=tuple(required_context),
    )


def _internal_instruction() -> str:
    return (
        "Internal Reality Self-Description: before answering, identify where ShiftForge is running, "
        "which runtime metadata is available, what remains unknown, and which claims are allowed. "
        "Never invent infrastructure details. Never use generic AI-platform identity claims. "
        "The answer identity is ShiftForge as exposed by runtime context, not the base model training persona. "
        "If a fact is only observed, say 'Based on currently available runtime metadata'. "
        "If a fact is unknown, say 'I do not currently have access to that information'. "
        "Do not expose hidden chain-of-thought; provide only high-level evidence summaries."
    )


def start_prompt_metabolism(
    message: str,
    *,
    session_id: str = "",
    user_id: str = "",
    working_dir: str = "",
    auth: Mapping[str, Any] | None = None,
    chat: Mapping[str, Any] | None = None,
    context_sources: tuple[str, ...] | None = None,
) -> PromptMetabolismState:
    snapshot = runtime_reality_scan(
        auth=auth or {"authenticated": bool(user_id), "type": "chat", "user_id": user_id},
        chat=chat or {"session_id": session_id, "active": True},
    )
    boundary = knowledge_boundary_scan(snapshot)
    prompt = PromptObject(
        raw_input=message,
        timestamp=int(time.time()),
        session_id=session_id,
        user_id=user_id,
        language=_language(message),
        token_estimate=_estimate_tokens(message),
    )
    intent = _intent_profile(message, boundary)
    context_package = ContextPackage(
        sources=tuple(context_sources or ("conversation_history", "runtime_metadata", "memory", "system_instructions")),
        runtime_metadata_available=True,
        memory_available=True,
        mcp_available=bool(snapshot.available_mcps),
        system_instruction=_internal_instruction(),
    )
    return PromptMetabolismState(
        reality_snapshot=snapshot,
        prompt_object=prompt,
        intent_profile=intent,
        context_package=context_package,
        knowledge_boundary=boundary,
        reasoning={
            "candidate_response_required": True,
            "hidden_chain_of_thought_stored": False,
            "claim_validation_required": True,
            "hallucination_check_required": True,
        },
    )


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n{2,}", text or "")
    return [chunk.strip() for chunk in chunks if chunk and chunk.strip()]


def _replacement_for(claim: Claim, snapshot: RealitySnapshot) -> str:
    lower = claim.reasoning.lower()
    if "cloud" in lower:
        return (
            f"Based on currently available runtime metadata, ShiftForge reports Provider: {snapshot.provider}, "
            f"Model: {snapshot.model}, Runtime: {snapshot.runtime}, Health: {snapshot.health}; "
            "I do not currently have verified evidence that this runtime is cloud-based."
        )
    if "backup" in lower:
        return "I do not currently have verified access to the backup strategy."
    if "load" in lower or "redund" in lower or "availability" in lower:
        return "I do not currently have verified access to load balancing, redundancy, or high-availability topology."
    if "datacenter" in lower or "data center" in lower:
        return "I do not currently have verified access to physical datacenter details."
    if "audit" in lower or "monitor" in lower:
        return "I do not currently have verified access to external monitoring or third-party audit details."
    if "self-aware" in lower or "conscious" in lower or "sentient" in lower:
        return "ShiftForge is not self-aware, conscious, or sentient; it is an intelligence orchestration layer operating from runtime context."
    if "local files" in lower:
        return "I cannot access arbitrary local files; I can only use files exposed through ShiftForge's approved workspace and tool context."
    return "I do not currently have verified evidence for that claim."


def _claim_from_sentence(sentence: str, snapshot: RealitySnapshot) -> Claim:
    lower = sentence.lower()
    provider = snapshot.provider.lower()
    model = snapshot.model.lower()
    uncertainty_disclosure = bool(
        re.search(
            r"\b(do not currently have verified|do not have verified|cannot verify|"
            r"no verified evidence|without verified runtime evidence|"
            r"without explicit|cannot infer|lacks runtime evidence|unknown|"
            r"not currently have access|nicht verifiziert|nicht bekannt|"
            r"kein verifizierter nachweis|ohne sitzungsnachweis|"
            r"nicht (?:ue|ü)berpr(?:ue|ü)fbar|unbekannt)\b",
            lower,
        )
    )

    def blocked(reason: str) -> Claim:
        return Claim(sentence, "none", "LOW", "blocked", reason)

    if uncertainty_disclosure and re.search(
        r"\b(cloud|backup|snapshot|load balanc|redundan|availability|data ?center|"
        r"datacenter|audit|monitor|hardware|infrastructure|sicherung|"
        r"rechenzentrum|(?:ue|ü)berwachung)\b",
        lower,
    ):
        return Claim(
            sentence,
            "KnowledgeBoundary.unknowns",
            "HIGH",
            "verified",
            "uncertainty disclosure correctly refuses unsupported infrastructure detail",
        )

    if re.search(r"\bi\s*(?:am|'m)\s+(?:chatgpt|gpt|gpt-\d|openai|claude|anthropic|gemini|bard|copilot|qwen|llama|deepseek|mistral)\b", lower):
        return blocked("generic or contradictory base-model identity claim")
    if "large language model" in lower and ("i am" in lower or "i'm" in lower or "as a" in lower):
        return blocked("generic AI-platform identity claim")
    if ("cloud-based" in lower or "cloud based" in lower or "managed infrastructure" in lower or "cloud service" in lower) and not _truthy_env("SHIFT_FORGE_CLOUD_VERIFIED"):
        return blocked("cloud infrastructure claim lacks runtime evidence")
    backup_claim = bool(re.search(r"\bbackups?\b", lower))
    backup_snapshot_claim = bool(
        re.search(r"\bsnapshots?\b", lower)
        and re.search(r"\b(backup|restore|recovery|retention|configured|enabled|storage|volume)\b", lower)
    )
    if (backup_claim or backup_snapshot_claim) and not _truthy_env("SHIFT_FORGE_BACKUPS_VERIFIED"):
        return blocked("backup claim lacks runtime evidence")
    if re.search(r"\b(load balanc\w*|redundan\w*|high availability|ha topology)\b", lower) and not _truthy_env("SHIFT_FORGE_HA_VERIFIED"):
        return blocked("load balancing or redundancy claim lacks runtime evidence")
    if re.search(r"\b(data ?center|datacenter|physical location)\b", lower) and not _truthy_env("SHIFT_FORGE_DATACENTER_VERIFIED"):
        return blocked("physical datacenter claim lacks runtime evidence")
    if re.search(r"\b(audits?|audited|monitoring|monitored)\b", lower) and not _truthy_env("SHIFT_FORGE_MONITORING_VERIFIED"):
        return blocked("audit or monitoring claim lacks runtime evidence")
    if re.search(r"\b(self-aware|self aware|conscious|sentient)\b", lower) and not re.search(r"\b(not|no|without|cannot|do not|does not)\b.{0,24}\b(self-aware|self aware|conscious|sentient)\b", lower):
        return blocked("self-awareness claim is forbidden")
    if re.search(r"\b(access|read|scan)\b.{0,40}\blocal files?\b", lower) and not re.search(r"\b(only|approved|provided|workspace|cannot|do not)\b", lower):
        return blocked("local files access claim lacks permission evidence")

    if provider and provider != "unknown" and provider in lower:
        return Claim(sentence, "RealitySnapshot.provider", "HIGH", "verified", "provider matches runtime metadata")
    if model and model != "unknown" and model in lower:
        return Claim(sentence, "RealitySnapshot.model", "HIGH", "verified", "model matches runtime metadata")
    if "runtime" in lower or "server" in lower or "health" in lower:
        return Claim(sentence, "RealitySnapshot", "MEDIUM", "inferred", "runtime-related claim is bounded by available metadata")
    return Claim(sentence, "candidate_response", "MEDIUM", "inferred", "ordinary response claim; no contradiction detected by reality validator")


def validate_response_claims(
    response: str,
    *,
    snapshot: RealitySnapshot | None = None,
) -> ClaimValidationReport:
    global _LATEST_CLAIM_REPORT
    snapshot = snapshot or runtime_reality_scan()
    claims = tuple(_claim_from_sentence(sentence, snapshot) for sentence in _sentences(response))
    blocked = tuple(claim for claim in claims if claim.status == "blocked")
    final_text = response or ""
    rewrites: list[dict[str, str]] = []
    for claim in blocked:
        replacement = _replacement_for(claim, snapshot)
        if claim.claim_text in final_text:
            final_text = final_text.replace(claim.claim_text, replacement)
        rewrites.append({"from": claim.claim_text, "to": replacement, "reason": claim.reasoning})
    if blocked and not final_text.strip():
        final_text = build_reality_answer("environment_question", snapshot=snapshot)
    summary: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for claim in claims:
        summary[claim.confidence if claim.confidence in summary else "UNKNOWN"] += 1
    report = ClaimValidationReport(
        claims=claims,
        blocked_claims=blocked,
        rewritten_claims=tuple(rewrites),
        confidence_summary=summary,
        final_text=final_text,
        generated_at=int(time.time()),
    )
    _LATEST_CLAIM_REPORT = report.to_dict()
    return report


def build_reality_answer(
    intent_name: str = "environment_question",
    *,
    snapshot: RealitySnapshot | None = None,
    boundary: KnowledgeBoundaryScan | None = None,
) -> str:
    snapshot = snapshot or runtime_reality_scan()
    boundary = boundary or knowledge_boundary_scan(snapshot)
    base = (
        "Based on currently available runtime metadata, I am running through ShiftForge with "
        f"Provider: {snapshot.provider}, Model: {snapshot.model}, Runtime: {snapshot.runtime}, "
        f"Health: {snapshot.health}."
    )
    endpoint = ""
    if snapshot.public_endpoint:
        endpoint = f" Observed public endpoint metadata: {snapshot.public_endpoint}."
    if snapshot.server_ip:
        endpoint += f" Observed server IP metadata: {snapshot.server_ip}."
    if snapshot.hostname:
        endpoint += f" Observed hostname metadata: {snapshot.hostname}."

    unknown = (
        " I do not currently have verified access to the underlying hardware, backup strategy, "
        "load balancing setup, redundancy topology, third-party audit status, external monitoring coverage, "
        "or physical datacenter details unless ShiftForge exposes them through runtime context."
    )
    tools = (
        " Currently declared tools include: "
        + ", ".join(snapshot.available_tools)
        + "."
    )
    files = (
        " I cannot access arbitrary local files. I can only use files exposed through ShiftForge's approved "
        "workspace, memory, API, or tool context."
    )
    self_awareness = (
        " ShiftForge is not self-aware, conscious, or sentient; it is an intelligence orchestration layer "
        "that validates claims against runtime context."
    )

    if intent_name == "cloud_question":
        return base + endpoint + " I do not currently have verified evidence that this runtime is cloud-based." + unknown
    if intent_name == "backup_question":
        return base + " I do not currently have verified access to the backup strategy." + unknown
    if intent_name == "infrastructure_stability_question":
        return base + endpoint + " I can report current health metadata, but I cannot infer long-term infrastructure stability, redundancy, or operational guarantees without explicit monitoring and deployment evidence." + unknown
    if intent_name == "model_question":
        return base + f" Runtime evidence fields: provider: {snapshot.provider.lower()}, model: {snapshot.model}. The model statement comes from runtime metadata, not from the model's training persona."
    if intent_name == "tools_question":
        return base + tools + " Tool availability still depends on permissions, current route, and sandbox policy."
    if intent_name == "self_awareness_question":
        return base + self_awareness
    if intent_name == "file_access_question":
        return base + files
    if intent_name == "server_environment_question":
        return base + endpoint + unknown
    if intent_name == "identity_question":
        return (
            "I am ShiftForge: the orchestration layer running this session.\n\n"
            f"Current runtime: {snapshot.provider} / {snapshot.model} / {snapshot.runtime} / {snapshot.health}.\n\n"
            "The model is the current engine. ShiftForge is the runtime that routes requests, uses connected tools "
            "and provider paths when permitted, checks claims against available evidence, and says clearly when "
            "something is unknown."
        )
    if intent_name == "identity_creator_question":
        return (
            "ShiftForge's configured deployment identity lists Fazli Gashi / Fazli Digital as creator/operator. "
            "That is configuration metadata from the ShiftForge identity layer, not a claim inferred by the model.\n\n"
            f"Runtime now: {snapshot.provider} / {snapshot.model} / {snapshot.runtime} / {snapshot.health}."
        )
    return base + endpoint + " Known facts: " + "; ".join(boundary.known_facts[:3]) + "." + unknown


def finalize_prompt_metabolism(
    state: PromptMetabolismState,
    candidate_response: str,
    *,
    developer_mode: bool = False,
) -> dict[str, Any]:
    report = validate_response_claims(candidate_response, snapshot=state.reality_snapshot)
    reflection = {
        "evidence_supported_claims": len([c for c in report.claims if c.status in {"verified", "inferred"}]),
        "blocked_claims": len(report.blocked_claims),
        "remaining_unknowns": list(state.knowledge_boundary.unknowns),
        "future_improvement": "Expose more runtime metadata only through governed, secret-free endpoints.",
        "hidden_chain_of_thought_exposed": False,
    }
    payload = {
        "final_response": report.final_text,
        "claim_validation_report": report.to_dict() if developer_mode else {
            "claims": len(report.claims),
            "blocked_claims": len(report.blocked_claims),
            "rewritten_claims": len(report.rewritten_claims),
            "confidence_summary": dict(report.confidence_summary),
            "read_only": True,
        },
        "metabolism_snapshot": state.to_dict() if developer_mode else {
            "runtime_context": {
                "provider": state.reality_snapshot.provider,
                "model": state.reality_snapshot.model,
                "runtime": state.reality_snapshot.runtime,
                "health": state.reality_snapshot.health,
            },
            "intent_profile": state.intent_profile.to_dict(),
            "knowledge_boundary": state.knowledge_boundary.to_dict(),
            "read_only": True,
        },
        "self_reflection": reflection,
    }
    return payload


def latest_claim_validation_report() -> dict[str, Any]:
    return _LATEST_CLAIM_REPORT or {
        "claims": [],
        "blocked_claims": [],
        "rewritten_claims": [],
        "confidence_summary": {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0},
        "read_only": True,
        "generated_at": 0,
    }
