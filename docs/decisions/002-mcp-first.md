# ADR 002 — MCP Server Before Interface Layer

**Status:** Accepted

---

## Context

AdCode's core functionality — applying campaign JSON to Facebook, detecting drift, validating against ad policies — can be exposed through multiple interface layers: a CLI, a web app, an email bot, or an AI model interface. The question is what to build first and how to structure the system to avoid painting into a corner.

The agency that will use AdCode already has an AI workflow using Gemini. They are familiar with attaching files and issuing natural language instructions to a model. They do not want to adopt a new purpose-built application if their existing AI workflow can be extended instead.

Three build-order strategies were evaluated:

**CLI first.** Write standalone Python scripts invokable from the command line. Simple, testable, no dependencies on external protocols. But the CLI is not the end-state interface, so this approach produces throwaway glue code and defers integration concerns.

**Web app first.** Build a web application with a UI, backend API, and authentication. The interface is immediately usable by non-technical staff but requires building and hosting a full-stack application before any core logic is validated. High up-front investment with the most unknowns.

**MCP server first.** Expose core scripts as MCP tools. The agency attaches the MCP server to their existing Gemini workflow and interacts via natural language. The email bot (v2) is implemented as a model call with the same MCP server and email transport layered on top. No new interface to learn; the interface layer is deferred until core scripts are stable.

---

## Decision

Build the MCP server and core scripts before any interface layer.

Core scripts (`traffic.py`, `reconcile.py`, validation logic, Excel ingestion) are implemented first. Each script is wrapped as an MCP tool. The MCP server is the stable API surface. Interface layers (email bot, Gemini integration) are built on top of it.

The agency brings their own model (Gemini). AdCode does not bundle a model.

---

## Rationale

MCP decouples the core logic from the interface. Once the tools are stable, any model that supports MCP can call them. The email bot becomes a thin wrapper around the same tool surface rather than a parallel implementation.

The agency's existing Gemini workflow means MCP integration has immediate value — they can attach the server and begin using it without waiting for an email bot or web app. This creates a shorter path to a working demo.

Building the interface first (web app or email bot) would require standing up infrastructure before knowing what the core scripts actually need to expose. The MCP tool surface is the natural point to stabilize first; interface design follows naturally from it.

Deferring model bundling keeps the system model-agnostic. The agency uses Gemini today; forcing them to use a different model would be a blocker. Letting them bring their own model removes a dependency.

---

## Consequences

**Positive:**
- Core logic is decoupled from interface layer. Interfaces can be added, swapped, or layered without touching core scripts.
- Immediate value for the agency via their existing Gemini workflow.
- The email bot (v2) is a thin composition over existing MCP tools, not a parallel implementation.
- Model-agnostic by design — any MCP-compatible model can call the tools.
- MCP tool surface doubles as the internal API contract, making the system easier to test and reason about.

**Negative:**
- MCP is a relatively new protocol. Tooling, documentation, and community support are less mature than REST APIs or CLIs.
- Non-technical users cannot interact with the system until an interface layer (email bot or similar) is built. V1 requires technical staff to interact via Gemini or direct MCP calls.
- The agency's dependence on Gemini means AdCode's usability is tied to Gemini's MCP support and capability — factors outside AdCode's control.

**Deferred to v2.** Email bot interface. Google Ads MCP tools. Any web-based interface.
