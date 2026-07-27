import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { NotificationService } from '../services/notification.service';

/** Surfaces unexpected errors as a toast (401 is handled by refreshInterceptor). */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const notif = inject(NotificationService);

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      const silent = req.url.includes('/api/auth/login') || err.status === 401;
      if (!silent) {
        const msg =
          err.error?.detail ||
          err.error?.message ||
          err.message ||
          'Une erreur est survenue';
        notif.toast(typeof msg === 'string' ? msg : 'Erreur serveur', 'error');
      }
      return throwError(() => err);
    }),
  );
};
