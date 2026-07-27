import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

/**
 * Thin HttpClient wrapper that prefixes the API base URL and normalises
 * query params (dropping null/undefined). Interceptors handle auth & errors.
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  readonly baseUrl = environment.apiBaseUrl;

  get<T>(path: string, params?: Record<string, unknown>): Observable<T> {
    return this.http.get<T>(this.url(path), { params: this.toParams(params) });
  }

  post<T>(path: string, body?: unknown, params?: Record<string, unknown>): Observable<T> {
    return this.http.post<T>(this.url(path), body ?? {}, { params: this.toParams(params) });
  }

  private url(path: string): string {
    return `${this.baseUrl}${path.startsWith('/') ? path : '/' + path}`;
  }

  private toParams(params?: Record<string, unknown>): HttpParams {
    let hp = new HttpParams();
    if (!params) return hp;
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== '') {
        hp = hp.set(key, String(value));
      }
    }
    return hp;
  }
}
