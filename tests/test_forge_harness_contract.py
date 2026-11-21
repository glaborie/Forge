from __future__ import annotations

import httpx

from forge_harness import Case, Conformance, Runner, Spec, Target

SPEC = {
    "paths": {
        "/v1/chat/completions": {
            "post": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Completion"}
                            }
                        }
                    },
                    "422": {"description": "validation"},
                    "4XX": {"description": "client error, unspecified body"},
                }
            }
        },
        "/bare": {"post": {"responses": {"200": {"description": "no schema"}}}},
    },
    "components": {
        "schemas": {
            "Completion": {
                "type": "object",
                "required": ["choices"],
                "properties": {
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["message"],
                            "properties": {"message": {"type": "object"}},
                        },
                    }
                },
            }
        }
    },
}


def check(body: object, status: int = 200, path: str = "/v1/chat/completions") -> Conformance:
    return Spec(SPEC).check(path=path, method="post", status=status, body=body)


def test_conformant_body() -> None:
    result = check({"choices": [{"message": {"content": "hi"}}]})
    assert result.verdict == "conformant"


def test_undeclared_status() -> None:
    # 5XX is not declared and the fixture has no wildcard for it.
    result = check({"detail": "boom"}, status=500)
    assert result.verdict == "undeclared_status"
    assert "500" in result.detail


def test_wildcard_status_is_declared_but_unspecified() -> None:
    result = check({"error": "forbidden"}, status=403)
    assert result.verdict == "unspecified"


def test_schema_violation_names_a_pointer() -> None:
    result = check({"choices": "not-an-array"})
    assert result.verdict == "schema_violation"
    assert result.detail.startswith("choices")


def test_missing_required_field_is_a_violation() -> None:
    assert check({}).verdict == "schema_violation"


def test_no_schema_is_unspecified_not_conformant() -> None:
    assert check({}, path="/bare").verdict == "unspecified"


def test_strict_mode_treats_unspecified_as_failure() -> None:
    strict = Spec(SPEC, strict=True)
    assert (
        strict.check(path="/bare", method="post", status=200, body={}).verdict == "schema_violation"
    )


def test_unknown_path_is_undeclared() -> None:
    assert check({}, path="/nope").verdict == "undeclared_status"


def test_broken_reference_does_not_crash() -> None:
    spec = Spec(
        {
            "paths": {
                "/x": {
                    "post": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Missing"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    )
    assert spec.check(path="/x", method="post", status=200, body={}).verdict in {
        "unspecified",
        "conformant",
    }


def test_runner_records_conformance_per_case() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    target = Target("http://t.test", model="m", transport=httpx.MockTransport(handler))
    run = Runner(spec=Spec(SPEC)).run([Case(id="a", prompt="hi")], target)

    assert run.records[0].conformance == "conformant"
    assert run.summary()["by_conformance"] == {"conformant": 1}


def test_runner_without_a_spec_records_nothing() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    run = Runner().run(
        [Case(id="a", prompt="hi")], Target("http://t.test", model="m", transport=transport)
    )

    assert run.records[0].conformance is None
    assert run.summary()["by_conformance"] == {}


def test_a_type_only_schema_is_unspecified_not_conformant() -> None:
    """`{"type": "object"}` accepts anything, so it promises nothing."""
    spec = Spec(
        {
            "paths": {
                "/x": {
                    "post": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object", "description": "anything"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    )

    assert spec.check(path="/x", method="post", status=200, body={"a": 1}).verdict == "unspecified"


def test_strict_mode_promotes_a_type_only_schema_to_a_violation() -> None:
    spec = Spec(
        {
            "paths": {
                "/x": {
                    "post": {
                        "responses": {
                            "200": {"content": {"application/json": {"schema": {"type": "object"}}}}
                        }
                    }
                }
            }
        },
        strict=True,
    )

    assert spec.check(path="/x", method="post", status=200, body={}).verdict == "schema_violation"
