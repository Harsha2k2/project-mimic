# Project Mimic TypeScript SDK

Official TypeScript SDK for integrating with Project Mimic control-plane APIs.

## Install

```bash
npm install @project-mimic/sdk
```

## Usage

```ts
import { ProjectMimicClient } from "@project-mimic/sdk";

const client = new ProjectMimicClient({
  baseUrl: "http://localhost:8000",
  apiKey: process.env.API_AUTH_KEY,
  tenantId: "tenant-a",
});

const created = await client.createSession({ goal: "book flight", maxSteps: 20 });
const state = await client.sessionState(String(created.session_id));
```

## Supported Operations

- `createSession`
- `stepSession`
- `sessionState`
- `listSessions`
- `restoreSession`
- `rollbackSession`
- `resumeSession`
- `operatorSnapshot`
