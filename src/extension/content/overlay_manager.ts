/**
 * Isolated Shadow DOM Translation Overlay Manager.
 *
 * Implements W3C Shadow DOM v1 encapsulation for manga speech bubbles,
 * preventing host website stylesheets from contaminating translation typography.
 * Strictly adheres to Zero innerHTML policy for XSS defense.
 */

import type { TranslationResponse, TranslatedBlock, BoundingBox } from '../../types/contract';
import { computeRenderedImageRect, scaleBoxToPixels, type RenderedRect } from './geometry';
import { fitFontSize } from './font_fitter';
import { createExtensionLogger } from '../shared/extension_logger';

const logger = createExtensionLogger('Overlay');

export type OverlayOpacity = 'semi-transparent' | 'opaque';
export type ReaderLayoutMode = 'single' | 'double' | 'strip';

export interface OverlayOptions {
  /** Opacity style of speech bubble background (default: 'semi-transparent' or 0-100 number). */
  opacity?: OverlayOpacity | number;
  /** Custom background color in hex (default: '#ffffff'). */
  color?: string;
  /** Custom font family key or font-family stack (default: 'itim'). */
  fontFamily?: string;
  /** Visibility toggle (default: true). */
  visible?: boolean;
  /** When true, renders diagnostic boundary outlines for geometry debugging. */
  debugGeometry?: boolean;
}

export type OverlayStatus = 'processing' | 'completed' | 'failed';

export interface StatusPillOptions {
  status: OverlayStatus;
  errorCode?: string;
  errorMessage?: string;
}

/**
 * Resolves text color with guaranteed high contrast against the background color.
 * Uses W3C relative luminance formula (L = 0.299*R + 0.587*G + 0.114*B).
 */
export function getContrastTextColor(hexOrRgb: string): string {
  let r = 255;
  let g = 255;
  let b = 255;

  if (hexOrRgb.startsWith('#')) {
    let hex = hexOrRgb.slice(1);
    if (hex.length === 3) {
      hex = hex
        .split('')
        .map((c) => c + c)
        .join('');
    }
    if (hex.length === 6) {
      r = parseInt(hex.substring(0, 2), 16);
      g = parseInt(hex.substring(2, 4), 16);
      b = parseInt(hex.substring(4, 6), 16);
    }
  } else if (hexOrRgb.startsWith('rgb')) {
    const match = hexOrRgb.match(/\d+/g);
    if (match && match.length >= 3) {
      r = parseInt(match[0], 10);
      g = parseInt(match[1], 10);
      b = parseInt(match[2], 10);
    }
  }

  const luminance = 0.299 * r + 0.587 * g + 0.114 * b;
  return luminance < 128 ? '#ffffff' : '#000000';
}

/**
 * Computes CSS rgba/rgb color string from hex color and opacity (0-100 or OverlayOpacity).
 */
export function computeBubbleBackgroundColor(
  colorHex: string = '#ffffff',
  opacity: OverlayOpacity | number = 'semi-transparent'
): string {
  let alpha = 0.88;
  if (opacity === 'opaque') {
    alpha = 1.0;
  } else if (opacity === 'semi-transparent') {
    alpha = 0.88;
  } else if (typeof opacity === 'number') {
    alpha = Math.max(0, Math.min(100, opacity)) / 100;
  }

  let r = 255;
  let g = 255;
  let b = 255;

  if (colorHex.startsWith('#')) {
    let hex = colorHex.slice(1);
    if (hex.length === 3) {
      hex = hex
        .split('')
        .map((c) => c + c)
        .join('');
    }
    if (hex.length === 6) {
      r = parseInt(hex.substring(0, 2), 16);
      g = parseInt(hex.substring(2, 4), 16);
      b = parseInt(hex.substring(4, 6), 16);
    }
  }

  if (alpha >= 1) {
    return `rgb(${r}, ${g}, ${b})`;
  }
  // Standardize two-decimal alpha representation
  const alphaStr = alpha === 0.88 ? '0.88' : String(Number(alpha.toFixed(2)));
  return `rgba(${r}, ${g}, ${b}, ${alphaStr})`;
}

/**
 * Resolves Chrome extension URL for bundled local font assets.
 */
