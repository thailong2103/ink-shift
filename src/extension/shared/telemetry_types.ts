/**
 * Shared Telemetry Contracts for Browser Extension and Backend.
 *
 * Defines structured log entry payloads, severity levels, and batch envelopes
 * exchanged over HTTP to /api/v1/telemetry/logs and across IPC message channels.
 */

export type TelemetryLogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

export interface TelemetryLogEntry {
  /**
   * Epoch timestamp in milliseconds recorded at event occurrence (Date.now()).
   */
  timestamp_ms: number;
  /**
   * Logging severity level matching backend Python levels.
   */
  level: TelemetryLogLevel;
  /**
   * Extension module identifier (e.g. 'CS', 'SW', 'Prefetch', 'Popup', 'DOMScanner').
   */
  module: string;
  /**
   * Human-readable informational or error message.
   */
  message: string;
  /**
   * Correlation trace ID matching translation pipeline context.
   */
  trace_id?: string;
  /**
   * Optional structured metadata attributes.
   */
  extra?: Record<string, unknown>;
}

export interface TelemetryBatchRequest {
  /**
   * Ordered sequence of buffered telemetry events.
   */
  logs: TelemetryLogEntry[];
}

export interface TelemetryBatchResponse {
  success: boolean;
  count: number;
}
