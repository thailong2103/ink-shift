// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initContentScript,
  teardownContentScript,
} from '../../src/extension/content/content_script';
import { handleIPCMessage } from '../../src/extension/background/service_worker';
import { BackendGateway } from '../../src/extension/background/backend_gateway';
import type { TranslationResponse } from '../../src/types/contract';
import type { IPCMessage, IPCResponse } from '../../src/extension/shared/ipc_types';
import type { ProcessedImageResult } from '../../src/extension/background/cors_fetcher';

describe('Extension End-to-End Simulation Flow', () => {
  let mockGateway: BackendGateway;
  let mockFetcher: (url: string) => Promise<ProcessedImageResult>;
  let badgeCalls: Array<{ text: string; tabId?: number }>;

  const mockTranslationData: TranslationResponse = {
    success: true,
    page_hash: 'e2e-hash-1234',
    engine_used: 'gemini-2.5-flash',
    execution_time_ms: 180,
    from_cache: false,
    blocks: [
      {
        id: 'blk-e2e-1',
        box: [120, 200, 350, 600],
        translated_text: 'Đó là một sức mạnh khủng khiếp!',
      },
    ],
  };

  beforeEach(() => {
    document.body.innerHTML = '';
    badgeCalls = [];

    // Mock Gateway methods
    mockGateway = new BackendGateway('http://127.0.0.1:8000');
    vi.spyOn(mockGateway, 'checkCache').mockResolvedValue(null);
    vi.spyOn(mockGateway, 'requestTranslation').mockResolvedValue(mockTranslationData);

    // Mock CORS Fetcher
    mockFetcher = vi.fn().mockImplementation(async (url: string) => ({
      buffer: new ArrayBuffer(0),
      sha256Hex: url.includes('002.jpg') ? 'e2e-hash-5678' : 'e2e-hash-1234',
      base64: 'base64-e2e-payload',
      mimeType: 'image/jpeg',
      sizeBytes: 4096,
    }));


    // Wire up true IPC loop: content script -> handleIPCMessage -> response
    vi.stubGlobal('chrome', {
      runtime: {
        sendMessage: vi.fn().mockImplementation((msg: IPCMessage) => {
          return handleIPCMessage(
            msg,
            { tab: { id: 777 } } as unknown as chrome.runtime.MessageSender,
            mockGateway,
            mockFetcher
          );
        }),
        onMessage: {
          addListener: vi.fn(),
          removeListener: vi.fn(),
        },
      },
      action: {
        setBadgeText: vi.fn((opts) => badgeCalls.push(opts)),
        setBadgeBackgroundColor: vi.fn(),
      },
      storage: {
        local: {
          get: vi.fn().mockResolvedValue({ opacity: 'semi-transparent', debugGeometry: false }),
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

  it('executes complete translation lifecycle: detection -> SW IPC -> Shadow DOM rendering -> badge tracking', async () => {
    // 1. Create page DOM with 2 manga pages and 1 banner ad
    const mangaImg1 = document.createElement('img');
    mangaImg1.src = 'https://cdn.manga.org/ch1/001.jpg';
    Object.defineProperty(mangaImg1, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(mangaImg1, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(mangaImg1, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(mangaImg1, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(mangaImg1, 'complete', { value: true, configurable: true });
    mangaImg1.getBoundingClientRect = () => ({
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

    const mangaImg2 = document.createElement('img');
    mangaImg2.src = 'https://cdn.manga.org/ch1/002.jpg';
    Object.defineProperty(mangaImg2, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(mangaImg2, 'clientHeight', { value: 1200, configurable: true });
    Object.defineProperty(mangaImg2, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(mangaImg2, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(mangaImg2, 'complete', { value: true, configurable: true });
    mangaImg2.getBoundingClientRect = () => ({
      left: 0,
      top: 1300,
      width: 800,
      height: 1200,
      right: 800,
      bottom: 2500,
      x: 0,
      y: 1300,
      toJSON: () => {},
    });

    const adBanner = document.createElement('img');
    adBanner.className = 'ad-banner-widget';
    adBanner.src = 'https://ads.track.org/banner.png';
    Object.defineProperty(adBanner, 'clientWidth', { value: 728, configurable: true });
    Object.defineProperty(adBanner, 'clientHeight', { value: 90, configurable: true });

    document.body.appendChild(mangaImg1);
    document.body.appendChild(adBanner);
    document.body.appendChild(mangaImg2);

    // 2. Initialize content script
    await initContentScript();

    // 3. Verify ad banner was filtered out and only 2 overlay hosts exist
    const hosts = document.querySelectorAll('.ink-shift-overlay-host');
    expect(hosts.length).toBe(2);

    // 4. Verify speech bubbles are isolated inside Shadow Roots
    const host1 = hosts[0];
    expect(host1.shadowRoot).not.toBeNull();
    const bubble1 = host1.shadowRoot!.querySelector('.inkshift-speech-bubble');
    expect(bubble1).not.toBeNull();
    expect(bubble1!.textContent).toBe('Đó là một sức mạnh khủng khiếp!');

    // 5. Verify diagnostic status pill is present and marked completed
    const pill1 = host1.shadowRoot!.querySelector('.inkshift-status-pill') as HTMLElement;
    expect(pill1).not.toBeNull();
    expect(pill1.dataset.status).toBe('completed');
    expect(pill1.textContent).toContain('✓ 1');

    // 6. Verify Service Worker tracked badge counts
    expect(badgeCalls.length).toBeGreaterThan(0);
    const lastBadge = badgeCalls[badgeCalls.length - 1];
    expect(lastBadge.text).toBe('2');
    expect(lastBadge.tabId).toBe(777);

    // 7. Verify teardown cleanly cleans DOM without leftovers
    teardownContentScript();
    expect(document.querySelectorAll('.ink-shift-overlay-host').length).toBe(0);
  });
});
