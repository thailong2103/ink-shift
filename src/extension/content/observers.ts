/**
 * Layout Shift & Mutation Observers for InkShift In-Page Overlays.
 *
 * Implements ResizeObserver to update speech bubble positions on layout changes,
 * and debounced MutationObserver to detect infinite scroll lazy-loaded images
 * and clean up detached image overlay hosts.
 */

import { isMangaImage } from './dom_scanner';

export interface ObserverConfig {
  /** Debounce delay in milliseconds for batched DOM mutations (default: 300ms). */
  debounceMs?: number;
  /** Callback fired when newly added candidate manga images are detected. */
  onNewImages: (images: HTMLImageElement[]) => void;
  /** Callback fired when tracked images are removed from the DOM. */
  onRemoveImage: (img: HTMLImageElement) => void;
  /** Optional callback fired when an observed image resizes. */
  onImageResize?: (img: HTMLImageElement) => void;
  /** Optional callback fired when reader container attributes (class, mode) mutate. */
  onContainerLayoutShift?: () => void;
  /** Optional reader container element to monitor. */
  readerContainer?: Element | null;
  /** Optional dynamic getter for active reader container (useful when detected post-init). */
  getReaderContainer?: () => Element | null | undefined;
}

let activeResizeObserver: ResizeObserver | null = null;
let activeMutationObserver: MutationObserver | null = null;
let mutationDebounceTimer: ReturnType<typeof setTimeout> | null = null;
const trackedResizeElements = new Map<HTMLImageElement, (img: HTMLImageElement) => void>();

/**
 * Attaches a ResizeObserver to an image to track dimensions and trigger position updates.
 */
export function observeImageResize(
  img: HTMLImageElement,
  callback: (img: HTMLImageElement) => void
): void {
  if (typeof ResizeObserver === 'undefined') {
    return;
  }

  if (!activeResizeObserver) {
    activeResizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const target = entry.target as HTMLImageElement;
        const cb = trackedResizeElements.get(target);
        if (cb) {
          cb(target);
        }
      }
    });
  }

  trackedResizeElements.set(img, callback);
  activeResizeObserver.observe(img);
}

/**
 * Unobserves an image from ResizeObserver tracking.
 */
export function unobserveImageResize(img: HTMLImageElement): void {
  trackedResizeElements.delete(img);
  if (activeResizeObserver) {
    activeResizeObserver.unobserve(img);
  }
}

/**
 * Initializes DOM observers for dynamic manga page insertions and layout changes.
 */
export function setupObservers(config: ObserverConfig): {
  resizeObserver: ResizeObserver | null;
  mutationObserver: MutationObserver;
} {
  const debounceMs = config.debounceMs ?? 300;
  const pendingAddedImages = new Set<HTMLImageElement>();

  const isInsideReaderContainer = (el: Element): boolean => {
    const readerRoot = config.getReaderContainer?.() ?? config.readerContainer;
    if (!readerRoot || readerRoot === document.body || !readerRoot.isConnected) {
      return true;
    }
    return readerRoot.contains(el);
  };

  activeMutationObserver = new MutationObserver((mutations) => {
    let containerShiftDetected = false;

    for (const mutation of mutations) {
      // Check attribute shifts on reader container (Hot Change) or recycled <img> src updates
      if (mutation.type === 'attributes') {
        const target = mutation.target as Element;
        const attr = mutation.attributeName;
        if ((attr === 'src' || attr === 'srcset') && target instanceof HTMLImageElement) {
          if (isInsideReaderContainer(target) && isMangaImage(target)) {
            pendingAddedImages.add(target);
          }
          continue;
        }
        if (
          attr === 'class' ||
          attr === 'data-reader-mode' ||
          attr === 'data-mode' ||
          attr === 'style'
        ) {
          const className = typeof target.className === 'string' ? target.className : '';
          const activeReader = config.getReaderContainer?.() ?? config.readerContainer;
          if (
            className.includes('reader') ||
            target.hasAttribute('data-reader-mode') ||
            target === activeReader
          ) {
            containerShiftDetected = true;
          }
        }
        continue;
      }

      // Check removed nodes
      for (let i = 0; i < mutation.removedNodes.length; i++) {
        const node = mutation.removedNodes[i];
        if (node instanceof HTMLImageElement) {
          config.onRemoveImage(node);
          unobserveImageResize(node);
        } else if (node instanceof HTMLElement) {
          const nestedImgs = node.querySelectorAll('img');
          for (let j = 0; j < nestedImgs.length; j++) {
            config.onRemoveImage(nestedImgs[j]);
            unobserveImageResize(nestedImgs[j]);
          }
        }
      }

      // Check added nodes
      for (let i = 0; i < mutation.addedNodes.length; i++) {
        const node = mutation.addedNodes[i];
        if (node instanceof HTMLImageElement && isInsideReaderContainer(node) && isMangaImage(node)) {
          pendingAddedImages.add(node);
        } else if (node instanceof HTMLElement) {
          const nestedImgs = node.querySelectorAll('img');
          for (let j = 0; j < nestedImgs.length; j++) {
            if (isInsideReaderContainer(nestedImgs[j]) && isMangaImage(nestedImgs[j])) {
              pendingAddedImages.add(nestedImgs[j]);
            }
          }
        }
      }
    }

    if (containerShiftDetected && typeof config.onContainerLayoutShift === 'function') {
      config.onContainerLayoutShift();
    }

    if (pendingAddedImages.size > 0) {
      if (mutationDebounceTimer !== null) {
        clearTimeout(mutationDebounceTimer);
      }
      mutationDebounceTimer = setTimeout(() => {
        const images = Array.from(pendingAddedImages);
        pendingAddedImages.clear();
        mutationDebounceTimer = null;
        if (images.length > 0) {
          config.onNewImages(images);
        }
      }, debounceMs);
    }
  });

  if (document.body) {
    activeMutationObserver.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'data-reader-mode', 'data-mode', 'src', 'srcset'],
    });
  }

  if (config.readerContainer && config.readerContainer !== document.body) {
    activeMutationObserver.observe(config.readerContainer, {
      attributes: true,
      attributeFilter: ['class', 'data-reader-mode', 'data-mode', 'style'],
    });
  }

  return {
    resizeObserver: activeResizeObserver,
    mutationObserver: activeMutationObserver,
  };
}

/**
 * Disconnects and resets all active observers and debouncers.
 */
export function disconnectObservers(): void {
  if (mutationDebounceTimer !== null) {
    clearTimeout(mutationDebounceTimer);
    mutationDebounceTimer = null;
  }
  if (activeMutationObserver) {
    activeMutationObserver.disconnect();
    activeMutationObserver = null;
  }
  if (activeResizeObserver) {
    activeResizeObserver.disconnect();
    activeResizeObserver = null;
  }
  trackedResizeElements.clear();
}
