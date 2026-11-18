/**
 * InkShift Aesthetics Controls UI Component
 * Modular controller managing comic font selection, speech bubble opacity slider,
 * and bubble palette swatches with live synchronization.
 */

export interface AestheticsElements {
  fontSelectEl?: HTMLSelectElement | null;
  opacitySliderEl?: HTMLInputElement | null;
  opacityValueEl?: HTMLElement | null;
  colorButtons?: NodeListOf<HTMLButtonElement> | HTMLButtonElement[];
}

export interface AestheticsSettings {
  fontFamily: string;
  opacity: number;
  bubbleColor: string;
}

export const DEFAULT_AESTHETICS: AestheticsSettings = {
  fontFamily: "'Itim', cursive, sans-serif",
  opacity: 88,
  bubbleColor: '#ffffff',
};

export class AestheticsControlsUI {
  private elements: AestheticsElements;
  private currentSettings: AestheticsSettings = { ...DEFAULT_AESTHETICS };
  private onChange?: (settings: AestheticsSettings) => void;

  constructor(elements: AestheticsElements, onChange?: (settings: AestheticsSettings) => void) {
    this.elements = elements;
    this.onChange = onChange;
  }

  public async init(): Promise<void> {
    await this.loadFromStorage();
    this.bindEvents();
    this.render();
  }

  public async loadFromStorage(): Promise<void> {
    if (typeof chrome !== 'undefined' && chrome.storage?.local) {
      try {
        const stored = await chrome.storage.local.get([
          'overlayFontFamily',
          'overlayOpacity',
          'overlayBubbleColor',
        ]);
        if (stored.overlayFontFamily) {
          this.currentSettings.fontFamily = stored.overlayFontFamily as string;
        }
        if (typeof stored.overlayOpacity === 'number') {
          this.currentSettings.opacity = stored.overlayOpacity as number;
        }
        if (stored.overlayBubbleColor) {
          this.currentSettings.bubbleColor = stored.overlayBubbleColor as string;
        }
      } catch {
        // Fall back to default
      }
    }
  }

  public bindEvents(): void {
    const { fontSelectEl, opacitySliderEl, colorButtons } = this.elements;

    if (fontSelectEl) {
      fontSelectEl.addEventListener('change', () => {
        this.currentSettings.fontFamily = fontSelectEl.value;
        void this.saveSetting('overlayFontFamily', fontSelectEl.value);
        this.notifyChange();
      });
    }

    if (opacitySliderEl) {
      opacitySliderEl.addEventListener('input', () => {
        const val = parseInt(opacitySliderEl.value, 10);
        this.currentSettings.opacity = val;
        this.updateOpacityDisplay(val);
      });

      opacitySliderEl.addEventListener('change', () => {
        const val = parseInt(opacitySliderEl.value, 10);
        void this.saveSetting('overlayOpacity', val);
        this.notifyChange();
      });
    }

    if (colorButtons) {
      colorButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
          const color = btn.getAttribute('data-color');
          if (color) {
            this.currentSettings.bubbleColor = color;
            this.highlightSelectedColor(color);
            void this.saveSetting('overlayBubbleColor', color);
            this.notifyChange();
          }
        });
      });
    }
  }

  public render(): void {
    const { fontSelectEl, opacitySliderEl } = this.elements;

    if (fontSelectEl) {
      fontSelectEl.value = this.currentSettings.fontFamily;
    }

    if (opacitySliderEl) {
      opacitySliderEl.value = this.currentSettings.opacity.toString();
    }

    this.updateOpacityDisplay(this.currentSettings.opacity);
    this.highlightSelectedColor(this.currentSettings.bubbleColor);
  }

  public updateOpacityDisplay(val: number): void {
    const { opacityValueEl } = this.elements;
    if (opacityValueEl) {
      opacityValueEl.textContent = `${val}%`;
    }
  }

  public highlightSelectedColor(selectedColor: string): void {
    const { colorButtons } = this.elements;
    if (!colorButtons) return;

    colorButtons.forEach((btn) => {
      const color = btn.getAttribute('data-color');
      if (color?.toLowerCase() === selectedColor.toLowerCase()) {
        btn.classList.add('active');
        btn.setAttribute('aria-pressed', 'true');
      } else {
        btn.classList.remove('active');
        btn.setAttribute('aria-pressed', 'false');
      }
    });
  }

  private async saveSetting(key: string, value: unknown): Promise<void> {
    if (typeof chrome !== 'undefined' && chrome.storage?.local) {
      try {
        await chrome.storage.local.set({ [key]: value });
      } catch {
        // storage save error
      }
    }
  }

  private notifyChange(): void {
    this.onChange?.({ ...this.currentSettings });
  }

  public getSettings(): AestheticsSettings {
    return { ...this.currentSettings };
  }
}
