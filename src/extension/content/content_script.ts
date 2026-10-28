/**
 * InkShift Chromium Content Script Entry Point & Orchestrator.
 *
 * In-page manga reader coordinator: discovers manga images, dispatches
 * concurrent IPC requests to privileged background service worker with traceId,
 * and mounts isolated Shadow DOM overlays with Vietnamese typography.
 */

import type { IPCMessage, IPCResponse } from '../shared/ipc_types';
import type { TranslationResponse, EngineMode } from '../../types/contract';
import { findMangaImages, waitForImageReady } from './dom_scanner';
import {
  mountOverlay,
  updateStatus,
  removeOverlay,
  teardownAll,
  updateOverlayPosition,
  updateActiveOverlaysAppearance,
  syncOverlaysVisibilityAndPosition,
  getOverlayHost,
  type OverlayOpacity,
  type ReaderLayoutMode,
} from './overlay_manager';
import {
  setupObservers,
  disconnectObservers,
  observeImageResize,
} from './observers';
import {
  isDomainAllowed,
  loadDomainFilterSettings,
  type DomainFilterSettings,
} from '../shared/domain_filter';
import {
  detectReaderContext,
  type ReaderDetectionResult,
} from './reader_detector';
import { extractChapterManifest } from './page_manifest_extractor';
import type { ChapterContextReport } from '../shared/context_types';
import { PrefetchScheduler, type PrefetchDepth } from './prefetch_scheduler';
import { ReadingProgressTracker } from './reading_progress_tracker';
import type { PageReaderStatusData } from '../shared/ipc_types';
import { createExtensionLogger } from '../shared/extension_logger';
import { MascotHUD } from './mascot_hud';

const logger = createExtensionLogger('CS');

export interface ContentScriptConfig {
  opacity?: OverlayOpacity | number;
  overlayOpacity?: number;
  overlayColor?: string;
  overlayVisible?: boolean;
  speechBubbleFont?: string;
  debugGeometry?: boolean;
  engine?: EngineMode;
  provider?: string;
  translator?: string;
  model?: string;
  sourceLang?: string;
  prefetchEnabled?: boolean;
  prefetchDepth?: PrefetchDepth;
}

let activeConfig: ContentScriptConfig = {
  opacity: 'semi-transparent',
  overlayOpacity: 88,
  overlayColor: '#ffffff',
  overlayVisible: true,
  speechBubbleFont: 'itim',
  debugGeometry: false,
  prefetchEnabled: true,
  prefetchDepth: 3,
};

let activeScheduler: PrefetchScheduler | null = null;
let activeProgressTracker: ReadingProgressTracker | null = null;
let activeChapterId: string | null = null;
let spaDebounceTimer: ReturnType<typeof setTimeout> | null = null;
let activeMascotHUD: MascotHUD | null = null;

export function getActiveMascotHUD(): MascotHUD | null {
  return activeMascotHUD;
}

let keyboardShortcutListener: ((e: KeyboardEvent) => void) | null = null;

export function isTypingContext(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false;
  const tagName = target.tagName;
  return (
    tagName === 'INPUT' ||
    tagName === 'TEXTAREA' ||
    tagName === 'SELECT' ||
    target.isContentEditable ||
    (Boolean(document.activeElement) &&
      (document.activeElement?.tagName === 'INPUT' ||
        document.activeElement?.tagName === 'TEXTAREA' ||
        (document.activeElement as HTMLElement)?.isContentEditable))
  );
}

export function handleGlobalKeyboardShortcuts(e: KeyboardEvent): void {
  // Ignore when user is actively typing in text inputs or IME composition
  if (e.isComposing || isTypingContext(e.target)) {
    return;
  }

  // Alt + Z: Toggle translation overlays visibility
  if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'z' || e.key === 'Z')) {
    e.preventDefault();
    const nextVisibility = activeConfig.overlayVisible === false;
    activeConfig.overlayVisible = nextVisibility;
    logger.info(`Toggled overlay visibility via Alt+Z shortcut: ${nextVisibility ? 'ON' : 'OFF'}`);

    updateActiveOverlaysAppearance({ visible: nextVisibility });
    if (activeMascotHUD) {
      activeMascotHUD.setState(nextVisibility ? 'reading' : 'sleeping');
    }
    if (nextVisibility) {
      const mode = detectCurrentReaderLayoutMode(activeDetection?.readerContainer);
      syncOverlaysVisibilityAndPosition({ layoutMode: mode });
    }

    if (typeof chrome !== 'undefined' && chrome.storage?.local?.set) {
      chrome.storage.local.set({ overlayVisible: nextVisibility }).catch(() => {});
    }
    return;
  }

  // Alt + M: Toggle Mascot HUD visibility
  if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'm' || e.key === 'M')) {
    e.preventDefault();
    const currentEnabled = activeMascotHUD ? activeMascotHUD.isEnabled() : true;
    const nextEnabled = !currentEnabled;
    logger.info(`Toggled Mascot HUD via Alt+M shortcut: ${nextEnabled ? 'ON' : 'OFF'}`);

    if (activeMascotHUD) {
      activeMascotHUD.setEnabled(nextEnabled);
    }
    if (typeof chrome !== 'undefined' && chrome.storage?.local?.set) {
      chrome.storage.local.set({ mascotEnabled: nextEnabled }).catch(() => {});
    }
  }
}


const processedImages = new Set<HTMLImageElement>();
const translationCacheByUrl = new Map<string, TranslationResponse>();
const translationCacheByPage = new Map<string, TranslationResponse>();
const imageProcessedUrlMap = new WeakMap<HTMLImageElement, string>();
let isInitialized = false;
let isSpaHookInstalled = false;
let activeDetection: ReaderDetectionResult | null = null;
let activeDomainSettings: DomainFilterSettings | null = null;
let activeManifest: ChapterContextReport | null = null;

function getPageCacheKey(chapterId: string | null | undefined, pageNumber: number): string {
  return `${chapterId || 'unknown'}:${pageNumber}`;
}

function getNormalizedImageUrl(url: string): string {
  return url ? url.split('?')[0] : '';
}

