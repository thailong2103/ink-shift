/**
 * InkShift Extension Settings Popup Controller.
 *
 * Manages live backend health connectivity checks, engine mode selection,
 * opacity toggling, visual geometry debug overlays, and manual page re-scanning.
 */

import type {
  IPCMessage,
  BackendHealthResponse,
  PageReaderStatusData,
  DiscoveredModel,
  DiscoveredModelsData,
  ProviderSettingsData,
  SaveProviderSettingsData,
  IPCResponse,
  ClearCacheResponseData,
} from '../shared/ipc_types';
import {
  loadDomainFilterSettings,
  saveDomainFilterSettings,
  resetToDefaultFilterSettings,
  normalizeHostname,
  matchesDomain,
  type DomainFilterSettings,
} from '../shared/domain_filter';
import { createExtensionLogger } from '../shared/extension_logger';
import { Icons } from '../shared/icons';

const logger = createExtensionLogger('Popup');

export let activeTabId: number | null = null;
export let activeTabHostname: string = '';
export let currentDomainSettings: DomainFilterSettings | null = null;

export let currentProviderModels: Record<string, DiscoveredModel[]> = {};
export let selectedModelsByProvider: Record<string, string> = {};
export let activeComboboxIndex: number = -1;
export let isComboboxOpen: boolean = false;


/**
 * Checks backend API server connectivity via privileged service worker IPC.
 */
export async function checkBackendHealth(): Promise<boolean> {
  const badge = document.getElementById('backend-status-badge');
  if (badge) {
    badge.innerHTML = `${Icons.statusDot('checking')} Checking...`;
    badge.className = 'status-indicator';
  }

  try {
    const message: IPCMessage = { type: 'CHECK_BACKEND_HEALTH' };
    const response = (await chrome.runtime.sendMessage(message)) as BackendHealthResponse;

    if (response && response.success === true) {
      if (badge) {
        badge.innerHTML = `${Icons.statusDot('online')} Online`;
        badge.className = 'status-indicator online';
      }
      return true;
    } else {
      if (badge) {
        badge.innerHTML = `${Icons.statusDot('offline')} Offline`;
        badge.className = 'status-indicator offline';
      }
      return false;
    }
  } catch {
    if (badge) {
      badge.innerHTML = `${Icons.statusDot('offline')} Offline`;
      badge.className = 'status-indicator offline';
    }
    return false;
  }
}

/**
 * Loads persisted configuration from chrome.storage.local into UI elements.
 */
