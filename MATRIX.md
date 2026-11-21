# AgentGuard AI Reliability Matrix

**Version 1.0** · Q2 2026 · Vendor-neutral framework for measuring, enforcing, and governing AI system reliability.

This document defines the four reliability dimensions used across AgentGuard (Functional, Security, Operational, Temporal) and maps each to the standards the platform is designed to satisfy. It is the reference for the `Dimension` and `Standard` fields in the GitHub project and for the control-to-standard evidence used in compliance reporting.

---

## 1. Purpose

AgentGuard exists to make AI reliability measurable and enforceable rather than aspirational. This matrix provides:

- A **taxonomy** of reliability across four orthogonal dimensions.
- A **standards mapping** between each dimension and NIST, ISO/IEC, OWASP, CSA, ENISA, and the EU AI Act.
- A **traceability layer** from framework requirement → AgentGuard control → backlog item → evidence artifact.

The matrix is tool-agnostic and provider-agnostic. It does not prescribe a model, a vendor, or a deployment model; it prescribes what must be measured and which standards satisfy the measurement.

---

## 2. The Four Reliability Dimensions

| Dimension | Core question | Failure modes | Primary mitigations |
| :--- | :--- | :--- | :--- |
| **Functional** | Did the AI produce the right answer? | Hallucination, context loss, reasoning error, faithfulness failure | LLM-as-judge, golden datasets, statistical confidence |
| **Security** | Did the AI resist adversarial manipulation? | Prompt injection, jailbreak, PII leakage, tool-call injection, excessive agency | Input/output guardrails, adversarial testing, tool-call authorization |
| **Operational** | Did the AI behave predictably and efficiently? | Latency spikes, cost explosion, rate-limit exhaustion, cascading failures | OTel traces, budget controls, circuit breakers |
| **Temporal** | Does reliability hold over time? | Model drift, data drift, degradation after updates, regulatory drift | Drift detection, canary + auto-rollback, continuous regression |

These dimensions are orthogonal but interdependent. A functionally accurate system that drifts within days is not reliable; a secure system that cannot meet latency SLOs is not usable. The matrix treats reliability as the *conjunction* of the four, not the average.

---

## 3. Dimension Definitions

### 3.1 Functional Reliability

The system produces outputs that are factually correct, contextually appropriate, and faithful to the user's intent.

Required evaluation signals:

- **Hallucination rate** — share of outputs with unsupported factual claims.
- **Faithfulness** — share of output claims entailed by the retrieved or provided source.
- **Answer relevance** — semantic and intent match between query and answer.
- **Context recall** — share of relevant retrieved chunks actually used in generation.
- **Confidence interval** — every metric reported with sample size and interval, not as a point estimate (per NIST AI 800-3).

### 3.2 Security Reliability

The system resists adversarial manipulation and cannot be coerced into unsafe or non-compliant behavior.

Required controls:

- **Input guardrails** — prompt injection, jailbreak, system-prompt leakage detection.
- **Output guardrails** — PII redaction, unsafe content scoring, length limits.
- **Tool-call authorization** — per-agent allow/deny lists enforced before execution.
- **Adversarial testing** — automated red teaming in CI across at least five attack categories.
- **Evidence mapping** — every detection and every finding tagged to an OWASP LLM Top 10 category.

### 3.3 Operational Reliability

The system performs predictably and within defined resource constraints.

Required signals:

- **Latency** — P95/P99 per endpoint, with SLO thresholds.
- **Error rate** — per model provider and per tool.
- **Token and cost usage** — per tenant, per workload, per request.
- **Circuit breaker state** — trip frequency, fallback activations.
- **Trace completeness** — OTel spans covering LLM, RAG, tool calls, and guardrail decisions.

SLO and alert thresholds — the numbers `A2` alerts on and `E1`–`E3` enforce:

| Metric | Target | Alert threshold |
| :--- | :--- | :--- |
| P95 latency | < 2,000 ms | > 5,000 ms |
| Token usage per request | < 2,000 tokens | > 10,000 tokens |
| API error rate | < 0.1% | > 1% |
| Circuit breaker trips | 0 per hour | > 5 per hour |
| Queue wait time | < 100 ms | > 1,000 ms |