export function detectCurrentReaderLayoutMode(
  container?: Element | null,
  candidateImages?: HTMLImageElement[]
): ReaderLayoutMode {
  // 1. Check Reader Container / Document Class Indicators
  if (typeof document !== 'undefined') {
    const hasStripClass = Boolean(
      document.querySelector(
        '.reader--mode-long-strip, .reader--mode-webtoon, .reader--layout-strip, [data-reader-mode="long-strip"], [data-reader-mode="webtoon"]'
      ) ||
        container?.classList?.contains('reader--mode-long-strip') ||
        container?.classList?.contains('reader--mode-webtoon') ||
        container?.getAttribute('data-reader-mode') === 'long-strip' ||
        container?.getAttribute('data-reader-mode') === 'webtoon'
    );
    if (hasStripClass) {
      return 'strip';
    }

    const hasDoubleClass = Boolean(
      document.querySelector(
        '.reader--mode-double, [data-reader-mode="double"], .reader--fit-both'
      ) ||
        container?.classList?.contains('reader--mode-double') ||
        container?.getAttribute('data-reader-mode') === 'double'
    );
    if (hasDoubleClass) {
      return 'double';
    }

    // Check MangaDex localStorage settings if available
    const isMangaDex =
      (typeof window !== 'undefined' && window.location.hostname.includes('mangadex.org')) ||
      Boolean(activeDetection?.signals.some((s) => s.details?.toLowerCase().includes('mangadex')));

    if (isMangaDex) {

      // Check MangaDex localStorage settings if available
      try {
        if (typeof window !== 'undefined' && window.localStorage) {
          const rawSetting =
            window.localStorage.getItem('reader-settings') ||
            window.localStorage.getItem('reader-mode');
          if (rawSetting) {
            const lower = rawSetting.toLowerCase();
            if (lower.includes('long-strip') || lower.includes('webtoon')) return 'strip';
            if (lower.includes('double') || lower.includes('spread')) return 'double';
            if (lower.includes('single')) return 'single';
          }
        }
      } catch {
        // Fall through to DOM geometry inspection
      }
    }
  }

  // 2. DOM Geometry Fallback (Universal for any manga website)
  const root = container ?? (typeof document !== 'undefined' ? document.body : null);
  const images =
    candidateImages && candidateImages.length > 0
      ? candidateImages
      : root
        ? findMangaImages(root)
        : [];

  const vpWidth = typeof window !== 'undefined' && window.innerWidth > 0 ? window.innerWidth : 1920;
  const vpHeight = typeof window !== 'undefined' && window.innerHeight > 0 ? window.innerHeight : 1080;

  // Filter strictly for visible images intersecting the visible viewport
  const visibleImages = images.filter((img) => {
    if (!img.isConnected || img.clientWidth <= 0 || img.clientHeight <= 0) {
      return false;
    }
    const r = img.getBoundingClientRect();
    return (
      r.width > 50 &&
      r.height > 50 &&
      r.right > 10 &&
      r.left < vpWidth - 10 &&
      r.bottom > 10 &&
      r.top < vpHeight - 10
    );
  });

  if (visibleImages.length >= 2) {
    const r0 = visibleImages[0].getBoundingClientRect();
    const r1 = visibleImages[1].getBoundingClientRect();

    // Check if horizontally adjacent in viewport (Double Page Spread)
    if (Math.abs(r0.top - r1.top) < 80) {
      return 'double';
    }

    // Check if stacked vertically (Long Strip)
    if (r1.top >= r0.bottom - 60 || r0.top >= r1.bottom - 60) {
      return 'strip';
    }
  }

  // 3. Fallback to activeDetection layout type if available
  if (activeDetection?.layoutType === 'long-strip') {
    return 'strip';
  }
  if (activeDetection?.layoutType === 'single-page') {
    return 'single';
  }

  return 'single';
}

function isSinglePageReader(container?: Element | null): boolean {
  return detectCurrentReaderLayoutMode(container ?? activeDetection?.readerContainer) === 'single';
}

/**
 * Resilient multi-tier page number resolver.
 * Tier 1: MangaDex DOM attributes (data-page, alt="Page X", title="Page X").
 * Tier 2: Universal dataset attributes (data-index, dataset.page).
 * Tier 3: Chapter Manifest URL matching (against manifest.pages).
 * Tier 4: Single-page URL trailing segment (/chapter/.../X).
 * Tier 5: DOM order index fallback.
 */
