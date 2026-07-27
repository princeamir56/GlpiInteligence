import { AfterViewInit, Directive, ElementRef, Input, inject } from '@angular/core';

/**
 * Applies a staggered fade-up to the direct children of the host element.
 * Lightweight alternative to the Angular animation trigger for static lists.
 */
@Directive({
  selector: '[appStagger]',
  standalone: true,
})
export class StaggerDirective implements AfterViewInit {
  @Input() staggerDelay = 60;
  @Input() staggerDuration = 360;

  private el = inject(ElementRef<HTMLElement>).nativeElement as HTMLElement;

  ngAfterViewInit(): void {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const children = Array.from(this.el.children) as HTMLElement[];
    children.forEach((child, i) => {
      child.style.opacity = '0';
      child.style.transform = 'translateY(14px)';
      child.style.transition = `opacity ${this.staggerDuration}ms cubic-bezier(0.16,1,0.3,1) ${
        i * this.staggerDelay
      }ms, transform ${this.staggerDuration}ms cubic-bezier(0.16,1,0.3,1) ${i * this.staggerDelay}ms`;
      requestAnimationFrame(() => {
        child.style.opacity = '1';
        child.style.transform = 'translateY(0)';
      });
    });
  }
}
