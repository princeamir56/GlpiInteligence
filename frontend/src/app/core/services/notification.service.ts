import { Injectable } from '@angular/core';
import Swal, { SweetAlertResult } from 'sweetalert2';

/**
 * Wraps SweetAlert2 so components never touch Swal directly.
 * All popups reuse the theme tokens via customClass overrides in styles.css.
 */
@Injectable({ providedIn: 'root' })
export class NotificationService {
  private base = {
    buttonsStyling: false,
    customClass: {
      popup: 'sartex-popup',
      confirmButton: 'sartex-confirm-btn',
      cancelButton: 'sartex-cancel-btn',
    },
  };

  success(title: string, text?: string): Promise<SweetAlertResult> {
    return Swal.fire({ ...this.base, icon: 'success', title, text });
  }

  error(title: string, text?: string): Promise<SweetAlertResult> {
    return Swal.fire({ ...this.base, icon: 'error', title, text });
  }

  info(title: string, text?: string): Promise<SweetAlertResult> {
    return Swal.fire({ ...this.base, icon: 'info', title, text });
  }

  /** Returns true if the user confirmed. */
  async confirm(title: string, text?: string, confirmText = 'Confirmer'): Promise<boolean> {
    const res = await Swal.fire({
      ...this.base,
      icon: 'question',
      title,
      text,
      showCancelButton: true,
      confirmButtonText: confirmText,
      cancelButtonText: 'Annuler',
    });
    return res.isConfirmed;
  }

  /** Top-right auto-dismissing toast (used by WS alerts & quick confirmations). */
  toast(title: string, icon: 'success' | 'error' | 'warning' | 'info' = 'success', timer = 8000): void {
    Swal.fire({
      toast: true,
      position: 'top-end',
      icon,
      title,
      timer,
      timerProgressBar: true,
      showConfirmButton: false,
      customClass: { popup: 'sartex-toast' },
    });
  }
}
