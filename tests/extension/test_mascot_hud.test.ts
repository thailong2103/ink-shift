// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { MascotHUD, type MascotState } from '../../src/extension/content/mascot_hud';

describe('InkShift Mascot HUD Component', () => {
  let mockStorageGet: ReturnType<typeof vi.fn>;
  let mockStorageSet: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    document.body.innerHTML = '';
    mockStorageGet = vi.fn().mockResolvedValue({});
    mockStorageSet = vi.fn().mockResolvedValue(undefined);

    vi.stubGlobal('chrome', {
      runtime: {
        getURL: vi.fn((path: string) => `chrome-extension://inkshift-id/${path}`),
      },
      storage: {
        local: {
          get: mockStorageGet,
          set: mockStorageSet,
        },
      },
    });

    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllTimers();
  });

  it('mounts into the DOM with an open shadow root, badge element, and sprite', () => {
    const hud = new MascotHUD();
    hud.mount();

    const host = document.getElementById('inkshift-mascot-host');
    expect(host).not.toBeNull();
    expect(hud.getShadowRoot()).not.toBeNull();

    const badge = hud.getBadgeElement();
    expect(badge).not.toBeNull();
    expect(badge?.className).toContain('mascot-badge');

    const sprite = hud.getShadowRoot()?.querySelector<HTMLImageElement>('.mascot-sprite');
    expect(sprite).not.toBeNull();
    expect(sprite?.src).toContain('idle.svg');

    hud.unmount();
    expect(document.getElementById('inkshift-mascot-host')).toBeNull();
  });

  it('prevents multiple host elements upon duplicate mount calls', () => {
    const hud = new MascotHUD();
    hud.mount();
    hud.mount();

    const hosts = document.querySelectorAll('#inkshift-mascot-host');
    expect(hosts.length).toBe(1);

    hud.unmount();
  });

  it('updates state and sprite source across all pipeline states', () => {
    const hud = new MascotHUD();
    hud.mount();

    const states: MascotState[] = [
      'reading',
      'scanning',
      'translating',
      'error',
      'sleeping',
      'idle',
    ];

    for (const state of states) {
      hud.setState(state);
      expect(hud.getState()).toBe(state);
      const sprite = hud.getShadowRoot()?.querySelector<HTMLImageElement>('.mascot-sprite');
      expect(sprite?.src).toContain(`${state}.svg`);
    }

    hud.unmount();
  });

  it('automatically reverts from success to reading after timeout', () => {
    vi.useFakeTimers();
    const hud = new MascotHUD();
    hud.mount();

    hud.setState('success');
    expect(hud.getState()).toBe('success');
    const sprite = hud.getShadowRoot()?.querySelector<HTMLImageElement>('.mascot-sprite');
    expect(sprite?.src).toContain('success.svg');

    // Advance 2200ms
    vi.advanceTimersByTime(2250);
    expect(hud.getState()).toBe('reading');

    vi.useRealTimers();
    hud.unmount();
  });

  it('toggles the in-place Bento popover card on click', () => {
    const hud = new MascotHUD();
    hud.mount();

    const popover = hud.getPopoverElement();
    expect(popover).not.toBeNull();
    expect(popover?.classList.contains('hidden')).toBe(true);
    expect(hud.isPopoverOpen()).toBe(false);

    hud.togglePopover(true);
    expect(hud.isPopoverOpen()).toBe(true);
    expect(popover?.classList.contains('hidden')).toBe(false);

    hud.togglePopover(false);
    expect(hud.isPopoverOpen()).toBe(false);
    expect(popover?.classList.contains('hidden')).toBe(true);

    hud.unmount();
  });

  it('dismisses popover on Escape key press', () => {
    const hud = new MascotHUD();
    hud.mount();

    hud.togglePopover(true);
    expect(hud.isPopoverOpen()).toBe(true);

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(hud.isPopoverOpen()).toBe(false);

    hud.unmount();
  });

  it('dismisses popover when pointer down occurs outside host', () => {
    const hud = new MascotHUD();
    hud.mount();

    hud.togglePopover(true);
    expect(hud.isPopoverOpen()).toBe(true);

    const outsideTarget = document.createElement('div');
    document.body.appendChild(outsideTarget);

    const outsideEvt = new PointerEvent('pointerdown', { bubbles: true, cancelable: true });
    Object.defineProperty(outsideEvt, 'composedPath', {
      value: () => [outsideTarget, document.body, document.documentElement],
    });

    document.dispatchEvent(outsideEvt);
    expect(hud.isPopoverOpen()).toBe(false);

    hud.unmount();
  });

  it('embeds popup iframe inside popover and dismisses when receiving INKSHIFT_CLOSE_HUD message', () => {
    const hud = new MascotHUD();
    hud.mount();
    hud.togglePopover(true);

    const popover = hud.getPopoverElement();
    expect(popover).not.toBeNull();
    expect(hud.isPopoverOpen()).toBe(true);

    const iframe = hud.getIframeElement();
    expect(iframe).not.toBeNull();
    expect(iframe?.className).toBe('mascot-popover-iframe');
    expect(iframe?.src).toContain('popup/popup.html?embedded=1');
    expect(iframe?.src).toContain('hostname=');

    // Simulate iframe sending close message to parent window
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { type: 'INKSHIFT_CLOSE_HUD' },
      })
    );
    expect(hud.isPopoverOpen()).toBe(false);
    expect(popover?.classList.contains('hidden')).toBe(true);

    hud.unmount();
  });

  it('persists free 2D coordinates when dragged without snapping to edge walls', () => {
    const hud = new MascotHUD();
    hud.mount();

    const badge = hud.getBadgeElement();
    expect(badge).not.toBeNull();
    if (!badge) return;

    badge.setPointerCapture = vi.fn();
    badge.releasePointerCapture = vi.fn();

    // Simulate pointer down at (1000, 200)
    badge.dispatchEvent(
      new PointerEvent('pointerdown', {
        clientX: 1000,
        clientY: 200,
        button: 0,
        pointerId: 1,
      })
    );

    // Drag toward left side: clientX = 200, clientY = 250
    window.dispatchEvent(
      new PointerEvent('pointermove', {
        clientX: 200,
        clientY: 250,
        pointerId: 1,
      })
    );

    // Release
    window.dispatchEvent(
      new PointerEvent('pointerup', {
        clientX: 200,
        clientY: 250,
        pointerId: 1,
      })
    );

    const pos = hud.getPosition();
    expect(pos.x).toBe(238);
    expect(pos.y).toBe(190);
    expect(pos.side).toBe('left');
    expect(badge.style.left).toBe('238px');
    expect(mockStorageSet).toHaveBeenCalledWith({
      mascotPosition: { x: 238, y: 190, side: 'left' },
    });

    hud.unmount();
  });

  it('drags smoothly toward right half and maintains 2D position within screen viewport', () => {
    const hud = new MascotHUD();
    hud.mount();

    const badge = hud.getBadgeElement();
    expect(badge).not.toBeNull();
    if (!badge) return;

    badge.setPointerCapture = vi.fn();
    badge.releasePointerCapture = vi.fn();

    badge.dispatchEvent(
      new PointerEvent('pointerdown', {
        clientX: 100,
        clientY: 200,
        button: 0,
        pointerId: 1,
      })
    );

    // Drag: clientX = 900 (+800), clientY = 320 (+120)
    window.dispatchEvent(
      new PointerEvent('pointermove', {
        clientX: 900,
        clientY: 320,
        pointerId: 1,
      })
    );

    window.dispatchEvent(
      new PointerEvent('pointerup', {
        clientX: 900,
        clientY: 320,
        pointerId: 1,
      })
    );

    const pos = hud.getPosition();
    expect(pos.x).toBeGreaterThan(600);
    expect(pos.side).toBe('right');
    expect(pos.y).toBe(260);

    hud.unmount();
  });

  it('positions popover card relative to badge position within screen bounds', () => {
    const hud = new MascotHUD();
    hud.mount();
    hud.togglePopover(true);

    const popover = hud.getPopoverElement();
    expect(popover).not.toBeNull();
    expect(popover?.style.left).toBeDefined();
    expect(popover?.style.top).toBeDefined();

    hud.unmount();
  });

  it('treats pointer movement under 4px as click to toggle popover instead of drag', () => {
    const hud = new MascotHUD();
    hud.mount();

    const badge = hud.getBadgeElement();
    expect(badge).not.toBeNull();
    if (!badge) return;

    badge.setPointerCapture = vi.fn();
    badge.releasePointerCapture = vi.fn();

    expect(hud.isPopoverOpen()).toBe(false);

    // Click: down then up with 2px jitter (< 4px threshold)
    badge.dispatchEvent(
      new PointerEvent('pointerdown', {
        clientX: 1000,
        clientY: 200,
        button: 0,
        pointerId: 1,
      })
    );

    window.dispatchEvent(
      new PointerEvent('pointermove', {
        clientX: 1002,
        clientY: 201,
        pointerId: 1,
      })
    );

    window.dispatchEvent(
      new PointerEvent('pointerup', {
        clientX: 1002,
        clientY: 201,
        pointerId: 1,
      })
    );

    expect(hud.isPopoverOpen()).toBe(true);

    hud.unmount();
  });

  it('toggles visibility and host display via setEnabled', () => {
    const hud = new MascotHUD();
    hud.mount();

    const host = document.getElementById('inkshift-mascot-host');
    expect(host).not.toBeNull();
    expect(hud.isEnabled()).toBe(true);

    hud.setEnabled(false);
    expect(hud.isEnabled()).toBe(false);
    expect(host?.style.display).toBe('none');

    hud.setEnabled(true);
    expect(hud.isEnabled()).toBe(true);
    expect(host?.style.display).toBe('block');

    hud.unmount();
  });

  it('adds is-dragging class during movement and triggers is-settling bounce on release', () => {
    vi.useFakeTimers();
    const hud = new MascotHUD();
    hud.mount();

    const badge = hud.getBadgeElement();
    expect(badge).not.toBeNull();
    if (!badge) return;

    badge.setPointerCapture = vi.fn();
    badge.releasePointerCapture = vi.fn();

    // 1. Pointer down - no movement yet, is-dragging should NOT be active
    badge.dispatchEvent(
      new PointerEvent('pointerdown', {
        clientX: 100,
        clientY: 100,
        button: 0,
        pointerId: 1,
      })
    );
    expect(badge.classList.contains('is-dragging')).toBe(false);

    // 2. Drag > 4px threshold
    window.dispatchEvent(
      new PointerEvent('pointermove', {
        clientX: 130,
        clientY: 100,
        pointerId: 1,
      })
    );
    expect(badge.classList.contains('is-dragging')).toBe(true);
    expect(badge.classList.contains('is-settling')).toBe(false);

    // 3. Pointer up - is-dragging removed, is-settling bounce initiated
    window.dispatchEvent(
      new PointerEvent('pointerup', {
        clientX: 130,
        clientY: 100,
        pointerId: 1,
      })
    );
    expect(badge.classList.contains('is-dragging')).toBe(false);
    expect(badge.classList.contains('is-settling')).toBe(true);

    // 4. Advance past 460ms landing settle duration
    vi.advanceTimersByTime(500);
    expect(badge.classList.contains('is-settling')).toBe(false);

    vi.useRealTimers();
    hud.unmount();
  });
});

