import { importProvidersFrom, Provider, EnvironmentProviders } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { LucideAngularModule } from 'lucide-angular';
import { ICONS } from '../app.config';

/**
 * Providers most component specs need: HTTP (mocked), router, no-op animations,
 * and the lucide icon set that app.config registers at runtime.
 */
export const commonTestProviders: (Provider | EnvironmentProviders)[] = [
  provideHttpClient(),
  provideHttpClientTesting(),
  provideRouter([]),
  provideNoopAnimations(),
  importProvidersFrom(LucideAngularModule.pick(ICONS)),
];
