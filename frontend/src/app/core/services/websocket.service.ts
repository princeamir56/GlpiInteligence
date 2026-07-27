import { Injectable, inject, signal } from '@angular/core';
import { environment } from '../../../environments/environment';
import { AuthService } from './auth.service';
import { NotificationService } from './notification.service';

export interface LiveAlert {
  id: string;
  severity: string;
  title: string;
  description?: string;
  timestamp?: string;
}

/**
 * Subscribes to WS /ws/alerts. Pushes each alert to a toast and keeps an
 * unread counter + recent-alerts buffer the header badge reads.
 */
@Injectable({ providedIn: 'root' })
export class WebsocketService {
  private auth = inject(AuthService);
  private notif = inject(NotificationService);

  readonly unread = signal(0);
  readonly alerts = signal<LiveAlert[]>([]);
  readonly connected = signal(false);

  private socket?: WebSocket;
  private reconnectTimer?: ReturnType<typeof setTimeout>;

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    const token = this.auth.accessToken();
    if (!token) return;

    const url = `${environment.wsBaseUrl}/ws/alerts?token=${encodeURIComponent(token)}`;
    try {
      this.socket = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.socket.onopen = () => this.connected.set(true);
    this.socket.onmessage = (ev) => this.handleMessage(ev.data);
    this.socket.onclose = () => {
      this.connected.set(false);
      this.scheduleReconnect();
    };
    this.socket.onerror = () => this.socket?.close();
  }

  disconnect(): void {
    clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = undefined;
    this.connected.set(false);
  }

  markAllRead(): void {
    this.unread.set(0);
  }

  private handleMessage(raw: string): void {
    let alert: LiveAlert;
    try {
      alert = JSON.parse(raw);
    } catch {
      return;
    }
    this.alerts.update((list) => [alert, ...list].slice(0, 50));
    const prefs = this.readPrefs();
    if (prefs.badge) this.unread.update((n) => n + 1);
    if (prefs.toast) {
      const icon = /crit/i.test(alert.severity) ? 'error' : 'warning';
      this.notif.toast(alert.title, icon);
    }
  }

  private readPrefs(): { toast: boolean; badge: boolean } {
    try {
      const raw = JSON.parse(localStorage.getItem('sartex.notif.prefs') || '{}');
      return {
        toast: raw.toast !== false,
        badge: raw.badge !== false,
      };
    } catch {
      return { toast: true, badge: true };
    }
  }

  private scheduleReconnect(): void {
    if (!this.auth.isAuthenticated()) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), 5000);
  }
}
