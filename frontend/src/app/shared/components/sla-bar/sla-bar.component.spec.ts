import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SlaBarComponent } from './sla-bar.component';

describe('SlaBarComponent', () => {
  let fixture: ComponentFixture<SlaBarComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [SlaBarComponent] }).compileComponents();
    fixture = TestBed.createComponent(SlaBarComponent);
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should classify thresholds (good/warn/bad) and clamp to 0-100', () => {
    const cmp = fixture.componentInstance;
    cmp.value = 95;
    expect(cmp.tone()).toBe('good');
    cmp.value = 75;
    expect(cmp.tone()).toBe('warn');
    cmp.value = 40;
    expect(cmp.tone()).toBe('bad');
    cmp.value = 150;
    expect(cmp.pct()).toBe(100);
  });
});
