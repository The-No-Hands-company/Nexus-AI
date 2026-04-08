# Nexus Cloud Roadmap

## Purpose

This is the living roadmap for Nexus Cloud. It is the shared map for how we keep building without losing context: what we are building, why it matters, what is in progress, and what comes next.

Nexus Cloud is the control layer that lets Nexus Hosting, Nexus Chat, and future Nexus Systems tools expose safe public URLs, register domains, route traffic, and coordinate cloud services without depending on a hyperscaler.

## Blueprint alignment

This roadmap is grounded in `docs/BLUEPRINT.md`, which defines Nexus Cloud as the sovereign orchestrator and heart of the wider Nexus Systems ecosystem. The blueprint frames the platform as the central control plane, workload orchestrator, public access gateway, federation backbone, and unified platform layer for the 79+ core tools and future vertical branches.

That means this roadmap must always keep three responsibilities in view:

- the **public access layer** for tunnels, custom domains, and HTTPS exposure
- the **Systems API** as the canonical integration contract for tools and services
- **Nexus Guardian** as the policy, health, and safety layer around exposure and trust

## Guiding principle

If a feature does not help us operate a self-hosted, federated, privacy-first cloud, it does not belong in the first pass.

## Milestone board

### Now

| Owner | Status | Milestone | What it means | Exit condition |
| --- | --- | --- | --- | --- |
| Systems API | in progress | Canonical exposure contract | Public URL issuance, tool discovery, and normalized status all speak one contract | Clients can ask one place for tool identity, exposure, and status |
| Tunnel | planned | Reachability pipeline | A service can be made reachable through a stable network path | A tool gets a canonical public URL record |
| Edge | planned | Traffic entry and routing | Public requests are terminated and routed by host and service identity | External traffic lands on the intended service safely |
| Guardian | planned | Exposure policy and trust | Public reachability is approved, audited, and bounded by policy | Exposure decisions are explicit and reviewable |

### Next

| Owner | Status | Milestone | What it means | Exit condition |
| --- | --- | --- | --- | --- |
| Systems API | planned | Tool registry growth | More Nexus Systems tools can register without router churn | New tools can be added by extending the service layer, not the HTTP surface |
| Tunnel | planned | Refresh and renewal | URL exposure can be refreshed without breaking clients | Public URLs can be rotated and renewed cleanly |
| Edge | planned | Custom domains | Nexus Hosting can bind domains to services and keep routing stable | Custom domain workflows are supported end to end |
| Guardian | planned | Safety controls | Exposure requests can be rate-limited, denied, or quarantined | Unsafe or untrusted exposure is blocked by policy |

### Later

| Owner | Status | Milestone | What it means | Exit condition |
| --- | --- | --- | --- | --- |
| Federation | planned | Cross-cluster trust | Trusted peers can exchange signed requests and route safely | Federation state is explicit and usable for service discovery |
| Observability | planned | Operator visibility | Health, audit, placement, and exposure events are visible end to end | Operators can explain what happened without reading source code |
| Storage | planned | Durable platform substrate | Storage classes, attachments, and retention become first-class | Workloads can depend on storage without bespoke handling |
| Data plane | planned | Runtime expansion | More execution targets are available for workloads | Scheduling can target multiple runtime models cleanly |

## Current sprint

### Sprint goal

Make the public URL pipeline real, explicit, and safe enough to support hosted Nexus services.

### Sprint outcomes

- a tool can request a public URL and receive a stable result
- Tunnel, Edge, and Guardian each have a visible responsibility boundary
- public URL issuance is traceable from request to exposure record
- the roadmap reflects the actual execution order

### Sprint execution table

| Work item | Owner | Dependency | Blocker | Status |
| --- | --- | --- | --- | --- |
| Canonical public URL contract | Systems API | registry model, status model, route metadata | agreement on canonical request/response fields | in progress |
| Reachability records | Tunnel | Systems API contract, tool identity | refresh semantics and lifecycle shape | planned |
| Host routing | Edge | reachability records, URL registry | host mapping format and routing target model | planned |
| Exposure policy | Guardian | identity model, public URL metadata | policy rules and deny/quarantine semantics | planned |
| Audit trail | Observability | Guardian decisions, Systems API events | event taxonomy for exposure lifecycle | planned |

### Sprint checklist

- [ ] define the canonical public URL request/response shape in the Systems API
- [ ] make Tunnel responsible for creating and refreshing reachability records
- [ ] make Edge responsible for host-based public routing
- [ ] make Guardian responsible for approval, denial, and policy checks
- [ ] add a clear exposure state to the tool registry
- [ ] add audit events for public URL issuance and refresh
- [ ] document how Nexus Hosting uses the public URL pipeline
- [ ] document how Nexus Chat uses the public URL pipeline

