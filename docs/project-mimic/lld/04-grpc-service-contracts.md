# LLD: gRPC Service Contracts

## 1) Contract Principles

- Protobuf-first with strict schema versioning.
- Deadlines required for all request/response calls.
- Idempotency key on mutating operations.
- Trace context propagated in metadata.

## 2) Package Layout

```text
proto/
  common/v1/common.proto
  session/v1/session.proto
  vision/v1/vision.proto
  mimetic/v1/mimetic.proto
  orchestrator/v1/orchestrator.proto
```

## 3) Common Messages

```proto
syntax = "proto3";
package common.v1;

message RequestMeta {
  string trace_id = 1;
  string session_id = 2;
  string idempotency_key = 3;
  int64 deadline_unix_ms = 4;
}

message Ack {
  bool ok = 1;
  string message = 2;
}
```

## 4) Session Service

```proto
service SessionService {
  rpc CreateSession(CreateSessionRequest) returns (CreateSessionResponse);
  rpc AttachSiteTask(AttachSiteTaskRequest) returns (common.v1.Ack);
  rpc CloseSession(CloseSessionRequest) returns (CloseSessionResponse);
}
```

Responsibilities:

- session lifecycle
- identity bundle binding
- site task attachment

## 5) Vision Service

```proto
service VisionService {
  rpc AnalyzeFrame(AnalyzeFrameRequest) returns (AnalyzeFrameResponse);
  rpc GroundAction(GroundActionRequest) returns (GroundActionResponse);
}
```

Responsibilities:

- run inference cascade
- return UIMap and grounded candidates

## 6) Mimetic Service

```proto
service MimeticService {
  rpc PlanPointer(PlanPointerRequest) returns (PlanPointerResponse);
  rpc EmitPointer(EmitPointerRequest) returns (common.v1.Ack);
  rpc PlanKeystrokes(PlanKeystrokesRequest) returns (PlanKeystrokesResponse);
  rpc EmitKeystrokes(EmitKeystrokesRequest) returns (common.v1.Ack);
}
```

Responsibilities:

- pointer and keyboard planning
- low-level event emission control

## 7) Orchestrator Service

```proto
service OrchestratorService {
  rpc NextStep(NextStepRequest) returns (NextStepResponse);
  rpc VerifyStep(VerifyStepRequest) returns (VerifyStepResponse);
}
```

Responsibilities:

- action selection
- post-action verification and recovery routing

## 8) Timeouts and Retries

Recommended defaults:

- AnalyzeFrame: 800 ms deadline, retry once on UNAVAILABLE
- PlanPointer: 100 ms deadline, no retry
- EmitPointer: 500 ms deadline, retry once if transport failure before execution ack
- NextStep: 250 ms deadline, retry once on transient infra errors

## 9) Backward Compatibility

- Do not reuse field numbers.
- Additive changes only for minor versions.
- Breaking changes require new version package (v2).

## 10) Transport Security

- mTLS certificates rotated automatically.
- Service account based authorization per RPC.
- Request signatures for high-risk mutation calls.
