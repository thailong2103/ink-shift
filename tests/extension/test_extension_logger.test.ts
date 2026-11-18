import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  createExtensionLogger,
  formatLocalTimestamp,
  registerServiceWorkerTelemetryHandler,
} from '../../src/extension/shared/extension_logger';
import type { TelemetryLogEntry } from '../../src/extension/shared/telemetry_types';

describe('Extension Logger', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    registerServiceWorkerTelemetryHandler(null);
  });

  afterEach(() => {
    registerServiceWorkerTelemetryHandler(null);
  });

  it('formats local timestamp with 3-digit millisecond precision (HH:mm:ss.SSS)', () => {
    const fixedDate = new Date(2026, 9, 22, 9, 5, 2, 45); // 09:05:02.045
    const formatted = formatLocalTimestamp(fixedDate);
    expect(formatted).toBe('09:05:02.045');
    expect(formatted).toMatch(/^\d{2}:\d{2}:\d{2}\.\d{3}$/);
  });

  it('outputs formatted log lines to console methods with module tag and without icons', () => {
    const consoleInfoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const consoleDebugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});

    const logger = createExtensionLogger('Prefetch');

    logger.info('Starting prefetch window');
    expect(consoleInfoSpy).toHaveBeenCalledTimes(1);
    expect(consoleInfoSpy.mock.calls[0][0]).toMatch(/\[\d{2}:\d{2}:\d{2}\.\d{3}\] \[InkShift:Prefetch\] Starting prefetch window/);

    logger.debug('Debug detail');
    expect(consoleDebugSpy).toHaveBeenCalledTimes(1);

    logger.warn('Warning detail');
    expect(consoleWarnSpy).toHaveBeenCalledTimes(1);

    logger.error('Error detail');
    expect(consoleErrorSpy).toHaveBeenCalledTimes(1);
  });

  it('passes structured extra payload to console and telemetry', () => {
    const consoleInfoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const directSpy = vi.fn();
    registerServiceWorkerTelemetryHandler(directSpy);

    const logger = createExtensionLogger('CS');
    const extra = { trace_id: 'trace-xyz', pageIndex: 3 };

    logger.info('Page loaded', extra);

    expect(consoleInfoSpy).toHaveBeenCalledWith(
      expect.stringMatching(/\[InkShift:CS\] Page loaded/),
      extra
    );

    expect(directSpy).toHaveBeenCalledTimes(1);
    const entry: TelemetryLogEntry = directSpy.mock.calls[0][0];
    expect(entry.module).toBe('CS');
    expect(entry.message).toBe('Page loaded');
    expect(entry.trace_id).toBe('trace-xyz');
    expect(entry.extra).toEqual(extra);
    expect(entry.level).toBe('INFO');
    expect(typeof entry.timestamp_ms).toBe('number');
  });

  it('forwards telemetry via chrome.runtime.sendMessage in content script context', () => {
    const sendMessageSpy = vi.fn().mockResolvedValue(true);
    // Mock global chrome
    (globalThis as unknown as Record<string, unknown>).chrome = {
      runtime: {
        sendMessage: sendMessageSpy,
      },
    };

    const logger = createExtensionLogger('DOMScanner');
    logger.warn('Canvas not found');

    expect(sendMessageSpy).toHaveBeenCalledTimes(1);
    expect(sendMessageSpy).toHaveBeenCalledWith({
      type: 'FORWARD_TELEMETRY',
      payload: expect.objectContaining({
        level: 'WARNING',
        module: 'DOMScanner',
        message: 'Canvas not found',
      }),
    });

    // Clean up global mock
    delete (globalThis as unknown as Record<string, unknown>).chrome;
  });

  it('does not throw when chrome.runtime is missing (e.g. Node test environment)', () => {
    delete (globalThis as unknown as Record<string, unknown>).chrome;

    const logger = createExtensionLogger('Worker');
    expect(() => logger.info('Silent test')).not.toThrow();
  });
});
