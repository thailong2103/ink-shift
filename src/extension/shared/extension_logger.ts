/**
 * Structured Extension Logger with Sub-Millisecond Precision and Telemetry Forwarding.
 *
 * Provides uniform console logging format across Content Script, Service Worker, and Popup:
 *   [HH:mm:ss.SSS] [InkShift:<MODULE>] <message>
 *
 * Forwards structured telemetry events to the Service Worker TelemetryBatcher
 * via IPC or direct enqueueing without blocking user workflows.
 */

import type { TelemetryLogEntry, TelemetryLogLevel } from './telemetry_types';

export interface ExtensionLogger {
  debug(message: string, extra?: Record<string, unknown>): void;
  info(message: string, extra?: Record<string, unknown>): void;
  log(message: string, extra?: Record<string, unknown>): void;
  warn(message: string, extra?: Record<string, unknown>): void;
  error(message: string, extra?: Record<string, unknown>): void;
}

export type DirectBatcherEnqueue = (entry: TelemetryLogEntry) => void;

let directEnqueueFn: DirectBatcherEnqueue | null = null;

/**
 * Registers direct enqueuing handler when running inside the Service Worker.
 */
export function registerServiceWorkerTelemetryHandler(handler: DirectBatcherEnqueue | null): void {
  directEnqueueFn = handler;
}

/**
 * Formats a Date object into a local time string with 3-digit millisecond precision (HH:mm:ss.SSS).
 */
export function formatLocalTimestamp(date: Date = new Date()): string {
  const pad = (n: number, z = 2) => String(n).padStart(z, '0');
  const h = pad(date.getHours());
  const m = pad(date.getMinutes());
  const s = pad(date.getSeconds());
  const ms = pad(date.getMilliseconds(), 3);
  return `${h}:${m}:${s}.${ms}`;
}

/**
 * Creates a scoped logger for a specific extension module.
 *
 * @param moduleName Module identifier (e.g. 'CS', 'SW', 'Prefetch', 'Popup', 'DOMScanner').
 */
export function createExtensionLogger(moduleName: string): ExtensionLogger {
  const emit = (level: TelemetryLogLevel, message: string, extra?: Record<string, unknown>) => {
    const now = new Date();
    const timestampMs = now.getTime();
    const timeStr = formatLocalTimestamp(now);
    const tag = `[${timeStr}] [InkShift:${moduleName}]`;

    // 1. Output to local browser console (standard formatting, no emojis)
    const consoleArgs = extra !== undefined ? [`${tag} ${message}`, extra] : [`${tag} ${message}`];

    switch (level) {
      case 'DEBUG':
        console.debug(...consoleArgs);
        break;
      case 'INFO':
        console.info(...consoleArgs);
        break;
      case 'WARNING':
        console.warn(...consoleArgs);
        break;
      case 'ERROR':
        console.error(...consoleArgs);
        break;
    }

    // 2. Dispatch telemetry entry for backend archiving
    const traceId = extra?.trace_id ? String(extra.trace_id) : (extra?.traceId ? String(extra.traceId) : undefined);
    const entry: TelemetryLogEntry = {
      timestamp_ms: timestampMs,
      level,
      module: moduleName,
      message,
      ...(traceId ? { trace_id: traceId } : {}),
      ...(extra !== undefined ? { extra } : {}),
    };

    // If direct enqueue handler registered (in Service Worker)
    if (directEnqueueFn !== null) {
      try {
        directEnqueueFn(entry);
      } catch {
        // Suppress failure in telemetry forwarder
      }
      return;
    }

    // If in content script or popup, forward via chrome.runtime.sendMessage
    if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
      try {
        const responsePromise = chrome.runtime.sendMessage({
          type: 'FORWARD_TELEMETRY',
          payload: entry,
        });

        // If returned a promise, catch rejection silently (e.g. extension unloaded)
        if (responsePromise && typeof responsePromise.catch === 'function') {
          responsePromise.catch(() => {
            // Service worker asleep or no active listener
          });
        }
      } catch {
        // Ignore extension context invalidation
      }
    }
  };

  return {
    debug: (message: string, extra?: Record<string, unknown>) => emit('DEBUG', message, extra),
    info: (message: string, extra?: Record<string, unknown>) => emit('INFO', message, extra),
    log: (message: string, extra?: Record<string, unknown>) => emit('INFO', message, extra),
    warn: (message: string, extra?: Record<string, unknown>) => emit('WARNING', message, extra),
    error: (message: string, extra?: Record<string, unknown>) => emit('ERROR', message, extra),
  };
}
