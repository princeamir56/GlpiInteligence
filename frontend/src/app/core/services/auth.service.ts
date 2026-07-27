import { Injectable, inject, signal, computed } from '@angular/core';
import { Observable, tap, map } from 'rxjs';
import { ApiService } from './api.service';
import { CurrentUser, LoginRequest, Role, TokenResponse } from '../models/auth.model';

const ACCESS_KEY = 'sartex.access_token';
const REFRESH_KEY = 'sartex.refresh_token';
const ROLE_KEY = 'sartex.role';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private api = inject(ApiService);

  readonly accessToken = signal<string | null>(localStorage.getItem(ACCESS_KEY));
  readonly role = signal<Role | null>(localStorage.getItem(ROLE_KEY) as Role | null);
  readonly currentUser = signal<CurrentUser | null>(null);
  readonly isAuthenticated = computed(() => !!this.accessToken());

  login(credentials: LoginRequest): Observable<TokenResponse> {
    return this.api.post<TokenResponse>('/api/auth/login', credentials).pipe(
      tap((res) => this.storeTokens(res)),
    );
  }

  refresh(): Observable<string> {
    const refreshToken = localStorage.getItem(REFRESH_KEY);
    return this.api
      .post<TokenResponse>('/api/auth/refresh', { refresh_token: refreshToken })
      .pipe(
        tap((res) => this.storeTokens(res)),
        map((res) => res.access_token),
      );
  }

  fetchMe(): Observable<CurrentUser> {
    return this.api.get<CurrentUser>('/api/auth/me').pipe(
      tap((user) => {
        this.currentUser.set(user);
        if (user.role) {
          this.role.set(user.role);
          localStorage.setItem(ROLE_KEY, user.role);
        }
      }),
    );
  }

  logout(): void {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(ROLE_KEY);
    this.accessToken.set(null);
    this.role.set(null);
    this.currentUser.set(null);
  }

  hasRole(roles: Role[]): boolean {
    const r = this.role();
    return !!r && roles.includes(r);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  }

  private storeTokens(res: TokenResponse): void {
    localStorage.setItem(ACCESS_KEY, res.access_token);
    if (res.refresh_token) localStorage.setItem(REFRESH_KEY, res.refresh_token);
    if (res.role) {
      localStorage.setItem(ROLE_KEY, res.role);
      this.role.set(res.role);
    }
    this.accessToken.set(res.access_token);
  }
}
