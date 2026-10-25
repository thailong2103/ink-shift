/**
 * InkShift Vector Micro-Icon System
 * Zero-emoji, crisp, pixel-aligned SVG vector icons for extension UI.
 * Standardized on 24x24 viewBox with 2px stroke and currentColor inheritance.
 */

export interface IconOptions {
  size?: number;
  className?: string;
  strokeWidth?: number;
}

function renderSvg(innerPath: string, options?: IconOptions): string {
  const size = options?.size ?? 15;
  const className = options?.className ? `ui-icon ${options.className}` : 'ui-icon';
  const stroke = options?.strokeWidth ?? 2;
  return `<svg class="${className}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${innerPath}</svg>`;
}

export const Icons = {
  // Navigation & Core Actions
  gear: (opts?: IconOptions): string =>
    renderSvg(
      `<circle cx="12" cy="12" r="3"/>
       <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>`,
      opts
    ),

  refresh: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>`,
      opts
    ),

  rescan: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
       <path d="M3 3v5h5M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/>
       <path d="M16 21h5v-5"/>`,
      opts
    ),

  arrowLeft: (opts?: IconOptions): string =>
    renderSvg(
      `<line x1="19" y1="12" x2="5" y2="12"/>
       <polyline points="12 19 5 12 12 5"/>`,
      opts
    ),

  chevronRight: (opts?: IconOptions): string =>
    renderSvg(
      `<polyline points="9 18 15 12 9 6"/>`,
      opts
    ),

  chevronDown: (opts?: IconOptions): string =>
    renderSvg(
      `<polyline points="6 9 12 15 18 9"/>`,
      opts
    ),

  close: (opts?: IconOptions): string =>
    renderSvg(
      `<line x1="18" y1="6" x2="6" y2="18"/>
       <line x1="6" y1="6" x2="18" y2="18"/>`,
      opts
    ),

  check: (opts?: IconOptions): string =>
    renderSvg(
      `<polyline points="20 6 9 17 4 12"/>`,
      opts
    ),

  alertTriangle: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
       <line x1="12" y1="9" x2="12" y2="13"/>
       <line x1="12" y1="17" x2="12.01" y2="17"/>`,
      opts
    ),

  // Feature Domains & Indicators
  globe: (opts?: IconOptions): string =>
    renderSvg(
      `<circle cx="12" cy="12" r="10"/>
       <line x1="2" y1="12" x2="22" y2="12"/>
       <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>`,
      opts
    ),

  shield: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>`,
      opts
    ),

  shieldCheck: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
       <polyline points="9 12 11 14 15 10"/>`,
      opts
    ),

  key: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M21 2l-2 2m-1.5 1.5L16 7l-1.5-1.5-2 2 1.5 1.5-2 2 1.5 1.5-2 2 1.5 1.5L9 17.5A6 6 0 1 1 6.5 15L8 13.5"/>`,
      opts
    ),

  sliders: (opts?: IconOptions): string =>
    renderSvg(
      `<line x1="4" y1="21" x2="4" y2="14"/>
       <line x1="4" y1="10" x2="4" y2="3"/>
       <line x1="12" y1="21" x2="12" y2="12"/>
       <line x1="12" y1="8" x2="12" y2="3"/>
       <line x1="20" y1="21" x2="20" y2="16"/>
       <line x1="20" y1="12" x2="20" y2="3"/>
       <line x1="1" y1="14" x2="7" y2="14"/>
       <line x1="9" y1="8" x2="15" y2="8"/>
       <line x1="17" y1="16" x2="23" y2="16"/>`,
      opts
    ),

  cpu: (opts?: IconOptions): string =>
    renderSvg(
      `<rect x="4" y="4" width="16" height="16" rx="2" ry="2"/>
       <rect x="9" y="9" width="6" height="6"/>
       <line x1="9" y1="1" x2="9" y2="4"/>
       <line x1="15" y1="1" x2="15" y2="4"/>
       <line x1="9" y1="20" x2="9" y2="23"/>
       <line x1="15" y1="20" x2="15" y2="23"/>
       <line x1="20" y1="9" x2="23" y2="9"/>
       <line x1="20" y1="14" x2="23" y2="14"/>
       <line x1="1" y1="9" x2="4" y2="9"/>
       <line x1="1" y1="14" x2="4" y2="14"/>`,
      opts
    ),

  cloud: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>`,
      opts
    ),

  sparkles: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/>`,
      opts
    ),

  bookOpen: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
       <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>`,
      opts
    ),

  eye: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
       <circle cx="12" cy="12" r="3"/>`,
      opts
    ),

  eyeOff: (opts?: IconOptions): string =>
    renderSvg(
      `<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
       <line x1="1" y1="1" x2="23" y2="23"/>`,
      opts
    ),

  statusDot: (status: 'online' | 'offline' | 'checking' | 'warning'): string => {
    let colorClass = 'status-dot-checking';
    if (status === 'online') colorClass = 'status-dot-online';
    if (status === 'offline') colorClass = 'status-dot-offline';
    if (status === 'warning') colorClass = 'status-dot-warning';
    return `<span class="status-dot ${colorClass}" aria-hidden="true"></span>`;
  },
};
