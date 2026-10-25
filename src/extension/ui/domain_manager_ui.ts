/**
 * InkShift Domain Manager UI Controller
 * Reusable controller managing domain status cards, whitelist/blacklist drawers,
 * and policy filtering across both Extension Popup and In-Page Mascot HUD.
 */

import {
  loadDomainFilterSettings,
  saveDomainFilterSettings,
  resetToDefaultFilterSettings,
  normalizeHostname,
  isDomainAllowed,
  type DomainFilterSettings,
} from '../shared/domain_filter';
import { Icons } from '../shared/icons';

export interface DomainManagerElements {
  root: Document | ShadowRoot;
  activeDomainNameEl?: HTMLElement | null;
  activeDomainBadgeEl?: HTMLElement | null;
  activeDomainDetailEl?: HTMLElement | null;
  whitelistContainerEl?: HTMLElement | null;
  blacklistContainerEl?: HTMLElement | null;
  newDomainInputEl?: HTMLInputElement | null;
  newDomainTypeEl?: HTMLSelectElement | null;
  addDomainBtnEl?: HTMLElement | null;
  resetDefaultBtnEl?: HTMLElement | null;
}

export class DomainManagerUI {
  private elements: DomainManagerElements;
  private currentHostname: string = '';
  private currentSettings: DomainFilterSettings | null = null;
  private onSettingsChanged?: (settings: DomainFilterSettings) => void;

  constructor(
    elements: DomainManagerElements,
    currentHostname: string = '',
    onSettingsChanged?: (settings: DomainFilterSettings) => void
  ) {
    this.elements = elements;
    this.currentHostname = normalizeHostname(currentHostname);
    this.onSettingsChanged = onSettingsChanged;
  }

  public async init(): Promise<void> {
    this.bindEvents();
    await this.refresh();
  }

