import { describe, it, expect } from 'vitest';
import { isIPCMessage, type IPCMessage } from '../../src/extension/shared/ipc_types';
import type {
  TelemetryLogEntry,
  TelemetryBatchRequest,
  TelemetryBatchResponse,
} from '../../src/extension/shared/telemetry_types';

describe('Telemetry Contracts & IPC Messages', () => {
  it('validates a well-formed FORWARD_TELEMETRY IPC message', () => {
    const entry: TelemetryLogEntry = {
      timestamp_ms: 1730000000123,
      level: 'INFO',
      module: 'CS',
      message: 'Prefetch triggered for page 2',
      trace_id: 'trace-1234',
      extra: { page_index: 2, total: 10 },
    };

    const msg: IPCMessage = {
      type: 'FORWARD_TELEMETRY',
      payload: entry,
    };

    expect(isIPCMessage(msg)).toBe(true);
  });

  it('validates a FLUSH_TELEMETRY IPC message', () => {
    const msg: IPCMessage = {
      type: 'FLUSH_TELEMETRY',
    };

    expect(isIPCMessage(msg)).toBe(true);
  });

  it('rejects malformed FORWARD_TELEMETRY messages', () => {
    expect(isIPCMessage({ type: 'FORWARD_TELEMETRY', payload: null })).toBe(false);
    expect(
      isIPCMessage({
        type: 'FORWARD_TELEMETRY',
        payload: {
          timestamp_ms: 'invalid-string',
          level: 'INFO',
          module: 'CS',
          message: 'test',
        },
      })
    ).toBe(false);
    expect(
      isIPCMessage({
        type: 'FORWARD_TELEMETRY',
        payload: {
          timestamp_ms: 1730000000000,
          level: 'INFO',
          module: 123, // not string
          message: 'test',
        },
      })
    ).toBe(false);
    expect(
      isIPCMessage({
        type: 'FORWARD_TELEMETRY',
        payload: {
          timestamp_ms: 1730000000000,
          level: 'INFO',
          module: 'CS',
          // missing message
        },
      })
    ).toBe(false);
  });

  it('matches TelemetryBatchRequest and TelemetryBatchResponse shape contracts', () => {
    const batch: TelemetryBatchRequest = {
      logs: [
        {
          timestamp_ms: Date.now(),
          level: 'DEBUG',
          module: 'Prefetch',
          message: 'Window advanced',
        },
      ],
    };
    expect(batch.logs).toHaveLength(1);

    const response: TelemetryBatchResponse = {
      success: true,
      count: 1,
    };
    expect(response.success).toBe(true);
    expect(response.count).toBe(1);
  });
});
