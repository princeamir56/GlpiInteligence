import { Component, inject, signal, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { SidebarComponent } from '../sidebar/sidebar.component';
import { HeaderComponent } from '../header/header.component';
import { AuthService } from '../../core/services/auth.service';
import { WebsocketService } from '../../core/services/websocket.service';
import { NotificationService } from '../../core/services/notification.service';
import { Router } from '@angular/router';
import { routeFade } from '../../shared/animations';

const SIDEBAR_KEY = 'sartex.sidebar.collapsed';

@Component({
  selector: 'app-main-layout',
  standalone: true,
  imports: [RouterOutlet, SidebarComponent, HeaderComponent],
  templateUrl: './main-layout.component.html',
  styleUrl: './main-layout.component.css',
  animations: [routeFade],
})
export class MainLayoutComponent implements OnInit {
  private auth = inject(AuthService);
  private ws = inject(WebsocketService);
  private notif = inject(NotificationService);
  private router = inject(Router);

  readonly collapsed = signal(localStorage.getItem(SIDEBAR_KEY) === '1');

  ngOnInit(): void {
    // Load current user (if token present) and open the alerts socket.
    if (this.auth.isAuthenticated()) {
      this.auth.fetchMe().subscribe({ error: () => {} });
      this.ws.connect();
    }
  }

  toggleSidebar(): void {
    this.collapsed.update((v) => {
      const next = !v;
      localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0');
      return next;
    });
  }

  async logout(): Promise<void> {
    const ok = await this.notif.confirm('Se déconnecter ?', 'Vous devrez vous reconnecter pour accéder au tableau de bord.', 'Déconnexion');
    if (!ok) return;
    this.ws.disconnect();
    this.auth.logout();
    this.router.navigate(['/login']);
  }

  prepareRoute(outlet: RouterOutlet): unknown {
    if (!outlet?.isActivated) return '';
    return outlet.activatedRouteData?.['animation'] ?? outlet.activatedRoute;
  }
}