export async function loadSettings(): Promise<void> {
  if (typeof chrome === 'undefined' || !chrome.storage?.local) {
    return;
  }

  try {
    const stored = await chrome.storage.local.get([
      'engine',
      'provider',
      'translator',
      'model',
      'selected_models',
      'filterVisionOnly',
      'sourceLang',
      'opacity',
      'overlayOpacity',
      'overlayColor',
      'speechBubbleFont',
      'overlayVisible',
      'debugGeometry',
      'prefetchEnabled',
      'prefetchDepth',
      'mascotEnabled',
    ]);


    const engineSelect = document.getElementById('engine-select') as HTMLSelectElement | null;
    if (engineSelect && stored.engine) {
      let mappedEngine = String(stored.engine);
      if (mappedEngine === 'local-manga' || mappedEngine === 'local-rapid') {
        mappedEngine = 'local';
      } else if (mappedEngine === 'cloud-gemini' || mappedEngine === 'cloud-xkiro') {
        mappedEngine = 'cloud';
      }
      engineSelect.value = mappedEngine;
    }

    const providerSelect = document.getElementById('provider-select') as HTMLSelectElement | null;
    if (providerSelect && typeof stored.provider === 'string') {
      providerSelect.value = stored.provider;
      if (!providerSelect.value) {
        providerSelect.value = normalizeProvider(stored.provider);
      }
    }

    const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement | null;
    if (translatorSelect && typeof stored.translator === 'string') {
      let transVal = stored.translator;
      if (transVal === 'llm-text' || transVal === 'llm' || transVal === 'llm-gemini') {
        transVal = 'llm-google';
      } else if (transVal === 'llm-qwen') {
        transVal = 'llm-custom';
      }
      translatorSelect.value = transVal;
      if (!translatorSelect.value) {
        translatorSelect.value = 'google-free';
      }
    }

    if (stored.selected_models && typeof stored.selected_models === 'object') {
      selectedModelsByProvider = { ...(stored.selected_models as Record<string, string>) };
    }
    if (typeof stored.model === 'string' && stored.model) {
      const activeProv = getActiveProvider();
      if (!selectedModelsByProvider[activeProv]) {
        selectedModelsByProvider[activeProv] = stored.model;
      }
    }

    const modelInput = document.getElementById('model-search-input') as HTMLInputElement | null;
    if (modelInput) {
      const activeProv = getActiveProvider();
      modelInput.value = selectedModelsByProvider[activeProv] || (typeof stored.model === 'string' ? stored.model : '');
    }

    const filterVisionToggle = document.getElementById('filter-vision-toggle') as HTMLInputElement | null;
    if (filterVisionToggle && stored.filterVisionOnly !== undefined) {
      filterVisionToggle.checked = Boolean(stored.filterVisionOnly);
    }

    updateConditionalVisibility(engineSelect?.value || 'auto');

    const sourceLangSelect = document.getElementById(
      'source-lang-select'
    ) as HTMLSelectElement | null;
    if (sourceLangSelect && stored.sourceLang) {
      sourceLangSelect.value = String(stored.sourceLang);
    }

    const visibilityToggle = document.getElementById(
      'overlay-visibility-toggle'
    ) as HTMLInputElement | null;
    if (visibilityToggle && stored.overlayVisible !== undefined) {
      visibilityToggle.checked = Boolean(stored.overlayVisible);
    }

    const opacitySlider = document.getElementById('opacity-slider') as HTMLInputElement | null;
    const opacityLabel = document.getElementById('opacity-val-label');

    let opacityVal = 88;
    if (typeof stored.overlayOpacity === 'number') {
      opacityVal = stored.overlayOpacity;
    } else if (stored.opacity === 'opaque') {
      opacityVal = 100;
    } else if (stored.opacity === 'semi-transparent') {
      opacityVal = 88;
    }

    if (opacitySlider) {
      opacitySlider.value = String(opacityVal);
    }
    if (opacityLabel) {
      opacityLabel.textContent = `${opacityVal}%`;
    }

    const colorSelect = document.getElementById('overlay-color-select') as HTMLSelectElement | null;
    const colorPicker = document.getElementById('overlay-color-picker') as HTMLInputElement | null;
    const colorVal = typeof stored.overlayColor === 'string' ? stored.overlayColor : '#ffffff';

    if (colorPicker) {
      colorPicker.value = colorVal;
    }
    if (colorSelect) {
      if (['#ffffff', '#18181b', '#f4ecd8'].includes(colorVal)) {
        colorSelect.value = colorVal;
      } else {
        colorSelect.value = 'custom';
      }
    }

    const fontSelect = document.getElementById('font-family-select') as HTMLSelectElement | null;
    if (fontSelect) {
      const fontVal = typeof stored.speechBubbleFont === 'string' ? stored.speechBubbleFont : 'itim';
      fontSelect.value = fontVal;
    }

    const debugToggle = document.getElementById(
      'debug-geometry-toggle'
    ) as HTMLInputElement | null;
    if (debugToggle && stored.debugGeometry !== undefined) {
      debugToggle.checked = Boolean(stored.debugGeometry);
    }

    const mascotEnabled = stored.mascotEnabled !== undefined ? Boolean(stored.mascotEnabled) : true;
    const mascotQuickToggle = document.getElementById('mascot-quick-toggle') as HTMLInputElement | null;
    const mascotEnabledToggle = document.getElementById('mascot-enabled-toggle') as HTMLInputElement | null;
    if (mascotQuickToggle) {
      mascotQuickToggle.checked = mascotEnabled;
    }
    if (mascotEnabledToggle) {
      mascotEnabledToggle.checked = mascotEnabled;
    }

    // Prefetch UI settings (Feature F3)
    const prefetchToggle = document.getElementById('prefetch-toggle') as HTMLInputElement | null;
    const prefetchDepthSelect = document.getElementById('prefetch-depth-select') as HTMLSelectElement | null;
    const prefetchDepthContainer = document.getElementById('prefetch-depth-container');

    const prefetchEnabled = stored.prefetchEnabled !== undefined ? Boolean(stored.prefetchEnabled) : true;
    if (prefetchToggle) {
      prefetchToggle.checked = prefetchEnabled;
    }
    if (prefetchDepthContainer) {
      prefetchDepthContainer.classList.toggle('hidden', !prefetchEnabled);
    }
    if (prefetchDepthSelect && stored.prefetchDepth) {
      prefetchDepthSelect.value = String(stored.prefetchDepth);
    }

  } catch (err) {
    logger.error('Failed to load settings from storage:', {
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

/**
 * Normalizes legacy provider strings into canonical tier identifiers.
 */
export function normalizeProvider(prov?: string): string {
  if (!prov) return 'google';
  if (prov === 'gemini') return 'google';
  if (prov === 'xkiro') return 'custom';
  if (['google', 'openai', 'anthropic', 'custom'].includes(prov)) {
    return prov;
  }
  return 'google';
}

/**
 * Determines the currently active LLM provider based on engine mode and selected settings.
 */
export function getActiveProvider(): string {
  const engineSelect = document.getElementById('engine-select') as HTMLSelectElement | null;
  const engine = engineSelect?.value || 'auto';

  if (engine === 'cloud') {
    const providerSelect = document.getElementById('provider-select') as HTMLSelectElement | null;
    return normalizeProvider(providerSelect?.value);
  }

  if (engine === 'local') {
    const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement | null;
    const trans = translatorSelect?.value;
    if (trans === 'llm-google' || trans === 'llm-gemini') return 'google';
    if (trans === 'llm-openai') return 'openai';
    if (trans === 'llm-anthropic') return 'anthropic';
    if (trans === 'llm-custom' || trans === 'llm-qwen') return 'custom';
    return 'google';
  }

  return 'google';
}

/**
 * Toggles visibility of engine-specific conditional dropdown containers.
 */
export function updateConditionalVisibility(engine: string): void {
  const providerContainer = document.getElementById('provider-container');
  const translatorContainer = document.getElementById('translator-container');
  const sourceLangContainer = document.getElementById('source-lang-container');
  const modelContainer = document.getElementById('model-container');
  const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement | null;

  if (providerContainer) {
    if (engine === 'cloud') {
      providerContainer.classList.remove('hidden');
    } else {
      providerContainer.classList.add('hidden');
    }
  }

  if (translatorContainer) {
    if (engine === 'local') {
      translatorContainer.classList.remove('hidden');
    } else {
      translatorContainer.classList.add('hidden');
    }
  }

  if (sourceLangContainer) {
    if (engine === 'cloud') {
      sourceLangContainer.classList.add('hidden');
    } else {
      sourceLangContainer.classList.remove('hidden');
    }
  }

  if (modelContainer) {
    if (engine === 'cloud') {
      modelContainer.classList.remove('hidden');
    } else if (engine === 'local') {
      const trans = translatorSelect?.value || 'google-free';
      const isLLM = trans.startsWith('llm-') || trans === 'llm-text';
      if (isLLM) {
        modelContainer.classList.remove('hidden');
      } else {
        modelContainer.classList.add('hidden');
      }
    } else {
      modelContainer.classList.add('hidden');
    }
  }
}

/**
 * Renders the floating dropdown options for the Searchable Combobox.
 */
export function renderComboboxDropdown(query: string = ''): void {
  const dropdown = document.getElementById('model-dropdown-list');
  const inputEl = document.getElementById('model-search-input') as HTMLInputElement | null;
  const filterVisionToggle = document.getElementById('filter-vision-toggle') as HTMLInputElement | null;
  if (!dropdown) return;

  const provider = getActiveProvider();
  const allModels = currentProviderModels[provider] || [];
  const shouldFilterVision = filterVisionToggle ? filterVisionToggle.checked : false;

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

  dropdown.innerHTML = '';
  activeComboboxIndex = -1;

  if (filtered.length === 0) {
    const emptyEl = document.createElement('div');
    emptyEl.className = 'combobox-empty';
    if (allModels.length === 0) {
      emptyEl.textContent = 'Chưa có model. Nhấn ↻ để tải từ API.';
    } else {
      emptyEl.textContent = 'Không tìm thấy model phù hợp.';
    }
    dropdown.appendChild(emptyEl);
  } else {
    const currentVal = inputEl?.value.trim() || selectedModelsByProvider[provider] || '';
    filtered.forEach((m, idx) => {
      const itemEl = document.createElement('div');
      itemEl.className = 'combobox-item';
      itemEl.setAttribute('role', 'option');
      itemEl.setAttribute('data-id', m.id);
      itemEl.setAttribute('data-index', String(idx));
      if (m.id === currentVal) {
        itemEl.classList.add('selected');
      }

      const nameEl = document.createElement('span');
      nameEl.className = 'combobox-item-name';
      nameEl.textContent = m.display_name || m.id;
      itemEl.appendChild(nameEl);

      if (m.supports_vision) {
        const badgeEl = document.createElement('span');
        badgeEl.className = 'combobox-item-badge vision';
        badgeEl.textContent = 'Vision';
        itemEl.appendChild(badgeEl);
      }

      itemEl.addEventListener('click', () => {
        selectModel(m.id);
      });

      dropdown.appendChild(itemEl);
    });
  }

  dropdown.classList.remove('hidden');
  isComboboxOpen = true;
}

/**
 * Highlights a specific item in the combobox dropdown for keyboard navigation.
 */
export function highlightComboboxItem(items: HTMLElement[], index: number): void {
  items.forEach((item, idx) => {
    if (idx === index) {
      item.classList.add('active');
      if (typeof item.scrollIntoView === 'function') {
        item.scrollIntoView({ block: 'nearest' });
      }
    } else {
      item.classList.remove('active');
    }
  });
}

/**
 * Applies a model value directly from text input or selection without requiring Enter or click.
 */
export function applyModelValue(rawVal: string): void {
  const modelId = rawVal.trim();
  const provider = getActiveProvider();
  selectedModelsByProvider[provider] = modelId;
  saveSetting('selected_models', selectedModelsByProvider).catch(() => {});
  saveSetting('model', modelId).catch(() => {});
}

/**
 * Selects a model, updates input, closes dropdown, and persists choice in chrome.storage.local.
 */
export function selectModel(modelId: string): void {
  const inputEl = document.getElementById('model-search-input') as HTMLInputElement | null;
  const dropdown = document.getElementById('model-dropdown-list');
  if (inputEl) {
    inputEl.value = modelId;
  }
  if (dropdown) {
    dropdown.classList.add('hidden');
  }
  isComboboxOpen = false;
  activeComboboxIndex = -1;

  applyModelValue(modelId);
}

/**
 * Fetches dynamic models for a provider via backend discovery proxy.
 */
export async function fetchModelsForProvider(
  provider: string,
  force: boolean = false
): Promise<void> {
  const normProvider = normalizeProvider(provider);
  if (!force && currentProviderModels[normProvider] && currentProviderModels[normProvider].length > 0) {
    const inputEl = document.getElementById('model-search-input') as HTMLInputElement | null;
    renderComboboxDropdown(inputEl?.value || '');
    return;
  }

  const spinner = document.getElementById('model-loading-indicator');
  const statusHelp = document.getElementById('model-status-help');
  if (spinner) spinner.classList.remove('hidden');
  if (statusHelp) {
    statusHelp.textContent = '';
    statusHelp.className = 'status-help-text';
  }

  try {
    const message: IPCMessage = {
      type: 'FETCH_PROVIDER_MODELS',
      payload: { provider: normProvider },
    };
    const response = (await chrome.runtime.sendMessage(message)) as IPCResponse<DiscoveredModelsData>;

    if (response && response.success === true && response.data?.models) {
      currentProviderModels[normProvider] = response.data.models;
      const inputEl = document.getElementById('model-search-input') as HTMLInputElement | null;
      renderComboboxDropdown(inputEl?.value || '');

      // If no model currently selected for this provider and input is empty, pick default
      const currentInputVal = (document.getElementById('model-search-input') as HTMLInputElement | null)?.value.trim() || '';
      if (!selectedModelsByProvider[normProvider] && !currentInputVal) {
        const filterVisionToggle = document.getElementById('filter-vision-toggle') as HTMLInputElement | null;
        const candidate = (filterVisionToggle && filterVisionToggle.checked)
          ? (response.data.models.find((m) => m.supports_vision) || response.data.models[0])
          : response.data.models[0];
        if (candidate) {
          selectModel(candidate.id);
        }
      } else if (currentInputVal && !selectedModelsByProvider[normProvider]) {
        applyModelValue(currentInputVal);
      }
    } else {
      const err = response && !response.success ? response.error : undefined;
      const code = err?.code || 'UNKNOWN';
      const msg = err?.message || 'Không thể tải danh sách model';
      if (statusHelp) {
        if (code === 'MISSING_API_KEY' || code === 'INVALID_API_KEY' || code.includes('401')) {
          statusHelp.textContent = '⚠️ Chưa cấu hình API Key. Vui lòng mở drawer bên trên để nhập key!';
        } else if (code.includes('429')) {
          statusHelp.textContent = '⚠️ Hạn mức API đã vượt quá (Quota Exceeded / Rate Limit).';
        } else {
          statusHelp.textContent = `⚠️ Lỗi lấy model: ${msg}`;
        }
        statusHelp.className = 'status-help-text error';
      }
    }
  } catch (err: unknown) {
    if (statusHelp) {
      statusHelp.textContent = `⚠️ Lỗi kết nối: ${err instanceof Error ? err.message : String(err)}`;
      statusHelp.className = 'status-help-text error';
    }
  } finally {
    if (spinner) spinner.classList.add('hidden');
  }
}

/**
 * Loads current provider configuration status (masked keys and base URLs) into drawer UI.
 */
export async function loadProviderSettings(): Promise<void> {
  try {
    const message: IPCMessage = { type: 'GET_PROVIDER_SETTINGS' };
    const response = (await chrome.runtime.sendMessage(message)) as IPCResponse<ProviderSettingsData>;

    if (response && response.success === true && response.data?.providers) {
      const providers = response.data.providers;
      for (const p of ['google', 'openai', 'anthropic', 'custom']) {
        const status = providers[p];
        const statusBadge = document.getElementById(`${p}-key-status`);
        if (statusBadge) {
          if (status?.configured) {
            statusBadge.textContent = `Đã cấu hình (${status.masked_key || '***'})`;
            statusBadge.className = 'count-pill status-pill configured';
          } else {
            statusBadge.textContent = 'Chưa cấu hình';
            statusBadge.className = 'count-pill status-pill not-configured';
          }
        }
        if (p === 'custom' && status?.base_url) {
          const endpointInput = document.getElementById('custom-endpoint-input') as HTMLInputElement | null;
          if (endpointInput && !endpointInput.value) {
            endpointInput.value = status.base_url;
          }
        }
      }
    }
  } catch (err) {
    logger.warn('Failed to load provider settings:', {
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

/**
 * Persists an API key or base URL to the backend host .env atomically.
 */
export async function saveProviderCredential(
  provider: string,
  apiKey?: string,
  baseUrl?: string
): Promise<boolean> {
  const feedbackEl = document.getElementById('drawer-save-feedback');
  if (feedbackEl) {
    feedbackEl.textContent = 'Đang lưu cấu hình...';
    feedbackEl.className = 'status-help-text';
  }

  try {
    const message: IPCMessage = {
      type: 'SAVE_PROVIDER_SETTINGS',
      payload: {
        provider,
        apiKey: apiKey || undefined,
        baseUrl: baseUrl || undefined,
      },
    };
    const response = (await chrome.runtime.sendMessage(message)) as IPCResponse<SaveProviderSettingsData>;

    if (response && response.success === true) {
      if (feedbackEl) {
        feedbackEl.textContent = `✅ Đã lưu cấu hình cho ${provider} thành công!`;
        feedbackEl.className = 'status-help-text success';
      }
      // Reload drawer status
      await loadProviderSettings();
      // Invalidate cached models for this provider
      delete currentProviderModels[provider];
      // If current provider is this one, refresh models live
      if (getActiveProvider() === provider) {
        await fetchModelsForProvider(provider, true);
      }
      return true;
    } else {
      const err = response && !response.success ? response.error : undefined;
      if (feedbackEl) {
        feedbackEl.textContent = `⚠️ Lỗi lưu cấu hình: ${err?.message || 'Thất bại'}`;
        feedbackEl.className = 'status-help-text error';
      }
      return false;
    }
  } catch (err) {
    if (feedbackEl) {
      feedbackEl.textContent = `⚠️ Lỗi: ${err instanceof Error ? err.message : String(err)}`;
      feedbackEl.className = 'status-help-text error';
    }
    return false;
  }
}

/**
 * Persists an updated setting key-value pair into chrome.storage.local.
 */
export async function saveSetting(key: string, value: unknown): Promise<void> {
  if (typeof chrome === 'undefined' || !chrome.storage?.local) {
    return;
  }

  await chrome.storage.local.set({ [key]: value });
}

/**
 * Loads domain filter settings and active tab detection context into popup UI.
 */
export async function loadDomainSettings(): Promise<void> {
  currentDomainSettings = await loadDomainFilterSettings();

  const domainNameEl = document.getElementById('active-domain-name');
  const domainBadgeEl = document.getElementById('active-domain-badge');
  const domainDetailEl = document.getElementById('active-domain-detail');
  const domainModeSelect = document.getElementById('domain-mode-select') as HTMLSelectElement | null;

  renderDomainTags();

  if (typeof chrome === 'undefined' || !chrome.tabs?.query) {
    if (domainNameEl) domainNameEl.textContent = 'Chrome Tabs không khả dụng';
    return;
  }

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs.length || tabs[0].id === undefined) {
      if (domainNameEl) domainNameEl.textContent = 'Không tìm thấy tab';
      return;
    }

    const activeTab = tabs[0];
    activeTabId = activeTab.id ?? null;
    const url = activeTab.url || '';

    if (
      !url ||
      url.startsWith('chrome://') ||
      url.startsWith('chrome-extension://') ||
      url.startsWith('edge://') ||
      url.startsWith('about:')
    ) {
      if (domainNameEl) domainNameEl.textContent = 'Trang hệ thống';
      if (domainBadgeEl) {
        domainBadgeEl.textContent = 'Hệ thống';
        domainBadgeEl.className = 'domain-status-badge status-normal';
      }
      if (domainDetailEl) {
        domainDetailEl.textContent = 'Extension không quét các trang nội bộ của trình duyệt.';
      }
      if (domainModeSelect) {
        domainModeSelect.disabled = true;
      }
      return;
    }

    activeTabHostname = normalizeHostname(url);
    if (domainNameEl) domainNameEl.textContent = activeTabHostname;
    if (domainModeSelect) domainModeSelect.disabled = false;

    // Check domain mode in settings
    let domainMode: 'auto' | 'whitelist' | 'blacklist' = 'auto';
    if (currentDomainSettings.whitelist.some((w) => matchesDomain(activeTabHostname, w))) {
      domainMode = 'whitelist';
    } else if (currentDomainSettings.blacklist.some((b) => matchesDomain(activeTabHostname, b))) {
      domainMode = 'blacklist';
    }
    if (domainModeSelect) domainModeSelect.value = domainMode;

    // Request active page detection status
    try {
      const message: IPCMessage = { type: 'GET_PAGE_READER_STATUS' };
      const res = (await chrome.tabs.sendMessage(activeTab.id!, message, { frameId: 0 })) as
        | { success: boolean; data?: PageReaderStatusData }
        | undefined;

      if (
        res &&
        res.success &&
        res.data &&
        (!res.data.hostname || matchesDomain(activeTabHostname, res.data.hostname))
      ) {
        const data = res.data;
        if (data.domainStatus === 'blacklisted') {
          if (domainBadgeEl) {
            domainBadgeEl.textContent = 'Bị chặn';
            domainBadgeEl.className = 'domain-status-badge status-blacklisted';
          }
          if (domainDetailEl) {
            domainDetailEl.textContent =
              'Domain này nằm trong Blacklist. Tiện ích sẽ không quét hay dịch.';
          }
        } else if (data.domainStatus === 'whitelisted') {
          if (domainBadgeEl) {
            domainBadgeEl.textContent = 'Buộc dịch';
            domainBadgeEl.className = 'domain-status-badge status-whitelisted';
          }
          if (domainDetailEl) {
            domainDetailEl.textContent = 'Đã buộc dịch trên domain này (Whitelist).';
          }
        } else if (data.isReaderPage) {
          if (domainBadgeEl) {
            domainBadgeEl.textContent = 'Trang đọc truyện';
            domainBadgeEl.className = 'domain-status-badge status-reader';
          }
          const meta = data.chapterMeta;
          const series = meta?.seriesSlug ? meta.seriesSlug : '';
          const chap = meta?.chapterNumber ? `Ch. ${meta.chapterNumber}` : '';
          const info = [series, chap].filter(Boolean).join(' - ');
          const pct = Math.round((data.confidence ?? 1) * 100);
          if (domainDetailEl) {
            domainDetailEl.textContent = `Đã nhận diện: ${info || 'Manga Reader'} (${pct}%)`;
          }
        } else {
          if (domainBadgeEl) {
            domainBadgeEl.textContent = 'Web thường';
            domainBadgeEl.className = 'domain-status-badge status-normal';
          }
          if (domainDetailEl) {
            domainDetailEl.textContent =
              'Không phát hiện trang đọc truyện. Tiện ích ở chế độ chờ.';
          }
        }
        return;
      }
    } catch {
      // Content script may not be loaded yet or tab unscriptable
    }

    // Fallback UI status based on domain filter alone
    if (domainMode === 'blacklist') {
      if (domainBadgeEl) {
        domainBadgeEl.textContent = 'Bị chặn';
        domainBadgeEl.className = 'domain-status-badge status-blacklisted';
      }
      if (domainDetailEl) {
        domainDetailEl.textContent = 'Domain nằm trong Blacklist.';
      }
    } else if (domainMode === 'whitelist') {
      if (domainBadgeEl) {
        domainBadgeEl.textContent = 'Buộc dịch';
        domainBadgeEl.className = 'domain-status-badge status-whitelisted';
      }
      if (domainDetailEl) {
        domainDetailEl.textContent = 'Domain nằm trong Whitelist.';
      }
    } else {
      if (domainBadgeEl) {
        domainBadgeEl.textContent = 'Tự động';
        domainBadgeEl.className = 'domain-status-badge status-normal';
      }
      if (domainDetailEl) {
        domainDetailEl.textContent = 'Chế độ tự động phát hiện trang đọc.';
      }
    }
  } catch (err) {
    logger.error('Failed to load domain settings:', {
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

/**
 * Renders domain tags into the management drawer and wires deletion handlers.
 */
export function renderDomainTags(): void {
  if (!currentDomainSettings) return;

  const whitelistContainer = document.getElementById('whitelist-tags');
  const blacklistContainer = document.getElementById('blacklist-tags');
  const whitelistCount = document.getElementById('whitelist-count');
  const blacklistCount = document.getElementById('blacklist-count');

  if (whitelistCount) whitelistCount.textContent = String(currentDomainSettings.whitelist.length);
  if (blacklistCount) blacklistCount.textContent = String(currentDomainSettings.blacklist.length);

  if (whitelistContainer) {
    whitelistContainer.innerHTML = '';
    currentDomainSettings.whitelist.forEach((d) => {
      const tag = document.createElement('span');
      tag.className = 'domain-tag';
      tag.innerHTML = `<span>${d}</span><button type="button" class="domain-tag-remove" data-domain="${d}" data-target="whitelist" title="Xóa domain">×</button>`;
      whitelistContainer.appendChild(tag);
    });
  }

  if (blacklistContainer) {
    blacklistContainer.innerHTML = '';
    currentDomainSettings.blacklist.forEach((d) => {
      const tag = document.createElement('span');
      tag.className = 'domain-tag';
      tag.innerHTML = `<span>${d}</span><button type="button" class="domain-tag-remove" data-domain="${d}" data-target="blacklist" title="Xóa domain">×</button>`;
      blacklistContainer.appendChild(tag);
    });
  }

  const removeButtons = document.querySelectorAll('.domain-tag-remove');
  removeButtons.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const domain = btn.getAttribute('data-domain');
      const target = btn.getAttribute('data-target') as 'whitelist' | 'blacklist';
      if (domain && target) {
        removeDomain(domain, target).catch(() => {});
      }
    });
  });
}

/**
 * Updates the domain mode for the current active tab and persists changes.
 */
export async function setDomainMode(mode: 'auto' | 'whitelist' | 'blacklist'): Promise<void> {
  if (!currentDomainSettings || !activeTabHostname) return;

  const norm = activeTabHostname;
  if (mode === 'whitelist') {
    currentDomainSettings.blacklist = currentDomainSettings.blacklist.filter((d) => d !== norm);
    if (!currentDomainSettings.whitelist.includes(norm)) {
      currentDomainSettings.whitelist.push(norm);
    }
  } else if (mode === 'blacklist') {
    currentDomainSettings.whitelist = currentDomainSettings.whitelist.filter((d) => d !== norm);
    if (!currentDomainSettings.blacklist.includes(norm)) {
      currentDomainSettings.blacklist.push(norm);
    }
  } else {
    // auto: remove from both custom lists
    currentDomainSettings.whitelist = currentDomainSettings.whitelist.filter((d) => d !== norm);
    currentDomainSettings.blacklist = currentDomainSettings.blacklist.filter((d) => d !== norm);
  }

  await saveDomainFilterSettings(currentDomainSettings);
  renderDomainTags();

  const domainBadgeEl = document.getElementById('active-domain-badge');
  const domainDetailEl = document.getElementById('active-domain-detail');
  if (mode === 'whitelist') {
    if (domainBadgeEl) {
      domainBadgeEl.textContent = 'Buộc dịch';
      domainBadgeEl.className = 'domain-status-badge status-whitelisted';
    }
    if (domainDetailEl) {
      domainDetailEl.textContent = 'Đã buộc dịch trên domain này (Whitelist).';
    }
    await triggerRescan();
  } else if (mode === 'blacklist') {
    if (domainBadgeEl) {
      domainBadgeEl.textContent = 'Bị chặn';
      domainBadgeEl.className = 'domain-status-badge status-blacklisted';
    }
    if (domainDetailEl) {
      domainDetailEl.textContent =
        'Domain này nằm trong Blacklist. Tiện ích sẽ không quét hay dịch.';
    }
  } else {
    if (domainBadgeEl) {
      domainBadgeEl.textContent = 'Tự động';
      domainBadgeEl.className = 'domain-status-badge status-normal';
    }
    if (domainDetailEl) {
      domainDetailEl.textContent = 'Chế độ tự động phát hiện trang đọc.';
    }
  }
}

/**
 * Adds a custom domain to whitelist or blacklist.
 */
export async function addCustomDomain(
  domain: string,
  target: 'whitelist' | 'blacklist'
): Promise<void> {
  if (!currentDomainSettings) {
    currentDomainSettings = await loadDomainFilterSettings();
  }
  const norm = normalizeHostname(domain);
  if (!norm) return;

  if (target === 'whitelist') {
    currentDomainSettings.blacklist = currentDomainSettings.blacklist.filter((d) => d !== norm);
    if (!currentDomainSettings.whitelist.includes(norm)) {
      currentDomainSettings.whitelist.push(norm);
    }
  } else {
    currentDomainSettings.whitelist = currentDomainSettings.whitelist.filter((d) => d !== norm);
    if (!currentDomainSettings.blacklist.includes(norm)) {
      currentDomainSettings.blacklist.push(norm);
    }
  }

  await saveDomainFilterSettings(currentDomainSettings);
  renderDomainTags();

  if (activeTabHostname && matchesDomain(activeTabHostname, norm)) {
    const domainModeSelect = document.getElementById('domain-mode-select') as HTMLSelectElement | null;
    if (domainModeSelect) domainModeSelect.value = target;
    const domainBadgeEl = document.getElementById('active-domain-badge');
    if (domainBadgeEl) {
      domainBadgeEl.textContent = target === 'whitelist' ? 'Buộc dịch' : 'Bị chặn';
      domainBadgeEl.className = `domain-status-badge ${
        target === 'whitelist' ? 'status-whitelisted' : 'status-blacklisted'
      }`;
    }
  }
}

/**
 * Removes a domain from whitelist or blacklist.
 */
export async function removeDomain(
  domain: string,
  target: 'whitelist' | 'blacklist'
): Promise<void> {
  if (!currentDomainSettings) return;
  const norm = normalizeHostname(domain);
  if (target === 'whitelist') {
    currentDomainSettings.whitelist = currentDomainSettings.whitelist.filter((d) => d !== norm);
  } else {
    currentDomainSettings.blacklist = currentDomainSettings.blacklist.filter((d) => d !== norm);
  }
  await saveDomainFilterSettings(currentDomainSettings);
  renderDomainTags();
}

/**
 * Restores domain filter settings to factory default.
 */
export async function restoreDefaultDomains(): Promise<void> {
  currentDomainSettings = await resetToDefaultFilterSettings();
  renderDomainTags();
  if (activeTabHostname) {
    const domainModeSelect = document.getElementById('domain-mode-select') as HTMLSelectElement | null;
    if (domainModeSelect) {
      const isBl = currentDomainSettings.blacklist.some((b) => matchesDomain(activeTabHostname, b));
      domainModeSelect.value = isBl ? 'blacklist' : 'auto';
    }
  }
}

/**
 * Sends a RESCAN_PAGE message to the active reading tab.
 */
export async function triggerRescan(): Promise<void> {
  const statusEl = document.getElementById('rescan-status');
  const rescanBtn = document.getElementById('rescan-btn') as HTMLButtonElement | null;

  if (typeof chrome === 'undefined' || !chrome.tabs?.query) {
    if (statusEl) {
      statusEl.textContent = 'Chrome tabs API không khả dụng';
      statusEl.className = 'status-help-text error';
    }
    return;
  }

  if (rescanBtn) {
    rescanBtn.disabled = true;
    rescanBtn.textContent = 'Đang quét...';
  }
  if (statusEl) {
    statusEl.textContent = 'Đang tìm ảnh manga trên trang...';
    statusEl.className = 'status-help-text';
  }

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs.length || tabs[0].id === undefined) {
      if (statusEl) {
        statusEl.textContent = 'Không tìm thấy tab hoạt động';
        statusEl.className = 'status-help-text error';
      }
      return;
    }

    const activeTab = tabs[0];
    const tabId = activeTab.id;
    if (tabId === undefined) {
      return;
    }
    const url = activeTab.url || '';

    if (
      url.startsWith('chrome://') ||
      url.startsWith('chrome-extension://') ||
      url.startsWith('edge://') ||
      url.startsWith('about:')
    ) {
      if (statusEl) {
        statusEl.textContent = '⚠️ Không thể quét trên trang hệ thống. Vui lòng mở trang đọc truyện web!';
        statusEl.className = 'status-help-text warning';
      }
      return;
    }

    const message: IPCMessage = { type: 'RESCAN_PAGE' };
    const response = (await chrome.tabs.sendMessage(tabId, message, { frameId: 0 })) as {
      success?: boolean;
      count?: number;
    } | undefined;

    if (statusEl) {
      const count = response && typeof response.count === 'number' ? response.count : 0;
      if (count > 0) {
        statusEl.textContent = `✅ Đã quét! Tìm thấy ${count} ảnh manga và đang dịch.`;
        statusEl.className = 'status-help-text success';
      } else {
        statusEl.textContent = '🔍 Đã quét nhưng không tìm thấy ảnh manga (cần kích thước >= 300px).';
        statusEl.className = 'status-help-text warning';
      }
    }
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    logger.warn(`Could not dispatch re-scan to active tab: ${errMsg}`);
    if (statusEl) {
      if (
        errMsg.includes('Could not establish connection') ||
        errMsg.includes('Receiving end does not exist')
      ) {
        statusEl.textContent =
          '⚠️ Hãy F5 (Tải lại) trang truyện 1 lần rồi quét lại! (Chrome không tự nhận extension trên tab đã mở sẵn)';
        statusEl.className = 'status-help-text warning';
      } else {
        statusEl.textContent = `⚠️ Lỗi quét trang: ${errMsg}`;
        statusEl.className = 'status-help-text error';
      }
    }
  } finally {
    if (rescanBtn) {
      rescanBtn.disabled = false;
      rescanBtn.textContent = 'Re-scan Current Page';
    }
  }
}

/**
 * Clears in-memory RAM caches and tears down DOM overlays on the active browser tab without affecting SQLite.
 */
export async function triggerClearBrowserCache(): Promise<void> {
  const btn = document.getElementById('clear-browser-cache-btn') as HTMLButtonElement | null;
  const feedbackEl = document.getElementById('clear-browser-cache-feedback');

  if (typeof chrome === 'undefined' || !chrome.tabs?.query) {
    if (feedbackEl) {
      feedbackEl.style.display = 'block';
      feedbackEl.textContent = 'Chrome tabs API không khả dụng';
      feedbackEl.className = 'status-help-text error';
    }
    return;
  }

  if (btn) {
    btn.disabled = true;
  }
  if (feedbackEl) {
    feedbackEl.style.display = 'block';
    feedbackEl.textContent = 'Đang làm mới bộ nhớ tạm trình duyệt...';
    feedbackEl.className = 'status-help-text';
  }

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs.length || tabs[0].id === undefined) {
      if (feedbackEl) {
        feedbackEl.textContent = 'Không tìm thấy tab hoạt động';
        feedbackEl.className = 'status-help-text error';
      }
      return;
    }

    const activeTab = tabs[0];
    const tabId = activeTab.id;
    if (tabId === undefined) {
      return;
    }
    const url = activeTab.url || '';

    if (
      url.startsWith('chrome://') ||
      url.startsWith('chrome-extension://') ||
      url.startsWith('edge://') ||
      url.startsWith('about:')
    ) {
      if (feedbackEl) {
        feedbackEl.textContent = '⚠️ Tab hiện tại không phải trang đọc truyện manga.';
        feedbackEl.className = 'status-help-text warning';
      }
      return;
    }

    const message: IPCMessage = { type: 'RESCAN_PAGE' };
    const response = (await chrome.tabs.sendMessage(tabId, message, { frameId: 0 })) as {
      success?: boolean;
      count?: number;
    } | undefined;

    const count = response && typeof response.count === 'number' ? response.count : 0;
    if (feedbackEl) {
      if (count > 0) {
        feedbackEl.textContent = `✅ Đã xóa bộ nhớ tạm RAM & làm mới ${count} ảnh trên trang!`;
        feedbackEl.className = 'status-help-text success';
      } else {
        feedbackEl.textContent = '✅ Đã xóa bộ nhớ tạm RAM và gỡ bỏ overlay trên tab.';
        feedbackEl.className = 'status-help-text success';
      }
    }
    logger.info(`Successfully cleared in-memory browser cache on tab ${tabId}`);
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    logger.warn(`Could not clear browser cache on active tab: ${errMsg}`);
    if (feedbackEl) {
      if (
        errMsg.includes('Could not establish connection') ||
        errMsg.includes('Receiving end does not exist')
      ) {
        feedbackEl.textContent = '⚠️ Hãy F5 trang truyện để nạp lại script content trước khi xóa bộ nhớ tạm.';
        feedbackEl.className = 'status-help-text warning';
      } else {
        feedbackEl.textContent = `❌ Lỗi xóa bộ nhớ tạm: ${errMsg}`;
        feedbackEl.className = 'status-help-text error';
      }
    }
  } finally {
    if (btn) {
      btn.disabled = false;
    }
  }
}

/**
 * Dispatches CLEAR_CACHE message to Service Worker to wipe SQLite database cache and provides user feedback.
 */
export async function triggerClearDatabaseCache(): Promise<void> {
  const clearBtn =
    (document.getElementById('clear-db-cache-btn') as HTMLButtonElement | null) ||
    (document.getElementById('clear-cache-btn') as HTMLButtonElement | null);
  const feedbackEl =
    document.getElementById('clear-db-cache-feedback') ||
    document.getElementById('clear-cache-feedback');

  if (typeof window !== 'undefined' && typeof window.confirm === 'function') {
    const confirmed = window.confirm(
      'Bạn có chắc chắn muốn xóa TOÀN BỘ bản dịch trong CSDL SQLite không? Mọi trang truyện trên tất cả website sẽ phải dịch lại từ đầu.'
    );
    if (!confirmed) {
      return;
    }
  }

  if (clearBtn) {
    clearBtn.disabled = true;
  }
  if (feedbackEl) {
    feedbackEl.style.display = 'block';
    feedbackEl.textContent = 'Đang dọn dẹp bộ nhớ đệm SQLite...';
    feedbackEl.className = 'status-help-text';
  }

  try {
    const message: IPCMessage = {
      type: 'CLEAR_CACHE',
      payload: { all: true },
    };
    const response = (await chrome.runtime.sendMessage(message)) as IPCResponse<ClearCacheResponseData>;

    if (response && response.success === true) {
      const count = response.data.deleted;
      if (feedbackEl) {
        feedbackEl.textContent = `✅ Đã xóa ${count} bản ghi bộ nhớ đệm!`;
        feedbackEl.className = 'status-help-text success';
      }
      logger.info(`Successfully cleared SQLite cache (${count} records) via popup.`);

      // Proactively trigger rescan on active reader tab if available
      try {
        await triggerRescan();
      } catch {
        // Rescan is secondary
      }
    } else {
      const err = response && !response.success ? response.error.message : 'Lỗi không xác định';
      if (feedbackEl) {
        feedbackEl.textContent = `❌ Xóa cache thất bại: ${err}`;
        feedbackEl.className = 'status-help-text error';
      }
    }
  } catch (err: unknown) {
    if (feedbackEl) {
      feedbackEl.textContent = `❌ Lỗi kết nối: ${err instanceof Error ? err.message : String(err)}`;
      feedbackEl.className = 'status-help-text error';
    }
  } finally {
    if (clearBtn) {
      clearBtn.disabled = false;
    }
  }
}

/**
 * Backwards compatibility alias for triggerClearDatabaseCache.
 */
export const triggerClearCache = triggerClearDatabaseCache;

/**
 * Initializes popup UI controls, attaches event listeners, and runs initial health check.
 */
export async function initPopup(): Promise<void> {
  await Promise.all([checkBackendHealth(), loadSettings(), loadDomainSettings()]);

  // Bind View navigation (Main View <-> Settings View)
  const appContainer = document.getElementById('app');
  const btnOpenSettings = document.getElementById('btn-open-settings');
  const btnCloseSettings = document.getElementById('btn-close-settings');

  if (btnOpenSettings && appContainer) {
    btnOpenSettings.addEventListener('click', () => {
      appContainer.classList.add('view-settings-active');
    });
  }

  if (btnCloseSettings && appContainer) {
    btnCloseSettings.addEventListener('click', () => {
      appContainer.classList.remove('view-settings-active');
    });
  }

  // Bind refresh health button
  const refreshBtn = document.getElementById('refresh-health-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      checkBackendHealth().catch(() => {});
    });
  }

  // Handle Embedded Mode in Mascot HUD Iframe
  if (typeof window !== 'undefined' && window.location) {
    const urlParams = new URLSearchParams(window.location.search);
    const isEmbedded = urlParams.get('embedded') === '1';
    const closeBtn = document.getElementById('btn-close-popup');
    if (closeBtn && isEmbedded) {
      closeBtn.classList.remove('hidden');
      closeBtn.addEventListener('click', () => {
        window.parent.postMessage({ type: 'INKSHIFT_CLOSE_HUD' }, '*');
      });
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && isEmbedded) {
        window.parent.postMessage({ type: 'INKSHIFT_CLOSE_HUD' }, '*');
      }
    });

    const hostnameParam = urlParams.get('hostname');
    if (hostnameParam && (!activeTabHostname || activeTabHostname === 'Chrome Tabs không khả dụng')) {
      activeTabHostname = normalizeHostname(hostnameParam);
      const domainNameEl = document.getElementById('active-domain-name');
      if (domainNameEl) domainNameEl.textContent = activeTabHostname;
    }
  }

  // Bind engine selector
  const engineSelect = document.getElementById('engine-select') as HTMLSelectElement | null;
  if (engineSelect) {
    engineSelect.addEventListener('change', () => {
      updateConditionalVisibility(engineSelect.value);
      saveSetting('engine', engineSelect.value).catch(() => {});
      if (engineSelect.value === 'cloud' || engineSelect.value === 'local') {
        fetchModelsForProvider(getActiveProvider()).catch(() => {});
      }
    });
  }

  // Bind cloud provider selector
  const providerSelect = document.getElementById('provider-select') as HTMLSelectElement | null;
  if (providerSelect) {
    providerSelect.addEventListener('change', () => {
      saveSetting('provider', providerSelect.value).catch(() => {});
      const prov = normalizeProvider(providerSelect.value);
      const modelInput = document.getElementById('model-search-input') as HTMLInputElement | null;
      const modelForProv = selectedModelsByProvider[prov] || '';
      if (modelInput) {
        modelInput.value = modelForProv;
      }
      saveSetting('model', modelForProv).catch(() => {});
      fetchModelsForProvider(prov).catch(() => {});
    });
  }

  // Bind local translator selector
  const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement | null;
  if (translatorSelect) {
    translatorSelect.addEventListener('change', () => {
      saveSetting('translator', translatorSelect.value).catch(() => {});
      updateConditionalVisibility(engineSelect?.value || 'auto');
      if (translatorSelect.value.startsWith('llm-')) {
        const prov = getActiveProvider();
        const modelInput = document.getElementById('model-search-input') as HTMLInputElement | null;
        const modelForProv = selectedModelsByProvider[prov] || '';
        if (modelInput) {
          modelInput.value = modelForProv;
        }
        saveSetting('model', modelForProv).catch(() => {});
        fetchModelsForProvider(prov).catch(() => {});
      }
    });
  }

  // Bind Searchable Combobox controls
  const modelSearchInput = document.getElementById('model-search-input') as HTMLInputElement | null;
  const refreshModelsBtn = document.getElementById('refresh-models-btn');
  const filterVisionToggle = document.getElementById('filter-vision-toggle') as HTMLInputElement | null;

  if (filterVisionToggle) {
    filterVisionToggle.addEventListener('change', () => {
      saveSetting('filterVisionOnly', filterVisionToggle.checked).catch(() => {});
      renderComboboxDropdown(modelSearchInput?.value || '');
    });
  }

  if (modelSearchInput) {
    modelSearchInput.addEventListener('focus', () => {
      fetchModelsForProvider(getActiveProvider()).catch(() => {});
    });
    modelSearchInput.addEventListener('click', () => {
      fetchModelsForProvider(getActiveProvider()).catch(() => {});
    });
    modelSearchInput.addEventListener('input', () => {
      applyModelValue(modelSearchInput.value);
      renderComboboxDropdown(modelSearchInput.value);
    });
    modelSearchInput.addEventListener('change', () => {
      applyModelValue(modelSearchInput.value);
    });
    modelSearchInput.addEventListener('blur', () => {
      applyModelValue(modelSearchInput.value);
    });
    modelSearchInput.addEventListener('keydown', (e: KeyboardEvent) => {
      const dropdown = document.getElementById('model-dropdown-list');
      if (!dropdown || dropdown.classList.contains('hidden')) {
        if (e.key === 'ArrowDown' || e.key === 'Enter') {
          e.preventDefault();
          renderComboboxDropdown(modelSearchInput.value);
        }
        return;
      }
      const items = Array.from(dropdown.querySelectorAll<HTMLElement>('.combobox-item'));
      if (items.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeComboboxIndex = (activeComboboxIndex + 1) % items.length;
        highlightComboboxItem(items, activeComboboxIndex);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeComboboxIndex = (activeComboboxIndex - 1 + items.length) % items.length;
        highlightComboboxItem(items, activeComboboxIndex);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (activeComboboxIndex >= 0 && activeComboboxIndex < items.length) {
          const selectedId = items[activeComboboxIndex].getAttribute('data-id');
          if (selectedId) selectModel(selectedId);
        } else if (modelSearchInput.value.trim()) {
          selectModel(modelSearchInput.value.trim());
        }
      } else if (e.key === 'Escape') {
        dropdown.classList.add('hidden');
        isComboboxOpen = false;
        activeComboboxIndex = -1;
      }
    });
  }

  if (refreshModelsBtn) {
    refreshModelsBtn.addEventListener('click', () => {
      fetchModelsForProvider(getActiveProvider(), true).catch(() => {});
    });
  }

  // Click outside Combobox closes dropdown
  document.addEventListener('click', (e) => {
    const combobox = document.getElementById('model-combobox');
    const dropdown = document.getElementById('model-dropdown-list');
    if (combobox && dropdown && !combobox.contains(e.target as Node)) {
      dropdown.classList.add('hidden');
      isComboboxOpen = false;
      activeComboboxIndex = -1;
    }
  });

  // Bind API Key Drawer toggle & credential saves
  const apiKeyDrawer = document.getElementById('api-key-drawer') as HTMLDetailsElement | null;
  if (apiKeyDrawer) {
    apiKeyDrawer.addEventListener('toggle', () => {
      if (apiKeyDrawer.open) {
        loadProviderSettings().catch(() => {});
      }
    });
  }

  // Password visibility eye buttons
  for (const p of ['google', 'openai', 'anthropic', 'custom']) {
    const toggleBtn = document.getElementById(`toggle-${p}-key-btn`);
    const keyInput = document.getElementById(`${p}-key-input`) as HTMLInputElement | null;
    if (toggleBtn && keyInput) {
      toggleBtn.addEventListener('click', () => {
        keyInput.type = keyInput.type === 'password' ? 'text' : 'password';
      });
    }
  }

  const saveGoogleBtn = document.getElementById('save-google-key-btn');
  const googleKeyInput = document.getElementById('google-key-input') as HTMLInputElement | null;
  if (saveGoogleBtn && googleKeyInput) {
    saveGoogleBtn.addEventListener('click', async () => {
      const val = googleKeyInput.value.trim();
      const ok = await saveProviderCredential('google', val);
      if (ok) googleKeyInput.value = '';
    });
  }

  const saveOpenAIBtn = document.getElementById('save-openai-key-btn');
  const openaiKeyInput = document.getElementById('openai-key-input') as HTMLInputElement | null;
  if (saveOpenAIBtn && openaiKeyInput) {
    saveOpenAIBtn.addEventListener('click', async () => {
      const val = openaiKeyInput.value.trim();
      const ok = await saveProviderCredential('openai', val);
      if (ok) openaiKeyInput.value = '';
    });
  }

  const saveAnthropicBtn = document.getElementById('save-anthropic-key-btn');
  const anthropicKeyInput = document.getElementById('anthropic-key-input') as HTMLInputElement | null;
  if (saveAnthropicBtn && anthropicKeyInput) {
    saveAnthropicBtn.addEventListener('click', async () => {
      const val = anthropicKeyInput.value.trim();
      const ok = await saveProviderCredential('anthropic', val);
      if (ok) anthropicKeyInput.value = '';
    });
  }

  const saveCustomBtn = document.getElementById('save-custom-key-btn');
  const customKeyInput = document.getElementById('custom-key-input') as HTMLInputElement | null;
  const customEndpointInput = document.getElementById('custom-endpoint-input') as HTMLInputElement | null;
  if (saveCustomBtn && customKeyInput && customEndpointInput) {
    saveCustomBtn.addEventListener('click', async () => {
      const keyVal = customKeyInput.value.trim();
      const endpointVal = customEndpointInput.value.trim();
      const ok = await saveProviderCredential('custom', keyVal, endpointVal || undefined);
      if (ok) customKeyInput.value = '';
    });
  }

  // Bind source language selector
  const sourceLangSelect = document.getElementById(
    'source-lang-select'
  ) as HTMLSelectElement | null;
  if (sourceLangSelect) {
    sourceLangSelect.addEventListener('change', () => {
      saveSetting('sourceLang', sourceLangSelect.value).catch(() => {});
    });
  }

  // Bind overlay visibility toggle
  const visibilityToggle = document.getElementById(
    'overlay-visibility-toggle'
  ) as HTMLInputElement | null;
  if (visibilityToggle) {
    visibilityToggle.addEventListener('change', () => {
      saveSetting('overlayVisible', visibilityToggle.checked).catch(() => {});
    });
  }

  // Bind opacity range slider
  const opacitySlider = document.getElementById('opacity-slider') as HTMLInputElement | null;
  const opacityLabel = document.getElementById('opacity-val-label');

  if (opacitySlider) {
    opacitySlider.addEventListener('input', () => {
      const val = parseInt(opacitySlider.value, 10);
      if (opacityLabel) {
        opacityLabel.textContent = `${val}%`;
      }
      saveSetting('overlayOpacity', val).catch(() => {});
      saveSetting('opacity', val >= 95 ? 'opaque' : 'semi-transparent').catch(() => {});
    });
  }

  // Bind overlay color select and picker
  const colorSelect = document.getElementById('overlay-color-select') as HTMLSelectElement | null;
  const colorPicker = document.getElementById('overlay-color-picker') as HTMLInputElement | null;

  if (colorSelect) {
    colorSelect.addEventListener('change', () => {
      if (colorSelect.value !== 'custom') {
        if (colorPicker) {
          colorPicker.value = colorSelect.value;
        }
        saveSetting('overlayColor', colorSelect.value).catch(() => {});
      } else if (colorPicker) {
        colorPicker.click();
      }
    });
  }

  if (colorPicker) {
    colorPicker.addEventListener('input', () => {
      if (colorSelect) {
        if (['#ffffff', '#18181b', '#f4ecd8'].includes(colorPicker.value)) {
          colorSelect.value = colorPicker.value;
        } else {
          colorSelect.value = 'custom';
        }
      }
      saveSetting('overlayColor', colorPicker.value).catch(() => {});
    });
  }

  // Bind overlay font family select
  const fontSelect = document.getElementById('font-family-select') as HTMLSelectElement | null;
  if (fontSelect) {
    fontSelect.addEventListener('change', () => {
      saveSetting('speechBubbleFont', fontSelect.value).catch(() => {});
    });
  }

  // Bind debug geometry toggle
  const debugToggle = document.getElementById(
    'debug-geometry-toggle'
  ) as HTMLInputElement | null;
  if (debugToggle) {
    debugToggle.addEventListener('change', () => {
      saveSetting('debugGeometry', debugToggle.checked).catch(() => {});
    });
  }

  // Bind mascot companion toggles (View A & View B synchronized)
  const mascotQuickToggle = document.getElementById('mascot-quick-toggle') as HTMLInputElement | null;
  const mascotEnabledToggle = document.getElementById('mascot-enabled-toggle') as HTMLInputElement | null;
  const handleMascotToggleChange = (enabled: boolean) => {
    if (mascotQuickToggle) mascotQuickToggle.checked = enabled;
    if (mascotEnabledToggle) mascotEnabledToggle.checked = enabled;
    saveSetting('mascotEnabled', enabled).catch(() => {});
  };
  if (mascotQuickToggle) {
    mascotQuickToggle.addEventListener('change', () => {
      handleMascotToggleChange(mascotQuickToggle.checked);
    });
  }
  if (mascotEnabledToggle) {
    mascotEnabledToggle.addEventListener('change', () => {
      handleMascotToggleChange(mascotEnabledToggle.checked);
    });
  }

  // Bind prefetch controls (Feature F3)
  const prefetchToggle = document.getElementById(
    'prefetch-toggle'
  ) as HTMLInputElement | null;
  const prefetchDepthContainer = document.getElementById('prefetch-depth-container');
  if (prefetchToggle) {
    prefetchToggle.addEventListener('change', () => {
      if (prefetchDepthContainer) {
        prefetchDepthContainer.classList.toggle('hidden', !prefetchToggle.checked);
      }
      saveSetting('prefetchEnabled', prefetchToggle.checked).catch(() => {});
    });
  }

  const prefetchDepthSelect = document.getElementById(
    'prefetch-depth-select'
  ) as HTMLSelectElement | null;
  if (prefetchDepthSelect) {
    prefetchDepthSelect.addEventListener('change', () => {
      saveSetting('prefetchDepth', prefetchDepthSelect.value).catch(() => {});
    });
  }


  // Bind domain mode select
  const domainModeSelect = document.getElementById(
    'domain-mode-select'
  ) as HTMLSelectElement | null;
  if (domainModeSelect) {
    domainModeSelect.addEventListener('change', () => {
      setDomainMode(domainModeSelect.value as 'auto' | 'whitelist' | 'blacklist').catch(() => {});
    });
  }

  // Bind add domain controls
  const addDomainBtn = document.getElementById('add-domain-btn');
  const newDomainInput = document.getElementById('new-domain-input') as HTMLInputElement | null;
  const newDomainTarget = document.getElementById('new-domain-target') as HTMLSelectElement | null;

  if (addDomainBtn && newDomainInput && newDomainTarget) {
    const handleAdd = () => {
      const val = newDomainInput.value.trim();
      if (val) {
        addCustomDomain(val, newDomainTarget.value as 'whitelist' | 'blacklist').catch(() => {});
        newDomainInput.value = '';
      }
    };
    addDomainBtn.addEventListener('click', handleAdd);
    newDomainInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleAdd();
      }
    });
  }

  // Bind restore defaults button
  const restoreDefaultsBtn = document.getElementById('restore-defaults-btn');
  if (restoreDefaultsBtn) {
    restoreDefaultsBtn.addEventListener('click', () => {
      restoreDefaultDomains().catch(() => {});
    });
  }

  // Bind re-scan button
  const rescanBtn = document.getElementById('rescan-btn');
  if (rescanBtn) {
    rescanBtn.addEventListener('click', () => {
      triggerRescan().catch(() => {});
    });
  }

  // Bind clear-browser-cache button
  const clearBrowserCacheBtn = document.getElementById('clear-browser-cache-btn');
  if (clearBrowserCacheBtn) {
    clearBrowserCacheBtn.addEventListener('click', () => {
      triggerClearBrowserCache().catch(() => {});
    });
  }

  // Bind clear-db-cache button (and legacy clear-cache-btn)
  const clearDbCacheBtn =
    document.getElementById('clear-db-cache-btn') || document.getElementById('clear-cache-btn');
  if (clearDbCacheBtn) {
    clearDbCacheBtn.addEventListener('click', () => {
      triggerClearDatabaseCache().catch(() => {});
    });
  }
}

// Auto-run when in browser environment
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initPopup().catch((err) => {
        logger.error(`Initialization error: ${err instanceof Error ? err.message : String(err)}`);
      });
    });
  } else {
    initPopup().catch((err) => {
      logger.error(`Initialization error: ${err instanceof Error ? err.message : String(err)}`);
    });
  }
}
