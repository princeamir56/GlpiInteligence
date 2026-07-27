import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { Role } from '../models/auth.model';

/** Reads allowed roles from route.data.roles. Redirects to /dashboard if not permitted. */
export const roleGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const roles = (route.data?.['roles'] as Role[] | undefined) ?? [];
  if (roles.length === 0 || auth.hasRole(roles)) return true;
  return router.createUrlTree(['/dashboard']);
};