## Weekly checkpoints

### Week 1

- lock the public URL contract
- confirm the first registry fields for tool exposure
- identify the first batch of tools that must enter the registry

### Week 2

- implement the first end-to-end public URL registration flow
- wire Tunnel to the contract
- wire Systems API status to exposure state

### Week 3

- connect Edge routing to registry entries
- add Guardian policy decisions to the flow
- define the deny / quarantine behavior for unsafe exposure

### Week 4

- add audit events for every public exposure mutation
- test refresh and renewal paths
- verify the hosted Nexus services story end to end

## Current focus

The immediate problem we are solving is the public URL pipeline for hosted Nexus services.

That means Nexus Cloud must be able to:

- issue or refresh public URLs for tools and services
- connect those URLs to stable tool identities
- support domain registration and routing for Nexus Hosting
- support server registration and exposure flows for Nexus Chat
- stay compatible with the much larger 79+ tool ecosystem described in the blueprint

## Public URL work checklist

This is the execution checklist for Tunnel, Edge, and Guardian.

### 1) Tunnel

- [ ] create a canonical exposure record for each tool
- [ ] support refresh without losing the tool identity
- [ ] store expiration and renewal timestamps
- [ ] expose a clear status for active, pending, and revoked URLs
- [ ] keep the record auditable for operators

### 2) Edge

- [ ] accept requests by host and route them to the right service identity
- [ ] support custom domain mapping for hosted services
- [ ] keep the public entrypoint stable even when the backing service changes
- [ ] surface route health to the Systems API and observability layer
- [ ] avoid hidden routing behavior

### 3) Guardian

- [ ] approve or deny public URL issuance
- [ ] enforce exposure policy for untrusted services
- [ ] require explicit trust for sensitive routes
- [ ] emit an audit event for every exposure decision
- [ ] provide a reviewable reason for each deny or quarantine action

## Progress tracking rule

Every change should answer three questions:

1. What user or operator problem does this solve?
2. Which layer owns the behavior?
3. What is the next dependency unlocked by shipping it?

If a change does not fit a current milestone, it goes into a later phase or a backlog note.

## Phases

### Phase 1: Core control plane

Own the smallest useful core first.

#### Scope

- identity and trust
- node registration
- scheduling
- policy and quota checks
- placement decisions
- workload state snapshots

#### Exit criteria

- a node can register and be stored in state
- a workload can be accepted, validated, and planned
- the control plane is split into real modules instead of living in the HTTP handler

### Phase 2: API extraction

Keep the HTTP entrypoint thin and predictable.

#### Scope

- `src/server.ts` only starts the server
- `src/api/router.ts` owns request routing
- business logic lives in control-plane and federation modules
- route metadata stays in `src/api/index.ts`
- legacy compatibility routes stay only where needed

#### Exit criteria

- `src/server.ts` is mostly wiring
- endpoint behavior is unchanged after the refactor
- API and domain logic are independently testable

### Phase 3: Systems API foundation

Introduce the canonical platform contract for tools and services.

#### Scope

- tool discovery
- normalized status
- capability catalog
- public URL exposure
- session and identity introspection
- alerts and events
- webhook delivery

#### Exit criteria

- `src/systems-api/` exists as a real module boundary
- tool registration, status, and exposure live behind one contract
- the contract is ready for future SDK extraction
- the API can support many more Nexus Systems tools without widening the core router

### Phase 4: Tunnel, Edge, and Guardian

This phase turns the Systems API into a real public access layer.

#### Nexus Tunnel

- create and manage reachability between public URLs and internal services
- support refreshable exposure records
- keep tunnel state explicit and auditable

#### Nexus Edge

- terminate public traffic
- route requests by host and service identity
- preserve a stable external surface for hosting and chat integrations

#### Nexus Guardian

- enforce exposure policy
- approve or deny public URL issuance
- manage trust and safety around external reachability

#### Exit criteria

- a tool can request a public URL and get a canonical result
- exposure decisions are policy-backed, not ad hoc
- public routing is safe enough to support hosting and chat use cases

### Phase 5: Federation trust

Add first-class peer trust handling.

#### Scope

- peer records
- signed request metadata
- trust renewal and expiry
- future routing hooks
- federated service summaries

#### Exit criteria

- trusted peers are stored and enumerable
- signed request data is preserved in the trust model
- federation can participate in route and service discovery later

