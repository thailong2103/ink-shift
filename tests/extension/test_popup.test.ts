// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initPopup,
  checkBackendHealth,
  loadSettings,
  saveSetting,
  triggerRescan,
  triggerClearBrowserCache,
  triggerClearDatabaseCache,
  triggerClearCache,
  updateConditionalVisibility,
  loadDomainSettings,
  renderDomainTags,
  setDomainMode,
  addCustomDomain,
  restoreDefaultDomains,
  renderComboboxDropdown,
  selectModel,
  applyModelValue,
  fetchModelsForProvider,
  loadProviderSettings,
  saveProviderCredential,
  currentProviderModels,
  selectedModelsByProvider,
  getActiveProvider,
  normalizeProvider,
} from '../../src/extension/popup/popup';
import type { IPCMessage, IPCResponse, DiscoveredModelsData, ProviderSettingsData, SaveProviderSettingsData } from '../../src/extension/shared/ipc_types';

describe('Popup Settings Controller', () => {
  let mockSendMessage: ReturnType<typeof vi.fn>;
  let mockStorageGet: ReturnType<typeof vi.fn>;
  let mockStorageSet: ReturnType<typeof vi.fn>;
  let mockTabsQuery: ReturnType<typeof vi.fn>;
  let mockTabsSendMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="app" class="popup-container">
        <header class="popup-header">
          <h1>InkShift</h1>
          <button id="btn-open-settings" aria-label="Cài đặt"><svg></svg></button>
          <span id="backend-status-badge" class="status-indicator">Checking...</span>
          <button id="refresh-health-btn" title="Refresh health">↻</button>
        </header>
        <button id="btn-close-settings" aria-label="Quay lại"><svg></svg></button>
        <main class="popup-content">
          <!-- Domain Context Card -->
          <div class="domain-card" id="domain-card">
            <div class="domain-header">
              <span class="domain-name" id="active-domain-name">Checking...</span>
              <span class="domain-status-badge status-normal" id="active-domain-badge">...</span>
            </div>
            <div class="domain-detail-text" id="active-domain-detail">Đang phân tích trang...</div>
          </div>

          <div class="setting-item">
            <label for="domain-mode-select">Chế độ trang web này</label>
            <select id="domain-mode-select">
              <option value="auto">Tự động phát hiện (Khuyên dùng)</option>
              <option value="whitelist">🟢 Luôn dịch trên domain này (Whitelist)</option>
              <option value="blacklist">🔴 Chặn domain này (Blacklist)</option>
            </select>
          </div>

          <details class="domain-drawer" id="domain-drawer">
            <summary class="domain-drawer-summary">⚙️ Quản lý Blacklist & Whitelist</summary>
            <div class="drawer-content">
              <div class="drawer-section">
                <div class="drawer-section-header">
                  <span>Whitelist (Luôn dịch)</span>
                  <span id="whitelist-count" class="count-pill">0</span>
                </div>
                <div id="whitelist-tags" class="domain-tags-container"></div>
              </div>

              <div class="drawer-section">
                <div class="drawer-section-header">
                  <span>Blacklist (Chặn dịch)</span>
                  <span id="blacklist-count" class="count-pill">0</span>
                </div>
                <div id="blacklist-tags" class="domain-tags-container"></div>
              </div>

              <div class="add-domain-row">
                <input
                  type="text"
                  id="new-domain-input"
                  class="form-input flex-1"
                  placeholder="domain-can-them.com"
                />
                <select id="new-domain-target" class="form-select">
                  <option value="blacklist">Blacklist</option>
                  <option value="whitelist">Whitelist</option>
                </select>
                <button id="add-domain-btn" class="secondary-btn" type="button">Thêm</button>
              </div>

              <button id="restore-defaults-btn" class="outline-btn" type="button">
                Khôi phục danh sách mặc định
              </button>
            </div>
          </details>

          <!-- API Key Drawer -->
          <details class="domain-drawer" id="api-key-drawer">
            <summary class="domain-drawer-summary">🔑 Quản lý API Key & Endpoint</summary>
            <div class="drawer-content">
              <div class="drawer-section">
                <span id="google-key-status" class="count-pill status-pill not-configured">Chưa cấu hình</span>
                <input type="password" id="google-key-input" class="form-input flex-1" />
                <button id="toggle-google-key-btn" type="button">👁️</button>
                <button id="save-google-key-btn" class="secondary-btn" type="button">Lưu</button>
              </div>
              <div class="drawer-section">
                <span id="openai-key-status" class="count-pill status-pill not-configured">Chưa cấu hình</span>
                <input type="password" id="openai-key-input" class="form-input flex-1" />
                <button id="toggle-openai-key-btn" type="button">👁️</button>
                <button id="save-openai-key-btn" class="secondary-btn" type="button">Lưu</button>
              </div>
              <div class="drawer-section">
                <span id="anthropic-key-status" class="count-pill status-pill not-configured">Chưa cấu hình</span>
                <input type="password" id="anthropic-key-input" class="form-input flex-1" />
                <button id="toggle-anthropic-key-btn" type="button">👁️</button>
                <button id="save-anthropic-key-btn" class="secondary-btn" type="button">Lưu</button>
              </div>
              <div class="drawer-section">
                <span id="custom-key-status" class="count-pill status-pill not-configured">Chưa cấu hình</span>
                <input type="text" id="custom-endpoint-input" class="form-input flex-1" />
                <input type="password" id="custom-key-input" class="form-input flex-1" />
                <button id="toggle-custom-key-btn" type="button">👁️</button>
                <button id="save-custom-key-btn" class="secondary-btn" type="button">Lưu</button>
              </div>
              <div id="drawer-save-feedback" class="status-help-text"></div>
            </div>
          </details>

          <div class="setting-item">
            <label for="engine-select">Translation Engine</label>
            <select id="engine-select">
              <option value="auto">Tự động (Auto)</option>
              <option value="local">Local DirectML (On-Device)</option>
              <option value="cloud">Cloud AI</option>
            </select>
          </div>
          <div id="provider-container" class="setting-item conditional-item hidden">
            <label for="provider-select">Cloud Vision Provider</label>
            <select id="provider-select">
              <option value="google">Google Gemini</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic Claude</option>
              <option value="custom">Tùy chỉnh (OpenAI-compatible)</option>
            </select>
          </div>
          <div id="translator-container" class="setting-item conditional-item hidden">
            <label for="translator-select">Local Text Translator</label>
            <select id="translator-select">
              <option value="google-free">Google Translate (Miễn phí)</option>
              <option value="llm-google">Google Gemini Text</option>
              <option value="llm-openai">OpenAI Text</option>
              <option value="llm-anthropic">Anthropic Claude Text</option>
              <option value="llm-custom">Tùy chỉnh (OpenAI-compatible Text)</option>
            </select>
          </div>

          <!-- Model Combobox -->
          <div id="model-container" class="setting-item conditional-item hidden">
            <input type="checkbox" id="filter-vision-toggle" />
            <input type="text" id="model-search-input" class="form-input" />
            <button id="refresh-models-btn" type="button">↻</button>
            <span id="model-loading-indicator" class="combobox-spinner hidden"></span>
            <div id="model-combobox">
              <div id="model-dropdown-list" class="combobox-dropdown hidden"></div>
            </div>
            <div id="model-status-help" class="status-help-text"></div>
          </div>
          <div id="source-lang-container" class="setting-item conditional-item">
            <label for="source-lang-select">Source Language</label>
            <select id="source-lang-select">
              <option value="auto">Tự động (Auto)</option>
              <option value="ja">Tiếng Nhật (Manga)</option>
              <option value="en">Tiếng Anh (Comic)</option>
              <option value="ko">Tiếng Hàn (Manhwa)</option>
            </select>
          </div>
          <div class="setting-item toggle-row">
            <label for="overlay-visibility-toggle">Hiển thị bản dịch</label>
            <input type="checkbox" id="overlay-visibility-toggle" checked />
          </div>
          <div class="setting-item toggle-row">
            <label for="prefetch-toggle">Dịch trước các trang tiếp theo</label>
            <input type="checkbox" id="prefetch-toggle" checked />
          </div>
          <div id="prefetch-depth-container" class="setting-item conditional-item">
            <select id="prefetch-depth-select">
              <option value="3">3 trang</option>
              <option value="5">5 trang</option>
              <option value="10">10 trang</option>
              <option value="all">Toàn bộ chapter</option>
            </select>
          </div>
          <div class="setting-item">
            <span id="opacity-val-label">88%</span>

            <input type="range" id="opacity-slider" min="10" max="100" value="88" />
          </div>
          <div class="setting-item">
            <select id="overlay-color-select">
              <option value="#ffffff">Trắng</option>
              <option value="#18181b">Đen</option>
              <option value="#f4ecd8">Sepia</option>
              <option value="custom">Tùy chọn...</option>
            </select>
            <input type="color" id="overlay-color-picker" value="#ffffff" />
          </div>
          <div class="setting-item">
            <select id="font-family-select">
              <option value="itim">Itim</option>
              <option value="bangers">Bangers</option>
              <option value="patrick-hand">Patrick Hand</option>
              <option value="system-ui">System</option>
            </select>
          </div>
          <div class="setting-item">
            <label for="debug-geometry-toggle">Visual Debug Overlays</label>
            <input type="checkbox" id="debug-geometry-toggle" />
          </div>
          <div class="setting-item">
            <input type="checkbox" id="mascot-quick-toggle" checked />
            <input type="checkbox" id="mascot-enabled-toggle" checked />
          </div>
          <div class="action-item">
            <button id="rescan-btn" class="primary-btn">Re-scan Page</button>
            <div id="rescan-status" class="status-help-text"></div>
            <button id="clear-browser-cache-btn" class="secondary-btn">Clear Browser Cache</button>
            <div id="clear-browser-cache-feedback" class="status-help-text"></div>
            <button id="clear-db-cache-btn" class="secondary-btn">Clear DB Cache</button>
            <div id="clear-db-cache-feedback" class="status-help-text"></div>
            <button id="clear-cache-btn" class="secondary-btn">Clear Cache</button>
            <div id="clear-cache-feedback" class="status-help-text"></div>
          </div>
        </main>
      </div>
    `;

    mockSendMessage = vi.fn();
    mockStorageGet = vi.fn().mockResolvedValue({
      engine: 'cloud',
      provider: 'google',
      translator: 'google-free',
      sourceLang: 'ja',
      opacity: 'opaque',
      overlayOpacity: 95,
      overlayColor: '#18181b',
      speechBubbleFont: 'bangers',
      overlayVisible: true,
      debugGeometry: true,
      inkshift_domain_filter: {
        blacklist: ['google.com', 'facebook.com'],
        whitelist: ['custom-manga.com'],
      },
    });
    mockStorageSet = vi.fn().mockResolvedValue(undefined);
    mockTabsQuery = vi.fn().mockResolvedValue([
      { id: 101, active: true, url: 'https://mangadex.org/chapter/123' },
    ]);
    mockTabsSendMessage = vi.fn().mockImplementation(async (_tabId, msg) => {
      if (msg.type === 'GET_PAGE_READER_STATUS') {
        return {
          success: true,
          data: {
            hostname: 'mangadex.org',
            domainStatus: 'allowed',
            isReaderPage: true,
            confidence: 0.98,
            layoutType: 'strip',
            chapterMeta: {
              seriesSlug: 'one-piece',
              chapterNumber: '102',
            },
          },
        };
      }
      return { success: true };
    });

    vi.stubGlobal('chrome', {
      runtime: {
        sendMessage: mockSendMessage,
      },
      storage: {
        local: {
          get: mockStorageGet,
          set: mockStorageSet,
        },
      },
      tabs: {
        query: mockTabsQuery,
        sendMessage: mockTabsSendMessage,
      },
    });

    for (const key of Object.keys(currentProviderModels)) delete currentProviderModels[key];
    for (const key of Object.keys(selectedModelsByProvider)) delete selectedModelsByProvider[key];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('Health Check Status', () => {
    it('displays Online when backend responds healthy', async () => {
      mockSendMessage.mockResolvedValueOnce({
        success: true,
        data: { status: 'healthy', engine: 'cloud', version: '0.1.0' },
      });

      await checkBackendHealth();

      const badge = document.getElementById('backend-status-badge')!;
      expect(badge.textContent).toContain('Online');
      expect(badge.classList.contains('online')).toBe(true);
      expect(badge.classList.contains('offline')).toBe(false);
    });

    it('displays Offline when backend health check fails', async () => {
      mockSendMessage.mockResolvedValueOnce({
        success: false,
        error: { code: 'CONN_REFUSED', message: 'Connection refused' },
      });

      await checkBackendHealth();

      const badge = document.getElementById('backend-status-badge')!;
      expect(badge.textContent).toContain('Offline');
      expect(badge.classList.contains('offline')).toBe(true);
      expect(badge.classList.contains('online')).toBe(false);
    });
  });

  describe('Conditional Dropdown Controls', () => {
    it('shows provider container and hides translator and source-lang containers when engine is cloud', () => {
      updateConditionalVisibility('cloud');
      const providerContainer = document.getElementById('provider-container')!;
      const translatorContainer = document.getElementById('translator-container')!;
      const sourceLangContainer = document.getElementById('source-lang-container')!;

      expect(providerContainer.classList.contains('hidden')).toBe(false);
      expect(translatorContainer.classList.contains('hidden')).toBe(true);
      expect(sourceLangContainer.classList.contains('hidden')).toBe(true);
    });

    it('shows translator and source-lang containers and hides provider container when engine is local', () => {
      updateConditionalVisibility('local');
      const providerContainer = document.getElementById('provider-container')!;
      const translatorContainer = document.getElementById('translator-container')!;
      const sourceLangContainer = document.getElementById('source-lang-container')!;

      expect(providerContainer.classList.contains('hidden')).toBe(true);
      expect(translatorContainer.classList.contains('hidden')).toBe(false);
      expect(sourceLangContainer.classList.contains('hidden')).toBe(false);
    });

    it('hides provider and translator containers but shows source-lang container when engine is auto', () => {
      updateConditionalVisibility('auto');
      const providerContainer = document.getElementById('provider-container')!;
      const translatorContainer = document.getElementById('translator-container')!;
      const sourceLangContainer = document.getElementById('source-lang-container')!;

      expect(providerContainer.classList.contains('hidden')).toBe(true);
      expect(translatorContainer.classList.contains('hidden')).toBe(true);
      expect(sourceLangContainer.classList.contains('hidden')).toBe(false);
    });
  });

  describe('Settings Storage Synchronization', () => {
    it('loads saved settings from chrome.storage.local into UI controls', async () => {
      await loadSettings();

      const engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
      const providerSelect = document.getElementById('provider-select') as HTMLSelectElement;
      const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement;
      const sourceLangSelect = document.getElementById('source-lang-select') as HTMLSelectElement;
      const debugToggle = document.getElementById('debug-geometry-toggle') as HTMLInputElement;
      const providerContainer = document.getElementById('provider-container')!;
      const translatorContainer = document.getElementById('translator-container')!;
      const visibilityToggle = document.getElementById(
        'overlay-visibility-toggle'
      ) as HTMLInputElement;
      const opacitySlider = document.getElementById('opacity-slider') as HTMLInputElement;
      const opacityLabel = document.getElementById('opacity-val-label')!;
      const colorSelect = document.getElementById('overlay-color-select') as HTMLSelectElement;
      const colorPicker = document.getElementById('overlay-color-picker') as HTMLInputElement;

      expect(engineSelect.value).toBe('cloud');
      expect(providerSelect.value).toBe('google');
      expect(translatorSelect.value).toBe('google-free');
      expect(providerContainer.classList.contains('hidden')).toBe(false);
      expect(translatorContainer.classList.contains('hidden')).toBe(true);
      expect(sourceLangSelect.value).toBe('ja');
      expect(visibilityToggle.checked).toBe(true);
      expect(opacitySlider.value).toBe('95');
      expect(opacityLabel.textContent).toBe('95%');
      expect(colorSelect.value).toBe('#18181b');
      expect(colorPicker.value).toBe('#18181b');
      const fontSelect = document.getElementById('font-family-select') as HTMLSelectElement;
      expect(fontSelect.value).toBe('bangers');
      expect(debugToggle.checked).toBe(true);
    });

    it('persists speechBubbleFont when user selects a different font in popup', async () => {
      await initPopup();
      const fontSelect = document.getElementById('font-family-select') as HTMLSelectElement;
      fontSelect.value = 'patrick-hand';
      fontSelect.dispatchEvent(new Event('change'));

      expect(mockStorageSet).toHaveBeenCalledWith({ speechBubbleFont: 'patrick-hand' });
    });

    it('saves setting changes back to chrome.storage.local', async () => {
      await saveSetting('engine', 'local');
      expect(mockStorageSet).toHaveBeenCalledWith({ engine: 'local' });

      await saveSetting('provider', 'openai');
      expect(mockStorageSet).toHaveBeenCalledWith({ provider: 'openai' });

      await saveSetting('translator', 'llm-text');
      expect(mockStorageSet).toHaveBeenCalledWith({ translator: 'llm-text' });

      await saveSetting('sourceLang', 'ko');
      expect(mockStorageSet).toHaveBeenCalledWith({ sourceLang: 'ko' });

      await saveSetting('overlayVisible', false);
      expect(mockStorageSet).toHaveBeenCalledWith({ overlayVisible: false });

      await saveSetting('overlayOpacity', 80);
      expect(mockStorageSet).toHaveBeenCalledWith({ overlayOpacity: 80 });

      await saveSetting('overlayColor', '#f4ecd8');
      expect(mockStorageSet).toHaveBeenCalledWith({ overlayColor: '#f4ecd8' });

      await saveSetting('opacity', 'semi-transparent');
      expect(mockStorageSet).toHaveBeenCalledWith({ opacity: 'semi-transparent' });

      await saveSetting('debugGeometry', false);
      expect(mockStorageSet).toHaveBeenCalledWith({ debugGeometry: false });
    });

    it('maps legacy llm-text or llm to llm-google upon loading', async () => {
      mockStorageGet.mockResolvedValueOnce({
        engine: 'local',
        translator: 'llm-text',
      });

      await loadSettings();
      const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement;
      expect(translatorSelect.value).toBe('llm-google');
    });

    it('maps legacy llm-qwen to llm-custom upon loading', async () => {
      mockStorageGet.mockResolvedValueOnce({
        engine: 'local',
        translator: 'llm-qwen',
      });

      await loadSettings();
      const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement;
      expect(translatorSelect.value).toBe('llm-custom');
    });
  });

  describe('Manual Re-scan Trigger', () => {
    it('sends RESCAN_PAGE message to active tab', async () => {
      await triggerRescan();

      expect(mockTabsQuery).toHaveBeenCalledWith({ active: true, currentWindow: true });
      expect(mockTabsSendMessage).toHaveBeenCalledWith(101, { type: 'RESCAN_PAGE' }, { frameId: 0 });
    });
  });

  describe('Full Popup Initialization', () => {
    it('binds event listeners and initializes UI', async () => {
      mockSendMessage.mockResolvedValue({
        success: true,
        data: { status: 'healthy', engine: 'cloud' },
      });

      await initPopup();

      // Trigger change event on engine select to local
      const engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
      engineSelect.value = 'local';
      engineSelect.dispatchEvent(new Event('change'));

      expect(mockStorageSet).toHaveBeenCalledWith({ engine: 'local' });

      const providerContainer = document.getElementById('provider-container')!;
      const translatorContainer = document.getElementById('translator-container')!;
      expect(providerContainer.classList.contains('hidden')).toBe(true);
      expect(translatorContainer.classList.contains('hidden')).toBe(false);

      // Trigger change on translator select
      const translatorSelect = document.getElementById('translator-select') as HTMLSelectElement;
      translatorSelect.value = 'llm-google';
      translatorSelect.dispatchEvent(new Event('change'));
      expect(mockStorageSet).toHaveBeenCalledWith({ translator: 'llm-google' });

      // Trigger change on provider select
      const providerSelect = document.getElementById('provider-select') as HTMLSelectElement;
      providerSelect.value = 'google';
      providerSelect.dispatchEvent(new Event('change'));
      expect(mockStorageSet).toHaveBeenCalledWith({ provider: 'google' });

      // Trigger change on visibility toggle
      const visibilityToggle = document.getElementById(
        'overlay-visibility-toggle'
      ) as HTMLInputElement;
      visibilityToggle.checked = false;
      visibilityToggle.dispatchEvent(new Event('change'));
      expect(mockStorageSet).toHaveBeenCalledWith({ overlayVisible: false });

      // Trigger input on opacity slider
      const opacitySlider = document.getElementById('opacity-slider') as HTMLInputElement;
      const opacityLabel = document.getElementById('opacity-val-label')!;
      opacitySlider.value = '70';
      opacitySlider.dispatchEvent(new Event('input'));
      expect(opacityLabel.textContent).toBe('70%');
      expect(mockStorageSet).toHaveBeenCalledWith({ overlayOpacity: 70 });

      // Trigger change on color select
      const colorSelect = document.getElementById('overlay-color-select') as HTMLSelectElement;
      colorSelect.value = '#18181b';
      colorSelect.dispatchEvent(new Event('change'));
      expect(mockStorageSet).toHaveBeenCalledWith({ overlayColor: '#18181b' });

      // Trigger click on rescan button
      const rescanBtn = document.getElementById('rescan-btn') as HTMLButtonElement;
      rescanBtn.click();
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(mockTabsSendMessage).toHaveBeenCalledWith(101, { type: 'RESCAN_PAGE' }, { frameId: 0 });
    });
  });

  describe('Domain Detection & Policy Controls', () => {
    it('loads active domain and reader detection status into UI', async () => {
      await loadDomainSettings();

      const domainName = document.getElementById('active-domain-name')!;
      const domainBadge = document.getElementById('active-domain-badge')!;
      const domainDetail = document.getElementById('active-domain-detail')!;
      const domainSelect = document.getElementById('domain-mode-select') as HTMLSelectElement;

      expect(domainName.textContent).toBe('mangadex.org');
      expect(domainBadge.textContent).toBe('Trang đọc truyện');
      expect(domainBadge.classList.contains('status-reader')).toBe(true);
      expect(domainDetail.textContent).toContain('one-piece');
      expect(domainDetail.textContent).toContain('102');
      expect(domainSelect.value).toBe('auto');
    });

    it('displays blacklisted status when active tab domain is blacklisted', async () => {
      mockTabsQuery.mockResolvedValueOnce([
        { id: 102, active: true, url: 'https://facebook.com/watch' },
      ]);
      mockTabsSendMessage.mockResolvedValueOnce({
        success: true,
        data: {
          hostname: 'facebook.com',
          domainStatus: 'blacklisted',
          isReaderPage: false,
          confidence: 0,
          layoutType: 'none',
        },
      });

      await loadDomainSettings();

      const domainBadge = document.getElementById('active-domain-badge')!;
      const domainSelect = document.getElementById('domain-mode-select') as HTMLSelectElement;
      expect(domainBadge.textContent).toBe('Bị chặn');
      expect(domainBadge.classList.contains('status-blacklisted')).toBe(true);
      expect(domainSelect.value).toBe('blacklist');
    });

    it('displays whitelisted status when active tab domain is in whitelist', async () => {
      mockTabsQuery.mockResolvedValueOnce([
        { id: 103, active: true, url: 'https://custom-manga.com/read' },
      ]);
      mockTabsSendMessage.mockResolvedValueOnce({
        success: true,
        data: {
          hostname: 'custom-manga.com',
          domainStatus: 'whitelisted',
          isReaderPage: true,
          confidence: 1.0,
          layoutType: 'strip',
        },
      });

      await loadDomainSettings();

      const domainBadge = document.getElementById('active-domain-badge')!;
      const domainSelect = document.getElementById('domain-mode-select') as HTMLSelectElement;
      expect(domainBadge.textContent).toBe('Buộc dịch');
      expect(domainBadge.classList.contains('status-whitelisted')).toBe(true);
      expect(domainSelect.value).toBe('whitelist');
    });

    it('handles browser internal system URLs gracefully', async () => {
      mockTabsQuery.mockResolvedValueOnce([
        { id: 104, active: true, url: 'chrome://extensions/' },
      ]);

      await loadDomainSettings();

      const domainName = document.getElementById('active-domain-name')!;
      const domainSelect = document.getElementById('domain-mode-select') as HTMLSelectElement;
      expect(domainName.textContent).toBe('Trang hệ thống');
      expect(domainSelect.disabled).toBe(true);
    });

    it('sets domain mode to whitelist, updates storage and triggers re-scan', async () => {
      await loadDomainSettings();
      await setDomainMode('whitelist');

      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({
          inkshift_domain_filter: expect.objectContaining({
            whitelist: expect.arrayContaining(['mangadex.org']),
          }),
        })
      );
      expect(mockTabsSendMessage).toHaveBeenCalledWith(101, { type: 'RESCAN_PAGE' }, { frameId: 0 });
    });

    it('sets domain mode to blacklist, updates storage and sets status badge', async () => {
      await loadDomainSettings();
      await setDomainMode('blacklist');

      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({
          inkshift_domain_filter: expect.objectContaining({
            blacklist: expect.arrayContaining(['mangadex.org']),
          }),
        })
      );
    });

    it('sets domain mode to auto, clearing domain from custom whitelist and blacklist', async () => {
      await loadDomainSettings();
      await setDomainMode('auto');

      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({
          inkshift_domain_filter: expect.objectContaining({
            blacklist: expect.not.arrayContaining(['mangadex.org']),
            whitelist: expect.not.arrayContaining(['mangadex.org']),
          }),
        })
      );
    });
  });

  describe('Domain Management Drawer', () => {
    it('renders domain tags with remove buttons and accurate count pills', async () => {
      await loadDomainSettings();

      const whitelistCount = document.getElementById('whitelist-count')!;
      const blacklistCount = document.getElementById('blacklist-count')!;
      const whitelistTags = document.getElementById('whitelist-tags')!;
      const blacklistTags = document.getElementById('blacklist-tags')!;

      expect(whitelistCount.textContent).toBe('1');
      expect(blacklistCount.textContent).toBe('2');
      expect(whitelistTags.textContent).toContain('custom-manga.com');
      expect(blacklistTags.textContent).toContain('google.com');
      expect(blacklistTags.textContent).toContain('facebook.com');
    });

    it('adds custom domain to blacklist via drawer input and updates UI', async () => {
      await loadDomainSettings();

      await addCustomDomain('twitter.com', 'blacklist');

      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({
          inkshift_domain_filter: expect.objectContaining({
            blacklist: expect.arrayContaining(['twitter.com']),
          }),
        })
      );
      const blacklistTags = document.getElementById('blacklist-tags')!;
      expect(blacklistTags.textContent).toContain('twitter.com');
    });

    it('restores default filter settings when restore defaults button is clicked', async () => {
      await loadDomainSettings();

      await restoreDefaultDomains();

      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({
          inkshift_domain_filter: expect.objectContaining({
            blacklist: expect.arrayContaining(['google.com', 'youtube.com', 'shopee.vn']),
            whitelist: [],
          }),
        })
      );
    });

    it('loads prefetch settings from storage', async () => {
      mockStorageGet.mockResolvedValue({
        prefetchEnabled: false,
        prefetchDepth: '5',
      });

      await loadSettings();

      const toggle = document.getElementById('prefetch-toggle') as HTMLInputElement;
      const depthSelect = document.getElementById('prefetch-depth-select') as HTMLSelectElement;
      const depthContainer = document.getElementById('prefetch-depth-container')!;

      expect(toggle.checked).toBe(false);
      expect(depthSelect.value).toBe('5');
      expect(depthContainer.classList.contains('hidden')).toBe(true);
    });

    it('persists prefetchEnabled when toggle is changed in popup', async () => {
      await initPopup();

      const toggle = document.getElementById('prefetch-toggle') as HTMLInputElement;
      const depthContainer = document.getElementById('prefetch-depth-container')!;

      toggle.checked = false;
      toggle.dispatchEvent(new Event('change'));

      expect(mockStorageSet).toHaveBeenCalledWith({ prefetchEnabled: false });
      expect(depthContainer.classList.contains('hidden')).toBe(true);
    });

    it('persists prefetchDepth when depth is changed in popup', async () => {
      await initPopup();

      const depthSelect = document.getElementById('prefetch-depth-select') as HTMLSelectElement;
      depthSelect.value = '10';
      depthSelect.dispatchEvent(new Event('change'));

      expect(mockStorageSet).toHaveBeenCalledWith({ prefetchDepth: '10' });
    });
  });

  describe('Searchable Combobox & Dynamic Model Hub (Phase 25)', () => {
    it('loads cached model from storage on startup with 0ms network request', async () => {
      mockStorageGet.mockResolvedValue({
        engine: 'cloud',
        provider: 'google',
        selected_models: { google: 'gemini-2.5-flash' },
      });

      await loadSettings();

      const modelInput = document.getElementById('model-search-input') as HTMLInputElement;
      expect(modelInput.value).toBe('gemini-2.5-flash');
      expect(mockSendMessage).not.toHaveBeenCalledWith(
        expect.objectContaining({ type: 'FETCH_PROVIDER_MODELS' })
      );
    });

    it('renders only vision-capable models when filterVisionToggle is checked', () => {
      currentProviderModels['google'] = [
        { id: 'gemini-2.5-flash', display_name: 'Gemini 2.5 Flash', supports_vision: true },
        { id: 'gemini-text-only', display_name: 'Gemini Text', supports_vision: false },
      ];

      const filterVisionToggle = document.getElementById('filter-vision-toggle') as HTMLInputElement;
      filterVisionToggle.checked = true;

      renderComboboxDropdown('');

      const items = document.querySelectorAll('.combobox-item');
      expect(items.length).toBe(1);
      expect(items[0].getAttribute('data-id')).toBe('gemini-2.5-flash');
    });

    it('renders all models when filterVisionToggle is unchecked', () => {
      currentProviderModels['google'] = [
        { id: 'gemini-2.5-flash', display_name: 'Gemini 2.5 Flash', supports_vision: true },
        { id: 'gemini-text-only', display_name: 'Gemini Text', supports_vision: false },
      ];

      const filterVisionToggle = document.getElementById('filter-vision-toggle') as HTMLInputElement;
      filterVisionToggle.checked = false;

      renderComboboxDropdown('');

      const items = document.querySelectorAll('.combobox-item');
      expect(items.length).toBe(2);
    });

    it('filters models dynamically by substring search query', () => {
      currentProviderModels['openai'] = [
        { id: 'gpt-4o', display_name: 'GPT-4o', supports_vision: true },
        { id: 'gpt-4o-mini', display_name: 'GPT-4o Mini', supports_vision: true },
        { id: 'o1', display_name: 'o1 Reasoning', supports_vision: true },
      ];

      const engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
      const providerSelect = document.getElementById('provider-select') as HTMLSelectElement;
      engineSelect.value = 'cloud';
      providerSelect.value = 'openai';

      renderComboboxDropdown('mini');

      const items = document.querySelectorAll('.combobox-item');
      expect(items.length).toBe(1);
      expect(items[0].getAttribute('data-id')).toBe('gpt-4o-mini');
    });

    it('navigates combobox with keyboard arrow keys and selects with Enter', async () => {
      await initPopup();

      currentProviderModels['google'] = [
        { id: 'gemini-2.0-flash', display_name: 'Gemini 2.0 Flash', supports_vision: true },
        { id: 'gemini-2.5-flash', display_name: 'Gemini 2.5 Flash', supports_vision: true },
      ];

      const engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
      engineSelect.value = 'cloud';
      renderComboboxDropdown('');

      const input = document.getElementById('model-search-input') as HTMLInputElement;
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));

      const items = document.querySelectorAll('.combobox-item');
      expect(items[0].classList.contains('active')).toBe(true);

      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
      expect(items[1].classList.contains('active')).toBe(true);

      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
      expect(input.value).toBe('gemini-2.5-flash');
      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({ model: 'gemini-2.5-flash' })
      );
    });

    it('persists selected model per provider in chrome.storage.local', () => {
      const providerSelect = document.getElementById('provider-select') as HTMLSelectElement;
      const engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
      engineSelect.value = 'cloud';
      providerSelect.value = 'anthropic';

      selectModel('claude-3-5-sonnet-20241022');

      expect(selectedModelsByProvider['anthropic']).toBe('claude-3-5-sonnet-20241022');
      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({ model: 'claude-3-5-sonnet-20241022' })
      );
    });

    it('immediately updates active model on input event without needing click or Enter', async () => {
      await initPopup();

      const providerSelect = document.getElementById('provider-select') as HTMLSelectElement;
      const engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
      engineSelect.value = 'cloud';
      providerSelect.value = 'custom';

      const input = document.getElementById('model-search-input') as HTMLInputElement;
      input.value = 'qwen-vl-plus';
      input.dispatchEvent(new Event('input'));

      expect(selectedModelsByProvider['custom']).toBe('qwen-vl-plus');
      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({ model: 'qwen-vl-plus' })
      );
    });

    it('immediately updates active model on blur or change event without Enter', async () => {
      await initPopup();

      const providerSelect = document.getElementById('provider-select') as HTMLSelectElement;
      const engineSelect = document.getElementById('engine-select') as HTMLSelectElement;
      engineSelect.value = 'cloud';
      providerSelect.value = 'openai';

      const input = document.getElementById('model-search-input') as HTMLInputElement;
      input.value = 'gpt-4o-2024-11-20';
      input.dispatchEvent(new Event('blur'));

      expect(selectedModelsByProvider['openai']).toBe('gpt-4o-2024-11-20');
      expect(mockStorageSet).toHaveBeenCalledWith(
        expect.objectContaining({ model: 'gpt-4o-2024-11-20' })
      );
    });

    it('loads provider settings and displays masked key badges in API key drawer', async () => {
      mockSendMessage.mockResolvedValueOnce({
        success: true,
        data: {
          success: true,
          providers: {
            google: { configured: true, masked_key: 'AIzaSy...4xK8' },
            openai: { configured: false },
            anthropic: { configured: true, masked_key: 'sk-ant...98ab' },
            custom: { configured: true, base_url: 'https://api.deepseek.com/v1', masked_key: 'sk-dep...1234' },
          },
        },
      });

      await loadProviderSettings();

      const googleBadge = document.getElementById('google-key-status')!;
      expect(googleBadge.textContent).toContain('Đã cấu hình (AIzaSy...4xK8)');
      expect(googleBadge.className).toContain('configured');

      const openaiBadge = document.getElementById('openai-key-status')!;
      expect(openaiBadge.textContent).toBe('Chưa cấu hình');
      expect(openaiBadge.className).toContain('not-configured');

      const customEndpoint = document.getElementById('custom-endpoint-input') as HTMLInputElement;
      expect(customEndpoint.value).toBe('https://api.deepseek.com/v1');
    });

    it('saves provider credentials and displays green success confirmation', async () => {
      mockSendMessage.mockResolvedValueOnce({
        success: true,
        data: {
          success: true,
          provider: 'google',
          status: { configured: true, masked_key: 'AIzaSy...9999' },
        },
      });
      mockSendMessage.mockResolvedValueOnce({
        success: true,
        data: {
          success: true,
          providers: {
            google: { configured: true, masked_key: 'AIzaSy...9999' },
            openai: { configured: false },
            anthropic: { configured: false },
            custom: { configured: false },
          },
        },
      });

      const ok = await saveProviderCredential('google', 'AIzaSy_new_key_123456789');
      expect(ok).toBe(true);

      const feedback = document.getElementById('drawer-save-feedback')!;
      expect(feedback.textContent).toContain('thành công');
      expect(feedback.className).toContain('success');
    });

    it('displays defensive error when model discovery encounters missing key 401', async () => {
      mockSendMessage.mockResolvedValueOnce({
        success: false,
        error: { code: 'MISSING_API_KEY', message: 'API key is required' },
      });

      await fetchModelsForProvider('google', true);

      const statusHelp = document.getElementById('model-status-help')!;
      expect(statusHelp.textContent).toContain('Chưa cấu hình API Key');
      expect(statusHelp.className).toContain('error');
    });

    it('displays defensive error when model discovery encounters rate limit 429', async () => {
      mockSendMessage.mockResolvedValueOnce({
        success: false,
        error: { code: 'HTTP_429', message: 'Quota exceeded' },
      });

      await fetchModelsForProvider('openai', true);

      const statusHelp = document.getElementById('model-status-help')!;
      expect(statusHelp.textContent).toContain('vượt quá');
      expect(statusHelp.className).toContain('error');
    });
  });

  describe('2-View Bento Navigation', () => {
    it('slides to settings view when clicking btn-open-settings and returns on btn-close-settings', async () => {
      await initPopup();
      const app = document.getElementById('app')!;
      const btnOpen = document.getElementById('btn-open-settings')!;
      const btnClose = document.getElementById('btn-close-settings')!;

      expect(app.classList.contains('view-settings-active')).toBe(false);

      btnOpen.click();
      expect(app.classList.contains('view-settings-active')).toBe(true);

      btnClose.click();
      expect(app.classList.contains('view-settings-active')).toBe(false);
    });
  });

  describe('Mascot Companion Toggle', () => {
    it('loads mascotEnabled boolean state from storage', async () => {
      mockStorageGet.mockResolvedValueOnce({ mascotEnabled: false });
      await loadSettings();
      const quickToggle = document.getElementById('mascot-quick-toggle') as HTMLInputElement;
      const enabledToggle = document.getElementById('mascot-enabled-toggle') as HTMLInputElement;
      expect(quickToggle.checked).toBe(false);
      expect(enabledToggle.checked).toBe(false);
    });

    it('synchronizes mascot toggles and saves to storage on change', async () => {
      await initPopup();
      const quickToggle = document.getElementById('mascot-quick-toggle') as HTMLInputElement;
      const enabledToggle = document.getElementById('mascot-enabled-toggle') as HTMLInputElement;

      quickToggle.checked = false;
      quickToggle.dispatchEvent(new Event('change'));

      expect(enabledToggle.checked).toBe(false);
      expect(mockStorageSet).toHaveBeenCalledWith({ mascotEnabled: false });

      enabledToggle.checked = true;
      enabledToggle.dispatchEvent(new Event('change'));

      expect(quickToggle.checked).toBe(true);
      expect(mockStorageSet).toHaveBeenCalledWith({ mascotEnabled: true });
    });
  });

  describe('Clear Cache Actions (Browser & Database)', () => {
    describe('triggerClearBrowserCache', () => {
      it('dispatches RESCAN_PAGE to active tab and updates feedback with count', async () => {
        mockTabsQuery.mockResolvedValueOnce([{ id: 202, url: 'https://mangadex.org/chapter/456' }]);
        mockTabsSendMessage.mockResolvedValueOnce({ success: true, count: 8 });

        await triggerClearBrowserCache();

        expect(mockTabsQuery).toHaveBeenCalledWith({ active: true, currentWindow: true });
        expect(mockTabsSendMessage).toHaveBeenCalledWith(202, { type: 'RESCAN_PAGE' }, { frameId: 0 });

        const feedback = document.getElementById('clear-browser-cache-feedback')!;
        expect(feedback.textContent).toContain('8');
        expect(feedback.className).toContain('success');
      });

      it('warns when active tab is a browser system page', async () => {
        mockTabsQuery.mockResolvedValueOnce([{ id: 101, url: 'chrome://extensions' }]);

        await triggerClearBrowserCache();

        expect(mockTabsSendMessage).not.toHaveBeenCalled();
        const feedback = document.getElementById('clear-browser-cache-feedback')!;
        expect(feedback.textContent).toContain('không phải trang đọc truyện manga');
        expect(feedback.className).toContain('warning');
      });

      it('handles content script disconnection error gracefully', async () => {
        mockTabsQuery.mockResolvedValueOnce([{ id: 303, url: 'https://mangadex.org/chapter/789' }]);
        mockTabsSendMessage.mockRejectedValueOnce(new Error('Could not establish connection. Receiving end does not exist.'));

        await triggerClearBrowserCache();

        const feedback = document.getElementById('clear-browser-cache-feedback')!;
        expect(feedback.textContent).toContain('Hãy F5 trang truyện');
        expect(feedback.className).toContain('warning');
      });
    });

    describe('triggerClearDatabaseCache', () => {
      it('sends CLEAR_CACHE message when user confirms dialog', async () => {
        vi.spyOn(window, 'confirm').mockReturnValue(true);
        mockSendMessage.mockResolvedValueOnce({
          success: true,
          data: { success: true, deleted: 15, scope: 'all' },
        });

        await triggerClearDatabaseCache();

        expect(window.confirm).toHaveBeenCalled();
        expect(mockSendMessage).toHaveBeenCalledWith({
          type: 'CLEAR_CACHE',
          payload: { all: true },
        });

        const feedback = document.getElementById('clear-db-cache-feedback')!;
        expect(feedback.textContent).toContain('15');
        expect(feedback.className).toContain('success');
      });

      it('does not send CLEAR_CACHE when user cancels dialog', async () => {
        vi.spyOn(window, 'confirm').mockReturnValue(false);

        await triggerClearDatabaseCache();

        expect(window.confirm).toHaveBeenCalled();
        expect(mockSendMessage).not.toHaveBeenCalled();
      });

      it('displays error feedback when database clear returns failure', async () => {
        vi.spyOn(window, 'confirm').mockReturnValue(true);
        mockSendMessage.mockResolvedValueOnce({
          success: false,
          error: { code: 'DATABASE_LOCKED', message: 'SQLite database is busy' },
        });

        await triggerClearDatabaseCache();

        const feedback = document.getElementById('clear-db-cache-feedback')!;
        expect(feedback.textContent).toContain('SQLite database is busy');
        expect(feedback.className).toContain('error');
      });
    });

    describe('triggerClearCache backwards compatibility alias', () => {
      it('executes triggerClearDatabaseCache logic and updates fallback feedback', async () => {
        vi.spyOn(window, 'confirm').mockReturnValue(true);
        mockSendMessage.mockResolvedValueOnce({
          success: true,
          data: { success: true, deleted: 12, scope: 'all' },
        });

        await triggerClearCache();

        expect(window.confirm).toHaveBeenCalled();
        expect(mockSendMessage).toHaveBeenCalledWith({
          type: 'CLEAR_CACHE',
          payload: { all: true },
        });
      });
    });
  });
});