export function resolveImagePageNumber(
  img: HTMLImageElement,
  fallbackIndex: number,
  manifestPages?: Array<{ page_number: number; image_url: string }>
): number {
  // Tier 1: MangaDex DOM Attributes
  const dataPage =
    img.getAttribute('data-page') ||
    img.dataset.page ||
    img.closest('[data-page]')?.getAttribute('data-page');
  if (dataPage) {
    const parsed = parseInt(dataPage, 10);
    if (!isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }

  const alt = img.getAttribute('alt') || '';
  const altMatch = alt.match(/page\s*(\d+)/i);
  if (altMatch && altMatch[1]) {
    const parsed = parseInt(altMatch[1], 10);
    if (!isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }

  const title = img.getAttribute('title') || '';
  const titleMatch = title.match(/page\s*(\d+)/i);
  if (titleMatch && titleMatch[1]) {
    const parsed = parseInt(titleMatch[1], 10);
    if (!isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }

  // Tier 2: Universal dataset attributes
  const dataIndex = img.dataset.index || img.getAttribute('data-index');
  if (dataIndex) {
    const parsed = parseInt(dataIndex, 10);
    if (!isNaN(parsed)) {
      return parsed >= 0 ? parsed + 1 : fallbackIndex + 1;
    }
  }

  // Tier 3: Chapter Manifest URL Matching
  if (manifestPages && manifestPages.length > 0) {
    const rawSrc = img.currentSrc || img.src || img.getAttribute('data-src') || '';
    if (rawSrc) {
      const normalizedSrc = getNormalizedImageUrl(rawSrc);
      const matched = manifestPages.find((p) => {
        if (!p.image_url) return false;
        const normP = getNormalizedImageUrl(p.image_url);
        return normP === normalizedSrc || rawSrc.includes(p.image_url) || p.image_url.includes(rawSrc);
      });
      if (matched && matched.page_number > 0) {
        return matched.page_number;
      }
    }
  }

  // Tier 4: Single Page URL fallback (strictly when in single-page mode and URL has an explicit numeric page segment)
  const container =
    img.closest('.reader, [data-reader-mode], .reader--mode-long-strip, .reader--mode-double') ||
    img.parentElement ||
    activeDetection?.readerContainer;

  if (isSinglePageReader(container) && typeof window !== 'undefined') {
    const segments = window.location.pathname.split('/').filter(Boolean);
    if (segments.length >= 1) {
      const last = segments[segments.length - 1];
      const parsed = parseInt(last, 10);
      if (!isNaN(parsed) && parsed > 0) {
        return parsed;
      }
    }
  }

  // Tier 5: Fallback to DOM image index
  return fallbackIndex + 1;
}

let scrollRafId: number | null = null;
let attachedScrollContainer: Element | null = null;

function handleScrollOrLayoutShift(): void {
  if (scrollRafId !== null) {
    return;
  }
  if (activeMascotHUD && activeMascotHUD.getState() === 'idle' && activeConfig.overlayVisible !== false) {
    activeMascotHUD.setState('reading');
  }
  scrollRafId =
    typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function'
      ? window.requestAnimationFrame(() => {
          scrollRafId = null;
          const mode = detectCurrentReaderLayoutMode(activeDetection?.readerContainer);
          syncOverlaysVisibilityAndPosition({ layoutMode: mode });
        })
      : (setTimeout(() => {
          scrollRafId = null;
          const mode = detectCurrentReaderLayoutMode(activeDetection?.readerContainer);
          syncOverlaysVisibilityAndPosition({ layoutMode: mode });
        }, 16) as unknown as number);
}
let messageListener:
  | ((
      message: any,
      sender: chrome.runtime.MessageSender,
      sendResponse: (response?: any) => void
    ) => boolean | void)
  | null = null;
let storageListener:
  | ((changes: { [key: string]: chrome.storage.StorageChange }, areaName: string) => void)
  | null = null;

function generateTraceId(index: number): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `trace-${crypto.randomUUID()}`;
  }
  return `trace-${Date.now()}-${index}-${Math.random().toString(36).substring(2, 8)}`;
}

export async function loadConfigFromStorage(): Promise<ContentScriptConfig> {
  if (typeof chrome !== 'undefined' && chrome.storage?.local) {
    try {
      const stored = await chrome.storage.local.get([
        'opacity',
        'overlayOpacity',
        'overlayColor',
        'speechBubbleFont',
        'overlayVisible',
        'debugGeometry',
        'engine',
        'provider',
        'translator',
        'model',
        'selected_models',
        'sourceLang',
        'prefetchEnabled',
        'prefetchDepth',
      ]);
      if (stored) {
        if (typeof stored.prefetchEnabled === 'boolean') {
          activeConfig.prefetchEnabled = stored.prefetchEnabled;
          activeScheduler?.setEnabled(stored.prefetchEnabled);
        }
        if (stored.prefetchDepth !== undefined) {
          const depth = stored.prefetchDepth === 'all' ? 'all' : (Number(stored.prefetchDepth) as PrefetchDepth);
          activeConfig.prefetchDepth = depth;
          activeScheduler?.setDepth(depth);
        }
        if (typeof stored.overlayVisible === 'boolean') {

          activeConfig.overlayVisible = stored.overlayVisible;
        }
        if (typeof stored.overlayColor === 'string' && stored.overlayColor) {
          activeConfig.overlayColor = stored.overlayColor;
        }
        if (typeof stored.speechBubbleFont === 'string' && stored.speechBubbleFont) {
          activeConfig.speechBubbleFont = stored.speechBubbleFont;
        }
        if (typeof stored.overlayOpacity === 'number') {
          activeConfig.overlayOpacity = stored.overlayOpacity;
          activeConfig.opacity = stored.overlayOpacity;
        } else if (stored.opacity === 'opaque') {
          activeConfig.overlayOpacity = 100;
          activeConfig.opacity = 'opaque';
        } else if (stored.opacity === 'semi-transparent') {
          activeConfig.overlayOpacity = 88;
          activeConfig.opacity = 'semi-transparent';
        }

        if (typeof stored.debugGeometry === 'boolean') {
          activeConfig.debugGeometry = stored.debugGeometry;
        }
        if (stored.engine) {
          let mappedEngine = stored.engine;
          if (mappedEngine === 'local-manga' || mappedEngine === 'local-rapid') {
            mappedEngine = 'local';
          } else if (mappedEngine === 'cloud-gemini' || mappedEngine === 'cloud-xkiro') {
            mappedEngine = 'cloud';
          }
          activeConfig.engine = mappedEngine;
        }
        if (typeof stored.provider === 'string') {
          activeConfig.provider = stored.provider;
        }
        if (typeof stored.translator === 'string') {
          activeConfig.translator = stored.translator;
        }
        if (typeof stored.model === 'string') {
          activeConfig.model = stored.model;
        }
        if (stored.selected_models && typeof stored.selected_models === 'object') {
          const activeProvider = activeConfig.provider || 'google';
          const selectedMap = stored.selected_models as Record<string, string>;
          if (selectedMap[activeProvider]) {
            activeConfig.model = selectedMap[activeProvider];
          }
        }
        if (typeof stored.sourceLang === 'string') {
          activeConfig.sourceLang = stored.sourceLang;
        }
        if (activeScheduler) {
          activeScheduler.setConfig({
            engine: activeConfig.engine,
            provider: activeConfig.provider,
            translator: activeConfig.translator,
            model: activeConfig.model,
            sourceLang: activeConfig.sourceLang,
          });
        }
      }
    } catch {
      // Default config on storage access fallback
    }
  }
  return activeConfig;
}

export function serializeImageElementToDataUrl(img: HTMLImageElement): string | null {
  try {
    const canvas = document.createElement('canvas');
    const width = img.naturalWidth || (img as unknown as { videoWidth?: number }).videoWidth || img.width || img.clientWidth;
    const height = img.naturalHeight || (img as unknown as { videoHeight?: number }).videoHeight || img.height || img.clientHeight;
    if (width <= 0 || height <= 0) {
      return null;
    }
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return null;
    }
    ctx.drawImage(img, 0, 0, width, height);
    return canvas.toDataURL('image/jpeg', 0.92);
  } catch (err) {
    logger.warn('Failed to serialize image element to DataURL via canvas:', err);
    return null;
  }
}

