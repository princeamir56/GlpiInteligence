import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';

/**
 * On a 401, tries a single token refresh and replays the request.
 * If refresh fails, logs out and redirects to /login.
 */
export const refreshInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const isAuthCall =
    req.url.includes('/api/auth/login') || req.url.includes('/api/auth/refresh');

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status !== 401 || isAuthCall || !auth.getRefreshToken()) {
        return throwError(() => err);
      }
      return auth.refresh().pipe(
        switchMap((token) => {
          const retried = req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
          return next(retried);
        }),
        catchError((refreshErr) => {
          auth.logout();
          router.navigate(['/login']);
          return throwError(() => refreshErr);
        }),
      );
    }),
  );
};
