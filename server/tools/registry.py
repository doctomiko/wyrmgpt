from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any, Callable, cast

from ..config import ToolConfig, get_prompt, load_tool_config
from .base import ToolExecutionContext, ToolInvocationRequest, ToolResult, ToolSpec

_TOOL_BLOCK_RE = re.compile(r"```tool\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_BARE_TOOL_JSON_RE = re.compile(
    r'(\{\s*"tool"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\})',
    re.DOTALL,
)

_DEFAULT_TOOL_PROMPT = """TOOL USE

You may request a tool by emitting exactly one fenced JSON block with language tag `tool`.
If you need a tool, reply with the tool block only.
Do not explain the tool call before or after it.

Example:
```tool
{"tool":"artifact.read_section","arguments":{"artifact_id":"abc123","section_ref":"Section V"}}
```

When to use tools:
* Use artifact.start_session when the user wants to begin reading a long artifact in order.
* Use artifact.read_next when the user says to continue, resume, or read the next step in an active reading session.
* Use artifact.resolve_section when the user names a section, chapter, page, or heading and you need the chunk range.
* Use artifact.read_section when the user explicitly wants a section read or after resolving a section.
* Use artifact.update_session_notes only after a section has been read and you are storing short retained notes.

Rules:
* Only use tools listed below.
* Do not invent tool results.
* Do not claim to have read a section unless its text is present in context or returned by a tool.
* Artifact IDs appear in ARTIFACT SUMMARY, ARTIFACT INDEX, FILE ARTIFACT, or ARTIFACT READING PLAN blocks when available.
* The scaffold may fill context-only arguments like conversation_id automatically; do not invent random IDs.
* After tool results are returned, continue with a normal answer unless another tool is still clearly required.

Allowed tools:
{{ALLOWED_TOOLS}}

Enabled tool details:
{{TOOL_DETAILS}}
"""


