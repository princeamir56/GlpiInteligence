import { Injectable, signal, effect } from '@angular/core';

export type ThemePreference = 'light' | 'dark' | 'auto';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'sartex.theme';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  /** User's explicit preference (may be 'auto'). */
  readonly preference = signal<ThemePreference>(this.readStored());
  /** The theme actually applied to the DOM. */
  readonly resolved = signal<ResolvedTheme>('light');

  private media = window.matchMedia('(prefers-color-scheme: dark)');

  constructor() {
    this.media.addEventListener('change', () => {
      if (this.preference() === 'auto') this.apply();
    });
    // Re-apply whenever preference changes and persist it.
    // apply() writes the `resolved` signal, so allow signal writes here.
    effect(
      () => {
        const pref = this.preference();
        localStorage.setItem(STORAGE_KEY, pref);
        this.apply();
      },
      { allowSignalWrites: true },
    );
  }

  setPreference(pref: ThemePreference): void {
    this.preference.set(pref);
  }

  /** Convenience toggle used by the header switch (light <-> dark). */
  toggle(): void {
    this.setPreference(this.resolved() === 'dark' ? 'light' : 'dark');
  }

  private apply(): void {
    const pref = this.preference();
    const resolved: ResolvedTheme =
      pref === 'auto' ? (this.media.matches ? 'dark' : 'light') : pref;
    document.documentElement.setAttribute('data-theme', resolved);
    this.resolved.set(resolved);
  }

  private readStored(): ThemePreference {
    const v = localStorage.getItem(STORAGE_KEY) as ThemePreference | null;
    return v === 'light' || v === 'dark' || v === 'auto' ? v : 'auto';
  }
}