### 3.4 Temporal Reliability

Reliability characteristics remain stable across model updates, data shifts, and regulatory change.

Required signals:

- **Input drift** — PSI/KS or embedding-distance against a reference distribution.
- **Output drift** — metric trend slope on golden-dataset regression.
- **Canary health** — performance delta between canary and baseline before promotion.
- **Incident recurrence** — share of incidents by previously observed failure mode.
- **Audit trail** — immutable record of every model change, evaluation result, and incident.

---

## 4. The Reliability Score

Each dimension produces a 0–100 score; the composite score is the **weighted geometric mean** (not the arithmetic mean) so that a zero in any dimension collapses the composite. This prevents a system that is excellent on three dimensions and failing on one from appearing healthy.

composite = (F^wF · S^wS · O^wO · T^wT)^(1/(wF+wS+wO+wT))


Default weights: `wF = 0.35`, `wS = 0.30`, `wO = 0.15`, `wT = 0.20`. Weights are configurable per use case; the geometric mean structure is not.

---

## 5. Failure Mode to Dimension Mapping

| Failure mode | Dimension | Detection method |
| :--- | :--- | :--- |
| Hallucination | Functional | LLM-as-judge with reference check |
| Faithfulness failure | Functional | NLI entailment against source |
| Context loss in RAG | Functional | Context recall + answer relevance |
| Prompt injection | Security | Input guardrail classifier |
| Jailbreak | Security | Adversarial test suite |
| System-prompt leakage | Security | Canary token monitoring |
| PII disclosure | Security | Output entity detection + redaction |
| Excessive agency | Security | Tool-call authorization log |
| Latency degradation | Operational | P95/P99 threshold alert |
| Cost explosion | Operational | Per-request token budget |
| Rate-limit exhaustion | Operational | Provider error classification |
| Cascading failure | Operational | Circuit breaker trip |
| Model drift | Temporal | Golden regression trend |
| Data drift | Temporal | PSI/KS on input distribution |
| Concept drift | Temporal | Accuracy trend on labeled samples |
| Regulatory drift | Temporal | Control-to-standard mapping review |

---

## 6. Standards Mapping (the core of this document)

This is the mapping AGENTS.md refers to. Each dimension is anchored to one or more external standards. The `Standard` field on every backlog item must use one of the identifiers in the left column so that `G1` (control-to-standard mapping) and `G2` (audit-ready report) can aggregate evidence.

### 6.1 Primary mapping table

| Reliability dimension | Primary standards | Specific sections / controls |
| :--- | :--- | :--- |
| **Functional** | NIST AI RMF 1.0 (AI 100-1) · NIST AI 800-3 | *Measure* function: validity, accuracy, reliability metrics; generalized vs. benchmark accuracy with confidence intervals |
| **Security** | OWASP Top 10 for LLMs 2025 · ISO/IEC 42119-8 · Google SAIF | LLM01–LLM10; standardized red-team protocols; detection-and-response automation |
| **Operational** | ISO/IEC 42001:2023 · NIST AI RMF | AIMS operational control (Cl. 8); *Manage* function; logging, monitoring, human oversight |
| **Temporal** | NIST AI RMF lifecycle · ISO/IEC 42001 | *Measure* + *Manage* continuous loop; continual improvement (Cl. 10); nonconformity & corrective action |
| **Cross-cutting** | CSA AI Controls Matrix (AICM) · ENISA FAICP | 18 domains / 243 control objectives; 3-layer AI cybersecurity framework |
| **Swiss regulatory** | Swiss FADP · FINMA · CoE AI Convention · ISO/IEC 27001 | FADP Arts. 7, 19, 21, 22; FINMA governance, inventory, data quality, testing, documentation, explainability, independent review; the convention as *upcoming*; ISMS certification as the buyer-facing baseline (§6.10) |
| **Regulatory** | EU AI Act (Reg. 2024/1689) | Ch. III: risk management, data governance, technical documentation, record-keeping, transparency, human oversight, accuracy, robustness, cybersecurity |

