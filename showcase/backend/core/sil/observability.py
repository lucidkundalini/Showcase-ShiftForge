from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.hardening.completion_markers import strip_terminal_completion_markers

try:
    from core.xray import new_trace as _xray_new_trace
    from core.xray import xray_probe as _xray_probe
except Exception:  # pragma: no cover - xray is optional in tests
    _xray_new_trace = None
    _xray_probe = None


_ROOT = Path(__file__).resolve().parents[2]
_EVENTS_PATH = Path(os.environ.get("SHIFTFORGE_OBSERVABILITY_EVENTS_PATH", str(_ROOT / "logs" / "events.ndjson")))
_TRACES_DIR = Path(os.environ.get("SHIFTFORGE_OBSERVABILITY_TRACES_DIR", str(_ROOT / "logs" / "traces")))

_LOCK = threading.RLock()
_TRACES: dict[str, "ShiftForgeTrace"] = {}
_ORDER: list[str] = []

_TEMPLATE_LEAK_RE = re.compile(
    r"\b(?:as an ai|based on available data|in conclusion|i can help with that|"
    r"i am unable to|cannot comply with|i hope this helps|certainly!|of course!|"
    r"shiftforge research mode|lead with what you know confidently|"
    r"separate verified facts from uncertain claims visually|"
    r"finish with a concise summary|end with a reliability note|"
    r"based on training data\s*\(cutoff|training data'?s cutoff|"
    r"critical rules\s*\(non-negotiable\))\b",
    re.IGNORECASE,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso(ms: int | None = None) -> str:
    return datetime.fromtimestamp((ms or _now_ms()) / 1000, tz=timezone.utc).isoformat()


def _safe_string(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > limit:
        return text[:limit]
    return text


def _safe_value(value: Any, limit: int = 240) -> Any:
    if isinstance(value, str):
        return _safe_string(value, limit=limit)
    if isinstance(value, Mapping):
        return {str(key): _safe_value(val, limit=limit) for key, val in value.items()}
    if isinstance(value, list):
        return [_safe_value(item, limit=limit) for item in value[:50]]
    if isinstance(value, tuple):
        return [_safe_value(item, limit=limit) for item in value[:50]]
    return value


def _preview(text: str, limit: int = 180) -> str:
    return _safe_string(text, limit=limit)


def _ensure_paths() -> None:
    try:
        _EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        _TRACES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _write_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    try:
        _ensure_paths()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _trace_path(trace_id: str) -> Path:
    day = _now_iso().split("T", 1)[0]
    return _TRACES_DIR / day / f"{trace_id}.json"


def _write_trace_file(trace: "ShiftForgeTrace") -> None:
    try:
        path = _trace_path(trace.trace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _load_trace_file(trace_id: str) -> dict[str, Any]:
    try:
        candidates = sorted(_TRACES_DIR.rglob(f"{trace_id}.json"), reverse=True)
    except Exception:
        candidates = []
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def _xray(stage: str, **extra: Any) -> None:
    if _xray_probe is None:
        return
    try:
        _xray_probe(stage, **{k: v for k, v in extra.items() if v is not None})
    except Exception:
        pass


@dataclass(frozen=True)
class TraceEvent:
    trace_id: str
    event: str
    stage: str
    timestamp_ms: int
    absolute_ms: int
    delta_ms: int
    request_id: str = ""
    session_id: str = ""
    client_type: str = ""
    surface: str = ""
    source: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceMutation:
    layer: str
    step: str
    before_length: int
    after_length: int
    changed_output: bool
    reason: str
    error: str = ""
    before_preview: str = ""
    after_preview: str = ""
    timestamp_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DebugIntent:
    suspected_subsystem: str
    reason_debugging_may_be_needed: str
    what_would_be_inspected: list[str]
    what_could_be_modified: list[str]
    risk_level: str
    expected_benefit: str
    possible_damage: str
    read_only_option: str
    sandbox_option: str
    rollback_plan: str
    verification_plan: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImpactSimulation:
    would_affect_state: bool
    would_affect_memory: bool
    would_affect_files: bool
    would_affect_config: bool
    would_affect_routing: bool
    would_affect_frontend: bool
    would_affect_user_visible_output: bool
    could_create_latency: bool
    could_create_loops: bool
    could_create_cascading_failures: bool
    could_corrupt_logs: bool
    could_break_sessions: bool
    could_create_false_positives: bool
    read_only_inspection_sufficient: bool
    sandbox_reproducible: bool
    minimum_diagnostic_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShiftForgeTrace:
    trace_id: str
    request_id: str = ""
    session_id: str = ""
    client_type: str = ""
    surface: str = ""
    user_input_metadata: dict[str, Any] = field(default_factory=dict)
    selected_route: str = ""
    selected_agent: str = ""
    selected_model: str = ""
    provider: str = ""
    router_reason: str = ""
    prompt_construction_metadata: dict[str, Any] = field(default_factory=dict)
    model_call_status: dict[str, Any] = field(default_factory=dict)
    raw_output_preview: str = ""
    raw_output_length: int = 0
    final_output_preview: str = ""
    final_output_length: int = 0
    token_estimate: int = 0
    response_expectation: str = "normal_chat_answer"
    empty_output_detected: bool = False
    empty_output_source: str = ""
    recovery_attempted: bool = False
    recovery_success: bool = False
    recovery_attempt_count: int = 0
    last_known_valid_output_available: bool = False
    recovered_from_last_known_valid_output: bool = False
    fallback_allowed: bool = True
    latency_metrics: dict[str, int] = field(default_factory=dict)
    middleware_steps: list[dict[str, Any]] = field(default_factory=list)
    postprocessor_steps: list[dict[str, Any]] = field(default_factory=list)
    fallback_activation: dict[str, Any] = field(default_factory=dict)
    frontend_delivery_status: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    root_cause_guess: str = ""
    confidence_score: float = 1.0
    release_decision: str = "allow"
    events: list[dict[str, Any]] = field(default_factory=list)
    mutations: list[dict[str, Any]] = field(default_factory=list)
    debug_intent: dict[str, Any] = field(default_factory=dict)
    impact_simulation: dict[str, Any] = field(default_factory=dict)
    runtime_context: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=_now_ms)
    updated_at_ms: int = field(default_factory=_now_ms)
    finalized_at_ms: int = 0
    last_event_ms: int = 0
    _raw_output_chunks: list[str] = field(default_factory=list, repr=False)
    _finalized: bool = field(default=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "client_type": self.client_type,
            "surface": self.surface,
            "user_input_metadata": dict(self.user_input_metadata),
            "selected_route": self.selected_route,
            "selected_agent": self.selected_agent,
            "selected_model": self.selected_model,
            "provider": self.provider,
            "router_reason": self.router_reason,
            "prompt_construction_metadata": dict(self.prompt_construction_metadata),
            "model_call_status": dict(self.model_call_status),
            "raw_output_preview": self.raw_output_preview,
            "raw_output_length": self.raw_output_length,
            "final_output_preview": self.final_output_preview,
            "final_output_length": self.final_output_length,
            "token_estimate": self.token_estimate,
            "response_expectation": self.response_expectation,
            "empty_output_detected": self.empty_output_detected,
            "empty_output_source": self.empty_output_source,
            "recovery_attempted": self.recovery_attempted,
            "recovery_success": self.recovery_success,
            "recovery_attempt_count": self.recovery_attempt_count,
            "last_known_valid_output_available": self.last_known_valid_output_available,
            "recovered_from_last_known_valid_output": self.recovered_from_last_known_valid_output,
            "fallback_allowed": self.fallback_allowed,
            "latency_metrics": dict(self.latency_metrics),
            "middleware_steps": list(self.middleware_steps),
            "postprocessor_steps": list(self.postprocessor_steps),
            "fallback_activation": dict(self.fallback_activation),
            "frontend_delivery_status": dict(self.frontend_delivery_status),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "root_cause_guess": self.root_cause_guess,
            "confidence_score": self.confidence_score,
            "release_decision": self.release_decision,
            "events": list(self.events),
            "mutations": list(self.mutations),
            "debug_intent": dict(self.debug_intent),
            "impact_simulation": dict(self.impact_simulation),
            "runtime_context": dict(self.runtime_context),
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "finalized_at_ms": self.finalized_at_ms,
            "finalized": self._finalized,
        }

    def public_summary(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "selected_route": self.selected_route,
            "selected_agent": self.selected_agent,
            "selected_model": self.selected_model,
            "provider": self.provider,
            "raw_output_length": self.raw_output_length,
            "final_output_length": self.final_output_length,
            "token_estimate": self.token_estimate,
            "response_expectation": self.response_expectation,
            "empty_output_detected": self.empty_output_detected,
            "empty_output_source": self.empty_output_source,
            "recovery_attempted": self.recovery_attempted,
            "recovery_success": self.recovery_success,
            "recovery_attempt_count": self.recovery_attempt_count,
            "last_known_valid_output_available": self.last_known_valid_output_available,
            "recovered_from_last_known_valid_output": self.recovered_from_last_known_valid_output,
            "fallback_allowed": self.fallback_allowed,
            "final_output_preview": self.final_output_preview,
            "middleware_actions": [step.get("step") or step.get("layer") for step in self.middleware_steps if step],
            "frontend_delivery_status": dict(self.frontend_delivery_status),
            "fallback_activation": dict(self.fallback_activation),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "root_cause_guess": self.root_cause_guess,
            "release_decision": self.release_decision,
            "confidence_score": self.confidence_score,
            "latency_metrics": dict(self.latency_metrics),
            "mutations": list(self.mutations),
        }

    def _touch(self) -> None:
        self.updated_at_ms = _now_ms()

    def _append_event(self, event: TraceEvent) -> TraceEvent:
        self.events.append(event.to_dict())
        _write_jsonl(_EVENTS_PATH, event.to_dict())
        self._touch()
        _xray(event.stage, trace_id=self.trace_id, session_id=self.session_id, event=event.event, source=event.source)
        return event

    def record_event(self, stage: str, *, event: str | None = None, source: str = "", payload: Mapping[str, Any] | None = None, **detail: Any) -> TraceEvent:
        now = _now_ms()
        delta = now - self.last_event_ms if self.last_event_ms else 0
        self.last_event_ms = now
        merged = dict(payload or {})
        merged.update(detail)
        merged = _safe_value(merged)
        ev = TraceEvent(
            trace_id=self.trace_id,
            event=event or stage,
            stage=stage,
            timestamp_ms=now,
            absolute_ms=now,
            delta_ms=max(0, int(delta)),
            request_id=self.request_id,
            session_id=self.session_id,
            client_type=self.client_type,
            surface=self.surface,
            source=source,
            payload=merged if isinstance(merged, dict) else {"value": merged},
        )
        if stage in {"route_selected", "route.decide"}:
            self.selected_route = str(merged.get("path") or merged.get("selected_route") or self.selected_route)
            self.router_reason = str(merged.get("reason") or self.router_reason)
        elif stage in {"agent_selected", "model_selected"}:
            self.selected_agent = str(merged.get("agent") or merged.get("selected_agent") or self.selected_agent)
            self.selected_model = str(merged.get("model") or self.selected_model)
            self.provider = str(merged.get("provider") or merged.get("backend") or self.provider)
        elif stage == "prompt_built":
            self.prompt_construction_metadata.update(merged)
        elif stage in {"model_call_started", "provider_start"}:
            self.model_call_status.update({"status": "running", **merged})
            self.selected_model = str(merged.get("model") or self.selected_model)
            self.provider = str(merged.get("provider") or merged.get("backend") or self.provider)
        elif stage in {"model_call_finished", "provider_end"}:
            self.model_call_status.update({"status": "finished", **merged})
        elif stage == "raw_output_received":
            text = str(merged.get("content") or merged.get("text") or merged.get("final") or "")
            if text:
                self._raw_output_chunks.append(text)
                combined = "".join(self._raw_output_chunks)
                self.raw_output_length = len(combined)
                self.raw_output_preview = _preview(combined)
        elif stage == "response_released":
            self.final_output_length = int(merged.get("final_length") or self.final_output_length or 0)
            preview = merged.get("final_preview")
            if isinstance(preview, str):
                self.final_output_preview = _preview(preview)
            self.latency_metrics.setdefault("response_release_ms", now - self.created_at_ms)
        elif stage == "response_blocked":
            self.release_decision = "block"
            self.latency_metrics.setdefault("response_blocked_ms", now - self.created_at_ms)
        elif stage == "frontend_rendered":
            self.frontend_delivery_status.update(merged)
        elif stage == "error_detected":
            message = str(merged.get("message") or merged.get("error") or "unknown error")
            if message and message not in self.errors:
                self.errors.append(message[:240])
        elif stage == "response_diagnostics":
            provider = str(merged.get("provider") or merged.get("backend") or "").strip()
            model = str(merged.get("model") or merged.get("selected_model") or "").strip()
            route = str(merged.get("selected_path") or merged.get("selected_route") or "").strip()
            if provider:
                self.provider = provider
            if model:
                self.selected_model = model
            if route and not self.selected_route:
                self.selected_route = route
            expectation = merged.get("responseExpectation") or merged.get("response_expectation")
            if expectation:
                self.response_expectation = str(expectation)
            if "emptyOutputDetected" in merged or "empty_output_detected" in merged:
                self.empty_output_detected = bool(merged.get("emptyOutputDetected", merged.get("empty_output_detected", False)))
            if "emptyOutputSource" in merged or "empty_output_source" in merged:
                self.empty_output_source = str(merged.get("emptyOutputSource") or merged.get("empty_output_source") or self.empty_output_source)
            if "recoveryAttempted" in merged or "recovery_attempted" in merged:
                self.recovery_attempted = bool(merged.get("recoveryAttempted", merged.get("recovery_attempted", False)))
            if "recoverySuccess" in merged or "recovery_success" in merged:
                self.recovery_success = bool(merged.get("recoverySuccess", merged.get("recovery_success", False)))
            if "recoveryAttemptCount" in merged or "recovery_attempt_count" in merged:
                self.recovery_attempt_count = int(merged.get("recoveryAttemptCount", merged.get("recovery_attempt_count", self.recovery_attempt_count)))
            if "lastKnownValidOutputAvailable" in merged or "last_known_valid_output_available" in merged:
                self.last_known_valid_output_available = bool(merged.get("lastKnownValidOutputAvailable", merged.get("last_known_valid_output_available", False)))
            if "recoveredFromLastKnownValidOutput" in merged or "recovered_from_last_known_valid_output" in merged:
                self.recovered_from_last_known_valid_output = bool(merged.get("recoveredFromLastKnownValidOutput", merged.get("recovered_from_last_known_valid_output", False)))
            if "fallbackAllowed" in merged or "fallback_allowed" in merged:
                self.fallback_allowed = bool(merged.get("fallbackAllowed", merged.get("fallback_allowed", self.fallback_allowed)))
            if "releaseDecision" in merged or "release_decision" in merged:
                self.release_decision = str(merged.get("releaseDecision") or merged.get("release_decision") or self.release_decision)
            if "rootCauseGuess" in merged or "root_cause_guess" in merged:
                self.root_cause_guess = str(merged.get("rootCauseGuess") or merged.get("root_cause_guess") or self.root_cause_guess)
        elif stage == "fallback_triggered":
            self.fallback_activation.update(merged)
        elif stage == "empty_output_detected":
            self.empty_output_detected = bool(merged.get("detected", True))
            if merged.get("response_expectation"):
                self.response_expectation = str(merged.get("response_expectation") or self.response_expectation)
            if merged.get("source"):
                self.empty_output_source = str(merged.get("source") or self.empty_output_source)
            self.recovery_attempted = bool(merged.get("recovery_attempted", self.recovery_attempted))
            self.recovery_success = bool(merged.get("recovery_success", self.recovery_success))
            self.recovery_attempt_count = int(merged.get("recovery_attempt_count", self.recovery_attempt_count))
            self.last_known_valid_output_available = bool(merged.get("last_known_valid_output_available", self.last_known_valid_output_available))
            self.fallback_allowed = bool(merged.get("fallback_allowed", self.fallback_allowed))
        elif stage == "empty_output_source_classified":
            if merged.get("source"):
                self.empty_output_source = str(merged.get("source") or self.empty_output_source)
        elif stage == "recovery_attempt_started":
            self.recovery_attempted = True
            self.recovery_attempt_count = int(merged.get("attempt", self.recovery_attempt_count or 1) or 1)
        elif stage == "recovery_attempt_finished":
            self.recovery_attempted = True
            self.recovery_success = bool(merged.get("success", False))
            self.recovery_attempt_count = int(merged.get("attempt", self.recovery_attempt_count or 1) or 1)
        elif stage == "response_recovered":
            self.recovery_attempted = True
            self.recovery_success = True
            self.fallback_allowed = bool(merged.get("fallback_allowed", True))
            self.release_decision = str(merged.get("release_decision") or "allow_with_warning")
            if merged.get("source"):
                self.empty_output_source = str(merged.get("source") or self.empty_output_source)
        elif stage == "fallback_blocked":
            self.fallback_allowed = False
            self.release_decision = str(merged.get("release_decision") or "block")
        elif stage == "fallback_released":
            self.fallback_allowed = True
            self.release_decision = str(merged.get("release_decision") or "allow_with_warning")
        elif stage == "unrecoverable_empty_output":
            self.empty_output_detected = True
            self.recovery_attempted = bool(merged.get("recovery_attempted", self.recovery_attempted))
            self.recovery_success = False
            self.fallback_allowed = False
            self.release_decision = str(merged.get("release_decision") or "block")
        elif stage == "middleware_modified_output":
            self.middleware_steps.append({
                "layer": str(merged.get("layer") or "middleware"),
                "step": str(merged.get("step") or stage),
                "before_length": int(merged.get("before_length") or 0),
                "after_length": int(merged.get("after_length") or 0),
                "changed_output": bool(merged.get("changed_output", False)),
                "reason": str(merged.get("reason") or ""),
                "error": str(merged.get("error") or ""),
                "before_preview": _preview(str(merged.get("before_preview") or "")),
                "after_preview": _preview(str(merged.get("after_preview") or "")),
            })
        elif stage == "postprocessor_modified_output":
            self.postprocessor_steps.append({
                "layer": str(merged.get("layer") or "postprocessor"),
                "step": str(merged.get("step") or stage),
                "before_length": int(merged.get("before_length") or 0),
                "after_length": int(merged.get("after_length") or 0),
                "changed_output": bool(merged.get("changed_output", False)),
                "reason": str(merged.get("reason") or ""),
                "error": str(merged.get("error") or ""),
                "before_preview": _preview(str(merged.get("before_preview") or "")),
                "after_preview": _preview(str(merged.get("after_preview") or "")),
            })
        self._append_event(ev)
        _write_trace_file(self)
        return ev

    def record_mutation(
        self,
        *,
        layer: str,
        step: str,
        before_text: str,
        after_text: str,
        reason: str,
        error: str = "",
    ) -> TraceMutation:
        mutation = TraceMutation(
            layer=layer,
            step=step,
            before_length=len(before_text or ""),
            after_length=len(after_text or ""),
            changed_output=(before_text or "") != (after_text or ""),
            reason=reason,
            error=error,
            before_preview=_preview(before_text),
            after_preview=_preview(after_text),
            timestamp_ms=_now_ms(),
        )
        payload = mutation.to_dict()
        self.mutations.append(payload)
        stage = "middleware_modified_output" if layer in {"middleware", "adapter", "transport"} else "postprocessor_modified_output"
        if layer == "frontend":
            stage = "frontend_rendered"
        self.record_event(stage, source=layer, payload=payload)
        if mutation.changed_output:
            if layer == "middleware":
                self.middleware_steps.append(payload)
            elif layer == "postprocessor":
                self.postprocessor_steps.append(payload)
        return mutation

    def record_warning(self, warning: str, *, source: str = "") -> None:
        warning = _preview(warning, 240)
        if warning and warning not in self.warnings:
            self.warnings.append(warning)
        self.record_event("warning_detected", source=source, payload={"warning": warning})

    def record_error(self, error: str, *, source: str = "") -> None:
        error = _preview(error, 240)
        if error and error not in self.errors:
            self.errors.append(error)
        self.record_event("error_detected", source=source, payload={"error": error})

    def _evaluate_issues(self, candidate_text: str, *, frontend_check: bool = False) -> list[str]:
        issues: list[str] = []
        text = strip_terminal_completion_markers(candidate_text or "")
        stripped = (candidate_text or "").strip()
        expectation = self.response_expectation or "normal_chat_answer"
        if not stripped:
            issues.append("empty output")
        if stripped.lower() in {"done", "done."} and expectation != "action_completion":
            issues.append("only done")
        if text != (candidate_text or "") and expectation != "action_completion":
            issues.append("completion marker leakage")
        if candidate_text and len(candidate_text.strip()) < 12 and expectation == "normal_chat_answer" and self.selected_route not in {"FAST", "deterministic"}:
            issues.append("output shorter than expected")
        if _TEMPLATE_LEAK_RE.search(candidate_text or ""):
            issues.append("template leakage")
        if any("truncate" in str(step.get("reason") or "").lower() or "truncate" in str(step.get("step") or "").lower() for step in self.middleware_steps):
            issues.append("middleware truncation")
        if self.fallback_activation:
            fallback_reason = str(self.fallback_activation.get("reason") or "").lower()
            if "timeout" in fallback_reason:
                issues.append("model timeout")
            else:
                issues.append("fallback overwrite")
        if self.model_call_status.get("status") in {"timeout", "timed_out"}:
            issues.append("model timeout")
        if self.selected_route and self.selected_agent:
            route = self.selected_route.lower()
            agent = self.selected_agent.lower()
            if route == "ceo" and "ceo" not in agent:
                issues.append("wrong agent routing")
            if route == "research" and "research" not in agent:
                issues.append("wrong agent routing")
        if frontend_check:
            rendered = int(self.frontend_delivery_status.get("rendered_length") or 0)
            if self.final_output_length and rendered != self.final_output_length:
                issues.append("frontend render mismatch")
        return list(dict.fromkeys(issues))

    def _is_transparent_timeout_fallback(self, candidate_text: str) -> bool:
        """Allow explicit timeout diagnostics without re-wrapping them as unsafe.

        Silent fallback overwrites remain severe. This exception only applies
        when the runtime trace says the fallback reason was a timeout and the
        user-facing text states that timeout directly.
        """
        fallback_reason = str(self.fallback_activation.get("reason") or "").lower()
        text = str(candidate_text or "").strip().lower()
        return bool(
            self.fallback_activation
            and "timeout" in fallback_reason
            and ("timed out" in text or "timeout" in text)
        )

    def _impact_for_issue(self, issue: str) -> ImpactSimulation:
        destructive = issue in {"fallback overwrite", "middleware truncation", "frontend render mismatch"}
        routing = issue in {"wrong agent routing", "model timeout", "fallback overwrite"}
        return ImpactSimulation(
            would_affect_state=False,
            would_affect_memory=False,
            would_affect_files=False,
            would_affect_config=destructive,
            would_affect_routing=routing,
            would_affect_frontend=issue == "frontend render mismatch",
            would_affect_user_visible_output=True,
            could_create_latency=issue in {"model timeout", "middleware truncation"},
            could_create_loops=issue in {"fallback overwrite", "wrong agent routing"},
            could_create_cascading_failures=destructive,
            could_corrupt_logs=False,
            could_break_sessions=False,
            could_create_false_positives=issue == "template leakage",
            read_only_inspection_sufficient=True,
            sandbox_reproducible=True,
            minimum_diagnostic_action="Inspect trace events and replay the request in read-only mode.",
        )

    def _debug_intent_for_issue(self, issue: str) -> DebugIntent:
        return DebugIntent(
            suspected_subsystem=issue,
            reason_debugging_may_be_needed=f"Trace reports {issue}.",
            what_would_be_inspected=[
                "request timeline",
                "selected route",
                "selected agent",
                "model/provider metadata",
                "output mutation chain",
                "frontend delivery status",
            ],
            what_could_be_modified=[],
            risk_level="high" if issue in {"fallback overwrite", "middleware truncation", "frontend render mismatch", "wrong agent routing"} else "medium",
            expected_benefit="Pinpoint the exact layer that changed or lost the response.",
            possible_damage="A stateful debug step could hide the true defect or create a feedback loop.",
            read_only_option="Inspect the trace file, event log, and runtime summary only.",
            sandbox_option="Replay the same request in an isolated, read-only sandbox.",
            rollback_plan="Do not modify runtime state unless a minimal reproducer and rollback path are available.",
            verification_plan="Re-run the request, compare raw and final lengths, and confirm the UI trace panel matches the stored trace.",
        )

    def inspect_release(self, candidate_text: str, *, frontend_check: bool = False) -> dict[str, Any]:
        issues = self._evaluate_issues(candidate_text, frontend_check=frontend_check)
        severe = {"empty output", "only done", "completion marker leakage", "fallback overwrite", "wrong agent routing", "model timeout"}
        if issues:
            self.warnings.extend([issue for issue in issues if issue not in self.warnings])
        if self.empty_output_detected and self.recovery_success and "empty output" not in issues:
            self.release_decision = "allow_with_warning"
        candidate_lower = str(candidate_text or "").lower()
        if (
            self.empty_output_detected
            and self.release_decision == "block"
            and candidate_lower
            and "empty runtime response" in candidate_lower
        ):
            fallback = candidate_text or self.safe_empty_output_text()
            self.record_event(
                "response_blocked",
                source="runtime_guardian",
                payload={
                    "reason": self.empty_output_source or "empty output",
                    "issues": issues or ["empty output"],
                },
            )
            self.record_event(
                "fallback_blocked",
                source="runtime_guardian",
                payload={
                    "reason": self.empty_output_source or "empty output",
                    "fallback_length": len(fallback),
                    "fallback_allowed": False,
                },
            )
            self.root_cause_guess = self.root_cause_guess or self.empty_output_source or "empty output"
            self.confidence_score = max(0.2, 1.0 - (0.12 * max(1, len(issues))))
            return {
                "decision": "block",
                "reason": self.empty_output_source or "empty output",
                "issues": issues or ["empty output"],
                "fallback_text": fallback,
                "confidence_score": round(self.confidence_score, 3),
                "debug_intent": dict(self.debug_intent),
                "impact_simulation": dict(self.impact_simulation),
            }
        if issues:
            root = issues[0]
            self.root_cause_guess = self.root_cause_guess or root
            self.confidence_score = max(0.2, 1.0 - (0.12 * len(issues)))
            if root == "model timeout" and self._is_transparent_timeout_fallback(candidate_text):
                self.release_decision = "allow_with_warning"
                self.record_event(
                    "response_released",
                    source="runtime_guardian",
                    payload={"decision": "allow_with_warning", "issues": issues},
                )
                return {
                    "decision": "allow_with_warning",
                    "reason": root,
                    "issues": issues,
                    "fallback_text": "",
                    "confidence_score": round(self.confidence_score, 3),
                    "debug_intent": dict(self.debug_intent),
                    "impact_simulation": dict(self.impact_simulation),
                }
            if root in severe or "template leakage" in issues:
                self.release_decision = "block"
                if not self.debug_intent:
                    debug = self._debug_intent_for_issue(root)
                    self.debug_intent = debug.to_dict()
                    self.impact_simulation = self._impact_for_issue(root).to_dict()
                self.record_event("response_blocked", source="runtime_guardian", payload={"reason": root, "issues": issues})
                self.record_error(f"release blocked: {root}", source="runtime_guardian")
                return {
                    "decision": "block",
                    "reason": root,
                    "issues": issues,
                    "fallback_text": self.safe_fallback_text(root, candidate_text=candidate_text),
                    "confidence_score": round(self.confidence_score, 3),
                    "debug_intent": dict(self.debug_intent),
                    "impact_simulation": dict(self.impact_simulation),
                }
            self.release_decision = "allow_with_warning"
            self.record_event("response_released", source="runtime_guardian", payload={"decision": "allow_with_warning", "issues": issues})
            return {
                "decision": "allow_with_warning",
                "reason": root,
                "issues": issues,
                "fallback_text": "",
                "confidence_score": round(self.confidence_score, 3),
                "debug_intent": dict(self.debug_intent),
                "impact_simulation": dict(self.impact_simulation),
            }
        if self.empty_output_detected and self.recovery_success:
            self.release_decision = "allow_with_warning"
            self.confidence_score = max(self.confidence_score, 0.88)
            self.record_event("response_released", source="runtime_guardian", payload={"decision": "allow_with_warning", "issues": ["empty output recovered"]})
            return {
                "decision": "allow_with_warning",
                "reason": self.empty_output_source or "empty output recovered",
                "issues": ["empty output recovered"],
                "fallback_text": "",
                "confidence_score": round(self.confidence_score, 3),
                "debug_intent": dict(self.debug_intent),
                "impact_simulation": dict(self.impact_simulation),
            }
        self.release_decision = "allow"
        self.confidence_score = max(self.confidence_score, 0.95)
        self.record_event("response_released", source="runtime_guardian", payload={"decision": "allow"})
        return {
            "decision": "allow",
            "reason": "",
            "issues": [],
            "fallback_text": "",
            "confidence_score": round(self.confidence_score, 3),
            "debug_intent": dict(self.debug_intent),
            "impact_simulation": dict(self.impact_simulation),
        }

    def register_frontend_delivery(self, *, status: str, rendered_length: int = 0, rendered_preview: str = "", message_id: str = "") -> None:
        self.frontend_delivery_status.update({
            "status": status,
            "rendered_length": int(rendered_length or 0),
            "rendered_preview": _preview(rendered_preview),
            "message_id": message_id,
            "timestamp_ms": _now_ms(),
        })
        if self.final_output_length and self.final_output_length != int(rendered_length or 0):
            self.record_warning("frontend render mismatch")
            self.root_cause_guess = self.root_cause_guess or "frontend render mismatch"
        self.record_event("frontend_rendered", source="frontend", payload=dict(self.frontend_delivery_status))

    def finalize(self, *, candidate_text: str = "", force: bool = False) -> dict[str, Any]:
        if self._finalized and not force:
            return self.to_dict()
        if candidate_text:
            self.final_output_length = len(candidate_text)
            self.final_output_preview = _preview(candidate_text)
        self.finalized_at_ms = _now_ms()
        self._finalized = True
        self._touch()
        _write_trace_file(self)
        return self.to_dict()

    def safe_empty_output_text(self) -> str:
        return f"ShiftForge detected an empty runtime response and blocked it. Trace ID: {self.trace_id}."

    def safe_fallback_text(self, reason: str = "", *, candidate_text: str = "") -> str:
        reason_lower = str(reason or "").lower()
        candidate_lower = str(candidate_text or "").lower()
        if (
            "empty" in reason_lower
            or "done" in reason_lower
            or "completion marker" in reason_lower
            or "empty runtime response" in candidate_lower
            or "blocked it" in candidate_lower
        ):
            return self.safe_empty_output_text()
        suffix = f" Reason: {reason}." if reason else ""
        return f"ShiftForge blocked this response because the output was not safe to release.{suffix} Trace ID: {self.trace_id}."


def _get_or_create(trace_id: str, **seed: Any) -> ShiftForgeTrace:
    trace_id = trace_id or f"sftr_{uuid.uuid4().hex[:12]}"
    with _LOCK:
        trace = _TRACES.get(trace_id)
        if trace is None:
            trace = ShiftForgeTrace(trace_id=trace_id, request_id=seed.get("request_id", trace_id))
            _TRACES[trace_id] = trace
            _ORDER.append(trace_id)
        for key, value in seed.items():
            if value is None:
                continue
            if hasattr(trace, key):
                current = getattr(trace, key)
                if isinstance(current, dict) and isinstance(value, Mapping):
                    current.update(dict(value))
                elif isinstance(current, list) and isinstance(value, list):
                    current.extend(value)
                elif key == "user_input_metadata" and isinstance(value, Mapping):
                    current.update(dict(value))
                elif not current:
                    setattr(trace, key, value)
        trace._touch()
        return trace


def begin_trace(
    *,
    trace_id: str = "",
    request_id: str = "",
    session_id: str = "",
    client_type: str = "",
    surface: str = "",
    user_input_metadata: Mapping[str, Any] | None = None,
    runtime_context: Mapping[str, Any] | None = None,
    prompt_construction_metadata: Mapping[str, Any] | None = None,
) -> ShiftForgeTrace:
    trace_id = trace_id or request_id or f"sftr_{uuid.uuid4().hex[:12]}"
    trace = _get_or_create(
        trace_id,
        request_id=request_id or trace_id,
        session_id=session_id,
        client_type=client_type,
        surface=surface,
        user_input_metadata=dict(user_input_metadata or {}),
        runtime_context=dict(runtime_context or {}),
        prompt_construction_metadata=dict(prompt_construction_metadata or {}),
    )
    if _xray_new_trace is not None:
        try:
            _xray_new_trace(trace_id=trace.trace_id, session_id=session_id, extra={"surface": surface, "client_type": client_type})
        except Exception:
            pass
    trace.record_event(
        "request_received",
        source="trace.bootstrap",
        payload={
            "request_id": trace.request_id,
            "session_id": trace.session_id,
            "client_type": trace.client_type,
            "surface": trace.surface,
            "user_input_metadata": dict(trace.user_input_metadata),
        },
    )
    return trace


def get_trace(trace_id: str) -> dict[str, Any]:
    with _LOCK:
        trace = _TRACES.get(trace_id)
        if trace is None:
            loaded = _load_trace_file(trace_id)
            if loaded:
                return loaded
            return {}
        return trace.to_dict()


def get_trace_object(trace_id: str) -> ShiftForgeTrace | None:
    with _LOCK:
        return _TRACES.get(trace_id)


def get_recent_traces(n: int = 20) -> list[dict[str, Any]]:
    with _LOCK:
        ids = _ORDER[-max(1, int(n)):][::-1]
        return [trace.public_summary() for trace_id in ids if (trace := _TRACES.get(trace_id))]


def record_trace_event(trace_id: str, stage: str, *, source: str = "", payload: Mapping[str, Any] | None = None, **detail: Any) -> dict[str, Any]:
    trace = _get_or_create(trace_id)
    event = trace.record_event(stage, source=source, payload=payload, **detail)
    return event.to_dict()


def record_trace_mutation(
    trace_id: str,
    *,
    layer: str,
    step: str,
    before_text: str,
    after_text: str,
    reason: str,
    error: str = "",
) -> dict[str, Any]:
    trace = _get_or_create(trace_id)
    return trace.record_mutation(
        layer=layer,
        step=step,
        before_text=before_text,
        after_text=after_text,
        reason=reason,
        error=error,
    ).to_dict()


def register_frontend_delivery(trace_id: str, *, status: str, rendered_length: int = 0, rendered_preview: str = "", message_id: str = "") -> dict[str, Any]:
    trace = _get_or_create(trace_id)
    trace.register_frontend_delivery(status=status, rendered_length=rendered_length, rendered_preview=rendered_preview, message_id=message_id)
    return trace.public_summary()


def guardian_decision(trace_id: str, candidate_text: str, *, frontend_check: bool = False) -> dict[str, Any]:
    trace = _get_or_create(trace_id)
    return trace.inspect_release(candidate_text, frontend_check=frontend_check)


def finalize_trace(trace_id: str, *, candidate_text: str = "") -> dict[str, Any]:
    trace = _get_or_create(trace_id)
    trace.finalize(candidate_text=candidate_text)
    return trace.to_dict()


def get_visibility_status() -> dict[str, Any]:
    with _LOCK:
        latest = _TRACES[_ORDER[-1]].public_summary() if _ORDER else {}
        events_path = str(_EVENTS_PATH)
        traces_dir = str(_TRACES_DIR)
        event_count = 0
        try:
            if _EVENTS_PATH.exists():
                with _EVENTS_PATH.open("r", encoding="utf-8", errors="ignore") as handle:
                    event_count = sum(1 for line in handle if line.strip())
        except Exception:
            event_count = 0
        return {
            "status": "available",
            "read_only": True,
            "trace_count": len(_TRACES),
            "event_count": event_count,
            "latest_trace": latest,
            "events_path": events_path,
            "traces_path": traces_dir,
            "backend_visible": True,
            "guardian": {
                "allow": "allow",
                "allow_with_warning": "allow_with_warning",
                "block": "block",
            },
            "debug_council": {
                "read_only_option": "Inspect trace logs and metadata only",
                "sandbox_option": "Replay in a sandbox",
            },
        }


def reset_for_test() -> None:
    with _LOCK:
        _TRACES.clear()
        _ORDER.clear()
    try:
        if _EVENTS_PATH.exists():
            _EVENTS_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass


__all__ = [
    "ShiftForgeTrace",
    "TraceEvent",
    "TraceMutation",
    "DebugIntent",
    "ImpactSimulation",
    "begin_trace",
    "get_trace",
    "get_trace_object",
    "get_recent_traces",
    "record_trace_event",
    "record_trace_mutation",
    "register_frontend_delivery",
    "guardian_decision",
    "finalize_trace",
    "get_visibility_status",
    "reset_for_test",
]
