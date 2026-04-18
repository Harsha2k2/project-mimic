# Diagram 7: Session Identity and Proxy Architecture

```mermaid
flowchart LR
    S[Session Request] --> IA[Identity Allocator]

    subgraph Bundle[Identity Bundle]
        PXY[Proxy Endpoint]
        TLS[TLS and HTTP Signature]
        UA[User Agent and Browser Version]
        LOC[Locale Timezone Geo]
        CAP[Fonts Canvas WebGL Profile]
        BHV[Behavior Profile ID]
    end

    IA --> Bundle
    Bundle --> SM[Session Manager]
    SM --> BW[Browser Worker]
    BW --> PG[Proxy Gateway]
    PG --> WEB[Target Website]

    WEB --> RSK[Risk Scorer]
    RSK -->|low| SM
    RSK -->|high| ROT[Rotate Identity]
    ROT --> IA
```

## What this shows

- Identity is assigned as a coherent bundle, not random fields.
- Risk-scored feedback loop governs rotation.
- Sticky identity per session with controlled rotation triggers.
