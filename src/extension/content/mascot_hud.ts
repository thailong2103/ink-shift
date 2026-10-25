/**
 * InkShift Dynamic Floating Mascot HUD Component.
 *
 * Provides an in-page, freely 2D draggable Mascot Companion rendered inside
 * an isolated Shadow DOM v1. Expands into a full-featured Bento HUD by directly
 * embedding the extension's original popup via an isolated iframe.
 *
 * Architecture (ADR-016 Option 1: Embedded Iframe Single Source of Truth):
 * - Prominent 150px × 160px Mascot scale with full 2D physics and squishy settle bounce.
 * - Reactive 7-state sprite machine (idle, reading, scanning, translating, success, error, sleeping).
 * - Direct iframe integration with popup.html?embedded=1 ensuring 100% feature parity.
 * - Zero duplicated DOM templates or desynchronized settings logic.
 */

import { createExtensionLogger } from '../shared/extension_logger';
import { normalizeHostname } from '../shared/domain_filter';

const logger = createExtensionLogger('MascotHUD');

export type MascotState =
  | 'idle'
  | 'reading'
  | 'scanning'
  | 'translating'
  | 'success'
  | 'error'
  | 'sleeping';

export interface MascotPosition {
  x?: number;
  y: number;
  side?: 'left' | 'right';
}

export interface MascotHUDCallbacks {
  onRescanRequested?: () => void;
  onVisibilityToggled?: (visible: boolean) => void;
  onFontChanged?: (font: string) => void;
  onOpacityChanged?: (opacity: number) => void;
  onColorChanged?: (color: string) => void;
}

export class MascotHUD {
  private host: HTMLElement | null = null;
  private shadow: ShadowRoot | null = null;
  private badgeEl: HTMLElement | null = null;
  private spriteImg: HTMLImageElement | null = null;
  private popoverEl: HTMLElement | null = null;
  private iframeEl: HTMLIFrameElement | null = null;

  private currentState: MascotState = 'idle';
  private successTimer: ReturnType<typeof setTimeout> | null = null;
  private isExpanded: boolean = false;
  private isDragging: boolean = false;
  private hasMoved: boolean = false;
  private pointerStartX: number = 0;
  private pointerStartY: number = 0;
  private initialX: number = 0;
  private initialY: number = 0;
  private lastPointerX: number = 0;
  private settleTimer: ReturnType<typeof setTimeout> | null = null;

  private position: MascotPosition = { side: 'right', y: 140 };
  private callbacks: MascotHUDCallbacks = {};
  private currentHostname: string = '';

  constructor(callbacks?: MascotHUDCallbacks) {
    if (callbacks) {
      this.callbacks = callbacks;
    }
    try {
      if (typeof window !== 'undefined' && window.location?.hostname) {
        this.currentHostname = normalizeHostname(window.location.hostname);
      }
    } catch {
      this.currentHostname = 'mangadex.org';
    }
  }

  /**
   * Mounts the isolated Mascot HUD into the document.
   */
  public mount(targetParent: HTMLElement = document.body): void {
    if (this.host) return;

    this.host = document.createElement('div');
    this.host.id = 'inkshift-mascot-host';
    this.host.style.position = 'fixed';
    this.host.style.zIndex = '2147483647';
    this.host.style.pointerEvents = 'none';
    this.host.style.top = '0';
    this.host.style.left = '0';
    this.host.style.width = '100%';
    this.host.style.height = '100%';

    this.shadow = this.host.attachShadow({ mode: 'open' });
    this.buildShadowDOM();

    targetParent.appendChild(this.host);

    void this.loadPersistedPosition();
    this.attachGlobalDismissalListeners();
    window.addEventListener('message', this.handleWindowMessage);
    logger.info('Mascot HUD mounted successfully');
  }