export async function translateImageElement(
  img: HTMLImageElement,
  index: number,
  forceRefresh: boolean = false
): Promise<void> {
  const rawUrl = img.currentSrc || img.src || img.getAttribute('data-src') || '';
  const normalizedUrl = getNormalizedImageUrl(rawUrl);
  const previousUrl = imageProcessedUrlMap.get(img);

  // If the element was previously processed with a different image URL,
  // the reader has recycled the DOM <img> element for a new page (e.g. MangaDex single-page carousel).
  // We must tear down the old overlay on this element to allow fresh translation.
  if (previousUrl && normalizedUrl && previousUrl !== normalizedUrl) {
    logger.info(
      `Detected recycled <img> element with new URL on image #${index}. Tearing down previous overlay.`,
      { previousUrl, normalizedUrl, imageIndex: index }
    );
    removeOverlay(img);
    processedImages.delete(img);
  }

  // If overlay is already mounted on this element and URL hasn't changed, ensure positioning and return
  const existingHost = getOverlayHost(img);
  if (existingHost && !forceRefresh) {
    logger.debug(
      `Skipping image #${index}: overlay host already active for this element (URL: ${normalizedUrl || 'empty'})`,
      { imageIndex: index, normalizedUrl }
    );
    syncOverlaysVisibilityAndPosition({
      layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
    });
    return;
  }

  if (processedImages.has(img) && !forceRefresh) {
    logger.debug(
      `Skipping image #${index}: element already marked as processed (URL: ${normalizedUrl || 'empty'})`,
      { imageIndex: index, normalizedUrl }
    );
    return;
  }

  // Guard against unready dimensions
  await waitForImageReady(img, 1500);

  const clientWidth = img.clientWidth;
  const clientHeight = img.clientHeight;

  if (clientWidth <= 0 || clientHeight <= 0) {
    logger.warn(
      `Skipping image #${index}: zero dimensions detected (${clientWidth}x${clientHeight})`,
      { imageIndex: index, clientWidth, clientHeight, url: normalizedUrl }
    );
    return;
  }

  processedImages.add(img);
  if (normalizedUrl) {
    imageProcessedUrlMap.set(img, normalizedUrl);
  }

  const traceId = generateTraceId(index);

  // Hook resize observer for live layout drift correction
  observeImageResize(img, () => {
    updateOverlayPosition(img);
  });

  const currentPageNumber = resolveImagePageNumber(img, index, activeManifest?.pages);

  const currentChapterId =
    activeChapterId ||
    (typeof window !== 'undefined' ? extractChapterIdFromUrl(new URL(window.location.href)) : '');
  const pageCacheKey = getPageCacheKey(currentChapterId, currentPageNumber);

  // Check frontend in-memory translation cache (Zero-Wait Page Flip deduplication)
  // Check both by normalized CDN URL and by chapter-scoped page number (crucial for blob: URLs on MangaDex)
  let cachedResponse: TranslationResponse | undefined = undefined;
  let cacheKeyType = '';

  if (!forceRefresh) {
    if (normalizedUrl && translationCacheByUrl.has(normalizedUrl)) {
      cachedResponse = translationCacheByUrl.get(normalizedUrl);
      cacheKeyType = 'url';
    } else if (translationCacheByPage.has(pageCacheKey)) {
      cachedResponse = translationCacheByPage.get(pageCacheKey);
      cacheKeyType = 'page_number';
    }
  }

  if (cachedResponse) {
    mountOverlay(img, cachedResponse, {
      opacity: activeConfig.overlayOpacity ?? activeConfig.opacity,
      color: activeConfig.overlayColor,
      fontFamily: activeConfig.speechBubbleFont,
      visible: activeConfig.overlayVisible,
      debugGeometry: activeConfig.debugGeometry,
    });
    syncOverlaysVisibilityAndPosition({
      layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
    });
    activeScheduler?.markPageCompleted(currentPageNumber);
    if (activeConfig.overlayVisible !== false) {
      activeMascotHUD?.setState('success');
    }
    logger.info(
      `Mounted overlay from prefetch cache (${cacheKeyType}) for image #${index} (page #${currentPageNumber}, ${cachedResponse.blocks.length} blocks)`,
      { trace_id: traceId, imageIndex: index, pageNum: currentPageNumber, blocks: cachedResponse.blocks.length, cacheKeyType }
    );
    return;
  } else if (!forceRefresh) {
    logger.debug(
      `Prefetch cache miss for image #${index} (page #${currentPageNumber}, URL: ${normalizedUrl})`,
      { imageIndex: index, pageNum: currentPageNumber, url: normalizedUrl }
    );
  }

  // Resolve blob: URLs to canonical manifest CDN URLs or serialize to canvas Base64 data URL
  let effectiveImageUrl = rawUrl;
  if (rawUrl.startsWith('blob:')) {
    const manifestPage = activeManifest?.pages?.find((p) => p.page_number === currentPageNumber);
    if (manifestPage?.image_url && !manifestPage.image_url.startsWith('blob:')) {
      effectiveImageUrl = manifestPage.image_url;
      logger.info(
        `Resolved blob: URL to canonical manifest CDN URL for page #${currentPageNumber}: ${effectiveImageUrl}`,
        { page: currentPageNumber, rawUrl, canonicalUrl: effectiveImageUrl }
      );
    } else {
      const canvasDataUrl = serializeImageElementToDataUrl(img);
      if (canvasDataUrl) {
        effectiveImageUrl = canvasDataUrl;
        logger.info(
          `Serialized blob: image #${index} (page #${currentPageNumber}) to canvas Base64 data URL (${Math.round(canvasDataUrl.length / 1024)} KB)`
        );
      } else {
        logger.warn(`Could not serialize blob: image #${index} to canvas. Falling back to raw blob URL.`);
      }
    }
  }

  const message: IPCMessage = {
    type: 'TRANSLATE_IMAGE',
    payload: {
      traceId,
      imageIndex: index,
      imageUrl: effectiveImageUrl,
      clientWidth,
      clientHeight,
      engine: activeConfig.engine,
      provider: activeConfig.provider,
      translator: activeConfig.translator,
      model: activeConfig.model,
      sourceLang: activeConfig.sourceLang,
      chapterUrl: typeof window !== 'undefined' ? window.location.href : undefined,
      forceRefresh: forceRefresh || undefined,
    },
  };

  logger.info(
    `Dispatched image #${index} (${clientWidth}x${clientHeight}) to background for translation...`,
    { trace_id: traceId, imageIndex: index, clientWidth, clientHeight }
  );

  if (activeConfig.overlayVisible !== false) {
    activeMascotHUD?.setState('translating');
  }

  try {
    const response = (await chrome.runtime.sendMessage(message)) as IPCResponse<TranslationResponse>;

    if (response && response.success === true && response.data) {
      if (normalizedUrl) {
        translationCacheByUrl.set(normalizedUrl, response.data);
      }
      translationCacheByPage.set(pageCacheKey, response.data);
      mountOverlay(img, response.data, {
        opacity: activeConfig.overlayOpacity ?? activeConfig.opacity,
        color: activeConfig.overlayColor,
        fontFamily: activeConfig.speechBubbleFont,
        visible: activeConfig.overlayVisible,
        debugGeometry: activeConfig.debugGeometry,
      });
      syncOverlaysVisibilityAndPosition({
        layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
      });
      activeScheduler?.markPageCompleted(currentPageNumber);
      if (activeConfig.overlayVisible !== false) {
        activeMascotHUD?.setState('success');
      }
      logger.info(
        `Mounted translated overlay for image #${index} (${response.data.blocks.length} blocks)`,
        { trace_id: traceId, imageIndex: index, blocks: response.data.blocks.length }
      );
    } else {
      const err =
        response && !response.success
          ? response.error
          : { code: 'UNKNOWN_ERROR', message: 'Translation failed' };

      logger.warn(
        `Image translation failed for #${index}: ${err.code} - ${err.message}`,
        { trace_id: traceId, imageIndex: index, code: err.code }
      );

      if (activeConfig.overlayVisible !== false) {
        activeMascotHUD?.setState('error');
      }

      // Mount base host and set status pill with error diagnostics
      mountOverlay(
        img,
        {
          success: true,
          page_hash: '',
          engine_used: '',
          execution_time_ms: 0,
          from_cache: false,
          blocks: [],
        },
        {
          opacity: activeConfig.overlayOpacity ?? activeConfig.opacity,
          color: activeConfig.overlayColor,
          fontFamily: activeConfig.speechBubbleFont,
          visible: activeConfig.overlayVisible,
          debugGeometry: activeConfig.debugGeometry,
        }
      );
      updateStatus(img, {
        status: 'failed',
        errorCode: err.code,
        errorMessage: err.message,
      });
    }
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    logger.warn(`IPC dispatch error for image #${index}: ${errorMsg}`, {
      trace_id: traceId,
      imageIndex: index,
    });
    if (activeConfig.overlayVisible !== false) {
      activeMascotHUD?.setState('error');
    }
    mountOverlay(
      img,
      {
        success: true,
        page_hash: '',
        engine_used: '',
        execution_time_ms: 0,
        from_cache: false,
        blocks: [],
      },
      {
        opacity: activeConfig.overlayOpacity ?? activeConfig.opacity,
        color: activeConfig.overlayColor,
        fontFamily: activeConfig.speechBubbleFont,
        visible: activeConfig.overlayVisible,
        debugGeometry: activeConfig.debugGeometry,
      }
    );
    updateStatus(img, {
      status: 'failed',
      errorCode: 'IPC_DISPATCH_FAILED',
      errorMessage: errorMsg,
    });
  }
}

