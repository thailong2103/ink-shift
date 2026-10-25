/**
 * Binary Search Font Sizing Algorithm for Speech Bubbles.
 *
 * Efficiently calculates the optimal font size (in pixels) to fit
 * translated text into manga speech bubbles without clipping or overflow,
 * specifically preserving line-height 1.25 for Vietnamese diacritics.
 */

export interface FontFitOptions {
  /** Minimum allowable font size in pixels (default: 10 per ADR-007). */
  minFontSize?: number;
  /** Maximum allowable font size in pixels (default: 22 per ADR-007). */
  maxFontSize?: number;
  /** Maximum binary search iterations (default: 6 per SPEC-extension-core). */
  maxIterations?: number;
  /** Line-height ratio for vertical accent spacing (default: 1.25). */
  lineHeight?: number;
}

/**
 * Fits font size inside container element via binary search within <= maxIterations.
 *
 * @param element The container HTML element containing the text to size.
 * @param options Sizing constraints and convergence settings.
 * @returns The converged font size in pixels.
 */
export function fitFontSize(element: HTMLElement, options: FontFitOptions = {}): number {
  const maxIterations = options.maxIterations ?? 6;
  const lineHeight = options.lineHeight ?? 1.25;

  element.style.lineHeight = `${lineHeight}`;
  element.style.wordBreak = 'keep-all';
  element.style.overflowWrap = 'break-word';
  element.style.hyphens = 'none';

  const clientH = element.clientHeight;
  const clientW = element.clientWidth;

  // Adaptive micro-bubble padding to prevent clipping in cramped balloons
  if (clientH > 0 && clientW > 0 && (clientH < 30 || clientW < 40)) {
    element.style.padding = '1px 2px';
  }

  // Dynamic max font size based on bubble height (scales up for dramatic shouting bubbles)
  const defaultMax = Math.min(Math.max(24, Math.floor(clientH * 0.65)), 80);
  const maxFontSize = options.maxFontSize ?? defaultMax;

  // Adaptive min font size (lowers floor to 7.5px for micro-bubbles)
  const defaultMin = clientH < 28 || clientW < 35 ? 7.5 : 10;
  const minFontSize = options.minFontSize ?? defaultMin;

  // Guard against unattached or zero-dimension containers
  if (clientH <= 0 || clientW <= 0) {
    element.style.fontSize = `${minFontSize}px`;
    return minFontSize;
  }

  // Fast-path: check if maximum allowable font size already fits without overflow
  element.style.fontSize = `${maxFontSize}px`;
  if (element.scrollHeight <= clientH && element.scrollWidth <= clientW) {
    return maxFontSize;
  }

  let low = minFontSize;
  let high = Math.max(minFontSize, maxFontSize);
  let bestFit = minFontSize;

  // One check was already performed at maxFontSize for the fast path
  const remainingIterations = Math.max(1, maxIterations - 1);
  for (let i = 0; i < remainingIterations; i++) {
    const mid = (low + high) / 2;
    element.style.fontSize = `${mid}px`;

    const overflows = element.scrollHeight > clientH || element.scrollWidth > clientW;

    if (overflows) {
      high = mid;
    } else {
      bestFit = mid;
      low = mid;
    }

    if (high - low < 0.5) {
      break;
    }
  }

  const finalSize = Math.max(minFontSize, Math.round(bestFit * 10) / 10);
  element.style.fontSize = `${finalSize}px`;
  return finalSize;
}
