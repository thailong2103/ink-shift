// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  mountOverlay,
  updateStatus,
  removeOverlay,
  teardownAll,
  getOverlayHost,
  updateActiveOverlaysAppearance,
  toggleAllOverlaysVisibility,
  getActiveOverlaysCount,
  syncOverlaysVisibilityAndPosition,
  updateOverlayPosition,
  getContrastTextColor,
  computeBubbleBackgroundColor,
  resolveFontFamily,
  type OverlayOptions,
  type StatusPillOptions,
  type ReaderLayoutMode,
} from '../../src/extension/content/overlay_manager';
import type { TranslationResponse } from '../../src/types/contract';

describe('Isolated Shadow DOM Overlay Manager & Diagnostics', () => {
  let mockImg: HTMLImageElement;

  const mockResponse: TranslationResponse = {
    success: true,
    page_hash: 'abc123hash',
    engine_used: 'gemini-2.5-flash',
    execution_time_ms: 120,
    from_cache: false,
    blocks: [
      {
        id: 'block-1',
        box: [100, 200, 300, 500],
        translated_text: 'Xin chào, đây là bản dịch mẫu!',
      },
      {
        id: 'block-2',
        box: [400, 100, 600, 400],
        translated_text: '<script>alert("XSS")</script> <b>Đậm</b>',
      },
    ],
  };

  beforeEach(() => {
    document.body.innerHTML = '';
    mockImg = document.createElement('img');
    mockImg.src = 'https://example.com/manga/p1.jpg';
    // Configure layout dimensions for jsdom
    Object.defineProperty(mockImg, 'naturalWidth', { value: 800, configurable: true });
    Object.defineProperty(mockImg, 'naturalHeight', { value: 1200, configurable: true });
    Object.defineProperty(mockImg, 'clientWidth', { value: 800, configurable: true });
    Object.defineProperty(mockImg, 'clientHeight', { value: 1200, configurable: true });
    mockImg.getBoundingClientRect = () => ({
      left: 100,
      top: 50,
      width: 800,
      height: 1200,
      right: 900,
      bottom: 1250,
      x: 100,
      y: 50,
      toJSON: () => {},
    });
    document.body.appendChild(mockImg);
  });

  afterEach(() => {
    teardownAll();
  });

  describe('Shadow DOM Mount & Isolation', () => {
    it('creates host element with Shadow Root v1 and attaches to document', () => {
      const host = mountOverlay(mockImg, mockResponse);
      expect(host).toBeDefined();
      expect(host.classList.contains('ink-shift-overlay-host')).toBe(true);
      expect(host.shadowRoot).not.toBeNull();
      expect(host.shadowRoot?.mode).toBe('open');

      // Verify position matches img coordinates
      expect(host.style.position).toBe('absolute');
      expect(host.style.top).toBe('50px');
      expect(host.style.left).toBe('100px');
      expect(host.style.width).toBe('800px');
      expect(host.style.height).toBe('1200px');
    });

    it('enforces zero innerHTML and prevents script injection (XSS defense)', () => {
      const host = mountOverlay(mockImg, mockResponse);
      const shadowRoot = host.shadowRoot!;
      const bubbles = shadowRoot.querySelectorAll('.inkshift-speech-bubble');
      expect(bubbles.length).toBe(2);

      // Block 2 contains <script>alert("XSS")</script>
      const maliciousBubble = bubbles[1];
      expect(maliciousBubble.textContent).toBe('<script>alert("XSS")</script> <b>Đậm</b>');
      // Must not create actual HTML tags
      expect(maliciousBubble.querySelector('script')).toBeNull();
      expect(maliciousBubble.querySelector('b')).toBeNull();
    });

    it('respects opacity toggle (semi-transparent vs opaque)', () => {
      const semiHost = mountOverlay(mockImg, mockResponse, { opacity: 'semi-transparent' });
      const semiBubble = semiHost.shadowRoot!.querySelector('.inkshift-speech-bubble') as HTMLElement;
      expect(semiBubble.style.backgroundColor).toContain('rgba(255, 255, 255, 0.88)');

      // Remount with opaque
      const opaqueHost = mountOverlay(mockImg, mockResponse, { opacity: 'opaque' });
      const opaqueBubble = opaqueHost.shadowRoot!.querySelector('.inkshift-speech-bubble') as HTMLElement;
      expect(opaqueBubble.style.backgroundColor).toBe('rgb(255, 255, 255)');
    });

    it('computes contrast text color and supports custom background colors with numeric opacity', () => {
      // Dark background should automatically invert text to white
      const darkHost = mountOverlay(mockImg, mockResponse, {
        color: '#18181b',
        opacity: 50,
      });
      const darkText = darkHost.shadowRoot!.querySelector('.inkshift-text-layer') as HTMLElement;
      expect(darkText.style.color).toBe('rgb(255, 255, 255)');

      // Sepia background should use dark text
      const sepiaHost = mountOverlay(mockImg, mockResponse, {
        color: '#f4ecd8',
        opacity: 90,
      });
      const sepiaText = sepiaHost.shadowRoot!.querySelector('.inkshift-text-layer') as HTMLElement;
      expect(sepiaText.style.color).toBe('rgb(0, 0, 0)');
    });

    it('hides host when visible option is false', () => {
      const hiddenHost = mountOverlay(mockImg, mockResponse, { visible: false });
      expect(hiddenHost.classList.contains('inkshift-overlay-hidden')).toBe(true);
      expect(hiddenHost.style.display).toBe('none');
    });
  });

  describe('Diagnostic Status Pills', () => {
    it('renders green completed status pill by default after mount', () => {
      const host = mountOverlay(mockImg, mockResponse);
      const pill = host.shadowRoot!.querySelector('.inkshift-status-pill') as HTMLElement;
      expect(pill).not.toBeNull();
      expect(pill.dataset.status).toBe('completed');
      expect(pill.title).toContain('InkShift');
      expect(pill.title).toContain('2');
    });

    it('updates status pill to failed with data-error-code and tooltip title', () => {
      const host = mountOverlay(mockImg, mockResponse);
      updateStatus(mockImg, {
        status: 'failed',
        errorCode: 'RATE_LIMITED',
        errorMessage: 'Backend returned 429 Too Many Requests',
      });

      const pill = host.shadowRoot!.querySelector('.inkshift-status-pill') as HTMLElement;
      expect(pill.dataset.status).toBe('failed');
      expect(pill.dataset.errorCode).toBe('RATE_LIMITED');
      expect(pill.title).toContain('RATE_LIMITED');
      expect(pill.title).toContain('Too Many Requests');
    });

    it('updates status pill to processing state', () => {
      const host = mountOverlay(mockImg, mockResponse);
      updateStatus(mockImg, {
        status: 'processing',
        errorMessage: 'Retrying translation...',
      });

      const pill = host.shadowRoot!.querySelector('.inkshift-status-pill') as HTMLElement;
      expect(pill.dataset.status).toBe('processing');
      expect(pill.title).toContain('Retrying');
    });
  });

  describe('Visual Geometry Debug Mode', () => {
    it('renders blue, yellow, and red outlines when debugGeometry is true', () => {
      const host = mountOverlay(mockImg, mockResponse, { debugGeometry: true });
      const shadowRoot = host.shadowRoot!;

      // Blue outline: inner rendered image rect
      const blueRect = shadowRoot.querySelector('.inkshift-debug-rendered-rect');
      expect(blueRect).not.toBeNull();

      // Yellow outlines: AI boxes scaled to pixels
      const yellowBoxes = shadowRoot.querySelectorAll('.inkshift-debug-box');
      expect(yellowBoxes.length).toBe(2);

      // Red outlines: speech bubbles
      const redBubbles = shadowRoot.querySelectorAll('.inkshift-speech-bubble');
      expect(redBubbles.length).toBe(2);
      expect((redBubbles[0] as HTMLElement).style.outline).toContain('red');
    });

    it('omits debug outlines when debugGeometry is false', () => {
      const host = mountOverlay(mockImg, mockResponse, { debugGeometry: false });
      const shadowRoot = host.shadowRoot!;

      expect(shadowRoot.querySelector('.inkshift-debug-rendered-rect')).toBeNull();
      expect(shadowRoot.querySelector('.inkshift-debug-box')).toBeNull();
    });
  });

  describe('Two-Layer Architecture, Polygon Clip-Path & Merged Bubbles', () => {
    it('creates Layer 1 (.inkshift-mask-layer) and Layer 2 (.inkshift-text-layer) inside each bubble', () => {
      const host = mountOverlay(mockImg, mockResponse);
      const shadowRoot = host.shadowRoot!;
      const bubbles = shadowRoot.querySelectorAll('.inkshift-speech-bubble');
      expect(bubbles.length).toBe(2);

      for (let i = 0; i < bubbles.length; i++) {
        const bubble = bubbles[i];
        const maskLayer = bubble.querySelector('.inkshift-mask-layer') as HTMLElement;
        const textLayer = bubble.querySelector('.inkshift-text-layer') as HTMLElement;

        expect(maskLayer).not.toBeNull();
        expect(textLayer).not.toBeNull();
        expect(textLayer.textContent).toBe(mockResponse.blocks[i].translated_text);
        // Layer 2 MUST NOT have clip-path
        expect(textLayer.style.clipPath).toBe('');
      }
    });

    it('applies clip-path polygon to Layer 1 when block contains polygon points', () => {
      const polygonResponse: TranslationResponse = {
        ...mockResponse,
        blocks: [
          {
            id: 'poly-1',
            box: [100, 100, 400, 400],
            polygon: [
              [10.0, 5.0],
              [80.0, 5.0],
              [95.0, 50.0],
              [70.0, 95.0],
              [20.0, 90.0],
            ],
            translated_text: 'Bóng thoại đa giác mượt mà',
          },
        ],
      };

      const host = mountOverlay(mockImg, polygonResponse);
      const shadowRoot = host.shadowRoot!;
      const bubble = shadowRoot.querySelector('.inkshift-speech-bubble') as HTMLElement;
      const maskLayer = bubble.querySelector('.inkshift-mask-layer') as HTMLElement;
      const textLayer = bubble.querySelector('.inkshift-text-layer') as HTMLElement;

      expect(maskLayer.style.clipPath).toBe(
        'polygon(10% 5%, 80% 5%, 95% 50%, 70% 95%, 20% 90%)'
      );
      expect(bubble.style.backgroundColor).toBe('transparent');
      // Layer 2 safe-zone text is never clipped
      expect(textLayer.style.clipPath).toBe('');
      expect(textLayer.textContent).toBe('Bóng thoại đa giác mượt mà');
    });

    it('links connected/merged bubbles sharing parent_bubble_id and triggers group hover', () => {
      const mergedResponse: TranslationResponse = {
        ...mockResponse,
        blocks: [
          {
            id: 'child-1',
            box: [100, 100, 200, 300],
            parent_bubble_id: 'merged-bubble-99',
            translated_text: 'Khối thoại 1 trong bóng chùm',
          },
          {
            id: 'child-2',
            box: [220, 100, 320, 300],
            parent_bubble_id: 'merged-bubble-99',
            translated_text: 'Khối thoại 2 trong bóng chùm',
          },
        ],
      };

      const host = mountOverlay(mockImg, mergedResponse);
      const shadowRoot = host.shadowRoot!;
      const bubbles = shadowRoot.querySelectorAll('.inkshift-speech-bubble');
      expect(bubbles.length).toBe(2);

      const b1 = bubbles[0] as HTMLElement;
      const b2 = bubbles[1] as HTMLElement;

      expect(b1.dataset.parentBubbleId).toBe('merged-bubble-99');
      expect(b2.dataset.parentBubbleId).toBe('merged-bubble-99');

      // Dispatch mouseenter on b1
      b1.dispatchEvent(new MouseEvent('mouseenter'));
      expect(b1.classList.contains('inkshift-group-hover')).toBe(true);
      expect(b2.classList.contains('inkshift-group-hover')).toBe(true);

      // Dispatch mouseleave on b1
      b1.dispatchEvent(new MouseEvent('mouseleave'));
      expect(b1.classList.contains('inkshift-group-hover')).toBe(false);
      expect(b2.classList.contains('inkshift-group-hover')).toBe(false);
    });

    it('groups child blocks with parent_box into a shared parent container with relative text layer positioning', () => {
      const parentBox: [number, number, number, number] = [100, 100, 400, 400];
      const polygon: [number, number][] = [
        [10.0, 10.0],
        [90.0, 10.0],
        [90.0, 90.0],
        [10.0, 90.0],
      ];
      const mergedResponse: TranslationResponse = {
        ...mockResponse,
        blocks: [
          {
            id: 'child-1',
            box: [120, 120, 200, 380],
            parent_bubble_id: 'merged-bubble-1',
            parent_box: parentBox,
            polygon,
            translated_text: 'Thoại con 1',
          },
          {
            id: 'child-2',
            box: [250, 120, 380, 380],
            parent_bubble_id: 'merged-bubble-1',
            parent_box: parentBox,
            polygon,
            translated_text: 'Thoại con 2',
          },
        ],
      };

      const host = mountOverlay(mockImg, mergedResponse);
      const shadowRoot = host.shadowRoot!;
      // Should have only 1 shared parent bubble container
      const bubbles = shadowRoot.querySelectorAll('.inkshift-speech-bubble');
      expect(bubbles.length).toBe(1);

      const parentBubble = bubbles[0] as HTMLElement;
      expect(parentBubble.dataset.parentBubbleId).toBe('merged-bubble-1');

      // 1 shared mask layer with polygon
      const maskLayer = parentBubble.querySelector('.inkshift-mask-layer') as HTMLElement;
      expect(maskLayer).not.toBeNull();
      expect(maskLayer.style.clipPath).toBe('polygon(10% 10%, 90% 10%, 90% 90%, 10% 90%)');

      // 2 child text layers inside parentBubble
      const textLayers = parentBubble.querySelectorAll('.inkshift-text-layer');
      expect(textLayers.length).toBe(2);

      const t1 = textLayers[0] as HTMLElement;
      const t2 = textLayers[1] as HTMLElement;

      expect(t1.dataset.blockId).toBe('child-1');
      expect(t1.textContent).toBe('Thoại con 1');
      expect(t2.dataset.blockId).toBe('child-2');
      expect(t2.textContent).toBe('Thoại con 2');

      // Text layers positioned relative to parent (childTop - parentTop)
      expect(parseFloat(t1.style.top)).toBeGreaterThan(0);
      expect(parseFloat(t2.style.top)).toBeGreaterThan(parseFloat(t1.style.top));
    });

    it('positions single block textLayer within safe-zone coordinates when parent_box is defined', () => {
      const spikyResponse: TranslationResponse = {
        success: true,
        page_hash: 'spiky123',
        engine_used: 'local',
        execution_time_ms: 100,
        from_cache: false,
        blocks: [
          {
            id: 'star-block',
            box: [200, 200, 400, 400], // Safe-zone box within (100, 100, 500, 500)
            parent_box: [100, 100, 500, 500],
            parent_bubble_id: 'star-bubble-1',
            polygon: [
              [50, 10], [60, 35], [90, 50], [60, 65],
              [50, 90], [40, 65], [10, 50], [40, 35],
            ],
            translated_text: 'VINH DANH THIÊN CHÚA',
          },
        ],
      };

      const host = mountOverlay(mockImg, spikyResponse);
      const shadowRoot = host.shadowRoot!;
      const bubble = shadowRoot.querySelector('.inkshift-speech-bubble') as HTMLElement;
      expect(bubble).not.toBeNull();

      const textLayer = bubble.querySelector('.inkshift-text-layer') as HTMLElement;
      expect(textLayer).not.toBeNull();
      // textLayer must NOT be 100% width and 0 left, it must be positioned at relative safe-zone offset
      expect(textLayer.style.left).not.toBe('0px');
      expect(textLayer.style.left).not.toBe('0');
      expect(textLayer.style.width).not.toBe('100%');
      expect(parseFloat(textLayer.style.left)).toBeGreaterThan(0);
      expect(parseFloat(textLayer.style.top)).toBeGreaterThan(0);
    });

    it('includes forced-color-adjust and color-scheme in stylesheet for Dark Mode defense', () => {

      const host = mountOverlay(mockImg, mockResponse);
      const shadowRoot = host.shadowRoot!;
      let styleText = '';
      if (shadowRoot.adoptedStyleSheets && shadowRoot.adoptedStyleSheets.length > 0) {
        for (const sheet of shadowRoot.adoptedStyleSheets) {
          for (let i = 0; i < sheet.cssRules.length; i++) {
            styleText += sheet.cssRules[i].cssText + '\n';
          }
        }
      } else {
        const styleEl = shadowRoot.querySelector('style');
        styleText = styleEl?.textContent || '';
      }

      expect(styleText).toContain('forced-color-adjust');
      expect(styleText).toContain('color-scheme');
    });
  });

  describe('Lifecycle & Teardown', () => {
    it('removes single overlay via removeOverlay', () => {
      const host = mountOverlay(mockImg, mockResponse);
      expect(document.body.contains(host)).toBe(true);

      removeOverlay(mockImg);
      expect(document.body.contains(host)).toBe(false);
      expect(getOverlayHost(mockImg)).toBeUndefined();
    });

    it('cleans up all overlays via teardownAll', () => {
      const img2 = document.createElement('img');
      document.body.appendChild(img2);

      mountOverlay(mockImg, mockResponse);
      mountOverlay(img2, mockResponse);
      expect(document.querySelectorAll('.ink-shift-overlay-host').length).toBe(2);

      teardownAll();
      expect(document.querySelectorAll('.ink-shift-overlay-host').length).toBe(0);
    });
  });

  describe('Empty and Non-Text Block Filtering', () => {
    it('skips mounting speech bubbles for blocks with empty or whitespace-only translated_text', () => {
      const emptyBlocksResponse: TranslationResponse = {
        ...mockResponse,
        blocks: [
          {
            id: 'block-valid',
            box: [100, 200, 300, 500],
            translated_text: 'Thoại hợp lệ',
          },
          {
            id: 'block-empty-1',
            box: [400, 100, 600, 400],
            translated_text: '',
          },
          {
            id: 'block-empty-2',
            box: [650, 100, 800, 400],
            translated_text: '   \n\t  ',
          },
        ],
      };

      const host = mountOverlay(mockImg, emptyBlocksResponse);
      const shadowRoot = host.shadowRoot!;
      const bubbles = shadowRoot.querySelectorAll('.inkshift-speech-bubble');

      // Only the 1 non-empty block should be mounted
      expect(bubbles.length).toBe(1);
      expect(bubbles[0].textContent).toBe('Thoại hợp lệ');

      // Status pill should accurately report 1 translated block
      const pill = shadowRoot.querySelector('.inkshift-status-pill') as HTMLElement;
      expect(pill.textContent).toContain('✓ 1');
    });
  });

  describe('Dynamic Appearance & Visibility Updates', () => {
    it('computes correct relative contrast text colors', () => {
      expect(getContrastTextColor('#ffffff')).toBe('#000000');
      expect(getContrastTextColor('#000000')).toBe('#ffffff');
      expect(getContrastTextColor('#18181b')).toBe('#ffffff');
      expect(getContrastTextColor('#f4ecd8')).toBe('#000000');
    });

    it('computes background color with various opacity styles', () => {
      expect(computeBubbleBackgroundColor('#ffffff', 'opaque')).toBe('rgb(255, 255, 255)');
      expect(computeBubbleBackgroundColor('#ffffff', 'semi-transparent')).toBe(
        'rgba(255, 255, 255, 0.88)'
      );
      expect(computeBubbleBackgroundColor('#000000', 50)).toBe('rgba(0, 0, 0, 0.5)');
    });

    it('updates appearance and toggles visibility across all active overlays in real time', () => {
      const host = mountOverlay(mockImg, mockResponse);
      expect(getActiveOverlaysCount()).toBe(1);

      // Hide all overlays
      toggleAllOverlaysVisibility(false);
      expect(host.classList.contains('inkshift-overlay-hidden')).toBe(true);

      // Reveal all overlays
      toggleAllOverlaysVisibility(true);
      expect(host.classList.contains('inkshift-overlay-hidden')).toBe(false);
      expect(host.style.display).toBe('');

      // Dynamically update color and opacity
      updateActiveOverlaysAppearance({ color: '#18181b', opacity: 75 });
      const maskLayer = host.shadowRoot!.querySelector('.inkshift-mask-layer') as HTMLElement;
      const textLayer = host.shadowRoot!.querySelector('.inkshift-text-layer') as HTMLElement;

      expect(maskLayer.style.backgroundColor).toBe('rgba(24, 24, 27, 0.75)');
      expect(textLayer.style.color).toBe('rgb(255, 255, 255)');
    });

    it('preserves spatial culling (display: none) on past/culled hosts when toggling visibility', () => {
      const imgPast = document.createElement('img');
      const imgActive = document.createElement('img');
      document.body.appendChild(imgPast);
      document.body.appendChild(imgActive);

      // Past page is 0x0 or offscreen
      imgPast.getBoundingClientRect = () => ({
        left: 0,
        top: 0,
        width: 0,
        height: 0,
        right: 0,
        bottom: 0,
        x: 0,
        y: 0,
        toJSON: () => {},
      });
      imgActive.getBoundingClientRect = () => ({
        left: 100,
        top: 50,
        width: 800,
        height: 1200,
        right: 900,
        bottom: 1250,
        x: 100,
        y: 50,
        toJSON: () => {},
      });

      const hostPast = mountOverlay(imgPast, mockResponse);
      const hostActive = mountOverlay(imgActive, mockResponse);

      // Sync culls imgPast to display: 'none'
      syncOverlaysVisibilityAndPosition({ isSinglePage: true });
      expect(hostPast.style.display).toBe('none');
      expect(hostActive.style.display).toBe('');

      // User toggles visibility OFF globally
      toggleAllOverlaysVisibility(false);
      expect(hostPast.classList.contains('inkshift-overlay-hidden')).toBe(true);
      expect(hostActive.classList.contains('inkshift-overlay-hidden')).toBe(true);

      // User toggles visibility ON globally
      toggleAllOverlaysVisibility(true);
      expect(hostPast.classList.contains('inkshift-overlay-hidden')).toBe(false);
      expect(hostActive.classList.contains('inkshift-overlay-hidden')).toBe(false);

      // Critical assertion: hostPast MUST NOT have been resurrected with display = ''!
      expect(hostPast.style.display).toBe('none');
      expect(hostActive.style.display).toBe('');
    });

    it('supports double-page spread mode by preserving up to 2 active pages in viewport', () => {
      const imgLeft = document.createElement('img');
      const imgRight = document.createElement('img');
      const imgBuffer = document.createElement('img');
      document.body.appendChild(imgLeft);
      document.body.appendChild(imgRight);
      document.body.appendChild(imgBuffer);

      // Viewport is 1280x800. Left page at x: 20..620, Right page at x: 640..1240
      imgLeft.getBoundingClientRect = () => ({
        left: 20,
        top: 50,
        width: 600,
        height: 700,
        right: 620,
        bottom: 750,
        x: 20,
        y: 50,
        toJSON: () => {},
      });
      imgRight.getBoundingClientRect = () => ({
        left: 640,
        top: 50,
        width: 600,
        height: 700,
        right: 1240,
        bottom: 750,
        x: 640,
        y: 50,
        toJSON: () => {},
      });
      // Buffer page is off-screen
      imgBuffer.getBoundingClientRect = () => ({
        left: 2500,
        top: 50,
        width: 600,
        height: 700,
        right: 3100,
        bottom: 750,
        x: 2500,
        y: 50,
        toJSON: () => {},
      });

      const hostLeft = mountOverlay(imgLeft, mockResponse);
      const hostRight = mountOverlay(imgRight, mockResponse);
      const hostBuffer = mountOverlay(imgBuffer, mockResponse);

      syncOverlaysVisibilityAndPosition({ layoutMode: 'double' });

      // Both left and right pages must be visible simultaneously
      expect(hostLeft.style.display).toBe('');
      expect(hostRight.style.display).toBe('');
      // Buffer page must be culled
      expect(hostBuffer.style.display).toBe('none');
    });

    it('supports long-strip mode by displaying all intersecting pages and culling off-screen ones', () => {
      const imgTop = document.createElement('img');
      const imgBottom = document.createElement('img');
      const imgOffscreen = document.createElement('img');
      document.body.appendChild(imgTop);
      document.body.appendChild(imgBottom);
      document.body.appendChild(imgOffscreen);

      // imgTop is partially in viewport
      imgTop.getBoundingClientRect = () => ({
        left: 200,
        top: -200,
        width: 800,
        height: 600,
        right: 1000,
        bottom: 400,
        x: 200,
        y: -200,
        toJSON: () => {},
      });
      // imgBottom is in viewport
      imgBottom.getBoundingClientRect = () => ({
        left: 200,
        top: 410,
        width: 800,
        height: 600,
        right: 1000,
        bottom: 1010,
        x: 200,
        y: 410,
        toJSON: () => {},
      });
      // imgOffscreen is way down below viewport (vpHeight is 800)
      imgOffscreen.getBoundingClientRect = () => ({
        left: 200,
        top: 2500,
        width: 800,
        height: 600,
        right: 1000,
        bottom: 3100,
        x: 200,
        y: 2500,
        toJSON: () => {},
      });

      const hostTop = mountOverlay(imgTop, mockResponse);
      const hostBottom = mountOverlay(imgBottom, mockResponse);
      const hostOffscreen = mountOverlay(imgOffscreen, mockResponse);

      syncOverlaysVisibilityAndPosition({ layoutMode: 'strip' });

      expect(hostTop.style.display).toBe('');
      expect(hostBottom.style.display).toBe('');
      expect(hostOffscreen.style.display).toBe('none');
    });

    it('rescales speech bubbles when image dimensions shift by >= 15% (e.g. Single to Double page mode)', () => {
      const host = mountOverlay(mockImg, mockResponse);
      const shadowRoot = host.shadowRoot!;
      const bubble = shadowRoot.querySelector('.inkshift-speech-bubble') as HTMLElement;
      expect(bubble).not.toBeNull();
      const initialLeft = parseFloat(bubble.style.left);

      // Now simulate switching from Single page mode (800x1200) to Double page mode (400x600, 50% width reduction)
      Object.defineProperty(mockImg, 'clientWidth', { value: 400, configurable: true });
      Object.defineProperty(mockImg, 'clientHeight', { value: 600, configurable: true });
      mockImg.getBoundingClientRect = () => ({
        left: 100,
        top: 50,
        width: 400,
        height: 600,
        right: 500,
        bottom: 650,
        x: 100,
        y: 50,
        toJSON: () => {},
      });

      updateOverlayPosition(mockImg);

      expect(host.style.width).toBe('400px');
      expect(host.style.height).toBe('600px');

      // The bubble should have been re-rendered and rescaled to match 400px width
      const rescaledBubble = shadowRoot.querySelector('.inkshift-speech-bubble') as HTMLElement;
      expect(rescaledBubble).not.toBeNull();
      const rescaledLeft = parseFloat(rescaledBubble.style.left);
      expect(rescaledLeft).toBeLessThan(initialLeft);
      expect(Math.round(rescaledLeft)).toBe(Math.round(initialLeft * 0.5));
    });
  });

  describe('Manga Typography & Smart Fitting v2', () => {
    it('resolves font family identifiers to proper font stacks', () => {
      expect(resolveFontFamily('anime-ace-3')).toContain("'Anime Ace 3'");
      expect(resolveFontFamily('itim')).toContain("'Itim'");
      expect(resolveFontFamily('bangers')).toContain("'Bangers'");
      expect(resolveFontFamily('patrick-hand')).toContain("'Patrick Hand'");
      expect(resolveFontFamily('system-ui')).toContain('-apple-system');
      expect(resolveFontFamily()).toContain("'Itim'");
      expect(resolveFontFamily('CustomComicFont')).toBe('CustomComicFont');
    });

    it('sets host --inkshift-font-family CSS variable from mount options', () => {
      const host = mountOverlay(mockImg, mockResponse, { fontFamily: 'bangers' });
      const styleFont = host.style.getPropertyValue('--inkshift-font-family');
      expect(styleFont).toContain("'Bangers'");
    });

    it('maintains uniform normal font-weight across speech bubbles without artificial bolding', () => {
      // 1000x1000 normalized image; bubble box: [100, 100, 300, 300] => 20% width x 20% height on 800x1200 image
      // width = 160px, height = 240px => area = 38,400px^2 >= 10,000px^2
      const shoutResponse: TranslationResponse = {
        success: true,
        page_hash: 'shout123',
        engine_used: 'gemini-2.5-flash',
        execution_time_ms: 100,
        from_cache: false,
        blocks: [
          {
            id: 'shout-1',
            box: [100, 100, 300, 300],
            translated_text: 'CHẾT ĐI!',
          },
        ],
      };

      const host = mountOverlay(mockImg, shoutResponse);
      const textLayer = host.shadowRoot!.querySelector('.inkshift-text-layer') as HTMLElement;
      expect(textLayer).not.toBeNull();
      expect(textLayer.style.fontWeight).toBe('');
    });

    it('applies max-width 82% and centers horizontally for wide oval bubbles (aspect ratio >= 1.3, words >= 4)', () => {
      // Wide bubble: box [100, 100, 200, 500] => height = 100/1000 = 10% (120px), width = 400/1000 = 40% (320px)
      // aspect ratio = 320 / 120 = 2.66 >= 1.3
      const ovalResponse: TranslationResponse = {
        success: true,
        page_hash: 'oval123',
        engine_used: 'gemini-2.5-flash',
        execution_time_ms: 100,
        from_cache: false,
        blocks: [
          {
            id: 'oval-1',
            box: [100, 100, 200, 500],
            translated_text: 'Chúng ta nhất định phải cứu lấy mọi người!',
          },
        ],
      };

      const host = mountOverlay(mockImg, ovalResponse);
      const textLayer = host.shadowRoot!.querySelector('.inkshift-text-layer') as HTMLElement;
      expect(textLayer).not.toBeNull();
      expect(textLayer.style.maxWidth).toBe('82%');
      expect(textLayer.style.width).toBe('82%');
      expect(textLayer.style.left).toBe('9%');
    });

    it('updates --inkshift-font-family across active overlays in real-time', () => {
      const host = mountOverlay(mockImg, mockResponse, { fontFamily: 'itim' });
      expect(host.style.getPropertyValue('--inkshift-font-family')).toContain("'Itim'");

      updateActiveOverlaysAppearance({ fontFamily: 'patrick-hand' });
      expect(host.style.getPropertyValue('--inkshift-font-family')).toContain("'Patrick Hand'");
    });

    it('ensures overlay host is attached to document.body so textLayer is connected to DOM during initial font fitting', () => {
      let wasConnectedDuringMount = false;
      const originalAppend = document.body.appendChild.bind(document.body);
      const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((node: Node) => {
        const result = originalAppend(node);
        if (node instanceof HTMLElement && node.classList.contains('ink-shift-overlay-host')) {
          wasConnectedDuringMount = true;
        }
        return result;
      });

      const host = mountOverlay(mockImg, mockResponse);
      expect(wasConnectedDuringMount).toBe(true);
      expect(host.isConnected).toBe(true);
      appendSpy.mockRestore();
    });
  });
});

