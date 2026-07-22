// Vitest setup: polyfill browser APIs not provided by jsdom.

// ResizeObserver is not available in jsdom, but ECharts uses it.
// A no-op implementation is sufficient for unit tests.
if (typeof ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
