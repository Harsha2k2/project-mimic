class SidecarClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async planPointer(payload) {
    return this._post("/v1/mimetic/pointer/plan", payload);
  }

  async planKeystrokes(payload) {
    return this._post("/v1/mimetic/keyboard/plan", payload);
  }

  async _post(path, payload) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const message = await response.text();
      throw new Error(`sidecar request failed: ${response.status} ${message}`.trim());
    }

    return response.json();
  }
}

module.exports = {
  SidecarClient,
};
