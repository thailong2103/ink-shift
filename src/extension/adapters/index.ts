/**
 * Adapters Module Exports & Automatic Registration.
 */

import { siteAdapterRegistry } from './registry';
import { mangaDexAdapter } from './mangadex_adapter';
import { hitomiAdapter } from './hitomi_adapter';

// Auto-register built-in adapters
siteAdapterRegistry.register(mangaDexAdapter);
siteAdapterRegistry.register(hitomiAdapter);

export * from './base';
export * from './registry';
export * from './mangadex_adapter';
export * from './hitomi_adapter';