### 6.2 Detail: NIST AI RMF (AI 100-1)

The AI RMF defines four functions — **Govern, Map, Measure, Manage** — that operate iteratively across the AI lifecycle.

| AI RMF function | Reliability dimension it serves | AgentGuard control |
| :--- | :--- | :--- |
| **Govern** | All | Policies, roles, and approval gates defined in project fields |
| **Map** | Functional, Security | Intended context and threat model documented per system |
| **Measure** | Functional, Security, Operational, Temporal | Evaluation suite, guardrail metrics, OTel, drift detection |
| **Manage** | Operational, Temporal | Circuit breakers, canary rollback, incident response |

Seven trustworthiness characteristics defined by NIST map to the matrix as: *valid and reliable* → Functional; *safe, secure and resilient* → Security; *accountable and transparent, explainable* → Cross-cutting (audit trail); *privacy-enhanced* → Security (PII guardrails); *fair with harmful bias managed* → Functional (evaluation rubric dimension).

### 6.3 Detail: NIST AI 800-3 (statistical evaluation)

AI 800-3 is the source of the requirement that every reliability metric be reported with **statistical confidence**, distinguishing *benchmark accuracy* (performance on a fixed test set) from *generalized accuracy* (estimated performance on the broader distribution). AgentGuard enforces this via `C2` (statistical confidence in reports) and the report schema in `G2`.

### 6.4 Detail: OWASP LLM Top 10 (2025)

The 2025 edition is the authoritative LLM threat model and the primary mapping target for the Security dimension.

| ID | Risk | AgentGuard control |
| :--- | :--- | :--- |
| LLM01 | Prompt Injection | `D1` input guardrails |
| LLM02 | Sensitive Information Disclosure | `D2` output PII redaction |
| LLM03 | Supply Chain | Cross-cutting; provider allow-list in policy |
| LLM04 | Data and Model Poisoning | Temporal (`F1` drift on inputs and outputs) |
| LLM05 | Improper Output Handling | `D2` output validation |
| LLM06 | Excessive Agency | `D4` tool-call authorization |
| LLM07 | System Prompt Leakage | `D1` canary token detection |
| LLM08 | Vector & Embedding Weaknesses | Temporal (`F1`) + RAG retrieval audit |
| LLM09 | Misinformation | Functional (`C1`) hallucination detection |
| LLM10 | Unbounded Consumption | `E2` budget and rate limits |

### 6.5 Detail: ISO/IEC 42001:2023

ISO/IEC 42001 defines the requirements for an **AI Management System (AIMS)**. AgentGuard covers the operational and continual-improvement clauses; the governance clauses are organizational.

| 42001 clause | Coverage | AgentGuard control |
| :--- | :--- | :--- |
| Cl. 6 Planning | Partial | Risk register maintained in project notes |
| Cl. 8 Operation | Full | `A1`–`A3`, `E1`–`E3` operational controls |
| Cl. 9 Performance evaluation | Full | `C1`–`C3`, `F1`–`F3` evaluation and audit |
| Cl. 10 Improvement | Full | `B2` closed-loop; `F4` incident recurrence |

### 6.6 Detail: ISO/IEC 42119-8

The proposed international standard for generative AI testing, focused on **benchmarking and red teaming**. It defines protocols for reproducible adversarial testing so results are comparable across organizations. AgentGuard's security story `D3` implements the test-execution side; `D5` maps results to OWASP categories so they remain comparable if 42119-8 is formally ratified.

### 6.7 Detail: CSA AI Controls Matrix (AICM)

AICM contains **243 control objectives across 18 security domains** and cross-walks to ISO 27001, NIST AI RMF, and BSI AIC4. It is the primary audit-ready control structure referenced by `A3` (immutable audit log), `G1` (control-to-standard mapping), and `G2` (audit-ready report). When a regulator or auditor asks "show me your AI controls," AICM is the structure the answer takes.

### 6.8 Detail: ENISA FAICP

