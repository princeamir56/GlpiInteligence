import { Directive, ElementRef, Input, OnChanges, OnDestroy, inject } from '@angular/core';

/**
 * Animates an element's text from 0 to [countUp] over ~800ms with easing,
 * starting when it first scrolls into view. Respects prefers-reduced-motion.
 */
@Directive({
  selector: '[countUp]',
  standalone: true,
})
export class CountUpDirective implements OnChanges, OnDestroy {
  @Input('countUp') value = 0;
  @Input() duration = 800;
  @Input() decimals = 0;
  @Input() suffix = '';
  @Input() prefix = '';

  private el = inject(ElementRef<HTMLElement>).nativeElement as HTMLElement;
  private frame?: number;
  private observer?: IntersectionObserver;
  private hasRun = false;

  ngOnChanges(): void {
    if (this.hasRun) {
      this.render(this.value); // update instantly on data changes after first run
      return;
    }
    this.observer?.disconnect();
    this.observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        this.observer?.disconnect();
        this.animate();
      }
    });
    this.observer.observe(this.el);
  }

  private animate(): void {
    this.hasRun = true;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || this.duration <= 0) {
      this.render(this.value);
      return;
    }
    const start = performance.now();
    const from = 0;
    const to = this.value;
    const ease = (t: number) => 1 - Math.pow(1 - t, 3); // easeOutCubic

    const step = (now: number) => {
      const t = Math.min((now - start) / this.duration, 1);
      this.render(from + (to - from) * ease(t));
      if (t < 1) this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);
  }

  private render(v: number): void {
    const n = v.toLocaleString('fr-FR', {
      minimumFractionDigits: this.decimals,
      maximumFractionDigits: this.decimals,
    });
    this.el.textContent = `${this.prefix}${n}${this.suffix}`;
  }

  ngOnDestroy(): void {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.observer?.disconnect();
  }
}