export async function scanAndTranslate(
  forceRefresh: boolean = false,
  rootContainer?: Element
): Promise<number> {
  const targetRoot = rootContainer ?? activeDetection?.readerContainer;
  let images = findMangaImages(targetRoot);

  // If scoped container yielded 0 images, fallback to document.body
  if (
    images.length === 0 &&
    targetRoot &&
    targetRoot !== document.body &&
    targetRoot !== document.documentElement
  ) {
    images = findMangaImages(document.body);
  }

  // If no images found on initial synchronous query, wait briefly (350ms) for SPA lazy-attach
  if (images.length === 0 && typeof window !== 'undefined') {
    await new Promise((resolve) => setTimeout(resolve, 350));
    images = findMangaImages(targetRoot);
    if (
      images.length === 0 &&
      targetRoot &&
      targetRoot !== document.body &&
      targetRoot !== document.documentElement
    ) {
      images = findMangaImages(document.body);
    }
  }

  const rootDesc = targetRoot
    ? `<${targetRoot.tagName.toLowerCase()}${targetRoot.className ? `.${targetRoot.className.replace(/\s+/g, '.')}` : ''}>`
    : 'document';
  const totalDocImages = typeof document !== 'undefined' ? document.querySelectorAll('img').length : 0;

  logger.info(
    `Scanning page (container: ${rootDesc}): Found ${images.length} valid manga images (total ${totalDocImages} images on page)`,
    { imagesCount: images.length, totalDocImages }
  );
  if (images.length === 0) {
    logger.warn('No images matching manga reader dimensions (>= 300px) found on this page.');
  } else if (activeConfig.overlayVisible !== false) {
    activeMascotHUD?.setState('scanning');
  }

  // Viewport-aware prioritization for Long Strip chapters
  const layoutMode = detectCurrentReaderLayoutMode(targetRoot, images);
  logger.info(
    `Reader layout mode detected: '${layoutMode}' for ${images.length} manga images`,
    { layoutMode, imagesCount: images.length, container: rootDesc }
  );
  if (layoutMode === 'strip' && images.length > 5) {
    const vpHeight = typeof window !== 'undefined' && window.innerHeight ? window.innerHeight : 800;
    const priorityImages: { img: HTMLImageElement; idx: number }[] = [];
    const distantImages: { img: HTMLImageElement; idx: number }[] = [];

    images.forEach((img, idx) => {
      const rect = typeof img.getBoundingClientRect === 'function' ? img.getBoundingClientRect() : null;
      if (!rect || (rect.top <= vpHeight * 2.5 && rect.bottom >= -vpHeight * 1.5)) {
        priorityImages.push({ img, idx });
      } else {
        distantImages.push({ img, idx });
      }
    });

    const priorityTasks = priorityImages.map(({ img, idx }) =>
      translateImageElement(img, idx, forceRefresh)
    );
    await Promise.all(priorityTasks);
    syncOverlaysVisibilityAndPosition({ layoutMode });

    // Asynchronously dispatch distant pages without blocking current viewport
    if (distantImages.length > 0) {
      Promise.all(
        distantImages.map(({ img, idx }) =>
          translateImageElement(img, idx, forceRefresh).catch(() => {})
        )
      ).catch(() => {});
    }
  } else {
    const tasks = images.map((img, idx) => translateImageElement(img, idx, forceRefresh));
    await Promise.all(tasks);
    syncOverlaysVisibilityAndPosition({ layoutMode });
  }

  if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage && images.length > 0) {
    const badgeMsg: IPCMessage = {
      type: 'UPDATE_TAB_BADGE',
      payload: {
        translated: processedImages.size,
        total: images.length,
      },
    };
    await chrome.runtime.sendMessage(badgeMsg).catch(() => {});
  }

  return images.length;
}

