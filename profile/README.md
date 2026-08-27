# <img width="45" height="45" alt="ExerisLogo" src="https://github.com/user-attachments/assets/56d05057-21c2-4baa-a669-6de8001ec341" /> Exeris Systems

**A JVM runtime where the things that usually need a second process run in yours — at a measured, published resident cost.**

[![Website](https://img.shields.io/badge/Website-exeris.eu-blue?style=flat-square)](https://exeris.eu)
[![Status](https://img.shields.io/badge/Kernel-v0.11_pre--1.0-orange?style=flat-square)](#status)
[![License](https://img.shields.io/badge/Open--core-Apache--2.0-green?style=flat-square)](#where-things-live)

## What we're building

Enterprise Java pays for its architecture twice. Once **inside** the process — abstraction layers, framework bookkeeping, classes loaded for features never used. And again **around** it — the saga coordinator, the event-store server, the APM sidecar: whole second processes that stay resident whether or not they are doing work.

Exeris removes both, and measures the removal.

- **[Exeris Kernel](https://github.com/exeris-systems/exeris-kernel)** — an off-heap runtime kernel for the JVM (JDK 25 LTS baseline, preview-clean; a `preview` line tracks the newest JDK). Request and response payloads live in Panama `MemorySegment`s behind deterministic buffer ownership; concurrency is virtual threads. Saga / durable execution (**Flow**), event sourcing (transactional outbox), and observability (JFR-first) run **inside the application process** — no coordinator, no event-store server, no sidecar. The runtime loads only the subsystems you declare: a plaintext deployment never carries the crypto subsystem's memory.
- **Exeris SDK + Tooling** — the framework part of the platform, moved to **build time**. Annotated domain types (`@ExerisDomain`, `@Action`, `@Field`, `@Relationship`...) are turned by the codegen pipeline into kernel-native handlers, sagas, OpenAPI, database migrations and UI components — idiomatic, editable Java, validated before the first byte of traffic. What a runtime framework does with reflection and auto-wiring on every startup happens here once, in the build — which is part of why the resident process stays small. **Exeris Studio** (roadmap) syncs visually with the same sources via LSP: visual speed without low-code lock-in. The same entity-first, build-time-verified pipeline is the substrate we are building toward AI-assisted generation of clean, reviewable code.
- **Exeris Spring Runtime** — hosts existing Spring applications on the kernel. Spring keeps DI, configuration and beans; the kernel owns ingress, lifecycle and the data plane. Brownfield adoption without a rewrite.
- **[Exeris Benchmark Lab](https://github.com/exeris-systems/exeris-benchmarks)** — the open harness behind every number we publish: matched contracts, fail-closed gates, AB/BA order control, committed raw artifacts, per-claim eligibility stamps.

Above the substrate, a composable capability ecosystem and vertical SKUs are in design — the whitepaper covers the three-tier picture.

## Numbers, and the rules they follow

Every comparative figure we publish carries a scope label (`comparison_eligible` = passed the strict fairness gate on dedicated bare metal; `descriptive` / `exploratory` = directional), a scenario contract, and raw artifacts committed next to the report. A few from the current series:

| What was measured | Result | Scope |
|---|---|---|
| Runtime-bound single-row read vs tuned pure-JDBC Quarkus and idiomatic Quarkus+Hibernate | **+39% / +57% throughput at −26% / −34% CPU per request** | `comparison_eligible` · [report](https://github.com/exeris-systems/exeris-benchmarks/blob/main/results/reports/2026-07-21-entity-read-by-id-tuned-pg-triad-comparison-eligible.md) |
| How small a memory budget the same work fits in | **Full speed in a 128 MiB budget**; the comparison stack's declared heap policy does not boot below 192 MiB | `descriptive` · [report](https://github.com/exeris-systems/exeris-benchmarks/blob/main/results/reports/2026-07-22-entity-read-by-id-memory-cpu-sweep.md) |
| Where a Spring request's cost actually sits (one app, five hostings) | The repository layer costs **headroom, not per-request latency** — and the largest identified contributor is projection proxies, not the ORM's row mapping | mixed, stated per table · [report](https://github.com/exeris-systems/exeris-benchmarks/blob/main/results/reports/2026-08-11-entity-read-by-id-spring-hosting-and-orm-axis.md) |
| What declaring 155 Valhalla value classes buys on an off-heap runtime | **≈1.3 MB of permanent non-heap cost, no workload movement** — published although it cuts against our own sweep | within-tier · [report](https://github.com/exeris-systems/exeris-benchmarks/blob/main/results/reports/2026-08-26-valhalla-carrier-sweep-on-an-off-heap-runtime.md) |

When a number loses, we retract it in public: the revision histories in those reports are load-bearing, not decorative. Review us — with or without an AI assistant; we use both — and tell us what you find. The artifacts are committed precisely so that a reviewer doesn't have to take the prose on trust.

## Status

Deep R&D, pre-1.0. The kernel is on the v0.11 line; API stability declarations have been honored since v0.9 (verified with japicmp across the full tag history). Kernel SPI, Core, the Community driver and the TCK are open under Apache-2.0; the Enterprise driver (`io_uring` / IOCP transport, QUIC/HTTP-3, NUMA-aware slab pools) is a commercial implementation of the same SPI — a Maven-coordinate swap, not a fork of your application.

## The exit is part of the design

We don't build golden cages. Business artifacts compile against the SPI, and the SPI is the contract: code detachment — taking your generated business logic and hosting it on your own infrastructure — is a documented, priced path, not a negotiation. A platform you can leave is a platform you can trust with production.

## Resources

- 🌍 **Website:** [exeris.eu](https://exeris.eu)
- 📊 **Benchmark reports:** [exeris-benchmarks/results/reports](https://github.com/exeris-systems/exeris-benchmarks/tree/main/results/reports)
- 📩 **Contact:** [github@exeris.eu](mailto:github@exeris.eu)
- 💼 **LinkedIn:** [Exeris Systems](https://www.linkedin.com/company/exeris-systems)
