/**
 * InkShift Chromium Content Script Entry Point & Orchestrator.
 *
 * In-page manga reader coordinator: discovers manga images, dispatches
 * concurrent IPC requests to privileged background service worker with traceId,
 * and mounts isolated Shadow DOM overlays with Vietnamese typography.
 */

import type { IPCMessage, IPCResponse } from '../shared/ipc_types';
import type { TranslationResponse, EngineMode } from '../../types/contract';
import { findMangaImages, waitForImageReady, MIN_MANGA_DIMENSION } from './dom_scanner';
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
import { siteAdapterRegistry } from '../adapters';

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
  prefetchEnabled?: boolean;
  prefetchDepth?: PrefetchDepth;
  customPrompt?: string;
  safeMask?: boolean;
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
  safeMask: true,
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
const pendingImages = new WeakSet<HTMLImageElement>();
const translationCacheByUrl = new Map<string, TranslationResponse>();
const translationCacheByPage = new Map<string, TranslationResponse>();
const imageProcessedUrlMap = new WeakMap<HTMLImageElement, string>();
const imagePendingUrlMap = new WeakMap<HTMLImageElement, string>();
const imageGenerationMap = new WeakMap<HTMLImageElement, number>();
let isInitialized = false;
let isSpaHookInstalled = false;
let activeDetection: ReaderDetectionResult | null = null;
let activeDomainSettings: DomainFilterSettings | null = null;
let activeManifest: ChapterContextReport | null = null;

function dispatchCancelPendingTranslations(reason: string, keepUrls: string[] = []): void {
  if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
    const cancelMsg: IPCMessage = {
      type: 'CANCEL_PENDING_TRANSLATIONS',
      payload: { reason, keepUrls },
    };
    chrome.runtime.sendMessage(cancelMsg).catch(() => {});
  }
}

