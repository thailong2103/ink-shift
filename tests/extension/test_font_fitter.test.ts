// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest';
import { fitFontSize, type FontFitOptions } from '../../src/extension/content/font_fitter';

describe('Vietnamese Typography & Binary Search Font Fitter', () => {
  let element: HTMLElement;

  beforeEach(() => {
    element = document.createElement('div');
    document.body.appendChild(element);
  });

  it('sets line-height to 1.25 to prevent clipping Vietnamese diacritics', () => {
    Object.defineProperty(element, 'clientHeight', { value: 100, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: 200, configurable: true });
    Object.defineProperty(element, 'scrollHeight', { value: 50, configurable: true });
    Object.defineProperty(element, 'scrollWidth', { value: 100, configurable: true });

    fitFontSize(element, { lineHeight: 1.25 });
    expect(element.style.lineHeight).toBe('1.25');
  });

  it('converges to optimal font size within at most 6 iterations', () => {
    let checkCount = 0;
    const clientH = 100;
    const clientW = 200;

    Object.defineProperty(element, 'clientHeight', { value: clientH, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: clientW, configurable: true });

    // Mock overflow behavior based on font size:
    // Any font size > 18 causes overflow
    Object.defineProperty(element, 'scrollHeight', {
      get: () => {
        checkCount++;
        const size = parseFloat(element.style.fontSize) || 12;
        return size > 18 ? 150 : 80;
      },
      configurable: true,
    });
    Object.defineProperty(element, 'scrollWidth', {
      get: () => 100,
      configurable: true,
    });

    const chosenSize = fitFontSize(element, {
      minFontSize: 8,
      maxFontSize: 32,
      maxIterations: 6,
    });

    // Should converge to approximately 18
    expect(chosenSize).toBeGreaterThanOrEqual(17);
    expect(chosenSize).toBeLessThanOrEqual(18.5);
    // Number of measurement iterations must be <= 6
    expect(checkCount).toBeLessThanOrEqual(6);
  });

  it('clamps to minFontSize when text cannot fit inside small container', () => {
    Object.defineProperty(element, 'clientHeight', { value: 20, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: 30, configurable: true });
    // Always overflows
    Object.defineProperty(element, 'scrollHeight', { value: 100, configurable: true });
    Object.defineProperty(element, 'scrollWidth', { value: 100, configurable: true });

    const size = fitFontSize(element, { minFontSize: 10, maxFontSize: 30 });
    expect(size).toBe(10);
    expect(element.style.fontSize).toBe('10px');
  });

  it('returns minFontSize when container has zero dimensions', () => {
    Object.defineProperty(element, 'clientHeight', { value: 0, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: 0, configurable: true });

    const size = fitFontSize(element, { minFontSize: 8 });
    expect(size).toBe(8);
  });

  it('safely handles Vietnamese accented strings', () => {
    element.textContent = 'Trời ơi! Quái vật xuất hiện rồi! Mau chạy đi kẻo chết!';
    Object.defineProperty(element, 'clientHeight', { value: 60, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: 120, configurable: true });
    Object.defineProperty(element, 'scrollHeight', { value: 40, configurable: true });
    Object.defineProperty(element, 'scrollWidth', { value: 100, configurable: true });

    const size = fitFontSize(element);
    expect(size).toBeGreaterThanOrEqual(8);
    expect(element.textContent).toContain('Quái vật');
  });

  it('dynamically scales font up to 50px-80px for large shouting bubbles when unbounded', () => {
    // Large shouting bubble: 250px height x 300px width
    element.textContent = 'CHẾT ĐI!';
    const clientH = 250;
    const clientW = 300;
    Object.defineProperty(element, 'clientHeight', { value: clientH, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: clientW, configurable: true });

    // Mock scrollHeight/scrollWidth: small text doesn't overflow until font size > 65
    Object.defineProperty(element, 'scrollHeight', {
      get: () => {
        const size = parseFloat(element.style.fontSize) || 12;
        return size > 65 ? 280 : 180;
      },
      configurable: true,
    });
    Object.defineProperty(element, 'scrollWidth', {
      get: () => {
        const size = parseFloat(element.style.fontSize) || 12;
        return size > 65 ? 320 : 220;
      },
      configurable: true,
    });

    const size = fitFontSize(element);
    // With dynamic max = min(max(24, 250 * 0.65), 80) = min(162, 80) = 80px
    // The algorithm should scale beyond old 22px cap up to ~65px
    expect(size).toBeGreaterThanOrEqual(60);
    expect(size).toBeLessThanOrEqual(66);
  });

  it('adapts to minFontSize 7.5px and compacts padding for micro-bubbles', () => {
    // Micro-bubble: 24px height x 30px width
    element.textContent = '...';
    const clientH = 24;
    const clientW = 30;
    Object.defineProperty(element, 'clientHeight', { value: clientH, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: clientW, configurable: true });

    // Any font size > 8 overflows in this tiny space
    Object.defineProperty(element, 'scrollHeight', {
      get: () => {
        const size = parseFloat(element.style.fontSize) || 12;
        return size > 8 ? 26 : 20;
      },
      configurable: true,
    });
    Object.defineProperty(element, 'scrollWidth', {
      get: () => {
        const size = parseFloat(element.style.fontSize) || 12;
        return size > 8 ? 32 : 25;
      },
      configurable: true,
    });

    const size = fitFontSize(element);
    expect(size).toBeLessThan(10);
    expect(size).toBeGreaterThanOrEqual(7.5);
    expect(element.style.padding).toBe('1px 2px');
  });

  it('respects explicit maxFontSize and minFontSize options overrides', () => {
    Object.defineProperty(element, 'clientHeight', { value: 300, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: 400, configurable: true });
    Object.defineProperty(element, 'scrollHeight', { value: 50, configurable: true });
    Object.defineProperty(element, 'scrollWidth', { value: 50, configurable: true });

    const size = fitFontSize(element, { maxFontSize: 20, minFontSize: 15 });
    expect(size).toBe(20);
  });
});
