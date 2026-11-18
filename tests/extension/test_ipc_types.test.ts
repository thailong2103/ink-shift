import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  isIPCMessage,
  isIPCResponse,
  createSuccessResponse,
  createErrorResponse,
  type IPCMessage,
  type IPCResponse,
  type TranslateImagePayload,
} from '../../src/extension/shared/ipc_types';

describe('IPC Types & Contracts', () => {
  it('validates CHECK_BACKEND_HEALTH message format', () => {
    const msg: IPCMessage = {
      type: 'CHECK_BACKEND_HEALTH',
      traceId: 'trace-123',
    };
    expect(isIPCMessage(msg)).toBe(true);
    expect(msg.type).toBe('CHECK_BACKEND_HEALTH');
  });

  it('validates TRANSLATE_IMAGE message with mandatory traceId and imageIndex', () => {
    const payload: TranslateImagePayload = {
      traceId: 'trace-456',
      imageIndex: 0,
      imageUrl: 'https://example.com/page1.jpg',
      clientWidth: 800,
      clientHeight: 1200,
    };
    const msg: IPCMessage = {
      type: 'TRANSLATE_IMAGE',
      payload,
    };
    expect(isIPCMessage(msg)).toBe(true);
    expect(msg.payload.traceId).toBe('trace-456');
    expect(msg.payload.imageIndex).toBe(0);
  });

  it('validates SPA_NAVIGATION_DETECTED and UPDATE_TAB_BADGE messages', () => {
    const spaMsg: IPCMessage = {
      type: 'SPA_NAVIGATION_DETECTED',
      payload: { url: 'https://example.com/chapter-2' },
    };
    expect(isIPCMessage(spaMsg)).toBe(true);

    const badgeMsg: IPCMessage = {
      type: 'UPDATE_TAB_BADGE',
      payload: { translated: 5, total: 12 },
    };
    expect(isIPCMessage(badgeMsg)).toBe(true);

    expect(isIPCMessage({ type: 'SPA_NAVIGATION_DETECTED', payload: null })).toBe(false);
    expect(isIPCMessage({ type: 'UPDATE_TAB_BADGE', payload: { translated: 'five' } })).toBe(false);
  });

  it('rejects invalid or malformed IPC messages', () => {
    expect(isIPCMessage(null)).toBe(false);
    expect(isIPCMessage({})).toBe(false);
    expect(isIPCMessage({ type: 'UNKNOWN_TYPE' })).toBe(false);
    expect(isIPCMessage({ type: 'TRANSLATE_IMAGE', payload: {} })).toBe(false);
  });

  it('constructs typed success and error responses echoing traceId', () => {
    const success = createSuccessResponse({ test: true }, 'trace-789');
    expect(success.success).toBe(true);
    expect(success.traceId).toBe('trace-789');
    expect(success.data).toEqual({ test: true });
    expect(isIPCResponse(success)).toBe(true);

    const error = createErrorResponse(
      { code: 'RATE_LIMITED', message: 'Too many requests' },
      'trace-789'
    );
    expect(error.success).toBe(false);
    expect(error.traceId).toBe('trace-789');
    expect(error.error.code).toBe('RATE_LIMITED');
    expect(isIPCResponse(error)).toBe(true);
  });

  it('validates and rejects malformed IPC responses', () => {
    expect(isIPCResponse(null)).toBe(false);
    expect(isIPCResponse(123)).toBe(false);
    expect(isIPCResponse({})).toBe(false);
    expect(isIPCResponse({ success: true, traceId: 123, data: {} })).toBe(false);
    expect(isIPCResponse({ success: false, error: 'string error' })).toBe(false);
    expect(isIPCResponse({ success: false, error: null })).toBe(false);
  });
});

describe('Manifest V3 Configuration', () => {
  it('manifest.json exists and conforms to Chrome MV3 specifications', () => {
    const manifestPath = resolve(__dirname, '../../src/extension/manifest.json');
    expect(existsSync(manifestPath)).toBe(true);

    const content = JSON.parse(readFileSync(manifestPath, 'utf-8'));
    expect(content.manifest_version).toBe(3);
    expect(content.name).toBe('InkShift — Manga Translation Overlay');
    expect(content.version).toBe('0.1.0');
    expect(content.permissions).toContain('storage');
    expect(content.permissions).toContain('webNavigation');
    expect(content.host_permissions).toContain('<all_urls>');
    expect(content.host_permissions).toContain('http://127.0.0.1:8000/*');
    expect(content.host_permissions).toContain('http://localhost:8000/*');
    expect(content.background.service_worker).toBe('background/service_worker.js');
    expect(content.background.type).toBe('module');
    expect(content.content_scripts[0].matches).toContain('<all_urls>');
    expect(content.content_scripts[0].js).toContain('content/content_script.js');
    expect(content.content_scripts[0].run_at).toBe('document_idle');
    expect(content.action.default_popup).toBe('popup/popup.html');
  });
});
