const playwright = require("playwright");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class PlaywrightEmitter {
  constructor({ browserName, headless = true } = {}) {
    this.browserName = browserName || "chromium";
    this.headless = headless;
    this.browser = null;
    this.context = null;
    this.page = null;
  }

  async ensureStarted() {
    if (this.page) {
      return;
    }

    const browserType = playwright[this.browserName] || playwright.chromium;
    this.browser = await browserType.launch({ headless: this.headless });
    this.context = await this.browser.newContext();
    this.page = await this.context.newPage();
    await this.page.goto("about:blank");
  }

  async emitPointer(events) {
    await this.ensureStarted();
    let lastTimestamp = 0;
    for (const event of events) {
      const delay = Math.max(0, event.t_ms - lastTimestamp);
      if (delay > 0) {
        await sleep(delay);
      }
      if (event.event_type === "move") {
        await this.page.mouse.move(event.x, event.y);
      }
      if (event.event_type === "down") {
        await this.page.mouse.down();
      }
      if (event.event_type === "up") {
        await this.page.mouse.up();
      }
      lastTimestamp = event.t_ms;
    }
  }

  async emitKeystrokes(events) {
    await this.ensureStarted();
    let lastTimestamp = 0;
    for (const event of events) {
      const delay = Math.max(0, event.t_ms - lastTimestamp);
      if (delay > 0) {
        await sleep(delay);
      }
      if (event.event_type === "keydown") {
        await this.page.keyboard.down(event.key);
      }
      if (event.event_type === "keyup") {
        await this.page.keyboard.up(event.key);
      }
      lastTimestamp = event.t_ms;
    }
  }

  async stop() {
    if (this.context) {
      await this.context.close();
    }
    if (this.browser) {
      await this.browser.close();
    }
    this.context = null;
    this.browser = null;
    this.page = null;
  }
}

module.exports = {
  PlaywrightEmitter,
};
