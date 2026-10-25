import { describe, it, expect } from 'vitest';
import {
  computeRenderedImageRect,
  scaleBoxToPixels,
  type RenderedRect,
  type BoundingBoxPixels,
} from '../../src/extension/content/geometry';
import type { BoundingBox } from '../../src/types/contract';

describe('Geometry Math & Letterbox Scaling', () => {
  describe('computeRenderedImageRect', () => {
    it('calculates rendered dimensions for exact aspect ratio (no letterbox)', () => {
      const mockImg = {
        clientWidth: 800,
        clientHeight: 1200,
        naturalWidth: 800,
        naturalHeight: 1200,
        getBoundingClientRect: () => ({ left: 50, top: 100, width: 800, height: 1200 }),
      } as unknown as HTMLImageElement;

      const rect = computeRenderedImageRect(mockImg);
      expect(rect.width).toBe(800);
      expect(rect.height).toBe(1200);
      expect(rect.left).toBe(50);
      expect(rect.top).toBe(100);
    });

    it('calculates letterboxing when image is wider than container (vertical offset)', () => {
      // Container: 600 x 1000 (aspect 0.6)
      // Image: 1200 x 800 (aspect 1.5) -> wider
      const mockImg = {
        clientWidth: 600,
        clientHeight: 1000,
        naturalWidth: 1200,
        naturalHeight: 800,
        getBoundingClientRect: () => ({ left: 0, top: 0, width: 600, height: 1000 }),
      } as unknown as HTMLImageElement;

      const rect = computeRenderedImageRect(mockImg);
      expect(rect.width).toBe(600);
      expect(rect.height).toBe(400); // 600 / 1.5
      expect(rect.left).toBe(0);
      expect(rect.top).toBe(300); // (1000 - 400) / 2
    });

    it('calculates pillarboxing when image is taller than container (horizontal offset)', () => {
      // Container: 1200 x 800 (aspect 1.5)
      // Image: 600 x 900 (aspect ~0.6667) -> taller
      const mockImg = {
        clientWidth: 1200,
        clientHeight: 800,
        naturalWidth: 600,
        naturalHeight: 900,
        getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }),
      } as unknown as HTMLImageElement;

      const rect = computeRenderedImageRect(mockImg);
      expect(rect.height).toBe(800);
      expect(Math.round(rect.width)).toBe(533); // 800 * (600 / 900) = 533.33
      expect(rect.top).toBe(0);
      expect(Math.round(rect.left)).toBe(333); // (1200 - 533.33) / 2
    });

    it('gracefully handles uninitialized or zero natural dimensions without NaN or Infinity', () => {
      const mockImg = {
        clientWidth: 800,
        clientHeight: 1200,
        naturalWidth: 0,
        naturalHeight: 0,
        getBoundingClientRect: () => ({ left: 10, top: 20, width: 800, height: 1200 }),
      } as unknown as HTMLImageElement;

      const rect = computeRenderedImageRect(mockImg);
      expect(rect.width).toBe(800);
      expect(rect.height).toBe(1200);
      expect(rect.left).toBe(10);
      expect(rect.top).toBe(20);
      expect(Number.isFinite(rect.width)).toBe(true);
      expect(Number.isFinite(rect.height)).toBe(true);
    });
  });

  describe('scaleBoxToPixels', () => {
    it('accurately maps [ymin, xmin, ymax, xmax] in [0, 1000] to physical pixels', () => {
      const renderedRect: RenderedRect = {
        left: 50,
        top: 100,
        width: 800,
        height: 1000,
      };

      // Box [ymin, xmin, ymax, xmax]
      const box: BoundingBox = [100, 200, 300, 600];
      const scaled: BoundingBoxPixels = scaleBoxToPixels(box, renderedRect);

      expect(scaled.top).toBe(100); // 100 / 1000 * 1000
      expect(scaled.left).toBe(160); // 200 / 1000 * 800
      expect(scaled.height).toBe(200); // (300 - 100) / 1000 * 1000
      expect(scaled.width).toBe(320); // (600 - 200) / 1000 * 800
    });

    it('clamps coordinates to stay within rendered rectangle bounds', () => {
      const renderedRect: RenderedRect = {
        left: 0,
        top: 0,
        width: 500,
        height: 500,
      };

      // Box with out-of-bounds normalized values
      const box: BoundingBox = [-50, -20, 1050, 1100];
      const scaled = scaleBoxToPixels(box, renderedRect);

      expect(scaled.top).toBe(0);
      expect(scaled.left).toBe(0);
      expect(scaled.width).toBeLessThanOrEqual(500);
      expect(scaled.height).toBeLessThanOrEqual(500);
    });
  });
});