  public bindEvents(): void {
    const { addDomainBtnEl, newDomainInputEl, resetDefaultBtnEl } = this.elements;

    if (addDomainBtnEl) {
      addDomainBtnEl.addEventListener('click', () => {
        void this.handleAddDomain();
      });
    }

    if (newDomainInputEl) {
      newDomainInputEl.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          void this.handleAddDomain();
        }
      });
    }

    if (resetDefaultBtnEl) {
      resetDefaultBtnEl.addEventListener('click', () => {
        void this.handleResetDefault();
      });
    }
  }

  public async refresh(): Promise<void> {
    this.currentSettings = await loadDomainFilterSettings();
    this.updateActiveDomainCard();
    this.renderDomainLists();
  }

  public updateActiveDomainCard(): void {
    const { activeDomainNameEl, activeDomainBadgeEl, activeDomainDetailEl } = this.elements;
    if (!this.currentHostname) {
      if (activeDomainNameEl) activeDomainNameEl.textContent = 'MangaDex (Mock)';
      if (activeDomainBadgeEl) {
        activeDomainBadgeEl.className = 'domain-status-badge status-normal';
        activeDomainBadgeEl.textContent = 'Hỗ trợ';
      }
      return;
    }

    if (activeDomainNameEl) {
      activeDomainNameEl.textContent = this.currentHostname;
    }

    const policy = isDomainAllowed(this.currentHostname, this.currentSettings ?? undefined);

    if (activeDomainBadgeEl) {
      if (policy === 'blacklisted') {
        activeDomainBadgeEl.className = 'domain-status-badge status-blacklisted';
        activeDomainBadgeEl.innerHTML = `${Icons.alertTriangle({ size: 12 })} Đã chặn`;
      } else if (policy === 'whitelisted') {
        activeDomainBadgeEl.className = 'domain-status-badge status-whitelisted';
        activeDomainBadgeEl.innerHTML = `${Icons.shieldCheck({ size: 12 })} Whitelist`;
      } else {
        activeDomainBadgeEl.className = 'domain-status-badge status-normal';
        activeDomainBadgeEl.innerHTML = `${Icons.globe({ size: 12 })} Hoạt động`;
      }
    }

    if (activeDomainDetailEl) {
      if (policy === 'blacklisted') {
        activeDomainDetailEl.textContent = 'Tên miền nằm trong danh sách đen — Extension không quét trang.';
      } else if (policy === 'whitelisted') {
        activeDomainDetailEl.textContent = 'Tên miền được ưu tiên — Luôn tự động quét & dịch truyện.';
      } else {
        activeDomainDetailEl.textContent = 'Đang theo dõi trang đọc truyện tranh.';
      }
    }
  }

  public renderDomainLists(): void {
    const { whitelistContainerEl, blacklistContainerEl } = this.elements;
    if (!this.currentSettings) return;

    if (whitelistContainerEl) {
      whitelistContainerEl.innerHTML = '';
      if (this.currentSettings.whitelist.length === 0) {
        whitelistContainerEl.innerHTML = '<span class="empty-hint">Chưa có tên miền nào</span>';
      } else {
        for (const domain of this.currentSettings.whitelist) {
          whitelistContainerEl.appendChild(this.createTagElement(domain, 'whitelist'));
        }
      }
    }

    if (blacklistContainerEl) {
      blacklistContainerEl.innerHTML = '';
      if (this.currentSettings.blacklist.length === 0) {
        blacklistContainerEl.innerHTML = '<span class="empty-hint">Chưa có tên miền nào</span>';
      } else {
        for (const domain of this.currentSettings.blacklist) {
          blacklistContainerEl.appendChild(this.createTagElement(domain, 'blacklist'));
        }
      }
    }
  }

  private createTagElement(domain: string, type: 'whitelist' | 'blacklist'): HTMLElement {
    const pill = document.createElement('span');
    pill.className = `domain-pill pill-${type}`;

    const text = document.createElement('span');
    text.className = 'pill-text';
    text.textContent = domain;

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'pill-delete-btn';
    delBtn.title = `Xóa ${domain}`;
    delBtn.innerHTML = Icons.close({ size: 10, strokeWidth: 2.5 });

    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      void this.removeDomain(domain, type);
    });

    pill.appendChild(text);
    pill.appendChild(delBtn);
    return pill;
  }

  public async handleAddDomain(): Promise<void> {
    const { newDomainInputEl, newDomainTypeEl } = this.elements;
    if (!newDomainInputEl || !this.currentSettings) return;

    const raw = newDomainInputEl.value.trim();
    const normalized = normalizeHostname(raw);
    if (!normalized) return;

    const listType = (newDomainTypeEl?.value as 'whitelist' | 'blacklist') || 'whitelist';

    if (listType === 'whitelist') {
      this.currentSettings.blacklist = this.currentSettings.blacklist.filter((d) => d !== normalized);
      if (!this.currentSettings.whitelist.includes(normalized)) {
        this.currentSettings.whitelist.push(normalized);
      }
    } else {
      this.currentSettings.whitelist = this.currentSettings.whitelist.filter((d) => d !== normalized);
      if (!this.currentSettings.blacklist.includes(normalized)) {
        this.currentSettings.blacklist.push(normalized);
      }
    }

    await saveDomainFilterSettings(this.currentSettings);
    newDomainInputEl.value = '';
    this.updateActiveDomainCard();
    this.renderDomainLists();
    this.onSettingsChanged?.(this.currentSettings);
  }

  public async removeDomain(domain: string, type: 'whitelist' | 'blacklist'): Promise<void> {
    if (!this.currentSettings) return;
    if (type === 'whitelist') {
      this.currentSettings.whitelist = this.currentSettings.whitelist.filter((d) => d !== domain);
    } else {
      this.currentSettings.blacklist = this.currentSettings.blacklist.filter((d) => d !== domain);
    }
    await saveDomainFilterSettings(this.currentSettings);
    this.updateActiveDomainCard();
    this.renderDomainLists();
    this.onSettingsChanged?.(this.currentSettings);
  }

  public async handleResetDefault(): Promise<void> {
    this.currentSettings = await resetToDefaultFilterSettings();
    this.updateActiveDomainCard();
    this.renderDomainLists();
    this.onSettingsChanged?.(this.currentSettings);
  }
}
