export type ActionType = "click" | "type" | "wait";

export interface CreateSessionRequest {
  goal: string;
  maxSteps?: number;
}

export interface StepSessionRequest {
  actionType: ActionType;
  target?: string;
  x?: number;
  y?: number;
  text?: string;
  waitMs?: number;
  metadata?: Record<string, unknown>;
}

export interface ListSessionsOptions {
  status?: string;
  goalContains?: string;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
}

export interface ProjectMimicClientOptions {
  baseUrl: string;
  apiPrefix?: string;
  apiKey?: string;
  tenantId?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export class ProjectMimicClient {
  private readonly baseUrl: string;
  private readonly apiPrefix: string;
  private readonly apiKey?: string;
  private readonly tenantId?: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ProjectMimicClientOptions) {
    if (!options.baseUrl || !options.baseUrl.trim()) {
      throw new Error("baseUrl is required");
    }

    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    const prefix = options.apiPrefix && options.apiPrefix.trim() ? options.apiPrefix : "/api/v1";
    this.apiPrefix = prefix.startsWith("/") ? prefix : `/${prefix}`;
    this.apiKey = options.apiKey;
    this.tenantId = options.tenantId;
    this.timeoutMs = options.timeoutMs ?? 15000;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async createSession(request: CreateSessionRequest): Promise<Record<string, unknown>> {
    return this.request("POST", "/sessions", {
      goal: request.goal,
      max_steps: request.maxSteps ?? 20,
    });
  }

  async stepSession(sessionId: string, request: StepSessionRequest): Promise<Record<string, unknown>> {
    const payload: Record<string, unknown> = {
      action_type: request.actionType,
      metadata: request.metadata ?? {},
    };

    if (request.target !== undefined) {
      payload.target = request.target;
    }
    if (request.x !== undefined) {
      payload.x = request.x;
    }
    if (request.y !== undefined) {
      payload.y = request.y;
    }
    if (request.text !== undefined) {
      payload.text = request.text;
    }
    if (request.waitMs !== undefined) {
      payload.wait_ms = request.waitMs;
    }

    return this.request("POST", `/sessions/${sessionId}/step`, payload);
  }

  async sessionState(sessionId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/sessions/${sessionId}/state`);
  }

  async listSessions(options: ListSessionsOptions = {}): Promise<Record<string, unknown>> {
    const params = new URLSearchParams();
    params.set("page", String(options.page ?? 1));
    params.set("page_size", String(options.pageSize ?? 50));
    params.set("sort_by", options.sortBy ?? "created_at");
    params.set("sort_order", options.sortOrder ?? "desc");

    if (options.status) {
      params.set("status", options.status);
    }
    if (options.goalContains) {
      params.set("goal_contains", options.goalContains);
    }

    return this.request("GET", `/sessions?${params.toString()}`);
  }

  async restoreSession(sessionId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/sessions/${sessionId}/restore`);
  }

  async rollbackSession(sessionId: string): Promise<Record<string, unknown>> {
    return this.request("POST", `/sessions/${sessionId}/rollback`);
  }

  async resumeSession(sessionId: string): Promise<Record<string, unknown>> {
    return this.request("POST", `/sessions/${sessionId}/resume`);
  }

  async operatorSnapshot(): Promise<Record<string, unknown>> {
    return this.request("GET", "/operator/snapshot");
  }

  private async request(
    method: string,
    path: string,
    payload?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const headers: Record<string, string> = {
        Accept: "application/json",
      };

      if (payload !== undefined) {
        headers["Content-Type"] = "application/json";
      }
      if (this.apiKey) {
        headers["X-API-Key"] = this.apiKey;
      }
      if (this.tenantId) {
        headers["X-Tenant-ID"] = this.tenantId;
      }

      const response = await this.fetchImpl(`${this.baseUrl}${this.apiPrefix}${path}`, {
        method,
        headers,
        body: payload !== undefined ? JSON.stringify(payload) : undefined,
        signal: controller.signal,
      });

      const text = await response.text();
      const parsed = text ? JSON.parse(text) : {};
      if (!response.ok) {
        throw new Error(`request failed with status ${response.status}: ${JSON.stringify(parsed)}`);
      }
      if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("response payload must be a JSON object");
      }
      return parsed as Record<string, unknown>;
    } finally {
      clearTimeout(timer);
    }
  }
}