export function extractChapterIdFromUrl(url: URL): string {
  const hostname = url.hostname.toLowerCase();
  if (hostname.includes('mangadex.org')) {
    const match = url.pathname.match(/\/chapter\/([a-f0-9-]+)/i);
    if (match && match[1]) {
      return match[1];
    }
  }
  return `${hostname}:${url.pathname.replace(/^\/|\/$/g, '') || 'ch'}`;
}

export function extractPageNumberFromUrl(url: URL): number {
  const segments = url.pathname.split('/').filter(Boolean);
  if (segments.length >= 1) {
    const last = segments[segments.length - 1];
    const num = parseInt(last, 10);
    if (!isNaN(num) && num > 0) {
      return num;
    }
  }
  return 1;
}

export function handleSpaNavigation(forceRefresh: boolean = false, debounceMs: number = 250): void {
  if (spaDebounceTimer) {
    clearTimeout(spaDebounceTimer);
    spaDebounceTimer = null;
  }
  spaDebounceTimer = setTimeout(() => {
    runReaderOrchestration(forceRefresh).catch((err) => {
      logger.warn(`SPA navigation orchestration failed: ${err instanceof Error ? err.message : String(err)}`);
    });
  }, debounceMs);
}

export function hookSpaNavigation(onNavigate: () => void): void {
  if (typeof window === 'undefined' || isSpaHookInstalled) return;
  isSpaHookInstalled = true;

  const patch = (type: 'pushState' | 'replaceState') => {
    const orig = window.history[type];
    if (typeof orig === 'function') {
      window.history[type] = function (data: any, unused: string, url?: string | URL | null) {
        const res = orig.call(this, data, unused, url);
        window.dispatchEvent(new Event('inkshift:locationchange'));
        return res;
      };
    }
  };

  patch('pushState');
  patch('replaceState');

  window.addEventListener('popstate', onNavigate);
  window.addEventListener('inkshift:locationchange', onNavigate);
}

export async function runReaderOrchestration(forceRefresh: boolean = false): Promise<number> {
  activeDomainSettings = await loadDomainFilterSettings();
  const hostname = typeof window !== 'undefined' ? window.location.hostname : '';
  const domainStatus = isDomainAllowed(hostname, activeDomainSettings);

  if (domainStatus === 'blacklisted') {
    logger.info(`Domain '${hostname}' is blacklisted. Bypassing translation.`, { hostname });
    activeDetection = {
      isReaderPage: false,
      confidence: 0,
      layoutType: 'none',
      signals: [{ name: 'domain_blacklisted', weight: -1, details: hostname }],
    };
    activeMascotHUD?.setState('sleeping');
    return 0;
  }

  activeDetection = detectReaderContext(window.location, document);
  const shouldTranslate = domainStatus === 'whitelisted' || activeDetection.isReaderPage;

  if (!shouldTranslate) {
    // If URL path indicates a reader in an SPA, retry detection after brief DOM render delay
    if (
      typeof window !== 'undefined' &&
      /\/(?:chapter|chap|ch|read|viewer)\b/i.test(window.location.pathname)
    ) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      activeDetection = detectReaderContext(window.location, document);
      if (activeDetection.isReaderPage) {
        logger.info(
          `Detected reader page after DOM completion (${activeDetection.layoutType}, confidence: ${(activeDetection.confidence * 100).toFixed(0)}%). Starting scan...`,
          { layoutType: activeDetection.layoutType, confidence: activeDetection.confidence }
        );
        return await scanAndTranslate(forceRefresh, activeDetection.readerContainer);
      }
    }

    logger.info(
      `No manga reader detected on '${hostname}' (confidence: ${activeDetection.confidence.toFixed(2)}). Waiting.`,
      { hostname, confidence: activeDetection.confidence }
    );
    activeMascotHUD?.setState('idle');
    return 0;
  }

  const currentUrl = new URL(window.location.href);
  const detectedChapterId = extractChapterIdFromUrl(currentUrl);

  // If navigating within the SAME chapter (e.g. flipping page /1 -> /2):
  // Preserve active prefetch tasks and slide lookahead window forward smoothly without teardown
  if (!forceRefresh && activeChapterId && activeChapterId === detectedChapterId && activeScheduler) {
    const pageNum = extractPageNumberFromUrl(currentUrl);
    logger.info(
      `Flipping page within same chapter (${activeChapterId}, page #${pageNum}). Sliding lookahead window...`,
      { chapterId: activeChapterId, pageNum }
    );
    syncOverlaysVisibilityAndPosition({
      layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
    });
    activeProgressTracker?.trackPage(pageNum);
    activeScheduler.onPageChange(pageNum);
    const count = await scanAndTranslate(forceRefresh, activeDetection.readerContainer);
    if (typeof window !== 'undefined') {
      setTimeout(() => {
        syncOverlaysVisibilityAndPosition({
          layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
        });
      }, 300);
    }
    return count;
  }

  // --- CHAPTER TRANSITION (switching from one chapter to a different chapter) ---
  if (activeChapterId && activeChapterId !== detectedChapterId) {
    logger.info(
      `Chapter transition detected (${activeChapterId} -> ${detectedChapterId}). Resetting prefetch tasks, tearing down overlays, and purging old chapter page cache.`,
      { previousChapter: activeChapterId, newChapter: detectedChapterId }
    );
    activeScheduler?.cancelAllTasks();
    teardownAll();
    processedImages.clear();
    translationCacheByPage.clear();
    if (activeProgressTracker) {
      activeProgressTracker.destroy();
      activeProgressTracker = null;
    }
  }

  activeChapterId = detectedChapterId;

  logger.info(
    `Detected manga reader page (${activeDetection.layoutType}, confidence: ${(activeDetection.confidence * 100).toFixed(0)}%). Starting scan...`,
    { layoutType: activeDetection.layoutType, confidence: activeDetection.confidence }
  );

  // Extract full chapter manifest and report to Context Graph
  extractChapterManifest(document, currentUrl, activeDetection)
    .then((manifest) => {
      if (manifest && manifest.pages.length > 0) {
        activeManifest = manifest;
        activeChapterId = manifest.chapter_id;
        if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
          chrome.runtime.sendMessage({
            type: 'REPORT_CHAPTER_CONTEXT',
            payload: manifest,
          }).catch(() => {});
        }

        const initialPage = extractPageNumberFromUrl(currentUrl);

        // Initialize / sync sliding window prefetch scheduler
        if (!activeScheduler) {
          activeScheduler = new PrefetchScheduler({
            enabled: activeConfig.prefetchEnabled ?? true,
            depth: activeConfig.prefetchDepth ?? 3,
            engine: activeConfig.engine,
            provider: activeConfig.provider,
            translator: activeConfig.translator,
            model: activeConfig.model,
            sourceLang: activeConfig.sourceLang,
            onPageReady: (pageNum, res, imageUrl, taskChapterId) => {
              if (imageUrl && res) {
                translationCacheByUrl.set(getNormalizedImageUrl(imageUrl), res);
              }
              if (pageNum && res) {
                // Guard against race condition: only cache if task belongs to active chapter
                if (!taskChapterId || !activeChapterId || taskChapterId === activeChapterId) {
                  const key = getPageCacheKey(taskChapterId || activeChapterId, pageNum);
                  translationCacheByPage.set(key, res);
                }
              }
            },
          });
        } else {
          activeScheduler.setConfig({
            engine: activeConfig.engine,
            provider: activeConfig.provider,
            translator: activeConfig.translator,
            model: activeConfig.model,
            sourceLang: activeConfig.sourceLang,
          });
        }
        activeScheduler.setChapterManifest(manifest, initialPage);

        // Initialize reading progress tracker
        if (activeProgressTracker) {
          activeProgressTracker.destroy();
        }
        activeProgressTracker = new ReadingProgressTracker(manifest.chapter_id, {
          onProgressUpdate: (page) => {
            activeScheduler?.onPageChange(page);
          },
        });

        // If vertical webtoon reader, observe manga images
        const container = activeDetection?.readerContainer || document.body;
        const mangaImages = Array.from(container.querySelectorAll<HTMLImageElement>('img')).filter(
          (img) => img.naturalWidth >= 300 || img.clientWidth >= 300
        );
        if (mangaImages.length > 0) {
          activeProgressTracker.observeStripImages(mangaImages);
        }
      }
    })
    .catch((err) => {
      logger.warn(`Could not resolve chapter manifest: ${err instanceof Error ? err.message : String(err)}`);
    });

  return await scanAndTranslate(forceRefresh, activeDetection.readerContainer);
}