function expandImageUrlCacheKeys(rawUrl: string): string[] {
  const base = getNormalizedImageUrl(rawUrl);
  if (!base) return [];
  const keys = new Set<string>([base]);
  const adapterNorm = siteAdapterRegistry.normalizeImageUrl(base);
  if (adapterNorm) {
    keys.add(adapterNorm);
  }
  if (base.includes('.gold-usergeneratedcontent.net/')) {
    keys.add(
      base
        .replace(/\/\/(?:a|w)\d+\.gold-usergeneratedcontent\.net\//i, '//a1.gold-usergeneratedcontent.net/')
        .replace(/\.(?:webp|avif)$/i, '.avif')
    );
    keys.add(
      base
        .replace(/\/\/(?:a|w)\d+\.gold-usergeneratedcontent\.net\//i, '//a2.gold-usergeneratedcontent.net/')
        .replace(/\.(?:webp|avif)$/i, '.avif')
    );
  }
  return Array.from(keys);
}

function storeTranslationCacheByUrl(rawUrl: string | undefined, res: TranslationResponse): void {
  if (!rawUrl) return;
  for (const cacheKey of expandImageUrlCacheKeys(rawUrl)) {
    translationCacheByUrl.set(cacheKey, res);
  }
}

function lookupTranslationCacheByUrl(rawUrl: string | undefined): TranslationResponse | undefined {
  if (!rawUrl) return undefined;
  for (const cacheKey of expandImageUrlCacheKeys(rawUrl)) {
    const hit = translationCacheByUrl.get(cacheKey);
    if (hit) {
      return hit;
    }
  }
  return undefined;
}

function areSameCanonicalImageUrls(urlA: string | undefined, urlB: string | undefined): boolean {
  if (!urlA || !urlB) return false;
  if (urlA === urlB) return true;
  const keysA = expandImageUrlCacheKeys(urlA);
  const keysB = new Set(expandImageUrlCacheKeys(urlB));
  return keysA.some((key) => keysB.has(key));
}

function collectActiveKeepUrls(pageNum?: number): string[] {
  const urls = new Set<string>();
  const addUrlVariants = (raw?: string | null) => {
    if (!raw) return;
    for (const variant of expandImageUrlCacheKeys(raw)) {
      urls.add(variant);
    }
  };

  if (pageNum && activeManifest?.pages) {
    for (const p of [pageNum, pageNum + 1, pageNum + 2]) {
      const manifestPage = activeManifest.pages.find((item) => item.page_number === p);
      addUrlVariants(manifestPage?.image_url);
    }
  }

  const root = activeDetection?.readerContainer ?? (typeof document !== 'undefined' ? document.body : null);
  if (root) {
    const vpWidth = typeof window !== 'undefined' && window.innerWidth > 0 ? window.innerWidth : 1920;
    const vpHeight = typeof window !== 'undefined' && window.innerHeight > 0 ? window.innerHeight : 1080;
    for (const img of findMangaImages(root)) {
      const rect = typeof img.getBoundingClientRect === 'function' ? img.getBoundingClientRect() : null;
      const inViewport =
        !rect ||
        (rect.width > 0 &&
          rect.height > 0 &&
          rect.right > 10 &&
          rect.left < vpWidth - 10 &&
          rect.bottom > 10 &&
          rect.top < vpHeight - 10);
      if (inViewport) {
        addUrlVariants(img.currentSrc || img.src || img.getAttribute('data-src'));
      }
    }
  }

  return Array.from(urls);
}

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

    // Query registered site adapter layout detection hook
    const adapterLayout = siteAdapterRegistry.detectReaderLayout(document);
    if (adapterLayout) {
      return adapterLayout;
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
      const normalizedSrc = siteAdapterRegistry.normalizeImageUrl(getNormalizedImageUrl(rawSrc));
      const hashMatch = normalizedSrc.match(/([0-9a-f]{64})/i);
      const targetHash = hashMatch ? hashMatch[1].toLowerCase() : null;

      const matched = manifestPages.find((p) => {
        if (!p.image_url) return false;
        const normP = siteAdapterRegistry.normalizeImageUrl(getNormalizedImageUrl(p.image_url));
        if (normP === normalizedSrc || rawSrc.includes(p.image_url) || p.image_url.includes(rawSrc)) {
          return true;
        }
        if (targetHash && normP.toLowerCase().includes(targetHash)) {
          return true;
        }
        return false;
      });
      if (matched && matched.page_number > 0) {
        logger.debug(
          `Resolved page #${matched.page_number} for image #${fallbackIndex} via Chapter Manifest matching`,
          { pageNumber: matched.page_number, imageIndex: fallbackIndex, matchedUrl: matched.image_url }
        );
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
    const currentUrl = new URL(window.location.href);
    const adapterPage = siteAdapterRegistry.extractPageNumber(currentUrl);
    if (adapterPage && adapterPage > 0) {
      logger.debug(
        `Resolved page #${adapterPage} for image #${fallbackIndex} via site adapter from URL`,
        { pageNumber: adapterPage, imageIndex: fallbackIndex, url: currentUrl.href }
      );
      return adapterPage;
    }
    const pageFromUrl = extractPageNumberFromUrl(currentUrl);
    if (pageFromUrl > 0) {
      logger.debug(
        `Resolved page #${pageFromUrl} for image #${fallbackIndex} via URL segment parsing`,
        { pageNumber: pageFromUrl, imageIndex: fallbackIndex, url: currentUrl.href }
      );
      return pageFromUrl;
    }
  }

  // Tier 5: Fallback to DOM image index
  return fallbackIndex + 1;
}

let scrollRafId: number | null = null;
let stripScrollTimer: ReturnType<typeof setTimeout> | null = null;
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
          if (mode === 'strip' && activeDetection?.isReaderPage) {
            if (stripScrollTimer) clearTimeout(stripScrollTimer);
            stripScrollTimer = setTimeout(() => {
              stripScrollTimer = null;
              scanAndTranslate(false, activeDetection?.readerContainer).catch(() => {});
            }, 200);
          }
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
        'prefetchEnabled',
        'prefetchDepth',
        'customPrompt',
        'custom_prompt',
        'safe_mask',
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
          let activeProvider = activeConfig.provider || 'google';
          if (activeConfig.engine === 'local') {
            const trans = activeConfig.translator || '';
            if (trans === 'llm-google' || trans === 'llm-gemini') activeProvider = 'google';
            else if (trans === 'llm-openai') activeProvider = 'openai';
            else if (trans === 'llm-anthropic') activeProvider = 'anthropic';
            else if (trans === 'llm-custom' || trans === 'llm-qwen') activeProvider = 'custom';
          }
          const selectedMap = stored.selected_models as Record<string, string>;
          if (selectedMap[activeProvider]) {
            activeConfig.model = selectedMap[activeProvider];
          }
        }
        if (typeof stored.customPrompt === 'string') {
          activeConfig.customPrompt = stored.customPrompt;
        } else if (typeof stored.custom_prompt === 'string') {
          activeConfig.customPrompt = stored.custom_prompt;
        }
        if (stored.safe_mask !== undefined) {
          activeConfig.safeMask = Boolean(stored.safe_mask);
        } else {
          activeConfig.safeMask = true;
        }
        if (activeScheduler) {
          activeScheduler.setConfig({
            engine: activeConfig.engine,
            provider: activeConfig.provider,
            translator: activeConfig.translator,
            model: activeConfig.model,
            customPrompt: activeConfig.customPrompt,
            safeMask: activeConfig.safeMask,
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
  } catch (err: unknown) {
    logger.warn(`Failed to serialize image element to DataURL via canvas: ${err instanceof Error ? err.message : String(err)}`);
    return null;
  }
}

export async function translateImageElement(
  img: HTMLImageElement,
  index: number,
  forceRefresh: boolean = false
): Promise<void> {
  let rawUrl = img.currentSrc || img.src || img.getAttribute('data-src') || '';
  // Fall back to img.src if currentSrc is a data URL (e.g. Hitomi adapose canvas polyfill)
  if (rawUrl.startsWith('data:') && img.src && (img.src.startsWith('http://') || img.src.startsWith('https://'))) {
    rawUrl = img.src;
  }
  const normalizedUrl = getNormalizedImageUrl(rawUrl);
  const previousUrl = imageProcessedUrlMap.get(img);
  const pendingUrl = imagePendingUrlMap.get(img);

  // If the element was previously processed or is currently pending with a DIFFERENT image URL,
  // the reader has recycled the DOM <img> element for a new page (e.g. Hitomi / MangaDex single-page carousel).
  // Preempt the stale request and tear down the old overlay BEFORE checking pending/processed locks.
  const isUrlChanged = Boolean(
    (previousUrl && normalizedUrl && !areSameCanonicalImageUrls(previousUrl, normalizedUrl)) ||
      (pendingUrl && normalizedUrl && !areSameCanonicalImageUrls(pendingUrl, normalizedUrl))
  );
  if (isUrlChanged) {
    logger.info(
      `Detected recycled <img> element with new URL on image #${index}. Tearing down previous overlay and preempting stale request.`,
      { previousUrl: pendingUrl || previousUrl, normalizedUrl, imageIndex: index }
    );
    removeOverlay(img);
    processedImages.delete(img);
    pendingImages.delete(img);
    imagePendingUrlMap.delete(img);
    imageGenerationMap.set(img, (imageGenerationMap.get(img) ?? 0) + 1);
  }

  // Synchronous race lock: reject duplicate dispatches for the SAME image URL currently in flight
  if (pendingImages.has(img)) {
    return;
  }

  // Check if an existing overlay is a failed or fallback placeholder BEFORE checking processedImages
  const existingHost = getOverlayHost(img);
  const isExistingFailedOrFallback = Boolean(
    existingHost &&
      (existingHost.getAttribute('data-is-fallback') === 'true' ||
        existingHost.shadowRoot?.querySelector('.inkshift-status-pill[data-status="failed"]'))
  );

  if (existingHost && !forceRefresh && !isExistingFailedOrFallback) {
    logger.debug(
      `Skipping image #${index}: overlay host already active for this element (URL: ${normalizedUrl || 'empty'})`,
      { imageIndex: index, normalizedUrl }
    );
    syncOverlaysVisibilityAndPosition({
      layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
    });
    return;
  }

  if (existingHost && isExistingFailedOrFallback) {
    logger.info(
      `Existing overlay on image #${index} is fallback or failed. Tearing down to allow fresh translation.`,
      { imageIndex: index, normalizedUrl }
    );
    removeOverlay(img);
    processedImages.delete(img);
  }

  if (processedImages.has(img) && !forceRefresh) {
    logger.debug(
      `Skipping image #${index}: element already marked as processed (URL: ${normalizedUrl || 'empty'})`,
      { imageIndex: index, normalizedUrl }
    );
    return;
  }

  const myGeneration = (imageGenerationMap.get(img) ?? 0) + 1;
  imageGenerationMap.set(img, myGeneration);
  pendingImages.add(img);
  if (normalizedUrl) {
    imagePendingUrlMap.set(img, normalizedUrl);
  }

  try {
    // Guard against unready dimensions
    await waitForImageReady(img, 1500);
    if (imageGenerationMap.get(img) !== myGeneration) {
      return;
    }

    const clientWidth = img.clientWidth || img.naturalWidth || 0;
    const clientHeight = img.clientHeight || img.naturalHeight || 0;

    if (clientWidth <= 0 || clientHeight <= 0) {
      logger.warn(
        `Skipping image #${index}: zero dimensions detected (${clientWidth}x${clientHeight})`,
        { imageIndex: index, clientWidth, clientHeight, url: normalizedUrl }
      );
      return;
    }

    // Guard against small thumbnail / icon images that bypassed initial scan while downloading
    if (clientWidth < MIN_MANGA_DIMENSION && clientHeight < MIN_MANGA_DIMENSION) {
      logger.debug(
        `Skipping image #${index}: dimensions below manga minimum (${clientWidth}x${clientHeight} < ${MIN_MANGA_DIMENSION})`,
        { imageIndex: index, clientWidth, clientHeight, url: normalizedUrl }
      );
      return;
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
      const urlCacheHit = lookupTranslationCacheByUrl(rawUrl);
      if (urlCacheHit) {
        cachedResponse = urlCacheHit;
        cacheKeyType = 'url';
      } else if (translationCacheByPage.has(pageCacheKey)) {
        cachedResponse = translationCacheByPage.get(pageCacheKey);
        cacheKeyType = 'page_number';
      }
    }

    if (cachedResponse) {
      processedImages.add(img);
      if (normalizedUrl) {
        imageProcessedUrlMap.set(img, normalizedUrl);
      }
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

    if (normalizedUrl) {
      imageProcessedUrlMap.set(img, normalizedUrl);
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
    } else {
      const normalized = siteAdapterRegistry.normalizeImageUrl(effectiveImageUrl);
      if (normalized !== effectiveImageUrl) {
        logger.info(
          `Normalized image URL via site adapter for image #${index}: ${normalized}`,
          { trace_id: traceId, imageIndex: index, rawUrl, normalizedUrl: normalized }
        );
        effectiveImageUrl = normalized;
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
        chapterUrl: typeof window !== 'undefined' ? window.location.href : undefined,
        forceRefresh: forceRefresh || undefined,
        custom_prompt: activeConfig.customPrompt || undefined,
        safe_mask: activeConfig.safeMask !== undefined ? activeConfig.safeMask : undefined,
        priority: 'P0',
      },
    };

    logger.info(
      `Dispatched image #${index} (${clientWidth}x${clientHeight}) to background for translation...`,
      { trace_id: traceId, imageIndex: index, clientWidth, clientHeight, imageUrl: effectiveImageUrl }
    );

    if (activeConfig.overlayVisible !== false) {
      activeMascotHUD?.setState('translating');
    }

    // Mount processing status pill so the user has live visual feedback while awaiting backend
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
      status: 'processing',
      errorMessage: 'InkShift: Đang dịch trang này...',
    });

    try {
      const response = (await chrome.runtime.sendMessage(message)) as IPCResponse<TranslationResponse>;

      if (response && response.success === true && response.data) {
        const isUsableTranslation =
          !response.data.is_fallback && response.data.blocks && response.data.blocks.length > 0;

        // Zero-Poisoning Policy: NEVER persist fallback or empty block responses to in-memory RAM cache
        if (isUsableTranslation) {
          storeTranslationCacheByUrl(normalizedUrl, response.data);
          translationCacheByPage.set(pageCacheKey, response.data);
          activeScheduler?.markPageCompleted(currentPageNumber);
        }

        // Discard stale overlay mount if DOM <img> was recycled to another URL while in-flight
        if (imageGenerationMap.get(img) !== myGeneration) {
          logger.debug(
            `Skipped stale overlay mount for recycled image #${index} (page #${currentPageNumber})`,
            { trace_id: traceId, imageIndex: index, pageNum: currentPageNumber }
          );
          return;
        }

        if (response.data.is_fallback) {
          processedImages.delete(img);
          mountOverlay(
            img,
            { ...response.data, blocks: [] },
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
            errorCode: 'FALLBACK_UNTRANSLATED',
            errorMessage: 'Dịch thất bại (đang hiện trang gốc). Lướt lại hoặc bấm Quét lại để thử lại.',
          });
          syncOverlaysVisibilityAndPosition({
            layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
          });
          if (activeConfig.overlayVisible !== false) {
            activeMascotHUD?.setState('error');
          }
          logger.warn(
            `Translation fell back to source text for image #${index} (page #${currentPageNumber}). Marked retryable.`,
            { trace_id: traceId, imageIndex: index, pageNum: currentPageNumber }
          );
        } else {
          processedImages.add(img);
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
          if (activeConfig.overlayVisible !== false) {
            activeMascotHUD?.setState('success');
          }
          logger.info(
            `Mounted translated overlay for image #${index} (${response.data.blocks.length} blocks)`,
            { trace_id: traceId, imageIndex: index, blocks: response.data.blocks.length }
          );
        }
      } else {
        const err =
          response && !response.success
            ? response.error
            : { code: 'UNKNOWN_ERROR', message: 'Translation failed' };

        if (imageGenerationMap.get(img) !== myGeneration) {
          return;
        }

        processedImages.delete(img);
        if (err.code === 'TRANSLATION_CANCELLED' || err.message?.toLowerCase().includes('aborted')) {
          removeOverlay(img);
          return;
        }

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
      if (imageGenerationMap.get(img) !== myGeneration) {
        return;
      }
      processedImages.delete(img);
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
  } finally {
    if (imageGenerationMap.get(img) === myGeneration) {
      pendingImages.delete(img);
      imagePendingUrlMap.delete(img);
    }
  }
}

export async function scanAndTranslate(
  forceRefresh: boolean = false,
  rootContainer?: Element
): Promise<number> {
  const hostname = typeof window !== 'undefined' ? window.location.hostname : '';
  const domainStatus = isDomainAllowed(hostname, activeDomainSettings ?? undefined);
  if (!activeDetection?.isReaderPage && domainStatus !== 'whitelisted') {
    logger.debug(`Bypassing scanAndTranslate on non-reader page (${hostname})`);
    return 0;
  }

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
  return siteAdapterRegistry.extractChapterId(url);
}

export function extractPageNumberFromUrl(url: URL): number {
  if (url.hash) {
    const hashMatch = url.hash.match(/^#(\d+)/);
    if (hashMatch && hashMatch[1]) {
      const pageNum = parseInt(hashMatch[1], 10);
      if (!isNaN(pageNum) && pageNum > 0) {
        return pageNum;
      }
    }
  }
  const segments = url.pathname.split('/').filter(Boolean);
  if (segments.length >= 1) {
    const last = segments[segments.length - 1];
    if (/^\d+$/.test(last)) {
      const num = parseInt(last, 10);
      if (!isNaN(num) && num > 0) {
        return num;
      }
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
  window.addEventListener('hashchange', onNavigate);
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
    dispatchCancelPendingTranslations('page_flip', collectActiveKeepUrls(pageNum));
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
    dispatchCancelPendingTranslations('chapter_transition');
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
            customPrompt: activeConfig.customPrompt,
            safeMask: activeConfig.safeMask,
            onPageReady: (pageNum, res, imageUrl, taskChapterId) => {
              // Zero-Poisoning Policy: NEVER persist fallback or empty block responses from prefetch
              if (res && !res.is_fallback && res.blocks && res.blocks.length > 0) {
                storeTranslationCacheByUrl(imageUrl, res);
                if (pageNum) {
                  // Guard against race condition: only cache if task belongs to active chapter
                  if (!taskChapterId || !activeChapterId || taskChapterId === activeChapterId) {
                    const key = getPageCacheKey(taskChapterId || activeChapterId, pageNum);
                    translationCacheByPage.set(key, res);
                  }
                }

                // Live-mount onto matching active DOM image if currently visible without a completed overlay
                if (!taskChapterId || !activeChapterId || taskChapterId === activeChapterId) {
                  const container =
                    activeDetection?.readerContainer ||
                    (typeof document !== 'undefined' ? document.body : null);
                  if (container) {
                    const currentImages = findMangaImages(container);
                    const readyUrlKeys = new Set(expandImageUrlCacheKeys(imageUrl));
                    currentImages.forEach((domImg, idx) => {
                      const domRawUrl =
                        domImg.currentSrc || domImg.src || domImg.getAttribute('data-src') || '';
                      const domNormUrl = getNormalizedImageUrl(domRawUrl);
                      const domPageNum = resolveImagePageNumber(domImg, idx, activeManifest?.pages);
                      const matchesPage = Boolean(pageNum && domPageNum === pageNum);
                      const matchesUrl = expandImageUrlCacheKeys(domRawUrl).some((k) =>
                        readyUrlKeys.has(k)
                      );
                      if (matchesPage || matchesUrl) {
                        const host = getOverlayHost(domImg);
                        const needsMount =
                          !host ||
                          host.getAttribute('data-is-fallback') === 'true' ||
                          Boolean(
                            host.shadowRoot?.querySelector(
                              '.inkshift-status-pill[data-status="processing"], .inkshift-status-pill[data-status="failed"]'
                            )
                          );
                        if (needsMount) {
                          imageGenerationMap.set(domImg, (imageGenerationMap.get(domImg) ?? 0) + 1);
                          processedImages.add(domImg);
                          if (domNormUrl) {
                            imageProcessedUrlMap.set(domImg, domNormUrl);
                          }
                          mountOverlay(domImg, res, {
                            opacity: activeConfig.overlayOpacity ?? activeConfig.opacity,
                            color: activeConfig.overlayColor,
                            fontFamily: activeConfig.speechBubbleFont,
                            visible: activeConfig.overlayVisible,
                            debugGeometry: activeConfig.debugGeometry,
                          });
                          syncOverlaysVisibilityAndPosition({
                            layoutMode: detectCurrentReaderLayoutMode(activeDetection?.readerContainer),
                          });
                          if (activeConfig.overlayVisible !== false) {
                            activeMascotHUD?.setState('success');
                          }
                          logger.info(
                            `Live-mounted prefetched overlay for page #${pageNum} (${res.blocks.length} blocks)`
                          );
                        }
                      }
                    });
                  }
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
            customPrompt: activeConfig.customPrompt,
            safeMask: activeConfig.safeMask,
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

        // Only attach vertical IntersectionObserver when reader is actually in long-strip mode
        const container = activeDetection?.readerContainer || document.body;
        const mangaImages = Array.from(container.querySelectorAll<HTMLImageElement>('img')).filter(
          (img) => img.naturalWidth >= 300 || img.clientWidth >= 300
        );
        if (
          mangaImages.length > 0 &&
          detectCurrentReaderLayoutMode(container, mangaImages) === 'strip'
        ) {
          activeProgressTracker.observeStripImages(mangaImages, (img, idx) =>
            resolveImagePageNumber(img, idx, manifest.pages)
          );
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
            dispatchCancelPendingTranslations('rescan_page');
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
            // Check if translation execution configuration changed
            const executionConfigChanged =
              changes.engine !== undefined ||
              changes.translator !== undefined ||
              changes.provider !== undefined ||
              changes.model !== undefined ||
              changes.selected_models !== undefined ||
              changes.customPrompt !== undefined ||
              changes.custom_prompt !== undefined ||
              changes.safe_mask !== undefined;

            if (executionConfigChanged) {
              logger.info('Translation execution configuration changed in storage. Invalidating cache and re-scanning.');
              dispatchCancelPendingTranslations('config_changed');
              translationCacheByUrl.clear();
              translationCacheByPage.clear();
              processedImages.clear();
              teardownAll();
              if (activeScheduler) {
                const currentUrl = typeof window !== 'undefined' ? new URL(window.location.href) : null;
                const currentPage = currentUrl ? extractPageNumberFromUrl(currentUrl) : 1;
                activeScheduler.resetForRescan(currentPage);
              }
              runReaderOrchestration(true).catch(() => {});
              return;
            }

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
    getReaderContainer: () => activeDetection?.readerContainer,
    onContainerLayoutShift: () => {
      if (!activeDetection?.isReaderPage) {
        return;
      }
      logger.info('Reader container layout mode shifted via attribute mutation. Re-syncing overlays...');
      handleScrollOrLayoutShift();
      scanAndTranslate(false).catch(() => {});
    },
    onNewImages: (newImages) => {
      // Guard: Only auto-translate newly inserted images on confirmed reader pages
      if (!activeDetection?.isReaderPage) {
        return;
      }
      const readerRoot = activeDetection.readerContainer;
      const layoutMode = detectCurrentReaderLayoutMode(readerRoot);
      const vpWidth = typeof window !== 'undefined' && window.innerWidth > 0 ? window.innerWidth : 1920;
      const vpHeight = typeof window !== 'undefined' && window.innerHeight > 0 ? window.innerHeight : 1080;

      const filtered = newImages.filter((img) => {
        if (readerRoot && readerRoot !== document.body && readerRoot.isConnected && !readerRoot.contains(img)) {
          return false;
        }
        if (layoutMode === 'single') {
          const rect = typeof img.getBoundingClientRect === 'function' ? img.getBoundingClientRect() : null;
          if (
            rect &&
            rect.width > 0 &&
            rect.height > 0 &&
            (rect.right <= 10 || rect.left >= vpWidth - 10 || rect.bottom <= 10 || rect.top >= vpHeight - 10)
          ) {
            return false;
          }
        }
        return true;
      });

      filtered.forEach((img, idx) => {
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
    if (stripScrollTimer) {
      clearTimeout(stripScrollTimer);
      stripScrollTimer = null;
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
