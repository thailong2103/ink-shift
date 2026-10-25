// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  setupObservers,
  disconnectObservers,
  observeImageResize,
  unobserveImageResize,
} from '../../src/extension/content/observers';

describe('Content Observers (Resize & Mutation)', () => {
  let mockResizeObserverInstances: Array<{
    callback: ResizeObserverCallback;
    observe: ReturnType<typeof vi.fn>;
    unobserve: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  }>;

  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = '';
    mockResizeObserverInstances = [];

    // Mock ResizeObserver
    class MockResizeObserver {
      callback: ResizeObserverCallback;
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
        mockResizeObserverInstances.push(this);
      }
    }
    vi.stubGlobal('ResizeObserver', MockResizeObserver);
  });

  afterEach(() => {
    disconnectObservers();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  describe('ResizeObserver tracking', () => {
    it('observes and unobserves image elements', () => {
      const img = document.createElement('img');
      const onResize = vi.fn();

      observeImageResize(img, onResize);
      expect(mockResizeObserverInstances.length).toBeGreaterThan(0);
      const instance = mockResizeObserverInstances[0];
      expect(instance.observe).toHaveBeenCalledWith(img);

      // Simulate resize callback trigger
      instance.callback(
        [{ target: img } as unknown as ResizeObserverEntry],
        instance as unknown as ResizeObserver
      );
      expect(onResize).toHaveBeenCalledWith(img);

      unobserveImageResize(img);
      expect(instance.unobserve).toHaveBeenCalledWith(img);
    });
  });

  describe('MutationObserver with Debounce', () => {
    it('triggers onNewImages after debounce when images are added', async () => {
      const onNewImages = vi.fn();
      const onRemoveImage = vi.fn();

      setupObservers({
        debounceMs: 300,
        onNewImages,
        onRemoveImage,
        onImageResize: vi.fn(),
      });

      const img = document.createElement('img');
      img.src = 'https://example.com/ch1/p1.jpg';
      Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
      Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
      Object.defineProperty(img, 'naturalWidth', { value: 800, configurable: true });
      Object.defineProperty(img, 'naturalHeight', { value: 1200, configurable: true });
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

      // Initially not called before debounce
      expect(onNewImages).not.toHaveBeenCalled();

      // Fast-forward past debounce time
      await vi.advanceTimersByTimeAsync(350);

      expect(onNewImages).toHaveBeenCalled();
    });

    it('triggers onRemoveImage immediately when image is detached from DOM', async () => {
      const onNewImages = vi.fn();
      const onRemoveImage = vi.fn();

      setupObservers({
        debounceMs: 300,
        onNewImages,
        onRemoveImage,
        onImageResize: vi.fn(),
      });

      const container = document.createElement('div');
      const img = document.createElement('img');
      img.src = 'https://example.com/ch1/p2.jpg';
      container.appendChild(img);
      document.body.appendChild(container);

      // Remove the img from the container
      container.removeChild(img);

      // Fast forward
      await vi.advanceTimersByTimeAsync(50);
      expect(onRemoveImage).toHaveBeenCalledWith(img);
    });

    it('cleans up timers and observers upon disconnect', () => {
      const { mutationObserver } = setupObservers({
        debounceMs: 300,
        onNewImages: vi.fn(),
        onRemoveImage: vi.fn(),
        onImageResize: vi.fn(),
      });

      const disconnectSpy = vi.spyOn(mutationObserver, 'disconnect');
      disconnectObservers();
      expect(disconnectSpy).toHaveBeenCalled();
    });
  });
});