export async function initContentScript(): Promise<void> {
  // Guard against running in third-party embedded child iframes (e.g. reCAPTCHA, ads, tracking)
  if (typeof window !== 'undefined' && window.self !== window.top) {
    return;
  }

  logger.info(`In-page Content Script activated: ${window.location.href}`, {
    url: window.location.href,
  });
  await loadConfigFromStorage();

  // Mount Floating Mascot HUD if enabled
  if (!activeMascotHUD && typeof document !== 'undefined' && document.body) {
    activeMascotHUD = new MascotHUD({
      onRescanRequested: () => {
        logger.info('Mascot requested full page re-scan');
        runReaderOrchestration(true).catch(() => {});
      },
      onVisibilityToggled: (visible) => {
        activeConfig.overlayVisible = visible;
        updateActiveOverlaysAppearance({
          visible,
          opacity: activeConfig.overlayOpacity ?? activeConfig.opacity,
          color: activeConfig.overlayColor,
          fontFamily: activeConfig.speechBubbleFont,
        });
        if (visible) {
          syncOverlaysVisibilityAndPosition({
            layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
          });
          activeMascotHUD?.setState('reading');
        } else {
          activeMascotHUD?.setState('sleeping');
        }
      },
      onFontChanged: (font) => {
        activeConfig.speechBubbleFont = font;
        updateActiveOverlaysAppearance({ fontFamily: font });
      },
      onOpacityChanged: (opac) => {
        activeConfig.overlayOpacity = opac;
        activeConfig.opacity = opac;
        updateActiveOverlaysAppearance({ opacity: opac });
      },
      onColorChanged: (color) => {
        activeConfig.overlayColor = color;
        updateActiveOverlaysAppearance({ color });
      },
    });
    activeMascotHUD.mount();
    if (activeConfig.overlayVisible === false) {
      activeMascotHUD.setState('sleeping');
    } else {
      activeMascotHUD.setState('idle');
    }
  }

  // Register chrome runtime listener for SPA and manual re-scan
  if (!messageListener && typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
    const listener = (
      msg: any,
      _sender: chrome.runtime.MessageSender,
      sendResponse: (res?: any) => void
    ): boolean => {
      const ipc = msg as IPCMessage;
      if (ipc && typeof ipc === 'object') {
        if (ipc.type === 'GET_PAGE_READER_STATUS') {
          const hostname = typeof window !== 'undefined' ? window.location.hostname : '';
          const domainStatus = isDomainAllowed(hostname, activeDomainSettings ?? undefined);
          const statusData: PageReaderStatusData = {
            hostname,
            domainStatus,
            isReaderPage: activeDetection?.isReaderPage ?? false,
            confidence: activeDetection?.confidence ?? 0,
            layoutType: activeDetection?.layoutType ?? 'none',
            chapterMeta: activeDetection?.chapterMeta,
          };
          if (typeof sendResponse === 'function') {
            sendResponse({ success: true, data: statusData });
          }
          return true;
        }

        if (ipc.type === 'SPA_NAVIGATION_DETECTED' || ipc.type === 'RESCAN_PAGE') {
          const isRescan = ipc.type === 'RESCAN_PAGE';
          if (isRescan) {
            teardownAll();
            processedImages.clear();
            translationCacheByUrl.clear();
            translationCacheByPage.clear();
            activeChapterId = null;
            if (activeScheduler) {
              const currentUrl = typeof window !== 'undefined' ? new URL(window.location.href) : null;
              const currentPage = currentUrl ? extractPageNumberFromUrl(currentUrl) : 1;
              activeScheduler.resetForRescan(currentPage);
            }
            loadConfigFromStorage()
              .then(() => runReaderOrchestration(true))
              .then((count) => {
                if (typeof sendResponse === 'function') {
                  sendResponse({ success: true, count });
                }
              })
              .catch(() => {
                if (typeof sendResponse === 'function') {
                  sendResponse({ success: false, count: 0 });
                }
              });
            return true;
          } else {
            handleSpaNavigation(false);
            if (typeof sendResponse === 'function') {
              sendResponse({ success: true });
            }
            return true;
          }
        }
      }
      return false;
    };
    messageListener = listener;
    chrome.runtime.onMessage.addListener(listener);
  }

  // Register storage change listener to sync settings dynamically
  if (!storageListener && typeof chrome !== 'undefined' && chrome.storage?.onChanged?.addListener) {
    storageListener = (changes, areaName) => {
      if (areaName === 'local') {
        if (changes.mascotEnabled !== undefined && activeMascotHUD) {
          const enabled = Boolean(changes.mascotEnabled.newValue);
          activeMascotHUD.setEnabled(enabled);
          logger.info(`Mascot HUD visibility toggled via storage: ${enabled ? 'ENABLED' : 'DISABLED'}`);
        }
        loadConfigFromStorage()
          .then((cfg) => {
            if (
              changes.overlayVisible !== undefined ||
              changes.overlayOpacity !== undefined ||
              changes.overlayColor !== undefined ||
              changes.opacity !== undefined ||
              changes.speechBubbleFont !== undefined
            ) {
              if (changes.overlayVisible !== undefined) {
                logger.info(
                  `Overlay visibility changed to: ${cfg.overlayVisible ? 'VISIBLE' : 'HIDDEN'} (re-syncing layout & spatial culling)`,
                  { overlayVisible: cfg.overlayVisible }
                );
                if (cfg.overlayVisible) {
                  activeMascotHUD?.setState('reading');
                } else {
                  activeMascotHUD?.setState('sleeping');
                }
              }
              updateActiveOverlaysAppearance({
                visible: cfg.overlayVisible,
                opacity: cfg.overlayOpacity ?? cfg.opacity,
                color: cfg.overlayColor,
                fontFamily: cfg.speechBubbleFont,
              });
              if (changes.overlayVisible !== undefined && cfg.overlayVisible) {
                const mode = detectCurrentReaderLayoutMode(activeDetection?.readerContainer);
                logger.info(
                  `Restored overlays visibility. Re-evaluated spatial culling with mode: '${mode}'`,
                  { layoutMode: mode }
                );
                syncOverlaysVisibilityAndPosition({
                  layoutMode: mode,
                });
              }
            }
          })
          .catch(() => {});
      }
    };
    chrome.storage.onChanged.addListener(storageListener);
  }

  // Setup DOM Observers for infinite scroll and removals
  setupObservers({
    debounceMs: 300,
    readerContainer: activeDetection?.readerContainer,
    onContainerLayoutShift: () => {
      logger.info('Reader container layout mode shifted via attribute mutation. Re-syncing overlays...');
      handleScrollOrLayoutShift();
      scanAndTranslate(false).catch(() => {});
    },
    onNewImages: (newImages) => {
      newImages.forEach((img, idx) => {
        translateImageElement(img, processedImages.size + idx).catch(() => {});
      });
    },
    onRemoveImage: (img) => {
      processedImages.delete(img);
      removeOverlay(img);
    },
    onImageResize: (img) => {
      updateOverlayPosition(img);
    },
  });

  // Attach smooth scroll listener to window and reader container
  if (typeof window !== 'undefined') {
    window.addEventListener('scroll', handleScrollOrLayoutShift, { passive: true });
    if (activeDetection?.readerContainer && activeDetection.readerContainer !== document.body) {
      attachedScrollContainer = activeDetection.readerContainer;
      attachedScrollContainer.addEventListener('scroll', handleScrollOrLayoutShift, { passive: true });
    }
    logger.info(
      `Smooth scroll anchoring attached to window${attachedScrollContainer ? ` and container <${attachedScrollContainer.tagName.toLowerCase()}>` : ''}`
    );
  }

  // Attach global keyboard shortcuts (Alt+Z: toggle overlay, Alt+M: toggle mascot)
  if (typeof window !== 'undefined') {
    keyboardShortcutListener = handleGlobalKeyboardShortcuts;
    window.addEventListener('keydown', keyboardShortcutListener);
  }

  isInitialized = true;

  // Setup SPA navigation hook to handle client-side page transitions
  hookSpaNavigation(() => {
    handleSpaNavigation(false);
  });

  await runReaderOrchestration();
}