  public unmount(): void {
    if (this.successTimer) {
      clearTimeout(this.successTimer);
      this.successTimer = null;
    }
    if (this.settleTimer) {
      clearTimeout(this.settleTimer);
      this.settleTimer = null;
    }
    this.removeGlobalDismissalListeners();
    window.removeEventListener('message', this.handleWindowMessage);
    if (this.host && this.host.parentNode) {
      this.host.parentNode.removeChild(this.host);
    }
    this.host = null;
    this.shadow = null;
    this.badgeEl = null;
    this.spriteImg = null;
    this.popoverEl = null;
    this.iframeEl = null;
  }

  public setState(state: MascotState): void {
    if (this.currentState === state) return;

    if (this.successTimer) {
      clearTimeout(this.successTimer);
      this.successTimer = null;
    }

    this.currentState = state;
    this.updateSpriteSource();

    if (state === 'success') {
      this.successTimer = setTimeout(() => {
        if (this.currentState === 'success') {
          this.setState('reading');
        }
      }, 2200);
    }
  }

  public getState(): MascotState {
    return this.currentState;
  }

  public isPopoverOpen(): boolean {
    return this.isExpanded;
  }

  public togglePopover(force?: boolean): void {
    const next = typeof force === 'boolean' ? force : !this.isExpanded;
    this.isExpanded = next;

    if (!this.popoverEl) return;

    if (this.isExpanded) {
      this.popoverEl.classList.remove('hidden');
      this.positionPopover();
    } else {
      this.popoverEl.classList.add('hidden');
    }
  }

  public setPosition(pos: MascotPosition): void {
    this.position = { ...pos };
    this.applyBadgePosition();
  }

  public getPosition(): MascotPosition {
    return { ...this.position };
  }

  public getShadowRoot(): ShadowRoot | null {
    return this.shadow;
  }

  public getBadgeElement(): HTMLElement | null {
    return this.badgeEl;
  }

  public getPopoverElement(): HTMLElement | null {
    return this.popoverEl;
  }

  public getIframeElement(): HTMLIFrameElement | null {
    return this.iframeEl;
  }

  public setEnabled(enabled: boolean): void {
    if (this.host) {
      this.host.style.display = enabled ? 'block' : 'none';
    }
    if (!enabled && this.isExpanded) {
      this.togglePopover(false);
    }
  }

  public isEnabled(): boolean {
    return this.host ? this.host.style.display !== 'none' : true;
  }

