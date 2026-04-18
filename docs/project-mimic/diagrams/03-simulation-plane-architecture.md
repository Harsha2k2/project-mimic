# Diagram 3: Simulation Plane Architecture

```mermaid
flowchart LR
    subgraph SW[Simulation Worker Namespace]
        subgraph BWP[Browser Worker Pod]
            PW[Playwright Runtime Node.js]
            MC[Mimetic Sidecar Rust]
            CA[Capture Agent]
            CDP[CDP Bridge]

            MC --> CDP
            PW --> CDP
            PW --> CA
        end

        subgraph VSN[Vision Service Namespace]
            VG[Vision Gateway Python]
            TR[Triton Inference]
            MR[Model Repository]

            VG --> TR
            TR --> MR
        end

        subgraph EG[Egress]
            PG[Proxy Gateway]
            NAT[NAT Egress]
        end
    end

    BWP --> VG
    VG --> BWP

    BWP --> PG
    PG --> NAT
    NAT --> WEB[Target Websites]
```

## What this shows

- Per-session pod composition for browser execution.
- Shared GPU inference services for visual reasoning.
- Controlled egress path for identity-aware outbound traffic.