The ENISA Framework for AI Cybersecurity Practices is a **three-layer model**: (I) basic cybersecurity of the host infrastructure, (II) AI-specific security, (III) sector-specific AI security. AgentGuard operates primarily at layer II (guardrails, adversarial testing) and layer III (policy customization per sector). It does not replace layer I (network, host, identity); that remains a prerequisite.

### 6.9 Detail: EU AI Act

For high-risk AI systems, Chapter III imposes obligations on risk management, data governance, technical documentation, record-keeping, transparency, human oversight, accuracy, robustness, and cybersecurity. The mapping to AgentGuard stories:

| EU AI Act requirement | AgentGuard control |
| :--- | :--- |
| Art. 9 Risk management | `G1` control mapping; risk register |
| Art. 10 Data governance | `B1` golden datasets; `F1` drift |
| Art. 11 Technical documentation | `G2` audit-ready report |
| Art. 12 Record-keeping | `A3` immutable audit log |
| Art. 13 Transparency | `A3` + guardrail decision reasons |
| Art. 14 Human oversight | Approval gates on `C3`, `F2` |
| Art. 15 Accuracy, robustness, cybersecurity | `C1`–`C3`, `D1`–`D5`, `F1`–`F2` |

Obligations for high-risk systems take effect in August 2026 (December 2027 for certain Annex III systems). The `G3` reliability score dashboard is designed to surface readiness against these articles before the deadline.

---

### 6.10 Detail: Swiss obligations

Switzerland has **no AI-specific statute in force** (§8.1). Obligations are resolved from the
`ai-compliance-pentest` rule packs rather than recalled: pack `v1.0.0`, commit `816b1e4`, FADP text
as of 2026-11-19 (Fedlex SR 235.1, consolidated English translation; the German or French text governs).
Do not copy article numbers out of this table — read them from the pack, because numbering shifts
between revisions and summaries lag.

Three fields decide what a finding may say:

- **`bindingness`** — only `statute` and `binding_circular` may be reported as a **breach**. A `supervisory_expectation` supports "deficient against" and nothing stronger.
- **`verification.automatable`** — `full` means a scanner decides; `partial` means a scanner contributes and document review finishes the job; `none` means organisational evidence only, and such a rule must never appear in a compliance percentage or be described as tested.
- **`effective_date`** — per rule, not per pack.

**FADP** — 14 rules, `CH` pack

| Provision | Rule | Testable | AgentGuard control |
| :--- | :--- | :--- | :--- |
| Art. 7 data protection by design and by default | `CH-DES-001` | partial | `D1` input guardrails; `D2` output guardrails and PII redaction |
| Art. 8 data security appropriate to the risk | `CH-SEC-001` | **full** | `D1`–`D5`; `E2` rate limiting; `I1`–`I8` abuse testing |
| Art. 19 duty to inform | `CH-INF-001` | partial | `A3` audit log; guardrail reasons an information notice can be built from |
| Art. 21 automated individual decisions | `CH-AID-001` | conditional | `H3` approval gate; `E1` human oversight; `F2` canary rollback |
| Art. 22 data protection impact assessment | `CH-DPI-001` | none | `G1` this mapping; `F1` drift, because a material change invalidates the assessment |
| *No Swiss requirement yet* | — | — | Non-discrimination testing and AI-specific transparency. The federal act is expected to reach consultation in spring 2027; no control claims it. |

**FINMA** — 17 rules, `CH-FINMA` pack, supervised institutions only

FINMA is an overlay, not a separate jurisdiction: it applies where the target is a bank, securities
firm, insurer or fund manager. The pack separates what can be breached from what is only expected.