### Phase 6: Observability and state

Expand the operator surface.

#### Scope

- health checks
- audit events
- placement visibility
- workload and peer snapshots
- exposure and routing events

#### Exit criteria

- operators can inspect state without digging through internals
- major platform actions leave a visible trail
- the public URL pipeline is observable end to end

### Phase 7: Storage and runtime expansion

Add the rest of the substrate.

#### Scope

- storage classes and attachments
- runtime adapters
- policy enforcement
- richer scheduling inputs
- workload lifecycle transitions
- service-level resource accounting

#### Exit criteria

- the platform can describe and attach storage cleanly
- workloads can target more than one runtime model
- scheduling can grow without breaking the API contract

## Tool-to-layer mapping

This section is the working map for the 80+ Nexus Systems tools. The rule is simple: map by behavior, not by name.

### Core platform tools

| Tool family | Primary owner | Secondary owners | Why it belongs there |
| --- | --- | --- | --- |
| Nexus Tunnel | Tunnel | Systems API, Guardian | It creates and refreshes reachability |
| Nexus Edge | Edge | Systems API, Guardian | It terminates traffic and routes by host |
| Nexus Guardian | Guardian | Systems API, Observability | It enforces policy, trust, and safety |
| Nexus Systems API | Systems API | Guardian, Observability | It is the canonical contract for tools and services |

### Control-plane tools

| Tool family | Primary owner | Secondary owners | Why it belongs there |
| --- | --- | --- | --- |
| Identity | Control plane | Guardian | It governs who and what can act |
| Node registration | Control plane | Observability | It records capacity and availability |
| Scheduling | Control plane | Data plane | It decides where workloads should run |
| Quota and policy | Control plane | Guardian | It constrains resource use and access |
| Placement | Control plane | Data plane | It turns a desired workload into a concrete plan |

### Public access and hosting tools

| Tool family | Primary owner | Secondary owners | Why it belongs there |
| --- | --- | --- | --- |
| Nexus Hosting | Systems API | Edge, Tunnel, Guardian | It needs domain binding, exposure, and safe routing |
| Nexus Chat registration | Systems API | Edge, Tunnel, Guardian | It needs a public backend URL for clients to connect |
| Domain registration | Edge | Tunnel, Guardian | It maps user-owned domains to reachable services |
| HTTPS/certificate provisioning | Edge | Guardian | It makes public endpoints trustworthy and stable |
| Reverse proxy policy | Edge | Guardian | It controls how external traffic is admitted |

### Federation tools

| Tool family | Primary owner | Secondary owners | Why it belongs there |
| --- | --- | --- | --- |
| Peer discovery | Federation | Systems API | It discovers other sovereign nodes |
| Signed routing | Federation | Guardian | It makes cross-node calls trustworthy |
| Trust renewal | Federation | Guardian | It keeps peer relationships current |
| Federation summaries | Federation | Observability | It helps operators understand the mesh |

### Storage and runtime tools

| Tool family | Primary owner | Secondary owners | Why it belongs there |
| --- | --- | --- | --- |
| Object storage | Storage | Data plane | It persists files and artifacts |
| Volume attachment | Storage | Data plane | It binds durable storage to workloads |
| Snapshots and backups | Storage | Observability | It preserves state and recovery points |
| Runtime adapters | Data plane | Control plane | They execute the workload plan |
| Workload lifecycle | Data plane | Control plane | It turns a plan into a running service |

### Observability and safety tools

| Tool family | Primary owner | Secondary owners | Why it belongs there |
| --- | --- | --- | --- |
| Audit events | Observability | Guardian | It records platform actions |
| Metrics | Observability | Control plane | It shows health and saturation |
| Logs | Observability | Guardian | It supports diagnosis and review |
| Alerts | Guardian | Observability | It escalates human-visible risk |
| Health summaries | Observability | Systems API | It gives clients a safe status surface |

### Rule for the long tail of tools

For any future tool, ask:

- does it decide trust, policy, identity, quota, or placement? → control plane or Guardian
- does it create a user-facing URL or route? → Systems API, Tunnel, or Edge
- does it touch peers or signed cross-node requests? → Federation
- does it store data or manage recovery? → Storage
- does it execute workloads? → Data plane
- does it record health or history? → Observability

If a tool spans multiple layers, assign one primary owner and list the rest as dependencies. Do not invent a new layer unless the existing ones truly do not fit.

## Tool-by-tool registry plan

This is the first batch of Nexus Systems tools that should enter the registry. The order matters: we register the contract first, then the reachability layers, then the hosting and safety surfaces that depend on them.

