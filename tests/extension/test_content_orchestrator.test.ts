// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initContentScript,
  teardownContentScript,
  extractChapterIdFromUrl,
  extractPageNumberFromUrl,
  translateImageElement,
  serializeImageElementToDataUrl,
  resolveImagePageNumber,
  detectCurrentReaderLayoutMode,
  handleGlobalKeyboardShortcuts,
  isTypingContext,
} from '../../src/extension/content/content_script';
import type { TranslationResponse } from '../../src/types/contract';
import type { IPCMessage, IPCResponse } from '../../src/extension/shared/ipc_types';

describe('Content Script Orchestrator Pipeline', () => {
  let mockSendMessage: ReturnType<typeof vi.fn>;
  let messageListeners: Array<(msg: IPCMessage, sender: unknown, sendResponse: unknown) => void>;

  const mockTranslation: TranslationResponse = {
    success: true,
    page_hash: 'hash-orchestrator',
    engine_used: 'gemini-2.5-flash',
    execution_time_ms: 150,
    from_cache: false,
    blocks: [
      {
        id: 'block-orch-1',
        box: [100, 100, 300, 400],
        translated_text: 'Dịch thử nghiệm orchestrator',
      },
    ],
  };

  beforeEach(() => {
    document.body.innerHTML = '';
    messageListeners = [];

    // Mock chrome.runtime
    mockSendMessage = vi.fn().mockImplementation((msg: IPCMessage) => {
      if (msg.type === 'TRANSLATE_IMAGE') {
        const res: IPCResponse<TranslationResponse> = {
          success: true,
          traceId: msg.payload.traceId,
          data: mockTranslation,
        };
        return Promise.resolve(res);
      }
      return Promise.resolve({ success: true, data: null });
    });

    vi.stubGlobal('chrome', {
      runtime: {
        sendMessage: mockSendMessage,
        onMessage: {
          addListener: vi.fn((listener) => {
            messageListeners.push(listener);
          }),
          removeListener: vi.fn(),
        },
      },
      storage: {
        local: {
          get: vi.fn().mockResolvedValue({ opacity: 'semi-transparent', debugGeometry: false }),
          set: vi.fn().mockResolvedValue(undefined),
          onChanged: {
            addListener: vi.fn(),
            removeListener: vi.fn(),
          },
        },
      },
    });

    // Mock ResizeObserver
    class MockResizeObserver {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    }
    vi.stubGlobal('ResizeObserver', MockResizeObserver);
  });

  afterEach(() => {
    teardownContentScript();
    vi.unstubAllGlobals();
  });

  it('scans manga images and dispatches TRANSLATE_IMAGE concurrently with traceId', async () => {
    const img1 = document.createElement('img');
    img1.src = 'https://example.com/ch1/p1.jpg';
    Object.defineProperty(img1, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img1, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img1, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img1, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img1, 'complete', { value: true, configurable: true });
    img1.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img1);

    await initContentScript();

    // Verify IPC message dispatched directly
    expect(mockSendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'TRANSLATE_IMAGE',
        payload: expect.objectContaining({
          imageUrl: 'https://example.com/ch1/p1.jpg',
          clientWidth: 800,
          clientHeight: 1200,
          imageIndex: 0,
        }),
      })
    );

    // Verify overlay mounted with speech bubble
    const hosts = document.querySelectorAll('.ink-shift-overlay-host');
    expect(hosts.length).toBe(1);
    const bubble = hosts[0].shadowRoot?.querySelector('.inkshift-speech-bubble');
    expect(bubble?.textContent).toBe('Dịch thử nghiệm orchestrator');
  });

  it('handles SPA navigation messages by tearing down overlays and re-scanning', async () => {
    const img = document.createElement('img');
    img.src = 'https://example.com/ch1/p1.jpg';
    Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
    img.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img);

    await initContentScript();
    expect(document.querySelectorAll('.ink-shift-overlay-host').length).toBe(1);

    // Simulate SPA navigation message
    const spaMessage: IPCMessage = {
      type: 'SPA_NAVIGATION_DETECTED',
      payload: { url: 'https://example.com/ch2' },
    };

    await Promise.all(
      messageListeners.map(
        (listener) =>
          new Promise((resolve) => {
            listener(spaMessage, {}, resolve);
          })
      )
    );

    // Overlays should be cleaned and rebuilt
    expect(document.querySelectorAll('.ink-shift-overlay-host').length).toBe(1);
  });

  it('handles RESCAN_PAGE messages by tearing down and re-running pipeline', async () => {
    const img = document.createElement('img');
    img.src = 'https://example.com/ch1/p1.jpg';
    Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
    img.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img);

    await initContentScript();

    mockSendMessage.mockClear();

    const rescanMessage: IPCMessage = { type: 'RESCAN_PAGE' };
    await Promise.all(
      messageListeners.map(
        (listener) =>
          new Promise((resolve) => {
            listener(rescanMessage, {}, resolve);
          })
      )
    );

    expect(mockSendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'TRANSLATE_IMAGE',
      })
    );
  });

  it('updates status pill with error diagnostics when translation fails', async () => {
    mockSendMessage.mockImplementation((msg: IPCMessage) => {
      if (msg.type === 'TRANSLATE_IMAGE') {
        return Promise.resolve({
          success: false,
          traceId: 'err-trace',
          error: { code: 'RATE_LIMITED', message: 'Too many requests' },
        });
      }
      return Promise.resolve({ success: true, data: null });
    });

    const img = document.createElement('img');
    img.src = 'https://example.com/ch1/err.jpg';
    Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
    img.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img);

    await initContentScript();

    const host = document.querySelector('.ink-shift-overlay-host');
    expect(host).not.toBeNull();
    const pill = host?.shadowRoot?.querySelector('.inkshift-status-pill') as HTMLElement;
    expect(pill).not.toBeNull();
    expect(pill.dataset.status).toBe('failed');
    expect(pill.dataset.errorCode).toBe('RATE_LIMITED');
  });

  it('updates status pill when IPC sendMessage throws network exception', async () => {
    mockSendMessage.mockImplementation((msg: IPCMessage) => {
      if (msg.type === 'TRANSLATE_IMAGE') {
        return Promise.reject(new Error('Connection closed'));
      }
      return Promise.resolve({ success: true, data: null });
    });

    const img = document.createElement('img');
    img.src = 'https://example.com/ch1/net-fail.jpg';
    Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
    img.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img);

    await initContentScript();

    const host = document.querySelector('.ink-shift-overlay-host');
    expect(host).not.toBeNull();
    const pill = host?.shadowRoot?.querySelector('.inkshift-status-pill') as HTMLElement;
    expect(pill).not.toBeNull();
    expect(pill.dataset.status).toBe('failed');
    expect(pill.dataset.errorCode).toBe('IPC_DISPATCH_FAILED');
  });

  it('loads custom opacity and debugGeometry options from storage', async () => {
    vi.stubGlobal('chrome', {
      runtime: {
        sendMessage: mockSendMessage,
        onMessage: { addListener: vi.fn(), removeListener: vi.fn() },
      },
      storage: {
        local: {
          get: vi.fn().mockResolvedValue({
            opacity: 'opaque',
            debugGeometry: true,
            engine: 'cloud',
          }),
        },
      },
    });

    const img = document.createElement('img');
    img.src = 'https://example.com/ch1/custom.jpg';
    Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
    img.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img);

    await initContentScript();

    const hosts = document.querySelectorAll('.ink-shift-overlay-host');
    expect(hosts.length).toBe(1);
    // Should render debug outline when debugGeometry is true
    const debugRect = hosts[0].shadowRoot?.querySelector('.inkshift-debug-rendered-rect');
    expect(debugRect).not.toBeNull();
  });

  it('handles reused DOM <img> elements with updated URLs by tearing down old overlay and translating new image', async () => {
    window.history.pushState({}, '', '/chapter/ch-1/1');
    const img = document.createElement('img');
    img.src = 'https://example.com/ch1/p1.jpg';
    Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img, 'complete', { value: true, configurable: true });
    img.getBoundingClientRect = () => ({
      left: 0,
      top: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img);

    await initContentScript();
    expect(mockSendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'TRANSLATE_IMAGE',
        payload: expect.objectContaining({
          imageUrl: 'https://example.com/ch1/p1.jpg',
        }),
      })
    );

    // Simulate single-page reader flipping to page 2: window location updates and same <img> gets p2.jpg
    window.history.pushState({}, '', '/chapter/ch-1/2');
    img.src = 'https://example.com/ch1/p2.jpg';
    mockSendMessage.mockClear();

    await translateImageElement(img, 0, false);

    expect(mockSendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'TRANSLATE_IMAGE',
        payload: expect.objectContaining({
          imageUrl: 'https://example.com/ch1/p2.jpg',
        }),
      })
    );
  });

  it('does not cross-contaminate page cache between chapters upon chapter transition', async () => {
    mockSendMessage.mockClear();

    // 1. Visit Chapter 1, Page 3 on MangaDex
    window.history.pushState({}, '', '/chapter/ch-1111-1111/3');
    const img1 = document.createElement('img');
    img1.src = 'blob:https://mangadex.org/blob-ch1-p3';
    Object.defineProperty(img1, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img1, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img1, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img1, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img1, 'complete', { value: true, configurable: true });
    img1.getBoundingClientRect = () => ({
      top: 0,
      left: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.appendChild(img1);

    mockSendMessage.mockImplementationOnce((msg: IPCMessage) => {
      if (msg.type === 'TRANSLATE_IMAGE') {
        return Promise.resolve({
          success: true,
          traceId: msg.payload.traceId,
          data: {
            ...mockTranslation,
            page_hash: 'hash-ch1-p3',
            blocks: [{ id: 'b1', box: [100, 100, 200, 200], translated_text: 'Bản dịch Chap 1 Trang 3' }],
          },
        });
      }
      return Promise.resolve({ success: true, data: null });
    });

    await translateImageElement(img1, 0, false);
    const translateCalls1 = mockSendMessage.mock.calls.filter((call) => call[0]?.type === 'TRANSLATE_IMAGE');
    expect(translateCalls1.length).toBe(1);

    // 2. User transitions to Chapter 2, Page 3
    window.history.pushState({}, '', '/chapter/ch-2222-2222/3');
    const img2 = document.createElement('img');
    img2.src = 'blob:https://mangadex.org/blob-ch2-p3';
    Object.defineProperty(img2, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(img2, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(img2, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(img2, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(img2, 'complete', { value: true, configurable: true });
    img2.getBoundingClientRect = () => ({
      top: 0,
      left: 0,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });
    document.body.innerHTML = '';
    document.body.appendChild(img2);

    mockSendMessage.mockClear();
    mockSendMessage.mockImplementationOnce((msg: IPCMessage) => {
      if (msg.type === 'TRANSLATE_IMAGE') {
        return Promise.resolve({
          success: true,
          traceId: msg.payload.traceId,
          data: {
            ...mockTranslation,
            page_hash: 'hash-ch2-p3',
            blocks: [{ id: 'b1', box: [100, 100, 200, 200], translated_text: 'Bản dịch Chap 2 Trang 3' }],
          },
        });
      }
      return Promise.resolve({ success: true, data: null });
    });

    // Translate page 3 of Chapter 2
    await translateImageElement(img2, 0, false);

    // Ensure TRANSLATE_IMAGE was dispatched for Chapter 2, Page 3 instead of reusing Chapter 1's page cache!
    const translateCalls2 = mockSendMessage.mock.calls.filter((call) => call[0]?.type === 'TRANSLATE_IMAGE');
    expect(translateCalls2.length).toBe(1);
    expect(translateCalls2[0][0].payload.imageUrl).toBe('blob:https://mangadex.org/blob-ch2-p3');
  });

  describe('URL chapter and page extraction', () => {
    it('correctly extracts chapter UUID on MangaDex URLs', () => {
      const url1 = new URL('https://mangadex.org/chapter/8c697e0a-216b-44cf-8afd-7b741989a7dd/2');
      expect(extractChapterIdFromUrl(url1)).toBe('8c697e0a-216b-44cf-8afd-7b741989a7dd');

      const url2 = new URL('https://mangadex.org/chapter/8c697e0a-216b-44cf-8afd-7b741989a7dd/15');
      expect(extractChapterIdFromUrl(url2)).toBe('8c697e0a-216b-44cf-8afd-7b741989a7dd');
    });

    it('correctly extracts page number from trailing path segment', () => {
      const url1 = new URL('https://mangadex.org/chapter/8c697e0a-216b-44cf-8afd-7b741989a7dd/2');
      expect(extractPageNumberFromUrl(url1)).toBe(2);

      const url2 = new URL('https://mangadex.org/chapter/8c697e0a-216b-44cf-8afd-7b741989a7dd/15');
      expect(extractPageNumberFromUrl(url2)).toBe(15);

      const url3 = new URL('https://example.com/reader/chapter-1');
      expect(extractPageNumberFromUrl(url3)).toBe(1);
    });
  });

  describe('Resilient Page Number Resolution (resolveImagePageNumber)', () => {
    it('resolves page number from Tier 1 MangaDex DOM attributes', () => {
      const img1 = document.createElement('img');
      img1.setAttribute('data-page', '8');
      expect(resolveImagePageNumber(img1, 0)).toBe(8);

      const parent = document.createElement('div');
      parent.setAttribute('data-page', '9');
      const img2 = document.createElement('img');
      parent.appendChild(img2);
      expect(resolveImagePageNumber(img2, 0)).toBe(9);

      const img3 = document.createElement('img');
      img3.setAttribute('alt', 'Page 14');
      expect(resolveImagePageNumber(img3, 0)).toBe(14);

      const img4 = document.createElement('img');
      img4.setAttribute('title', 'Page 22');
      expect(resolveImagePageNumber(img4, 0)).toBe(22);
    });

    it('resolves page number from Tier 2 dataset index', () => {
      const img = document.createElement('img');
      img.setAttribute('data-index', '5');
      // 0-indexed data-index=5 maps to page 6
      expect(resolveImagePageNumber(img, 0)).toBe(6);
    });

    it('resolves page number from Tier 3 Chapter Manifest URL matching', () => {
      const img = document.createElement('img');
      img.src = 'https://uploads.mangadex.org/data/abc123hash/10-xyz.jpg?token=123';
      const manifestPages = [
        { page_number: 9, image_url: 'https://uploads.mangadex.org/data/abc123hash/09-xyz.jpg' },
        { page_number: 10, image_url: 'https://uploads.mangadex.org/data/abc123hash/10-xyz.jpg' },
      ];
      expect(resolveImagePageNumber(img, 0, manifestPages)).toBe(10);
    });

    it('resolves page number from Tier 4 single-page URL when in single-page mode', () => {
      window.history.replaceState({}, '', 'http://localhost:3000/chapter/ch-1/7');
      const img = document.createElement('img');
      img.src = 'blob:https://example.com/blob-random';
      expect(resolveImagePageNumber(img, 0)).toBe(7);
    });

    it('falls back to Tier 5 DOM order index when attributes and manifest are missing in multi-page/strip mode', () => {
      const container = document.createElement('div');
      container.className = 'reader--mode-long-strip';
      document.body.appendChild(container);

      const img = document.createElement('img');
      img.src = 'blob:https://example.com/blob-random';
      container.appendChild(img);

      expect(resolveImagePageNumber(img, 4)).toBe(5);
    });
  });

  describe('Viewport-Aware Layout Detection (detectCurrentReaderLayoutMode)', () => {
    it('detects double-page layout even when off-screen buffer images exist at negative left coordinates', () => {
      const container = document.createElement('div');
      document.body.appendChild(container);

      // Off-screen cached image (e.g. MangaDex carousel buffer page at left: -1920)
      const offscreenImg = document.createElement('img');
      offscreenImg.src = 'https://example.com/p1.jpg';
      Object.defineProperty(offscreenImg, 'clientWidth', { value: 900, configurable: true });
      Object.defineProperty(offscreenImg, 'clientHeight', { value: 1200, configurable: true });
      offscreenImg.getBoundingClientRect = () => ({
        left: -1920,
        top: 0,
        width: 900,
        height: 1200,
        right: -1020,
        bottom: 1200,
        x: -1920,
        y: 0,
        toJSON: () => {},
      });
      container.appendChild(offscreenImg);

      // On-screen left page of spread
      const leftPage = document.createElement('img');
      leftPage.src = 'https://example.com/p8.jpg';
      Object.defineProperty(leftPage, 'clientWidth', { value: 900, configurable: true });
      Object.defineProperty(leftPage, 'clientHeight', { value: 1200, configurable: true });
      leftPage.getBoundingClientRect = () => ({
        left: 50,
        top: 0,
        width: 900,
        height: 1200,
        right: 950,
        bottom: 1200,
        x: 50,
        y: 0,
        toJSON: () => {},
      });
      container.appendChild(leftPage);

      // On-screen right page of spread
      const rightPage = document.createElement('img');
      rightPage.src = 'https://example.com/p9.jpg';
      Object.defineProperty(rightPage, 'clientWidth', { value: 900, configurable: true });
      Object.defineProperty(rightPage, 'clientHeight', { value: 1200, configurable: true });
      rightPage.getBoundingClientRect = () => ({
        left: 960,
        top: 0,
        width: 900,
        height: 1200,
        right: 1860,
        bottom: 1200,
        x: 960,
        y: 0,
        toJSON: () => {},
      });
      container.appendChild(rightPage);

      const mode = detectCurrentReaderLayoutMode(container, [offscreenImg, leftPage, rightPage]);
      expect(mode).toBe('double');
    });

    it('toggles overlay visibility when Alt+Z is pressed, ignoring input fields', async () => {
      await initContentScript();

      // 1. Pressing Alt+Z outside input toggles overlay visibility
      const altZEvt = new KeyboardEvent('keydown', { key: 'z', altKey: true, bubbles: true });
      window.dispatchEvent(altZEvt);

      // Verify storage was called to persist
      expect(chrome.storage.local.set).toHaveBeenCalledWith(
        expect.objectContaining({ overlayVisible: false })
      );

      // 2. Pressing Alt+Z inside an input field is ignored
      const searchInput = document.createElement('input');
      document.body.appendChild(searchInput);
      searchInput.focus();

      const ignoredEvt = new KeyboardEvent('keydown', { key: 'z', altKey: true, bubbles: true });
      Object.defineProperty(ignoredEvt, 'target', { value: searchInput });
      expect(isTypingContext(searchInput)).toBe(true);

      handleGlobalKeyboardShortcuts(ignoredEvt);
      // set should not have been called with overlayVisible: true
      expect(chrome.storage.local.set).not.toHaveBeenCalledWith({ overlayVisible: true });
    });

    it('toggles Mascot HUD when Alt+M is pressed', async () => {
      await initContentScript();

      const altMEvt = new KeyboardEvent('keydown', { key: 'm', altKey: true, bubbles: true });
      window.dispatchEvent(altMEvt);

      expect(chrome.storage.local.set).toHaveBeenCalledWith(
        expect.objectContaining({ mascotEnabled: false })
      );
    });
  });

  describe('Blob URL Canvas Serialization & Rescan Synchronization', () => {
    it('serializeImageElementToDataUrl returns null for zero dimensions', () => {
      const img = document.createElement('img');
      img.width = 0;
      img.height = 0;
      const res = serializeImageElementToDataUrl(img);
      expect(res).toBeNull();
    });

    it('translateImageElement serializes blob: URL via canvas before dispatching IPC', async () => {
      const img = document.createElement('img');
      img.src = 'blob:https://mangadex.org/test-uuid-blob';
      Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
      Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
      Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
      Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
      document.body.appendChild(img);

      // Mock HTMLCanvasElement.prototype.toDataURL and getContext
      const mockDataUrl = 'data:image/jpeg;base64,mockSerializedBlob';
      vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
        drawImage: vi.fn(),
      } as unknown as CanvasRenderingContext2D);
      vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(mockDataUrl);

      await translateImageElement(img, 0, true);

      expect(mockSendMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'TRANSLATE_IMAGE',
          payload: expect.objectContaining({
            imageUrl: mockDataUrl,
            forceRefresh: true,
          }),
        })
      );
    });
  });
});