class ToolRegistry:
    def __init__(self, *, specs: dict[str, ToolSpec], executors: dict[str, Callable[[dict[str, Any], ToolExecutionContext], ToolResult]]):
        self._specs = dict(specs)
        self._executors = dict(executors)

    @property
    def specs(self) -> dict[str, ToolSpec]:
        return dict(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get((name or "").strip())

    def list_enabled(self) -> list[ToolSpec]:
        return [spec for spec in self._specs.values() if spec.enabled]

    def execute(self, request: ToolInvocationRequest, *, ctx: ToolExecutionContext | None = None) -> ToolResult:
        name = (request.tool or "").strip()
        spec = self.get(name)
        if not spec:
            return ToolResult(ok=False, tool=name, error=f"unknown tool: {name}")
        if not spec.enabled:
            return ToolResult(ok=False, tool=name, error=f"tool disabled: {name}")

        exec_ctx = ctx or ToolExecutionContext()
        raw_args = dict(request.arguments or {})
        if "conversation_id" not in raw_args and exec_ctx.conversation_id:
            raw_args["conversation_id"] = exec_ctx.conversation_id
        if "project_id" not in raw_args and exec_ctx.project_id is not None:
            raw_args["project_id"] = exec_ctx.project_id

        validated_args = _validate_args_against_schema(raw_args, spec.input_schema or {"type": "object"})
        executor = self._executors.get(name)
        if not executor:
            return ToolResult(ok=False, tool=name, error=f"tool executor missing: {name}")
        return executor(validated_args, ctx or ToolExecutionContext())

    def build_system_prompt_block(self) -> str:
        prompt_template = get_prompt(
            _DEFAULT_TOOL_PROMPT,
            "./prompts/_tool_use.txt",
            cfg_default="built-in tool prompt",
            cfg_filepath="./prompts/_tool_use.txt",
        ).strip()

        enabled_specs = sorted(self.list_enabled(), key=lambda s: s.name)
        allowed_tools = "\n".join(f"* {spec.name}" for spec in enabled_specs) or "* (none)"
        tool_details = "\n\n".join(_render_tool_detail(spec) for spec in enabled_specs) or "- (none)"

        return (
            prompt_template
            .replace("{{ALLOWED_TOOLS}}", allowed_tools)
            .replace("{{TOOL_DETAILS}}", tool_details)
            .strip()
        )

    def extract_requests_from_text(self, text: str) -> list[ToolInvocationRequest]:
        out: list[ToolInvocationRequest] = []
        seen: set[tuple[str, str]] = set()
        raw_text = text or ""

        blocks: list[str] = []
        for match in _TOOL_BLOCK_RE.finditer(raw_text):
            raw = (match.group(1) or "").strip()
            if raw:
                blocks.append(raw)

        if not blocks:
            for match in _BARE_TOOL_JSON_RE.finditer(raw_text):
                raw = (match.group(1) or "").strip()
                if raw:
                    blocks.append(raw)

        for raw in blocks:
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            tool_name = (payload.get("tool") or payload.get("name") or "").strip()
            args = payload.get("arguments")
            if not tool_name:
                continue
            if args is None:
                args = {}
            if not isinstance(args, dict):
                continue
            key = (tool_name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            out.append(ToolInvocationRequest(tool=tool_name, arguments=args))
        return out


def _example_args_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    out: dict[str, Any] = {}
    for name in required:
        prop = props.get(name) or {}
        ptype = prop.get("type")
        enum = prop.get("enum")
        if enum:
            out[name] = enum[0]
        elif ptype == "integer":
            out[name] = max(int(prop.get("minimum", 1)), 1)
        elif ptype == "boolean":
            out[name] = bool(prop.get("default", True))
        else:
            if name == "artifact_id":
                out[name] = "<artifact_id_from_context>"
            elif name == "conversation_id":
                continue
            elif name == "section_ref":
                out[name] = "Section V"
            else:
                out[name] = f"<{name}>"
    return out


def _render_tool_detail(spec: ToolSpec) -> str:
    example = {"tool": spec.name, "arguments": _example_args_from_schema(spec.input_schema or {"type": "object"})}
    lines = [
        f"- {spec.name}",
        f"  Purpose: {(spec.system_usage or spec.description or '').strip()}",
        "  Call shape:",
        f"  ```tool  {json.dumps(example, ensure_ascii=False)}  ```",
    ]
    return "\n".join(lines)


def _load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _module_name_from_catalog(module_value: str) -> str:
    raw = (module_value or "").strip()
    if not raw:
        raise ValueError("tool module is required")
    if raw.startswith("server.tools."):
        return raw
    if "." not in raw:
        return f"server.tools.{raw}"
    return raw


def _load_tool_module(module_name: str):
    return importlib.import_module(module_name)


def _coerce_tool_spec(name: str, meta: dict[str, Any], module) -> ToolSpec:
    module_spec = getattr(module, "TOOL_SPEC", None)
    if isinstance(module_spec, ToolSpec):
        return ToolSpec(
            name=name,
            description=(meta.get("description") or module_spec.description or "").strip(),
            input_schema=meta.get("input_schema") or module_spec.input_schema,
            system_usage=(meta.get("system_usage") or module_spec.system_usage or "").strip(),
            display_name=(meta.get("display_name") or module_spec.display_name or "").strip(),
            enabled=bool(meta.get("enabled", module_spec.enabled)),
            tags=tuple(meta.get("tags") or module_spec.tags or ()),
        )

    return ToolSpec(
        name=name,
        description=(meta.get("description") or "").strip(),
        input_schema=meta.get("input_schema") or {"type": "object"},
        system_usage=(meta.get("system_usage") or "").strip(),
        display_name=(meta.get("display_name") or "").strip(),
        enabled=bool(meta.get("enabled", True)),
        tags=tuple(meta.get("tags") or ()),
    )


def load_tool_registry(tool_cfg: ToolConfig | None = None) -> ToolRegistry:
    cfg = tool_cfg or load_tool_config()
    catalog_path = Path(cfg.catalog_file)
    if not catalog_path.is_absolute():
        catalog_path = Path(__file__).resolve().parents[2] / catalog_path

    catalog = _load_catalog(catalog_path)
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[[dict[str, Any], ToolExecutionContext], ToolResult]] = {}

    for name, meta in catalog.items():
        if not isinstance(meta, dict):
            continue
        module_name = _module_name_from_catalog(str(meta.get("module") or ""))
        module = _load_tool_module(module_name)

        executor_obj = getattr(module, "execute", None)
        if not callable(executor_obj):
            raise TypeError(f"tool module {module_name} missing execute(arguments, ctx)")
        executor = cast(
            Callable[[dict[str, Any], ToolExecutionContext], ToolResult],
            executor_obj,
        )
        if not callable(executor):
            raise TypeError(f"tool module {module_name} missing execute(arguments, ctx)")
        spec = _coerce_tool_spec(name, meta, module)
        if not cfg.enabled:
            spec = ToolSpec(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                system_usage=spec.system_usage,
                display_name=spec.display_name,
                enabled=False,
                tags=spec.tags,
            )
        if name is not None:
            specs[name] = spec
            executors[name] = executor

    return ToolRegistry(specs=specs, executors=executors)


def _validate_args_against_schema(value: Any, schema: dict[str, Any], *, path: str = "arguments") -> Any:
    schema_type = schema.get("type", "object")
    if isinstance(schema_type, list):
        last_error: Exception | None = None
        for variant in schema_type:
            try:
                return _validate_args_against_schema(value, {**schema, "type": variant}, path=path)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return value

    if schema_type == "object":
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise TypeError(f"{path} must be an object")
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        out: dict[str, Any] = {}
        for key, prop_schema in props.items():
            if key in value:
                out[key] = _validate_args_against_schema(value[key], prop_schema, path=f"{path}.{key}")
            elif "default" in prop_schema:
                out[key] = prop_schema["default"]
            elif key in required:
                raise ValueError(f"missing required argument: {path}.{key}")
        for key, raw in value.items():
            if key not in props:
                out[key] = raw
        return out

    if schema_type == "string":
        if value is None:
            value = ""
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        min_len = schema.get("minLength")
        if min_len is not None and len(value) < int(min_len):
            raise ValueError(f"{path} must be at least {int(min_len)} characters")
        enum = schema.get("enum")
        if enum and value not in enum:
            raise ValueError(f"{path} must be one of: {', '.join(str(x) for x in enum)}")
        return value

    if schema_type == "integer":
        try:
            ivalue = int(value)
        except Exception as exc:
            raise TypeError(f"{path} must be an integer") from exc
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and ivalue < int(minimum):
            raise ValueError(f"{path} must be >= {int(minimum)}")
        if maximum is not None and ivalue > int(maximum):
            raise ValueError(f"{path} must be <= {int(maximum)}")
        return ivalue

    if schema_type == "number":
        try:
            fvalue = float(value)
        except Exception as exc:
            raise TypeError(f"{path} must be a number") from exc
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and fvalue < float(minimum):
            raise ValueError(f"{path} must be >= {float(minimum)}")
        if maximum is not None and fvalue > float(maximum):
            raise ValueError(f"{path} must be <= {float(maximum)}")
        return fvalue

    if schema_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    if schema_type == "array":
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError(f"{path} must be an array")
        item_schema = schema.get("items") or {}
        return [
            _validate_args_against_schema(item, item_schema, path=f"{path}[{idx}]")
            for idx, item in enumerate(value)
        ]

    return value