export function teardownContentScript(): void {
  if (typeof window !== 'undefined') {
    window.removeEventListener('scroll', handleScrollOrLayoutShift);
    if (attachedScrollContainer) {
      attachedScrollContainer.removeEventListener('scroll', handleScrollOrLayoutShift);
      attachedScrollContainer = null;
    }
    if (keyboardShortcutListener) {
      window.removeEventListener('keydown', keyboardShortcutListener);
      keyboardShortcutListener = null;
    }
    if (scrollRafId !== null) {
      if (typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(scrollRafId);
      } else {
        clearTimeout(scrollRafId);
      }
      scrollRafId = null;
    }
  }
  disconnectObservers();
  teardownAll();
  if (activeMascotHUD) {
    activeMascotHUD.unmount();
    activeMascotHUD = null;
  }
  processedImages.clear();
  translationCacheByUrl.clear();
  translationCacheByPage.clear();
  activeChapterId = null;
  activeManifest = null;
  activeDetection = null;
  if (spaDebounceTimer) {
    clearTimeout(spaDebounceTimer);
    spaDebounceTimer = null;
  }
  if (activeScheduler) {
    activeScheduler.cancelAllTasks();
    activeScheduler = null;
  }
  if (activeProgressTracker) {
    activeProgressTracker.destroy();
    activeProgressTracker = null;
  }
  if (messageListener && typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
    chrome.runtime.onMessage.removeListener(messageListener);
    messageListener = null;
  }
  if (storageListener && typeof chrome !== 'undefined' && chrome.storage?.onChanged?.removeListener) {
    chrome.storage.onChanged.removeListener(storageListener);
    storageListener = null;
  }
  isInitialized = false;
}


// Auto-run when in browser environment at document_idle
if (typeof window !== 'undefined' && typeof document !== 'undefined' && !isInitialized) {
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    initContentScript().catch((err) => {
      logger.error(`Failed to initialize content script: ${err instanceof Error ? err.message : String(err)}`);
    });
  } else {
    window.addEventListener('DOMContentLoaded', () => {
      initContentScript().catch((err) => {
        logger.error(`Failed to initialize content script: ${err instanceof Error ? err.message : String(err)}`);
      });
    });
  }
}
