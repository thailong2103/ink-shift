/**
 * InkShift Settings Drawer UI Component
 * Modular controller managing API keys, prefetch depth, and collapsible drawers.
 */

import { Icons } from '../shared/icons';

export interface SettingsDrawerElements {
  root: Document | ShadowRoot;
  drawers?: Array<{
    triggerEl: HTMLElement | null;
    contentEl: HTMLElement | null;
    chevronEl?: HTMLElement | null;
  }>;
  geminiKeyInputEl?: HTMLInputElement | null;
  openaiKeyInputEl?: HTMLInputElement | null;
  claudeKeyInputEl?: HTMLInputElement | null;
  customKeyInputEl?: HTMLInputElement | null;
  customEndpointInputEl?: HTMLInputElement | null;
  prefetchToggleEl?: HTMLInputElement | null;
  prefetchDepthSelectEl?: HTMLSelectElement | null;
}

export class SettingsDrawerUI {
  private elements: SettingsDrawerElements;

  constructor(elements: SettingsDrawerElements) {
    this.elements = elements;
  }

  public init(): void {
    this.setupDrawers();
    this.bindInputs();
    void this.loadSettings();
  }

  public setupDrawers(): void {
    if (!this.elements.drawers) return;

    for (const drawer of this.elements.drawers) {
      if (!drawer.triggerEl || !drawer.contentEl) continue;

      // Ensure initial collapsed chevron
      if (drawer.chevronEl) {
        drawer.chevronEl.innerHTML = Icons.chevronRight({ size: 14 });
      }

      drawer.triggerEl.addEventListener('click', (e) => {
        e.preventDefault();
        const isCollapsed = drawer.contentEl?.classList.contains('hidden');
        if (isCollapsed) {
          drawer.contentEl?.classList.remove('hidden');
          drawer.triggerEl?.classList.add('drawer-open');
          if (drawer.chevronEl) {
            drawer.chevronEl.innerHTML = Icons.chevronDown({ size: 14 });
          }
        } else {
          drawer.contentEl?.classList.add('hidden');
          drawer.triggerEl?.classList.remove('drawer-open');
          if (drawer.chevronEl) {
            drawer.chevronEl.innerHTML = Icons.chevronRight({ size: 14 });
          }
        }
      });
    }
  }

  public bindInputs(): void {
    const {
      geminiKeyInputEl,
      openaiKeyInputEl,
      claudeKeyInputEl,
      customKeyInputEl,
      customEndpointInputEl,
      prefetchToggleEl,
      prefetchDepthSelectEl,
    } = this.elements;

    const bindKey = (input: HTMLInputElement | null | undefined, storageKey: string) => {
      if (!input) return;
      input.addEventListener('change', () => {
        this.save(storageKey, input.value.trim());
      });
    };

    bindKey(geminiKeyInputEl, 'geminiApiKey');
    bindKey(openaiKeyInputEl, 'openaiApiKey');
    bindKey(claudeKeyInputEl, 'claudeApiKey');
    bindKey(customKeyInputEl, 'customApiKey');
    bindKey(customEndpointInputEl, 'customApiEndpoint');

    if (prefetchToggleEl) {
      prefetchToggleEl.addEventListener('change', () => {
        this.save('prefetchEnabled', prefetchToggleEl.checked);
      });
    }

    if (prefetchDepthSelectEl) {
      prefetchDepthSelectEl.addEventListener('change', () => {
        const depth = parseInt(prefetchDepthSelectEl.value, 10);
        this.save('prefetchDepth', depth);
      });
    }
  }

  public async loadSettings(): Promise<void> {
    if (typeof chrome === 'undefined' || !chrome.storage?.local) return;

    try {
      const stored = await chrome.storage.local.get([
        'geminiApiKey',
        'openaiApiKey',
        'claudeApiKey',
        'customApiKey',
        'customApiEndpoint',
        'prefetchEnabled',
        'prefetchDepth',
      ]);

      const {
        geminiKeyInputEl,
        openaiKeyInputEl,
        claudeKeyInputEl,
        customKeyInputEl,
        customEndpointInputEl,
        prefetchToggleEl,
        prefetchDepthSelectEl,
      } = this.elements;

      if (geminiKeyInputEl && stored.geminiApiKey) geminiKeyInputEl.value = stored.geminiApiKey as string;
      if (openaiKeyInputEl && stored.openaiApiKey) openaiKeyInputEl.value = stored.openaiApiKey as string;
      if (claudeKeyInputEl && stored.claudeApiKey) claudeKeyInputEl.value = stored.claudeApiKey as string;
      if (customKeyInputEl && stored.customApiKey) customKeyInputEl.value = stored.customApiKey as string;
      if (customEndpointInputEl && stored.customApiEndpoint) customEndpointInputEl.value = stored.customApiEndpoint as string;

      if (prefetchToggleEl && stored.prefetchEnabled !== undefined) {
        prefetchToggleEl.checked = Boolean(stored.prefetchEnabled);
      }
      if (prefetchDepthSelectEl && stored.prefetchDepth) {
        prefetchDepthSelectEl.value = String(stored.prefetchDepth);
      }
    } catch {
      // storage load error
    }
  }

  private save(key: string, value: unknown): void {
    if (typeof chrome !== 'undefined' && chrome.storage?.local) {
      void chrome.storage.local.set({ [key]: value });
    }
  }
}
