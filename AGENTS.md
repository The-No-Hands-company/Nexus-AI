# Nexus Cloud

This folder is the working area for the Nexus Cloud project: a self-hosted, federated cloud layer for The No Hands Company.

## Working notes
- Keep project files inside this folder.
- Prefer small, focused changes.
- Reuse ideas from `file '/home/workspace/Nexus'` and `file '/home/workspace/nexus-deploy'` when useful, but do not mix their codebases unless explicitly intended.
- Treat this as the main development workspace for the new project.
- The current scaffold centers on control plane, data plane, federation, storage, observability, and an expanded API surface.
- Testing convention: run `bun test src`, keep shared harnesses in `src/test/`, and prefer colocated `*.test.ts` for DTO/unit coverage.