  /**
   * Builds Shadow DOM stylesheet, badge container, and popover iframe using 3-layer tokens.
   */
  private buildShadowDOM(): void {
    if (!this.shadow) return;

    const style = document.createElement('style');
    style.textContent = `
      :host {
        /* Standard 3-Layer Design Tokens */
        --inkshift-bg: #12100E;
        --inkshift-card: #1C1917;
        --inkshift-border-subtle: #2E2825;
        --inkshift-border-brand: rgba(222, 136, 109, 0.35);
        --inkshift-brand: #DE886D;
        --inkshift-brand-hover: #E89D84;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }

      /* Prominent 150px × 160px Mascot Scale */
      .mascot-badge {
        position: fixed;
        width: 150px;
        height: 160px;
        background: transparent;
        border: none;
        box-shadow: none;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: grab;
        user-select: none;
        pointer-events: auto;
        touch-action: none;
        transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1);
        z-index: 2147483646;
        filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.75)) drop-shadow(0 0 12px rgba(222, 136, 109, 0.5));
      }

      .mascot-badge:hover {
        transform: translateY(-4px) scale(1.06);
        filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.85)) drop-shadow(0 0 16px rgba(222, 136, 109, 0.7));
      }

      .mascot-badge:active {
        cursor: grabbing;
        transform: scale(1.02);
      }

      .mascot-badge.is-dragging {
        cursor: grabbing !important;
        transform: scale(1.15) rotate(var(--drag-tilt, 0deg)) !important;
        transition: transform 60ms ease-out, filter 150ms ease !important;
        filter: drop-shadow(0 16px 30px rgba(0, 0, 0, 0.85)) drop-shadow(0 0 24px rgba(222, 136, 109, 0.95)) !important;
      }

      .mascot-badge.is-dragging .mascot-sprite {
        animation: mascot-dangle 1.2s ease-in-out infinite alternate;
        transform-origin: 50% 15%;
      }

      .mascot-badge.is-settling {
        animation: mascot-settle 460ms cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
      }

      @keyframes mascot-dangle {
        0% { transform: translateY(-3px) rotate(-3deg) scale(1.02, 0.98); }
        50% { transform: translateY(3px) rotate(3deg) scale(0.98, 1.02); }
        100% { transform: translateY(-2px) rotate(-2deg) scale(1.01, 0.99); }
      }

      @keyframes mascot-settle {
        0% { transform: scale(1.15) translateY(0); }
        35% { transform: scale(0.92, 1.12) translateY(6px); }
        65% { transform: scale(1.06, 0.96) translateY(-3px); }
        85% { transform: scale(0.98, 1.02) translateY(1px); }
        100% { transform: scale(1) translateY(0); }
      }

      .mascot-sprite {
        width: 150px;
        height: 160px;
        image-rendering: pixelated;
        image-rendering: crisp-edges;
        pointer-events: none;
        display: block;
      }

      /* Popover Card & Embedded Iframe */
      .mascot-popover {
        position: fixed;
        width: 382px;
        height: 592px;
        max-height: calc(100vh - 24px);
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid var(--inkshift-border-brand, rgba(222, 136, 109, 0.35));
        background: var(--inkshift-bg, #12100E);
        box-shadow: 0 16px 36px rgba(0, 0, 0, 0.75), 0 0 24px rgba(222, 136, 109, 0.2);
        z-index: 2147483647;
        pointer-events: auto;
        transition: opacity 180ms cubic-bezier(0.16, 1, 0.3, 1), transform 180ms cubic-bezier(0.16, 1, 0.3, 1);
        transform-origin: top left;
      }

      .mascot-popover.hidden {
        display: none !important;
      }

      .mascot-popover-iframe {
        width: 100%;
        height: 100%;
        border: none;
        display: block;
        background: transparent;
      }
    `;

    this.shadow.appendChild(style);

    // Mascot Badge
    this.badgeEl = document.createElement('div');
    this.badgeEl.className = 'mascot-badge';
    this.badgeEl.setAttribute('role', 'button');
    this.badgeEl.setAttribute('aria-label', 'InkShift Assistant Mascot');

    this.spriteImg = document.createElement('img');
    this.spriteImg.className = 'mascot-sprite';
    this.spriteImg.alt = 'InkShift Mascot';
    this.updateSpriteSource();

    this.badgeEl.appendChild(this.spriteImg);
    this.shadow.appendChild(this.badgeEl);

    // Draggable Pointer listeners
    this.badgeEl.addEventListener('pointerdown', this.handlePointerDown);

    // Popover Element with Embedded Iframe
    this.buildPopoverElement();
    if (this.popoverEl) {
      this.shadow.appendChild(this.popoverEl);
    }

    this.applyBadgePosition();
  }

  private buildPopoverElement(): void {
    this.popoverEl = document.createElement('div');
    this.popoverEl.className = 'mascot-popover hidden';

    this.iframeEl = document.createElement('iframe');
    this.iframeEl.className = 'mascot-popover-iframe';
    const popupRelPath = `popup/popup.html?embedded=1&hostname=${encodeURIComponent(this.currentHostname)}`;
    const popupUrl = typeof chrome !== 'undefined' && chrome.runtime?.getURL
      ? chrome.runtime.getURL(popupRelPath)
      : popupRelPath;

    this.iframeEl.src = popupUrl;
    this.iframeEl.title = 'InkShift Settings Dashboard';
    this.iframeEl.setAttribute('frameborder', '0');
    this.iframeEl.setAttribute('scrolling', 'no');

    this.popoverEl.appendChild(this.iframeEl);
  }