| Tool | Registry status | Primary owner | Dependencies | Blocker | First registry action |
| --- | --- | --- | --- | --- | --- |
| Nexus Systems API | planned | Systems API | observability summary, guardian policy hooks | canonical status and summary fields | create the base tool record and capability catalog |
| Nexus Tunnel | planned | Tunnel | Systems API, Guardian | exposure record schema | register the reachability tool and its refresh capability |
| Nexus Edge | planned | Edge | Tunnel, Guardian, Systems API | host routing model | register the traffic entry tool and routing capabilities |
| Nexus Guardian | planned | Guardian | Systems API, Observability | policy evaluation contract | register the approval and audit tool |
| Nexus Hosting | planned | Systems API | Edge, Tunnel, Guardian | domain binding flow | register the hosting-facing exposure consumer |
| Nexus Chat registration | planned | Systems API | Edge, Tunnel, Guardian | server exposure handshake | register the chat-facing backend URL consumer |
| Domain registration | planned | Edge | Tunnel, Guardian | DNS validation and ownership proof | register the domain binding workflow |
| HTTPS / certificate provisioning | planned | Edge | Guardian | certificate lifecycle automation | register the public TLS provisioning workflow |
| Reverse proxy policy | planned | Edge | Guardian | policy rule format | register the request admission workflow |
| Exposure audit | planned | Observability | Guardian, Systems API | audit event shape | register the exposure event sink |
| Public URL refresh | planned | Tunnel | Systems API | refresh semantics | register the URL renewal workflow |
| Status summary | in progress | Systems API | Observability, Tunnel, Guardian | aggregation fields | register the canonical status surface |

## RACI snapshot

| Layer | Responsible | Accountable | Consulted | Informed |
| --- | --- | --- | --- | --- |
| Systems API | contract shape, discovery, registry surfaces | canonical tool contract | Tunnel, Edge, Guardian, Observability | control plane, hosting, chat |
| Tunnel | reachability records, refresh, renewal | public URL creation path | Systems API, Edge, Guardian | hosting, chat, observability |
| Edge | host routing, traffic entry, domain binding | public request routing path | Systems API, Tunnel, Guardian | hosting, chat, observability |
| Guardian | policy, trust, deny/quarantine decisions | exposure safety and approval | Systems API, Edge, Observability | hosting, chat, operators |
| Observability | audit, metrics, event visibility | operational trail | Systems API, Guardian | control plane, tunnel, edge |
| Control plane | identity, registration, scheduling, placement | platform state and decisions | Systems API, Guardian | tunnel, edge, observability |

## Decision log

| Date | Subject | Decision | Reason | Owner | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-04-08 | Nexus Tunnel | Tunnel owns public reachability records and renewal | It needs direct control over refreshable exposure state for hosted services | Tunnel | Public URL lifecycle lives here |
| 2026-04-08 | Nexus Edge | Edge owns host routing and traffic entry | It is the stable external surface for hosted services and chat backends | Edge | Keep request routing separate from policy |
| 2026-04-08 | Nexus Guardian | Guardian owns exposure policy and safety decisions | Public reachability must be explicitly approved, denied, or quarantined | Guardian | Document policy reasons here |
| 2026-04-08 | Nexus Systems API | Systems API owns the canonical tool contract | Tool identity, status, and exposure must share one integration surface | Systems API | Record new registry fields here |

## Open questions

| Question | Options | Decision | Date | Owner |
| --- | --- | --- | --- | --- |
| What is the canonical refresh model for public URLs: replace-in-place, versioned renewal, or a new record per refresh? | replace-in-place, versioned renewal, new record per refresh | | | |
| Should Tunnel own the public URL record lifecycle, or should Guardian be able to revoke and reissue directly? | Tunnel owns lifecycle, Guardian can revoke/reissue | | | |
| What is the minimum data model needed for the first large batch of tools to register safely without overfitting the schema? | | | | |
| Which status fields must be exposed immediately to hosting and chat, and which can wait until later? | | | | |
| How should host routing behave when a tool is reachable through more than one surface? | | | | |

## Backlog principles

When a new Nexus Systems tool appears, decide first which layer it belongs to:

- control plane if it changes identity, scheduling, or placement
- Systems API if it changes tool discovery, status, or exposure
- federation if it changes trust or peer routing
- observability if it changes audit, metrics, or event visibility
- storage if it changes persistence or attachment behavior
- data plane if it changes runtime execution

If the answer is unclear, add a short note here instead of expanding the router.
