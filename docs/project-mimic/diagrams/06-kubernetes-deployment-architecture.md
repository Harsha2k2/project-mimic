# Diagram 6: Kubernetes Deployment and Scaling Architecture

```mermaid
flowchart TB
    subgraph K8S[Kubernetes Cluster]
        subgraph CTRL[Control Node Pool]
            GI[Goal Ingress Deployment]
            TP[Task Planner Deployment]
            DO[Orchestrator Deployment]
        end

        subgraph CPU[CPU Browser Node Pool]
            BW[Browser Worker Deployment]
        end

        subgraph GPU[GPU Inference Node Pool]
            TR[Triton Deployment]
        end

        subgraph EGR[Egress Node Pool]
            PG[Proxy Gateway]
        end

        KEDA[KEDA Scalers]
        HPA[HPA]
        PR[Prometheus]
    end

    GI --> TP --> DO --> BW
    BW --> TR
    BW --> PG

    PR --> KEDA
    KEDA --> HPA
    HPA --> BW
    HPA --> TR
    HPA --> DO
```

## What this shows

- Node pool separation by workload type.
- Autoscaling driven by queue and metrics signals.
- Inference and browser workers scaling independently.