| Instrument | Rule | Bindingness | Testable | AgentGuard control |
| :--- | :--- | :--- | :--- | :--- |
| Guidance 08/2024 §2.1 governance | `CH-FIN-001` | supervisory_expectation | partial | `G1`; `G3` dashboard |
| §2.2 inventory and risk classification | `CH-FIN-002` | supervisory_expectation | partial | board fields; `G3` |
| §2.3 data quality | `CH-FIN-003` | supervisory_expectation | partial | `B1` golden datasets |
| §2.4 tests and ongoing monitoring | `CH-FIN-004` | supervisory_expectation | **full** | `C1`–`C3`; `D3`; `F1` |
| §2.5 documentation | `CH-FIN-005` | supervisory_expectation | none | `G2` audit-ready report |
| §2.6 explainability | `CH-FIN-006` | supervisory_expectation | partial | `H2` canary verdicts; `A3` |
| §2.7 independent review | `CH-FIN-007` | supervisory_expectation | partial | Epic I; `D3` |
| Circular 2023/1 ICT and cyber risk (margins 47–96) | `CH-FIN-008`–`011` | **binding_circular** | full/partial/conditional | `E1`–`E3`; `D3`; `F1` |
| Circular 2023/1 operational resilience (margins 101–111) | `CH-FIN-012` | **binding_circular** | none | `G2`; `F2` |
| Circular 2018/3 outsourcing (margins 14–35) | `CH-FIN-013`–`015` | **binding_circular** | partial/none | `G2`; `A5` |
| Agentic AI: human ownership (2026 statement) | `CH-FIN-016` | supervisory_expectation | partial | `H3`; `D4` |
| Digital fraud (2026 guidance) | `CH-FIN-017` | supervisory_expectation | partial | `D3`; `I2`–`I5` |

**Council of Europe AI Convention** — upcoming, mapped so the work is ready when the act is

| Theme | Control that would evidence it |
| :--- | :--- |
| Transparency | `A3`, `G2` |
| Oversight | `H3`, `E1` |
| Risk assessment | `B1`, `F1`, `G1` |
| Data protection | the FADP rows above, which are current rather than upcoming |

**What a scanner can actually prove.** Forge tests behaviour. Of the Swiss rules, only the ones marked
`full` — `CH-SEC-001`, `CH-FIN-004`, `CH-FIN-009` — can be decided entirely by the harness. `partial`
and `conditional` rules need a document review alongside it, and `none` rules must be reported as
document evidence, never as tested. That boundary is the same one the harness applies to its own
verdicts: a case that never reached the model is not a pass.

---

## 7. Backlog Traceability

The GitHub project is the execution layer of this matrix. Each story is tagged with its dimension and primary standard.

### 7.1 Epics to dimensions

| Epic | Primary dimension | Secondary dimensions |
| :--- | :--- | :--- |
| **Epic A** Observability baseline | Operational | Cross-cutting (audit) |
| **Epic B** Golden dataset & regression | Functional | Temporal |
| **Epic C** Functional evaluation | Functional | — |
| **Epic D** Security guardrails & red teaming | Security | — |
| **Epic E** Operational reliability | Operational | — |
| **Epic F** Temporal reliability & drift | Temporal | Operational |
| **Epic G** Standards, compliance, reporting | Cross-cutting | All |

### 7.2 Story-to-standard index

Story-level dimension and standard assignments live on the issues themselves. The board is the only copy:

https://github.com/users/glaborie/projects/5

Query it with the repository script rather than keeping a table here:

```bash
./scripts/fetch-items.sh 5 | jq -r '
  .[] | select(.standard | test("OWASP")) | "\(.number) \(.title)"'
```

An evidence package for the frameworks an operator selected is exported as markdown:

```bash
./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh "Swiss FADP,FINMA" > ch-package.md
FORGE_FRAMEWORKS="Swiss FADP" ./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh
```

**Applicability is the operator's decision, not the tool's.** Forge does not detect a sector or a jurisdiction and does not decide that FINMA applies because the target looks like a bank; the same is true of Annex III uses under the EU AI Act. The operator selects the frameworks, the selection is checked against the §8 vocabulary, and the generated package records it in its header so an auditor can see what was claimed and by whom. A package is not evidence that the selection was right — only that it was made.

The package indexes the controls that claim a standard. It does not assert that their evidence is complete — the artifact that proves each control is named in the story.

`./scripts/validate-project.sh` fails if any `Standard` value falls outside the vocabulary in §8.

