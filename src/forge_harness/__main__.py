"""Live runs against a target: one command instead of a pasted snippet.

    uv run python -m forge_harness --target http://localhost:8000 --corpus harness/corpus/injection.json

Credentials come from `.env` through `BASTION_USER` / `BASTION_PASSWORD`, or from
`--token` when you already hold a bearer token. This is the same `Runner` the
tests use; nothing here is a second implementation.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

import httpx

from forge_audit import AuditLog

from . import Case, Runner, Spec, Target, load_corpus
from .auth import grants_from_env
from .tracing import init_tracing

DEFAULT_CORPUS = "harness/corpus/injection.json"
Credential = str | Callable[[], str]


def sends_model(path: str) -> bool:
    """/v1/chat forbids a `model` field; the OpenAI-compatible path requires one."""
    return path.rstrip("/").endswith("completions")


def resolve_grants(roles: list[str], token: str | None) -> dict[str, Credential]:
    if token:
        return {role: token for role in roles}
    grants = grants_from_env()
    if not grants:
        raise SystemExit(
            "error: no credentials. Set BASTION_USER/BASTION_PASSWORD in .env, or pass --token."
        )
    chosen = grants if roles == ["all"] else {r: g for r, g in grants.items() if r in roles}
    if not chosen:
        raise SystemExit(f"error: no grant for {', '.join(roles)}; have: {', '.join(grants)}")
    return dict(chosen)


def materialise(credential: Credential) -> str:
    return credential() if callable(credential) else credential


def build_cases(family: str, corpus: str, token: str) -> list[Case]:
    if family == "corpus":
        return load_corpus(corpus)
    if family == "credentials":
        from .chaos import credential_cases

        return credential_cases(token)
    from .chaos import conversation_cases

    return conversation_cases()


def build_identities(
    *, target: str, path: str, grants: dict[str, Credential], transport: httpx.BaseTransport | None
) -> dict[str, Target]:
    return {
        role: Target(
            target,
            path=path,
            token=credential,
            transport=transport,
            send_model=sends_model(path),
        )
        for role, credential in grants.items()
    }


def main(argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge_harness", description="Run a labelled corpus against a live target."
    )
    parser.add_argument("--target", required=True, help="base URL, e.g. http://localhost:8000")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--path", default="/v1/chat/completions")
    parser.add_argument("--family", choices=["corpus", "credentials", "history"], default="corpus")
    parser.add_argument("--roles", default="admin", help="'all' or a comma-separated list")
    parser.add_argument("--token", default=None, help="bearer token instead of .env grants")
    parser.add_argument("--spec", default=None, help="OpenAPI URL for conformance verdicts")
    parser.add_argument("--audit", default=None, help="write the hash-chained audit log here")
    parser.add_argument("--report", default=None, help="write the JSON run report here")
    parser.add_argument("--tracing", action="store_true", help="export spans to the collector")
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args(argv)

    roles = [role.strip() for role in args.roles.split(",") if role.strip()]
    grants = resolve_grants(roles, args.token)
    identities = build_identities(
        target=args.target, path=args.path, grants=grants, transport=transport
    )
    one_grant = next(iter(grants.values()))
    cases = build_cases(args.family, args.corpus, materialise(one_grant))

    runner = Runner(
        audit=AuditLog(args.audit) if args.audit else None,
        tracer=init_tracing() if args.tracing else None,
        spec=Spec.from_url(args.spec) if args.spec else None,
    )
    first = next(iter(identities.values()))
    run = runner.run(cases, first) if len(identities) == 1 else runner.run_matrix(cases, identities)

    summary = run.summary()
    print(f"target   {args.target}  path {args.path}  family {args.family}")
    print(f"roles    {', '.join(identities)}   cases {summary['cases']}")
    print(f"verdict  {summary['by_verdict']}")
    if summary["by_conformance"]:
        print(f"contract {summary['by_conformance']}")
    findings = run.findings()
    print(f"findings {summary['by_severity']}")
    for finding in findings:
        print(f"  {finding.severity:8} {finding.owasp} {finding.case_id:18} {finding.verdict}")

    if args.report:
        run.to_json(args.report)
        print(f"report   {args.report}")

    return 1 if (args.fail_on_findings and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