  private updateSpriteSource(): void {
    if (!this.spriteImg) return;
    const stateMap: Record<MascotState, string> = {
      idle: 'idle.svg',
      reading: 'reading.svg',
      scanning: 'scanning.svg',
      translating: 'translating.svg',
      success: 'success.svg',
      error: 'error.svg',
      sleeping: 'sleeping.svg',
    };

    const fileName = stateMap[this.currentState] || 'idle.svg';
    const path = `assets/mascot/${fileName}`;
    if (typeof chrome !== 'undefined' && chrome.runtime?.getURL) {
      this.spriteImg.src = chrome.runtime.getURL(path);
    } else {
      this.spriteImg.src = path;
    }
  }

  private handlePointerDown = (e: PointerEvent): void => {
    if (e.button !== 0 || !this.badgeEl) return;

    this.isDragging = true;
    this.hasMoved = false;
    this.pointerStartX = e.clientX;
    this.pointerStartY = e.clientY;
    this.lastPointerX = e.clientX;

    const parsedLeft = parseFloat(this.badgeEl.style.left);
    const parsedTop = parseFloat(this.badgeEl.style.top);

    if (!isNaN(parsedLeft)) {
      this.initialX = parsedLeft;
    } else if (typeof this.position.x === 'number') {
      this.initialX = this.position.x;
    } else {
      this.initialX = this.position.side === 'left' ? 12 : Math.max(8, window.innerWidth - 162);
    }

    if (!isNaN(parsedTop)) {
      this.initialY = parsedTop;
    } else {
      this.initialY = this.position.y;
    }

    if (typeof this.badgeEl.setPointerCapture === 'function') {
      try {
        this.badgeEl.setPointerCapture(e.pointerId);
      } catch {
        // Mock fallback
      }
    }

    window.addEventListener('pointermove', this.handlePointerMove);
    window.addEventListener('pointerup', this.handlePointerUp);
    window.addEventListener('pointercancel', this.handlePointerUp);

    e.stopPropagation();
  };

  private handlePointerMove = (e: PointerEvent): void => {
    if (!this.isDragging || !this.badgeEl) return;

    const deltaX = e.clientX - this.pointerStartX;
    const deltaY = e.clientY - this.pointerStartY;

    if (Math.abs(deltaX) > 4 || Math.abs(deltaY) > 4) {
      this.hasMoved = true;
    }

    if (this.hasMoved) {
      if (!this.badgeEl.classList.contains('is-dragging')) {
        this.badgeEl.classList.add('is-dragging');
        this.badgeEl.classList.remove('is-settling');
        if (this.settleTimer) {
          clearTimeout(this.settleTimer);
          this.settleTimer = null;
        }
      }

      const moveDeltaX = e.clientX - this.lastPointerX;
      this.lastPointerX = e.clientX;
      const tilt = Math.max(-14, Math.min(14, moveDeltaX * 1.5));
      this.badgeEl.style.setProperty('--drag-tilt', `${tilt}deg`);

      const curX = Math.max(8, Math.min(window.innerWidth - 162, this.initialX + deltaX));
      const curY = Math.max(8, Math.min(window.innerHeight - 172, this.initialY + deltaY));

      this.badgeEl.style.left = `${curX}px`;
      this.badgeEl.style.top = `${curY}px`;
      this.badgeEl.style.right = 'auto';
      this.badgeEl.style.bottom = 'auto';

      if (this.isExpanded) {
        this.positionPopover();
      }
    }
  };

