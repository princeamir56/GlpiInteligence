import { Component, EventEmitter, Output, inject, signal, HostListener } from '@angular/core';
import { NgIf } from '@angular/common';
import { Router, NavigationEnd, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { filter } from 'rxjs';
import { LucideAngularModule } from 'lucide-angular';
import { ThemeToggleComponent } from '../../shared/components/theme-toggle/theme-toggle.component';
import { AuthService } from '../../core/services/auth.service';
import { WebsocketService } from '../../core/services/websocket.service';
import { NAV_ITEMS, FOOTER_NAV } from '../nav.config';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [NgIf, FormsModule, RouterLink, LucideAngularModule, ThemeToggleComponent],
  templateUrl: './header.component.html',
  styleUrl: './header.component.css',
})
export class HeaderComponent {
  @Output() toggleSidebar = new EventEmitter<void>();
  @Output() logout = new EventEmitter<void>();

  private router = inject(Router);
  private auth = inject(AuthService);
  private ws = inject(WebsocketService);

  readonly title = signal('Tableau de bord');
  readonly search = signal('');
  readonly menuOpen = signal(false);
  readonly unread = this.ws.unread;

  constructor() {
    const all = [...NAV_ITEMS, ...FOOTER_NAV];
    this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => {
        const item = all.find((n) => e.urlAfterRedirects.startsWith(n.path));
        this.title.set(item?.label ?? 'Tableau de bord');
      });
  }

  get user() {
    return this.auth.currentUser();
  }
  get role() {
    return this.auth.role();
  }

  submitSearch(value: string): void {
    const q = value.trim().toLowerCase();
    if (!q) return;
    // Stub: route to the tab whose name best matches the query.
    const tabs = ['demandeurs', 'services', 'sites', 'repetitifs', 'techniciens', 'categories', 'dashboard'];
    const match = tabs.find((t) => t.startsWith(q)) ?? 'dashboard';
    this.router.navigate(['/' + match]);
  }

  clearBadge(): void {
    this.ws.markAllRead();
  }

  toggleMenu(): void {
    this.menuOpen.update((v) => !v);
  }

  @HostListener('document:click', ['$event'])
  onDocClick(ev: MouseEvent): void {
    if (!(ev.target as HTMLElement).closest('.user-menu')) this.menuOpen.set(false);
  }
}
