/**
 * InkShift AI Engine & Model Selector UI Component
 * Reusable controller managing Engine mode (Auto, Local, Cloud),
 * Provider selection (Gemini, OpenAI, Claude, Custom), Text OCR router,
 * and Model Combobox.
 */

export interface ProviderModelInfo {
  id: string;
  display_name: string;
  supports_vision: boolean;
  context_window?: number;
}

export interface EngineSelectorElements {
  root: Document | ShadowRoot;
  engineSelectEl?: HTMLSelectElement | null;
  providerSelectEl?: HTMLSelectElement | null;
  providerContainerEl?: HTMLElement | null;
  translatorSelectEl?: HTMLSelectElement | null;
  translatorContainerEl?: HTMLElement | null;
  sourceLangContainerEl?: HTMLElement | null;
  modelContainerEl?: HTMLElement | null;
  modelSearchInputEl?: HTMLInputElement | null;
  modelDropdownListEl?: HTMLElement | null;
  filterVisionToggleEl?: HTMLInputElement | null;
}

export function normalizeProvider(prov?: string): string {
  if (!prov) return 'google';
  if (prov === 'gemini') return 'google';
  if (prov === 'xkiro') return 'custom';
  if (['google', 'openai', 'anthropic', 'custom'].includes(prov)) {
    return prov;
  }
  return 'google';
}

export class EngineSelectorUI {
  private elements: EngineSelectorElements;
  private currentModels: Record<string, ProviderModelInfo[]> = {
    google: [
      { id: 'gemini-2.5-flash', display_name: 'Gemini 2.5 Flash', supports_vision: true },
      { id: 'gemini-1.5-pro', display_name: 'Gemini 1.5 Pro', supports_vision: true },
      { id: 'gemini-1.5-flash', display_name: 'Gemini 1.5 Flash', supports_vision: true },
    ],
    openai: [
      { id: 'gpt-4o', display_name: 'GPT-4o (Omni)', supports_vision: true },
      { id: 'gpt-4o-mini', display_name: 'GPT-4o Mini', supports_vision: true },
    ],
    anthropic: [
      { id: 'claude-3-5-sonnet', display_name: 'Claude 3.5 Sonnet', supports_vision: true },
      { id: 'claude-3-haiku', display_name: 'Claude 3 Haiku', supports_vision: true },
    ],
    custom: [
      { id: 'custom-model', display_name: 'Custom Endpoint Model', supports_vision: true },
    ],
  };

  private onEngineChanged?: (engine: string) => void;
  private onModelSelected?: (modelId: string) => void;

  constructor(
    elements: EngineSelectorElements,
    onEngineChanged?: (engine: string) => void,
    onModelSelected?: (modelId: string) => void
  ) {
    this.elements = elements;
    this.onEngineChanged = onEngineChanged;
    this.onModelSelected = onModelSelected;
  }

  public init(): void {
    this.bindEvents();
    this.updateVisibility();
  }

  public bindEvents(): void {
    const { engineSelectEl, providerSelectEl, translatorSelectEl, modelSearchInputEl, filterVisionToggleEl } = this.elements;

    if (engineSelectEl) {
      engineSelectEl.addEventListener('change', () => {
        this.updateVisibility();
        this.save('engine', engineSelectEl.value);
        this.onEngineChanged?.(engineSelectEl.value);
      });
    }

    if (providerSelectEl) {
      providerSelectEl.addEventListener('change', () => {
        const prov = normalizeProvider(providerSelectEl.value);
        this.save('provider', prov);
        this.renderModelsDropdown();
      });
    }

    if (translatorSelectEl) {
      translatorSelectEl.addEventListener('change', () => {
        this.save('translator', translatorSelectEl.value);
        this.updateVisibility();
      });
    }

    if (modelSearchInputEl) {
      modelSearchInputEl.addEventListener('input', () => {
        this.renderModelsDropdown(modelSearchInputEl.value);
      });
    }

    if (filterVisionToggleEl) {
      filterVisionToggleEl.addEventListener('change', () => {
        this.renderModelsDropdown(modelSearchInputEl?.value || '');
      });
    }
  }

  public updateVisibility(): void {
    const {
      engineSelectEl,
      providerContainerEl,
      translatorContainerEl,
      sourceLangContainerEl,
      modelContainerEl,
      translatorSelectEl,
    } = this.elements;

    const engine = engineSelectEl?.value || 'auto';

    if (providerContainerEl) {
      providerContainerEl.classList.toggle('hidden', engine !== 'cloud');
    }

    if (translatorContainerEl) {
      translatorContainerEl.classList.toggle('hidden', engine !== 'local');
    }

    if (sourceLangContainerEl) {
      sourceLangContainerEl.classList.toggle('hidden', engine === 'cloud');
    }

    if (modelContainerEl) {
      if (engine === 'cloud') {
        modelContainerEl.classList.remove('hidden');
      } else if (engine === 'local') {
        const trans = translatorSelectEl?.value || 'google-free';
        const isLLM = trans.startsWith('llm-') || trans === 'llm-text';
        modelContainerEl.classList.toggle('hidden', !isLLM);
      } else {
        modelContainerEl.classList.add('hidden');
      }
    }
  }

  public getActiveProvider(): string {
    const { engineSelectEl, providerSelectEl, translatorSelectEl } = this.elements;
    const engine = engineSelectEl?.value || 'auto';

    if (engine === 'cloud') {
      return normalizeProvider(providerSelectEl?.value);
    }

    if (engine === 'local') {
      const trans = translatorSelectEl?.value;
      if (trans === 'llm-google' || trans === 'llm-gemini') return 'google';
      if (trans === 'llm-openai') return 'openai';
      if (trans === 'llm-anthropic') return 'anthropic';
      if (trans === 'llm-custom' || trans === 'llm-qwen') return 'custom';
      return 'google';
    }

    return 'google';
  }

  public renderModelsDropdown(query: string = ''): void {
    const { modelDropdownListEl, filterVisionToggleEl, modelSearchInputEl } = this.elements;
    if (!modelDropdownListEl) return;

    const provider = this.getActiveProvider();
    const allModels = this.currentModels[provider] || [];
    const shouldFilterVision = filterVisionToggleEl?.checked ?? false;

    let filtered = allModels;
    if (shouldFilterVision) {
      filtered = filtered.filter((m) => m.supports_vision);
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      filtered = filtered.filter(
        (m) => m.id.toLowerCase().includes(q) || m.display_name.toLowerCase().includes(q)
      );
    }

    modelDropdownListEl.innerHTML = '';
    if (filtered.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'combobox-empty-item';
      empty.textContent = 'Không tìm thấy model phù hợp';
      modelDropdownListEl.appendChild(empty);
      return;
    }

    for (const model of filtered) {
      const item = document.createElement('div');
      item.className = 'combobox-option-item';
      item.textContent = `${model.display_name} (${model.id})`;
      item.addEventListener('click', () => {
        if (modelSearchInputEl) {
          modelSearchInputEl.value = model.id;
        }
        this.save('model', model.id);
        this.onModelSelected?.(model.id);
        modelDropdownListEl.classList.add('hidden');
      });
      modelDropdownListEl.appendChild(item);
    }
  }

  public setProviderModels(modelsMap: Record<string, ProviderModelInfo[]>): void {
    this.currentModels = { ...this.currentModels, ...modelsMap };
    this.renderModelsDropdown();
  }

  private save(key: string, value: unknown): void {
    if (typeof chrome !== 'undefined' && chrome.storage?.local) {
      void chrome.storage.local.set({ [key]: value });
    }
  }
}