function getFontUrl(relativePath: string): string {
  try {
    if (typeof chrome !== 'undefined' && chrome.runtime?.getURL) {
      return chrome.runtime.getURL(relativePath);
    }
  } catch {
    // Fall back to relative path in non-extension environments (e.g. unit tests)
  }
  return relativePath;
}

/**
 * Resolves manga font choice to an authentic CSS font-family stack.
 */
export function resolveFontFamily(fontKey?: string): string {
  if (fontKey === 'anime-ace-3') {
    return "'Anime Ace 3', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  }
  if (!fontKey || fontKey === 'itim') {
    return "'Itim', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  }
  if (fontKey === 'bangers') {
    return "'Bangers', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  }
  if (fontKey === 'patrick-hand') {
    return "'Patrick Hand', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  }
  if (fontKey === 'system-ui') {
    return '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif';
  }
  return fontKey;
}

const FONT_FACES_CSS = `
@font-face {
  font-family: 'Anime Ace 3';
  src: url('${getFontUrl('assets/fonts/AnimeAce3-Regular.otf')}') format('opentype');
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Itim';
  src: url('${getFontUrl('assets/fonts/Itim-Regular.ttf')}') format('truetype');
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Bangers';
  src: url('${getFontUrl('assets/fonts/Bangers-Regular.ttf')}') format('truetype');
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Patrick Hand';
  src: url('${getFontUrl('assets/fonts/PatrickHand-Regular.ttf')}') format('truetype');
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}
`;

/**
 * Chromium Bug 11085401 Workaround:
 * @font-face rules defined strictly inside Shadow DOM or adoptedStyleSheets are
 * ignored by Chromium's font loading engine, causing fallback to OS fonts ('cursive' -> Comic Sans MS).
 * Injecting the extension's @font-face rules into document.head allows Chromium to decode
 * and expose the fonts to all Shadow DOM subtrees.
 */
export function ensureDocumentFontFaces(): void {
  if (typeof document === 'undefined') return;
  const STYLE_ID = 'inkshift-font-faces';
  if (!document.getElementById(STYLE_ID)) {
    const styleEl = document.createElement('style');
    styleEl.id = STYLE_ID;
    styleEl.textContent = FONT_FACES_CSS;
    document.head?.appendChild(styleEl);
  }
}

const OVERLAY_STYLES = `
${FONT_FACES_CSS}

:host {
  all: initial;
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 2147483640;
  box-sizing: border-box;
  color-scheme: light !important;
  forced-color-adjust: none !important;
  --inkshift-bubble-bg: rgba(255, 255, 255, 0.88);
  --inkshift-text-color: #000000;
  --inkshift-font-family: 'Itim', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

:host(.inkshift-overlay-hidden) {
  display: none !important;
}

.inkshift-speech-bubble {
  all: initial;
  position: absolute;
  box-sizing: border-box;
  display: block;
  pointer-events: auto;
  user-select: text;
  transition: opacity 0.15s ease, filter 0.15s ease, box-shadow 0.15s ease;
  color-scheme: light !important;
  forced-color-adjust: none !important;
}

.inkshift-speech-bubble:hover,
.inkshift-speech-bubble.inkshift-group-hover {
  z-index: 10;
}

.inkshift-mask-layer {
  all: initial;
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  box-sizing: border-box;
  z-index: 1;
  background-color: var(--inkshift-bubble-bg, rgba(255, 255, 255, 0.88));
  transition: background-color 0.15s ease, filter 0.15s ease, box-shadow 0.15s ease;
  color-scheme: light !important;
  forced-color-adjust: none !important;
  -webkit-print-color-adjust: exact !important;
}

.inkshift-speech-bubble:hover .inkshift-mask-layer,
.inkshift-speech-bubble.inkshift-group-hover .inkshift-mask-layer {
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.35));
}

.inkshift-text-layer {
  all: initial;
  position: absolute;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  word-break: keep-all;
  overflow-wrap: break-word;
  hyphens: none;
  line-height: 1.25;
  font-family: var(--inkshift-font-family, 'Itim', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif);
  text-wrap: balance;
  color: var(--inkshift-text-color, #000000) !important;
  padding: 4px 6px;
  pointer-events: auto;
  user-select: text;
  z-index: 2;
  overflow: hidden;
  color-scheme: light !important;
  forced-color-adjust: none !important;
}

.inkshift-status-pill {
  all: initial;
  position: absolute;
  top: 8px;
  right: 8px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 12px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  pointer-events: auto;
  z-index: 10;
  user-select: none;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  transition: transform 0.1s ease;
}

.inkshift-status-pill:hover {
  transform: scale(1.05);
}

.inkshift-status-pill[data-status="processing"] {
  background-color: #fef08a;
  color: #854d0e;
  border: 1px solid #eab308;
}

.inkshift-status-pill[data-status="completed"] {
  background-color: #bbf7d0;
  color: #14532d;
  border: 1px solid #22c55e;
}

.inkshift-status-pill[data-status="failed"] {
  background-color: #fecaca;
  color: #7f1d1d;
  border: 1px solid #ef4444;
}

.inkshift-debug-rendered-rect {
  all: initial;
  position: absolute;
  box-sizing: border-box;
  border: 2px dashed #3b82f6;
  pointer-events: none;
  z-index: 5;
}

.inkshift-debug-box {
  all: initial;
  position: absolute;
  box-sizing: border-box;
  border: 2px dashed #eab308;
  pointer-events: none;
  z-index: 6;
}
`;

/** Active map of tracked image elements to their overlay host containers. */
const activeOverlays = new Map<HTMLImageElement, HTMLElement>();

let sharedStyleSheet: CSSStyleSheet | null = null;

/**
 * Injects isolated styles into a Shadow Root using Constructable Stylesheets
 * with a fallback to <style> tags where unsupported.
 */
function applyShadowStyles(shadowRoot: ShadowRoot): void {
  ensureDocumentFontFaces();
  try {
    if (
      typeof CSSStyleSheet !== 'undefined' &&
      'replaceSync' in CSSStyleSheet.prototype &&
      'adoptedStyleSheets' in shadowRoot
    ) {
      if (!sharedStyleSheet) {
        sharedStyleSheet = new CSSStyleSheet();
        sharedStyleSheet.replaceSync(OVERLAY_STYLES);
      }
      shadowRoot.adoptedStyleSheets = [sharedStyleSheet];
      return;
    }
  } catch {
    // Fall back to style tag injection
  }

  const styleEl = document.createElement('style');
  styleEl.textContent = OVERLAY_STYLES;
  shadowRoot.appendChild(styleEl);
}

/**
 * Creates or updates the status pill in the shadow root.
 */
function createStatusPill(
  shadowRoot: ShadowRoot,
  status: OverlayStatus,
  options: { count?: number; errorCode?: string; errorMessage?: string } = {}
): HTMLElement {
  let pill = shadowRoot.querySelector('.inkshift-status-pill') as HTMLElement | null;
  if (!pill) {
    pill = document.createElement('div');
    pill.className = 'inkshift-status-pill';
    shadowRoot.appendChild(pill);
  }

  pill.dataset.status = status;

  if (status === 'completed') {
    delete pill.dataset.errorCode;
    const count = options.count ?? 0;
    pill.textContent = `✓ ${count}`;
    pill.title = options.errorMessage ?? `InkShift: Translated ${count} blocks`;
  } else if (status === 'processing') {
    delete pill.dataset.errorCode;
    pill.textContent = 'Đang dịch...';
    pill.title = options.errorMessage ?? 'InkShift: Processing image...';
  } else {
    // status === 'failed'
    const code = options.errorCode ?? 'TRANSLATION_FAILED';
    pill.dataset.errorCode = code;
    pill.textContent = '✕ Lỗi';
    pill.title = `InkShift Error [${code}]: ${options.errorMessage ?? 'Translation failed'}`;
  }

  return pill;
}

interface OverlayMeta {
  response: TranslationResponse;
  options: OverlayOptions;
  lastWidth: number;
  lastHeight: number;
}

const overlayMetaMap = new WeakMap<HTMLImageElement, OverlayMeta>();

/**
 * Renders all inner speech bubbles, mask layers, and status pill into shadow root.
 */
function renderOverlayContent(
  shadowRoot: ShadowRoot,
  img: HTMLImageElement,
  response: TranslationResponse,
  options: OverlayOptions
): void {
  // Clear any existing speech bubbles and debug boxes (preserve <style>)
  const existingElements = shadowRoot.querySelectorAll(
    '.inkshift-speech-bubble, .inkshift-debug-rendered-rect, .inkshift-debug-box, .inkshift-status-pill'
  );
  for (let i = 0; i < existingElements.length; i++) {
    existingElements[i].remove();
  }

  const imgRect = img.getBoundingClientRect();
  const renderedRect = computeRenderedImageRect(img);
  const innerLeft = renderedRect.left - imgRect.left;
  const innerTop = renderedRect.top - imgRect.top;
  const innerWidth = renderedRect.width;
  const innerHeight = renderedRect.height;

  const innerContext: RenderedRect = {
    left: innerLeft,
    top: innerTop,
    width: innerWidth,
    height: innerHeight,
  };

  const backgroundColor = computeBubbleBackgroundColor(
    options.color || '#ffffff',
    options.opacity ?? 'semi-transparent'
  );
  const textColor = getContrastTextColor(options.color || '#ffffff');

  // Render visual geometry debug outlines when debugGeometry is enabled
  if (options.debugGeometry) {
    const blueRect = document.createElement('div');
    blueRect.className = 'inkshift-debug-rendered-rect';
    blueRect.style.top = `${innerTop}px`;
    blueRect.style.left = `${innerLeft}px`;
    blueRect.style.width = `${innerWidth}px`;
    blueRect.style.height = `${innerHeight}px`;
    shadowRoot.appendChild(blueRect);
  }

  // Group blocks by parent bubble if parent_box is defined
  interface BubbleGroup {
    groupKey: string;
    parentBox: BoundingBox;
    polygon?: TranslatedBlock['polygon'];
    parentBubbleId?: string;
    blocks: TranslatedBlock[];
  }

  const groups: BubbleGroup[] = [];
  const groupMap = new Map<string, BubbleGroup>();

  for (const block of response.blocks) {
    if (!block.translated_text || !block.translated_text.trim()) {
      continue;
    }

    if (options.debugGeometry) {
      const bubblePixels = scaleBoxToPixels(block.box, innerContext);
      const yellowBox = document.createElement('div');
      yellowBox.className = 'inkshift-debug-box';
      yellowBox.style.top = `${bubblePixels.top}px`;
      yellowBox.style.left = `${bubblePixels.left}px`;
      yellowBox.style.width = `${bubblePixels.width}px`;
      yellowBox.style.height = `${bubblePixels.height}px`;
      shadowRoot.appendChild(yellowBox);
    }

    if (block.parent_box && block.parent_bubble_id) {
      const key = block.parent_bubble_id;
      let group = groupMap.get(key);
      if (!group) {
        group = {
          groupKey: key,
          parentBox: block.parent_box,
          polygon: block.polygon,
          parentBubbleId: block.parent_bubble_id,
          blocks: [],
        };
        groupMap.set(key, group);
        groups.push(group);
      }
      group.blocks.push(block);
    } else {
      // Single block (or merged block without parent_box)
      groups.push({
        groupKey: block.id,
        parentBox: block.box,
        polygon: block.polygon,
        parentBubbleId: block.parent_bubble_id,
        blocks: [block],
      });
    }
  }

  for (const group of groups) {
    const parentPixels = scaleBoxToPixels(group.parentBox, innerContext);

    const bubble = document.createElement('div');
    bubble.className = 'inkshift-speech-bubble';
    if (group.blocks.length === 1) {
      bubble.dataset.blockId = group.blocks[0].id;
    }
    if (group.parentBubbleId) {
      bubble.dataset.parentBubbleId = group.parentBubbleId;
    }
    bubble.style.top = `${parentPixels.top}px`;
    bubble.style.left = `${parentPixels.left}px`;
    bubble.style.width = `${parentPixels.width}px`;
    bubble.style.height = `${parentPixels.height}px`;

    // Layer 1: Background Mask Layer (hugging bubble contour with clip-path polygon)
    const maskLayer = document.createElement('div');
    maskLayer.className = 'inkshift-mask-layer';
    maskLayer.style.backgroundColor = backgroundColor;

    if (group.polygon && group.polygon.length >= 3) {
      const polygonPoints = group.polygon.map(([x, y]) => `${x}% ${y}%`).join(', ');
      const polygonStr = `polygon(${polygonPoints})`;
      maskLayer.style.clipPath = polygonStr;
      maskLayer.style.setProperty('-webkit-clip-path', polygonStr);
      maskLayer.style.filter = 'drop-shadow(0 1px 3px rgba(0, 0, 0, 0.2))';
      bubble.style.backgroundColor = 'transparent';
    } else {
      maskLayer.style.borderRadius = '4px';
      maskLayer.style.boxShadow = '0 1px 4px rgba(0, 0, 0, 0.18)';
      bubble.style.backgroundColor = backgroundColor;
    }

    if (options.debugGeometry) {
      bubble.style.outline = '2px solid red';
      maskLayer.style.outline = '1px solid green';
    }

    bubble.appendChild(maskLayer);

    // Layer 2: Safe-Zone Text Layers for each block in the group
    const isSingle = group.blocks.length === 1 && !group.blocks[0].parent_box;

    for (const childBlock of group.blocks) {
      const textLayer = document.createElement('div');
      textLayer.className = 'inkshift-text-layer';
      textLayer.dataset.blockId = childBlock.id;
      // Strictly enforce textContent (Zero innerHTML for XSS defense)
      textLayer.textContent = childBlock.translated_text;
      textLayer.style.setProperty('color', textColor, 'important');

      const words = childBlock.translated_text.trim().split(/\s+/).filter(Boolean);
      const wordCount = words.length;

      if (isSingle) {
        const isWideOval =
          parentPixels.width / Math.max(1, parentPixels.height) >= 1.3 && wordCount >= 4;
        if (isWideOval) {
          textLayer.style.top = '0';
          textLayer.style.height = '100%';
          textLayer.style.width = '82%';
          textLayer.style.left = '9%';
          textLayer.style.maxWidth = '82%';
        } else {
          textLayer.style.top = '0';
          textLayer.style.left = '0';
          textLayer.style.width = '100%';
          textLayer.style.height = '100%';
        }
      } else {
        const childPixels = scaleBoxToPixels(childBlock.box, innerContext);
        const relTop = Math.max(0, childPixels.top - parentPixels.top);
        const relLeft = Math.max(0, childPixels.left - parentPixels.left);
        const relWidth = Math.min(parentPixels.width - relLeft, childPixels.width);
        const relHeight = Math.min(parentPixels.height - relTop, childPixels.height);

        textLayer.style.top = `${relTop}px`;
        textLayer.style.left = `${relLeft}px`;
        textLayer.style.width = `${relWidth}px`;
        textLayer.style.height = `${relHeight}px`;
      }

      bubble.appendChild(textLayer);
      fitFontSize(textLayer, { lineHeight: 1.25 });
    }

    // Wire up parent-child grouping interactions for connected bubbles
    if (group.parentBubbleId) {
      const parentId = group.parentBubbleId;
      bubble.addEventListener('mouseenter', () => {
        const hoverGroup = shadowRoot.querySelectorAll(`[data-parent-bubble-id="${parentId}"]`);
        for (let i = 0; i < hoverGroup.length; i++) {
          hoverGroup[i].classList.add('inkshift-group-hover');
        }
      });
      bubble.addEventListener('mouseleave', () => {
        const hoverGroup = shadowRoot.querySelectorAll(`[data-parent-bubble-id="${parentId}"]`);
        for (let i = 0; i < hoverGroup.length; i++) {
          hoverGroup[i].classList.remove('inkshift-group-hover');
        }
      });
    }

    shadowRoot.appendChild(bubble);
  }

  // Render completed status pill
  const renderedBlockCount = groups.reduce((acc, g) => acc + g.blocks.length, 0);
  createStatusPill(shadowRoot, 'completed', {
    count: renderedBlockCount,
    errorMessage: `InkShift: Translated ${renderedBlockCount} blocks (${response.engine_used}, ${response.execution_time_ms}ms)`,
  });
}

/**
 * Mounts an isolated, interactive Shadow DOM overlay on a detected manga page image.
 *
 * @param img The manga image DOM element to overlay.
 * @param response Translation response containing blocks to render.
 * @param options Styling and visual debug options.
 * @returns The created overlay host element.
 */
export function mountOverlay(
  img: HTMLImageElement,
  response: TranslationResponse,
  options: OverlayOptions = {}
): HTMLElement {
  // Remove existing overlay for this image if already mounted
  removeOverlay(img);

  const imgRect = img.getBoundingClientRect();
  const scrollX = window.scrollX !== undefined ? window.scrollX : window.pageXOffset || 0;
  const scrollY = window.scrollY !== undefined ? window.scrollY : window.pageYOffset || 0;

  const host = document.createElement('div');
  host.className = 'ink-shift-overlay-host';
  host.style.position = 'absolute';
  host.style.top = `${scrollY + imgRect.top}px`;
  host.style.left = `${scrollX + imgRect.left}px`;
  host.style.width = `${imgRect.width}px`;
  host.style.height = `${imgRect.height}px`;
  host.style.pointerEvents = 'none';
  host.style.zIndex = '2147483640';

  // Render speech bubbles configuration
  const backgroundColor = computeBubbleBackgroundColor(
    options.color || '#ffffff',
    options.opacity ?? 'semi-transparent'
  );
  const textColor = getContrastTextColor(options.color || '#ffffff');
  const fontFamily = resolveFontFamily(options.fontFamily);

  host.style.setProperty('--inkshift-bubble-bg', backgroundColor);
  host.style.setProperty('--inkshift-text-color', textColor);
  host.style.setProperty('--inkshift-font-family', fontFamily);

  if (options.visible === false) {
    host.classList.add('inkshift-overlay-hidden');
    host.style.display = 'none';
  }

  const shadowRoot = host.attachShadow({ mode: 'open' });
  applyShadowStyles(shadowRoot);

  overlayMetaMap.set(img, {
    response,
    options,
    lastWidth: imgRect.width,
    lastHeight: imgRect.height,
  });

  // Attach host to document.body before rendering content so that speech bubble
  // elements have real layout dimensions (clientHeight/clientWidth > 0) during font fitting.
  document.body.appendChild(host);
  activeOverlays.set(img, host);

  renderOverlayContent(shadowRoot, img, response, options);

  // Re-fit font sizes when custom @font-face assets (Itim, Bangers, etc.) finish loading
  if (typeof document !== 'undefined' && 'fonts' in document && document.fonts?.ready) {
    document.fonts.ready
      .then(() => {
        if (host.isConnected && host.shadowRoot) {
          const textLayers = host.shadowRoot.querySelectorAll('.inkshift-text-layer');
          textLayers.forEach((t) => {
            fitFontSize(t as HTMLElement, { lineHeight: 1.25 });
          });
        }
      })
      .catch(() => {});
  }

  return host;
}

/**
 * Updates diagnostic status pill for an image's overlay.
 */
export function updateStatus(img: HTMLImageElement, options: StatusPillOptions): void {
  const host = activeOverlays.get(img);
  if (!host || !host.shadowRoot) {
    return;
  }
  createStatusPill(host.shadowRoot, options.status, {
    errorCode: options.errorCode,
    errorMessage: options.errorMessage,
  });
}

/**
 * Updates host position and dimensions following image layout shifts.
 * Recomputes inner speech bubble pixel coordinates and font sizes if dimensions shift by >= 15%.
 */
export function updateOverlayPosition(img: HTMLImageElement): void {
  const host = activeOverlays.get(img);
  if (!host) {
    return;
  }
  const imgRect = img.getBoundingClientRect();
  const scrollX = window.scrollX !== undefined ? window.scrollX : window.pageXOffset || 0;
  const scrollY = window.scrollY !== undefined ? window.scrollY : window.pageYOffset || 0;

  host.style.top = `${scrollY + imgRect.top}px`;
  host.style.left = `${scrollX + imgRect.left}px`;
  host.style.width = `${imgRect.width}px`;
  host.style.height = `${imgRect.height}px`;

  const meta = overlayMetaMap.get(img);
  if (meta && host.shadowRoot && imgRect.width > 0 && imgRect.height > 0 && meta.lastWidth > 0) {
    const widthRatio = Math.abs(imgRect.width - meta.lastWidth) / meta.lastWidth;
    const heightRatio = Math.abs(imgRect.height - meta.lastHeight) / meta.lastHeight;
    if (widthRatio >= 0.15 || heightRatio >= 0.15) {
      logger.debug(
        `Rescaling speech bubbles for resized image (${meta.lastWidth}x${meta.lastHeight} -> ${imgRect.width}x${imgRect.height})`
      );
      renderOverlayContent(host.shadowRoot, img, meta.response, meta.options);
      meta.lastWidth = imgRect.width;
      meta.lastHeight = imgRect.height;
    }
  }
}

/**
 * Returns active overlay host associated with an image, if mounted.
 */
export function getOverlayHost(img: HTMLImageElement): HTMLElement | undefined {
  return activeOverlays.get(img);
}

/**
 * Removes and tears down the overlay host for a single image.
 */
export function removeOverlay(img: HTMLImageElement): void {
  const host = activeOverlays.get(img);
  if (host) {
    host.remove();
    activeOverlays.delete(img);
  }
}

/**
 * Tears down all active overlays across the document and resets tracking state.
 */
export function teardownAll(): void {
  for (const host of activeOverlays.values()) {
    host.remove();
  }
  activeOverlays.clear();

  // Safety cleanup for any orphaned overlay host elements
  const orphans = document.querySelectorAll('.ink-shift-overlay-host');
  for (let i = 0; i < orphans.length; i++) {
    orphans[i].remove();
  }
}

/**
 * Updates color, opacity, font family, or visibility across all actively mounted overlays.
 */
export function updateActiveOverlaysAppearance(options: {
  opacity?: OverlayOpacity | number;
  color?: string;
  visible?: boolean;
  fontFamily?: string;
}): void {
  const colorHex = options.color || '#ffffff';
  const bgColor = computeBubbleBackgroundColor(
    colorHex,
    options.opacity ?? 'semi-transparent'
  );
  const textColor = getContrastTextColor(colorHex);
  const resolvedFont = options.fontFamily ? resolveFontFamily(options.fontFamily) : undefined;

  for (const [img, host] of activeOverlays.entries()) {
    if (options.visible !== undefined) {
      if (!options.visible) {
        host.classList.add('inkshift-overlay-hidden');
      } else {
        host.classList.remove('inkshift-overlay-hidden');
      }
    }

    host.style.setProperty('--inkshift-bubble-bg', bgColor);
    host.style.setProperty('--inkshift-text-color', textColor);
    if (resolvedFont) {
      host.style.setProperty('--inkshift-font-family', resolvedFont);
    }

    const meta = overlayMetaMap.get(img);
    if (meta && options.fontFamily) {
      meta.options.fontFamily = options.fontFamily;
    }

    if (host.shadowRoot) {
      const masks = host.shadowRoot.querySelectorAll('.inkshift-mask-layer');
      masks.forEach((m) => {
        (m as HTMLElement).style.backgroundColor = bgColor;
      });

      const bubbles = host.shadowRoot.querySelectorAll('.inkshift-speech-bubble');
      bubbles.forEach((b) => {
        const el = b as HTMLElement;
        if (el.style.backgroundColor !== 'transparent') {
          el.style.backgroundColor = bgColor;
        }
      });

      const textLayers = host.shadowRoot.querySelectorAll('.inkshift-text-layer');
      textLayers.forEach((t) => {
        const el = t as HTMLElement;
        el.style.setProperty('color', textColor, 'important');
        if (resolvedFont) {
          fitFontSize(el, { lineHeight: 1.25 });
        }
      });
    }
  }

  // When unhiding overlays globally, immediately re-sync viewport spatial culling
  if (options.visible === true) {
    syncOverlaysVisibilityAndPosition();
  }
}

/**
 * Toggles visibility on or off for all active overlays on the page.
 */
export function toggleAllOverlaysVisibility(visible: boolean): void {
  updateActiveOverlaysAppearance({ visible });
}

/**
 * Returns the count of actively tracked overlay hosts.
 */
export function getActiveOverlaysCount(): number {
  return activeOverlays.size;
}

/**
 * Synchronizes visibility and coordinates of all actively mounted overlays.
 * Detaches orphaned overlays, hides off-screen or sliding carousel pages,
 * and handles layout-specific culling for single-page, double-page spread, or long-strip.
 */
export function syncOverlaysVisibilityAndPosition(options?: {
  layoutMode?: ReaderLayoutMode;
  isSinglePage?: boolean;
}): void {
  const vpWidth = typeof window !== 'undefined' && window.innerWidth ? window.innerWidth : 1280;
  const vpHeight = typeof window !== 'undefined' && window.innerHeight ? window.innerHeight : 800;
  const vpCenterX = vpWidth / 2;

  const scrollX = typeof window !== 'undefined' ? (window.scrollX !== undefined ? window.scrollX : window.pageXOffset || 0) : 0;
  const scrollY = typeof window !== 'undefined' ? (window.scrollY !== undefined ? window.scrollY : window.pageYOffset || 0) : 0;

  interface Candidate {
    img: HTMLImageElement;
    host: HTMLElement;
    rect: DOMRect;
    centerDistance: number;
  }

  const visibleCandidates: Candidate[] = [];

  for (const [img, host] of Array.from(activeOverlays.entries())) {
    if (!img.isConnected) {
      host.remove();
      activeOverlays.delete(img);
      continue;
    }

    const rect = img.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      host.style.display = 'none';
      continue;
    }

    // Check if off-screen (slid away to left/right in carousel or outside viewport vertically)
    const isOffscreen =
      rect.right <= 10 ||
      rect.left >= vpWidth - 10 ||
      rect.bottom <= 10 ||
      rect.top >= vpHeight - 10;

    if (isOffscreen) {
      host.style.display = 'none';
      continue;
    }

    // Candidate is in viewport
    const imgCenterX = rect.left + rect.width / 2;
    const centerDistance = Math.abs(imgCenterX - vpCenterX);
    visibleCandidates.push({ img, host, rect, centerDistance });
  }

  const mode: ReaderLayoutMode = options?.layoutMode ?? (options?.isSinglePage ? 'single' : 'strip');
  logger.debug(
    `Syncing overlays (mode: '${mode}', candidates in viewport: ${visibleCandidates.length}/${activeOverlays.size})`,
    { mode, visibleCandidates: visibleCandidates.length, totalTracked: activeOverlays.size }
  );

  if (mode === 'double') {
    // In double-page spread mode (e.g. MangaDex double page), preserve up to 2 active pages in viewport
    if (visibleCandidates.length > 2) {
      visibleCandidates.sort((a, b) => a.centerDistance - b.centerDistance);
      const activeWinners = new Set(visibleCandidates.slice(0, 2));

      for (let i = 0; i < visibleCandidates.length; i++) {
        const candidate = visibleCandidates[i];
        if (activeWinners.has(candidate)) {
          candidate.host.style.display = '';
          candidate.host.style.top = `${scrollY + candidate.rect.top}px`;
          candidate.host.style.left = `${scrollX + candidate.rect.left}px`;
          candidate.host.style.width = `${candidate.rect.width}px`;
          candidate.host.style.height = `${candidate.rect.height}px`;
        } else {
          candidate.host.style.display = 'none';
        }
      }
    } else {
      for (const candidate of visibleCandidates) {
        candidate.host.style.display = '';
        candidate.host.style.top = `${scrollY + candidate.rect.top}px`;
        candidate.host.style.left = `${scrollX + candidate.rect.left}px`;
        candidate.host.style.width = `${candidate.rect.width}px`;
        candidate.host.style.height = `${candidate.rect.height}px`;
      }
    }
  } else if (mode === 'single') {
    // In single-page carousel readers (e.g. MangaDex single page), pick the image closest to horizontal center
    if (visibleCandidates.length > 1) {
      visibleCandidates.sort((a, b) => a.centerDistance - b.centerDistance);
      const activeWinner = visibleCandidates[0];

      for (let i = 0; i < visibleCandidates.length; i++) {
        const candidate = visibleCandidates[i];
        if (candidate === activeWinner) {
          candidate.host.style.display = '';
          candidate.host.style.top = `${scrollY + candidate.rect.top}px`;
          candidate.host.style.left = `${scrollX + candidate.rect.left}px`;
          candidate.host.style.width = `${candidate.rect.width}px`;
          candidate.host.style.height = `${candidate.rect.height}px`;
        } else {
          candidate.host.style.display = 'none';
        }
      }
    } else if (visibleCandidates.length === 1) {
      const candidate = visibleCandidates[0];
      candidate.host.style.display = '';
      candidate.host.style.top = `${scrollY + candidate.rect.top}px`;
      candidate.host.style.left = `${scrollX + candidate.rect.left}px`;
      candidate.host.style.width = `${candidate.rect.width}px`;
      candidate.host.style.height = `${candidate.rect.height}px`;
    }
  } else {
    // In long-strip vertical webtoons, all candidates currently intersecting the viewport are visible
    for (const candidate of visibleCandidates) {
      candidate.host.style.display = '';
      candidate.host.style.top = `${scrollY + candidate.rect.top}px`;
      candidate.host.style.left = `${scrollX + candidate.rect.left}px`;
      candidate.host.style.width = `${candidate.rect.width}px`;
      candidate.host.style.height = `${candidate.rect.height}px`;
    }
  }
}

