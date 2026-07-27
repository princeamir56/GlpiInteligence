import { Component, inject, signal } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { AuthService } from '../../core/services/auth.service';
import { ThemeService, ThemePreference } from '../../core/services/theme.service';
import { fadeUp } from '../../shared/animations';

const PREF_KEY = 'sartex.notif.prefs';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [NgFor, NgIf, LucideAngularModule],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.css',
  animations: [fadeUp],
})
export class SettingsComponent {
  private auth = inject(AuthService);
  private themeSvc = inject(ThemeService);

  readonly themeOptions: { value: ThemePreference; label: string; icon: string }[] = [
    { value: 'light', label: 'Clair', icon: 'sun' },
    { value: 'dark', label: 'Sombre', icon: 'moon' },
    { value: 'auto', label: 'Système', icon: 'layout-dashboard' },
  ];

  readonly preference = this.themeSvc.preference;

  readonly toastEnabled = signal(this.readPref('toast', true));
  readonly badgeEnabled = signal(this.readPref('badge', true));

  get user() {
    return this.auth.currentUser();
  }
  get role() {
    return this.auth.role();
  }

  setTheme(pref: ThemePreference): void {
    this.themeSvc.setPreference(pref);
  }

  toggleToast(): void {
    this.toastEnabled.update((v) => !v);
    this.savePrefs();
  }
  toggleBadge(): void {
    this.badgeEnabled.update((v) => !v);
    this.savePrefs();
  }

  private readPref(key: string, def: boolean): boolean {
    try {
      const raw = JSON.parse(localStorage.getItem(PREF_KEY) || '{}');
      return typeof raw[key] === 'boolean' ? raw[key] : def;
    } catch {
      return def;
    }
  }
  private savePrefs(): void {
    localStorage.setItem(
      PREF_KEY,
      JSON.stringify({ toast: this.toastEnabled(), badge: this.badgeEnabled() }),
    );
  }
}