  private handlePointerUp = (e: PointerEvent): void => {
    if (!this.isDragging || !this.badgeEl) return;

    this.isDragging = false;
    this.badgeEl.classList.remove('is-dragging');
    this.badgeEl.style.setProperty('--drag-tilt', '0deg');

    if (typeof this.badgeEl.releasePointerCapture === 'function') {
      try {
        this.badgeEl.releasePointerCapture(e.pointerId);
      } catch {
        // Mock fallback
      }
    }

    window.removeEventListener('pointermove', this.handlePointerMove);
    window.removeEventListener('pointerup', this.handlePointerUp);
    window.removeEventListener('pointercancel', this.handlePointerUp);

    if (!this.hasMoved) {
      this.togglePopover();
      return;
    }

    this.badgeEl.classList.add('is-settling');
    if (this.settleTimer) {
      clearTimeout(this.settleTimer);
    }
    this.settleTimer = setTimeout(() => {
      this.badgeEl?.classList.remove('is-settling');
      this.settleTimer = null;
    }, 460);

    const currentLeft = parseFloat(this.badgeEl.style.left || '12');
    const currentTop = parseFloat(this.badgeEl.style.top || '140');
    const side: 'left' | 'right' = currentLeft + 75 < window.innerWidth / 2 ? 'left' : 'right';

    this.position = { x: currentLeft, y: currentTop, side };

    if (typeof chrome !== 'undefined' && chrome.storage?.local) {
      void chrome.storage.local.set({
        mascotPosition: { x: currentLeft, y: currentTop, side },
      });
    }
  };

  private positionPopover(): void {
    if (!this.popoverEl || !this.badgeEl) return;

    const badgeRect = this.badgeEl.getBoundingClientRect();
    const popoverWidth = 382;
    const popoverHeight = 592;

    let left = badgeRect.left - popoverWidth - 16;
    if (badgeRect.left + 75 < window.innerWidth / 2 || left < 12) {
      left = badgeRect.right + 16;
    }
    if (left + popoverWidth > window.innerWidth - 12) {
      left = window.innerWidth - popoverWidth - 12;
    }
    if (left < 12) left = 12;

    let top = badgeRect.top;
    if (top + popoverHeight > window.innerHeight - 12) {
      top = window.innerHeight - popoverHeight - 12;
    }
    if (top < 12) top = 12;

    this.popoverEl.style.left = `${left}px`;
    this.popoverEl.style.top = `${top}px`;
  }

  private applyBadgePosition(): void {
    if (!this.badgeEl) return;

    if (typeof this.position.x === 'number') {
      const clampedX = Math.max(8, Math.min(window.innerWidth - 162, this.position.x));
      const clampedY = Math.max(8, Math.min(window.innerHeight - 172, this.position.y));
      this.badgeEl.style.left = `${clampedX}px`;
      this.badgeEl.style.top = `${clampedY}px`;
      this.badgeEl.style.right = 'auto';
      this.badgeEl.style.bottom = 'auto';
      return;
    }

    this.badgeEl.style.top = `${this.position.y}px`;
    if (this.position.side === 'left') {
      this.badgeEl.style.left = '12px';
      this.badgeEl.style.right = 'auto';
    } else {
      this.badgeEl.style.left = `${Math.max(8, window.innerWidth - 162)}px`;
      this.badgeEl.style.right = 'auto';
    }
  }

  private async loadPersistedPosition(): Promise<void> {
    if (typeof chrome === 'undefined' || !chrome.storage?.local) return;
    try {
      const data = await chrome.storage.local.get(['mascotPosition']);
      if (data?.mascotPosition) {
        this.position = { ...this.position, ...data.mascotPosition };
      }
    } catch {
      // Fallback
    }
    this.applyBadgePosition();
  }

  private attachGlobalDismissalListeners(): void {
    window.addEventListener('keydown', this.handleKeyDown);
    document.addEventListener('pointerdown', this.handleOutsidePointerDown);
  }

  private removeGlobalDismissalListeners(): void {
    window.removeEventListener('keydown', this.handleKeyDown);
    document.removeEventListener('pointerdown', this.handleOutsidePointerDown);
  }

  private handleKeyDown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape' && this.isExpanded) {
      this.togglePopover(false);
    }
  };

  private handleOutsidePointerDown = (e: PointerEvent): void => {
    if (!this.isExpanded || !this.host) return;
    const path = e.composedPath();
    if (!path.includes(this.host)) {
      this.togglePopover(false);
    }
  };

  private handleWindowMessage = (e: MessageEvent): void => {
    if (e.data && e.data.type === 'INKSHIFT_CLOSE_HUD') {
      this.togglePopover(false);
    }
  };
}