### 7.3 Milestones to standards readiness

M1–M5 are repository milestones; a story's milestone is its readiness record.

```bash
./scripts/fetch-items.sh 5 | jq -r '.[] | select(.milestone == "M2 Guardrails") | .title'
```

### 7.4 Evidence lifecycle

1. A control executes (guardrail fires, evaluation runs, drift detected).
2. The event is recorded in the immutable audit log (`A3`) with its dimension and standard tag.
3. `G1` aggregates events by standard to produce a control-status view.
4. `G2` packages the view into a report per framework.
5. `G3` rolls the status into the composite reliability score.

This is the closed loop the matrix describes: execution → evidence → score → action.

---

## 8. Appendix: Standard identifiers used in the project

| Identifier (use verbatim in the `Standard` field) | Full name |
| :--- | :--- |
| `NIST AI RMF` | NIST AI Risk Management Framework 1.0 (AI 100-1) |
| `NIST AI 800-3` | Expanding the AI Evaluation Toolbox with Statistical Models |
| `ISO/IEC 42001` | Artificial Intelligence Management System |
| `ISO/IEC 42119-8` | Generative AI Testing: Benchmarking and Red Teaming |
| `OWASP LLM Top 10` | OWASP Top 10 for Large Language Model Applications (2025) |
| `Google SAIF` | Google Secure AI Framework |
| `CSA AICM` | Cloud Security Alliance AI Controls Matrix |
| `ENISA FAICP` | ENISA Framework for AI Cybersecurity Practices |
| `EU AI Act` | Regulation (EU) 2024/1689 |
| `Swiss FADP` | Federal Act on Data Protection (revised, in force 1 September 2023) |
| `FINMA` | Supervisory expectations for FINMA-supervised institutions: Guidance 08/2024 and Circulars 2023/1 and 2018/3 |
| `CoE AI Convention` | Council of Europe Framework Convention on Artificial Intelligence (signed by Switzerland 27 March 2025, not yet ratified) |
| `ISO/IEC 27001` | Information security, cybersecurity and privacy protection — requirements for an ISMS |

### 8.1 Swiss market

Switzerland has **no AI-specific statute in force**. AI-supported processing of personal data is governed by the revised FADP (in force 1 September 2023); Articles 21 (automated individual decisions) and 22 (data protection impact assessment) are the provisions a production AI system usually touches, and the FDPIC supervises compliance.

On 12 February 2025 the Federal Council decided to implement the Council of Europe's AI Convention through targeted, mostly sector-specific amendments rather than an EU-style act. The consultation draft is scheduled for spring 2027, with the Federal Council taking note of the non-binding measures in autumn 2026 — so nothing beyond existing law binds today, and a system cannot yet be "compliant with the Swiss AI Act".

FINMA-supervised institutions answer additionally to **`FINMA`**, which aggregates two different things: Guidance 08/2024 (governance, AI inventory and risk classification, data quality, testing and monitoring, documentation, explainability, independent review) and the binding circulars — Circular 2023/1 on ICT, cyber and operational risk, and Circular 2018/3 on outsourcing. Guidance is a supervisory expectation that supports "deficient against"; a circular breach can be reported as a breach. §6.10 keeps the two apart per rule.

Swiss providers that place systems on the EU market, or whose output is used in the EU, remain subject to the **EU AI Act**; its transparency provisions have applied since August 2026. **ISO/IEC 27001** is the certification baseline most Swiss buyers require, with **ISO/IEC 42001** the AI management system layered on top.

These identifiers are the values the `Standard` field may contain, verbatim, `; `-separated when an item spans several standards. `N/A` marks framework-internal stories. `scripts/validate-project.sh` enforces the list: this table and its `STANDARDS` set change together, in one commit.

> Suggested citation: AgentGuard AI Reliability Matrix v1.0. AgentGuard Project, GitHub, 2026.

---

## 9. ROI Impact

Every capability in the matrix is tied to a measured outcome rather than a claim.

### 9.1 By dimension

**Functional**

