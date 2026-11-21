"""Check what the target returned against what its own OpenAPI document promises.

Forge reports conformance; it does not grade the document. When a status
declares no schema the verdict is `unspecified`, which is deliberately not the
same as `conformant` — most of the surface this harness talks to is still
undescribed, and saying so is the honest result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import jsonschema

Verdict = Literal["conformant", "undeclared_status", "schema_violation", "unspecified"]


@dataclass(frozen=True)
class Conformance:
    verdict: Verdict
    detail: str = ""


# Keys that say something about a body's shape. A schema with none of them only
# restates the JSON type, which every JSON body satisfies.
_INFORMATIVE = frozenset(
    {"properties", "required", "items", "anyOf", "oneOf", "allOf", "patternProperties"}
)


def _constrains(schema: Any) -> bool:
    return isinstance(schema, dict) and bool(_INFORMATIVE & set(schema))


class Spec:
    """A loaded OpenAPI document, resolved just enough to validate responses."""

    def __init__(self, document: dict[str, Any], *, strict: bool = False) -> None:
        self.document = document
        self.strict = strict
        self._schemas: dict[str, Any] = document.get("components", {}).get("schemas", {})

    @classmethod
    def from_url(cls, url: str, *, strict: bool = False, timeout: float = 10.0) -> Spec:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        return cls(response.json(), strict=strict)

    @classmethod
    def from_file(cls, path: str, *, strict: bool = False) -> Spec:
        with open(path, encoding="utf-8") as handle:
            return cls(json.load(handle), strict=strict)

    def check(self, *, path: str, method: str, status: int, body: Any) -> Conformance:
        operation = self._operation(path, method)
        if operation is None:
            return Conformance(
                "undeclared_status", f"{method.upper()} {path} is not in the document"
            )

        responses = operation.get("responses", {})
        declared = self._match_status(responses, status)
        if declared is None:
            return Conformance(
                "undeclared_status",
                f"{method.upper()} {path} declares {sorted(responses)}; got {status}",
            )

        schema = declared.get("content", {}).get("application/json", {}).get("schema")
        if not schema:
            if self.strict:
                return Conformance(
                    "schema_violation", f"{status} declares no schema for {path} (strict)"
                )
            return Conformance("unspecified", f"{status} declares no schema for {path}")

        resolved = self._resolve(schema)
        if not _constrains(resolved):
            # `{"type": "object"}` validates anything. Calling that conformant
            # would turn an undescribed body into a pass.
            if self.strict:
                return Conformance(
                    "schema_violation", f"{status} schema for {path} constrains nothing (strict)"
                )
            return Conformance("unspecified", f"{status} schema for {path} constrains nothing")

        try:
            jsonschema.validate(instance=body, schema=resolved)
        except jsonschema.ValidationError as exc:
            pointer = "/".join(str(part) for part in exc.absolute_path) or "<body>"
            return Conformance("schema_violation", f"{pointer}: {exc.message}")
        except jsonschema.SchemaError as exc:  # the document itself is broken
            return Conformance("unspecified", f"unusable schema: {exc.message}")
        return Conformance("conformant")

    def _operation(self, path: str, method: str) -> dict[str, Any] | None:
        entry = self.document.get("paths", {}).get(path)
        if not isinstance(entry, dict):
            return None
        operation = entry.get(method.lower())
        return operation if isinstance(operation, dict) else None

    @staticmethod
    def _match_status(responses: dict[str, Any], status: int) -> dict[str, Any] | None:
        for key in (str(status), f"{status // 100}XX", f"{status // 100}xx", "default"):
            if key in responses:
                return responses[key]
        return None

    def _resolve(self, node: Any, depth: int = 0) -> Any:
        """Follow local `$ref`s. Anything exotic is left alone for jsonschema to judge."""
        if depth > 20 or not isinstance(node, dict):
            return node
        if "$ref" in node and isinstance(node["$ref"], str):
            reference = node["$ref"]
            if reference.startswith("#/components/schemas/"):
                target = self._schemas.get(reference.rsplit("/", 1)[-1])
                return self._resolve(target, depth + 1) if target is not None else {}
            return {}
        return {key: self._resolve(value, depth + 1) for key, value in node.items()}