| Capability | Risk mitigated | Estimated impact |
| :--- | :--- | :--- |
| Hallucination detection | Customer misinformation, regulatory liability | Prevents 60–80% of user-visible errors |
| Golden dataset regression | Silent degradation after updates | Catches 90% of regression failures pre-deployment |
| Statistical confidence scoring | Over-confident deployment decisions | Reduces false promotion of unreliable models by ~40% |

**Security**

| Capability | Risk mitigated | Estimated impact |
| :--- | :--- | :--- |
| Prompt injection guardrails | Model takeover, data breach | Blocks 85–95% of injection attempts (layered detection) |
| Automated red teaming | Undiscovered vulnerabilities | Discovers 3–5× more vulnerabilities than manual testing |
| PII redaction | Regulatory fines (GDPR, AI Act) | Prevents 90%+ of accidental PII exposure in outputs |

**Operational**

| Capability | Risk mitigated | Estimated impact |
| :--- | :--- | :--- |
| Token usage monitoring | Unbudgeted cost spikes | Reduces surprise overages by 70–90% |
| Circuit breakers | Cascading failures | Prevents 80% of system-wide outages |
| OpenTelemetry tracing | Debugging latency bottlenecks | Reduces MTTR from hours to minutes |

**Temporal**

| Capability | Risk mitigated | Estimated impact |
| :--- | :--- | :--- |
| Continuous drift detection | Silent performance degradation | Catches 95% of drifts before user impact |
| Canary + auto-rollback | Bad model updates reaching full production | Reduces blast radius from all users to 1–5% |
| Regression test automation | Repeated failure modes | Prevents 80% of previously observed incident types |

### 9.2 At the programme level

| ROI category | Direct benefits | Estimated annual impact |
| :--- | :--- | :--- |
| Risk reduction | Prevented AI security incidents (breach, injection, jailbreak) | 60–80% reduction in AI-specific incident rate |
| Compliance readiness | Audit-ready evidence for NIST AI RMF, ISO/IEC 42001, EU AI Act | 50–70% reduction in compliance documentation effort |
| Operational efficiency | Reduced debugging time, faster MTTR, lower surprise costs | 40–60% reduction in AI ops toil |
| User trust and retention | Higher output quality, fewer hallucinations, consistent behaviour | 20–30% reduction in churn due to reliability issues |

### 9.3 Which dimension to prioritise

| If you are… | Prioritise… |
| :--- | :--- |
| Building a customer-facing chatbot or RAG system | Functional + Operational — accuracy and latency are user-visible |
| Deploying AI agents with tool access | Security — excessive agency and tool-call injection are top risks |
| Operating in a regulated industry (finance, healthcare, EU) | Temporal + Security — compliance requires continuous monitoring and audit trails |
| Running cost-sensitive LLM workloads | Operational — unbounded consumption and cost spikes are immediate financial risks |

---

## 10. Implementation Roadmap

Five phases, mapping one-to-one onto the milestones in §7.3.

| Phase | Weeks | Scope | Milestone |
| :--- | :--- | :--- | :--- |
| 1. Baseline | 1–2 | OpenTelemetry traces, metrics, logs; golden dataset seeded from production traffic | M1 |
| 2. Guardrails | 3–4 | Input guardrails (injection, PII) and output guardrails (safety scoring, length limits) | M2 |
| 3. Evaluation | 5–6 | LLM-as-judge evaluators (hallucination, relevance, faithfulness); CI evaluation gates | M3 |
| 4. Red Teaming | 7–8 | Automated adversarial testing in CI; expand attack coverage (injection, jailbreak, PII extraction, tool-call injection) | M4 |
| 5. Continuous Improvement | 9–10 | Production failures become regression tests; drift detection and automated rollback | M5 |

---

## 11. Maintenance

This document is versioned with the project. When a standard is updated (OWASP releases a new Top 10, NIST publishes a revision, the EU AI Act delegates new codes of practice), the mapping in Section 6 is updated in the same PR that updates the affected stories. The `Standard` field values in Section 8 are the stable contract—do not introduce new identifiers without updating both Section 6 and the project schema.
