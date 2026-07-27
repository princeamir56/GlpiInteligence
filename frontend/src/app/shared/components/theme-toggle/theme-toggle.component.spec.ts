import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ThemeToggleComponent } from './theme-toggle.component';
import { ThemeService } from '../../../core/services/theme.service';
import { commonTestProviders } from '../../../testing/test-providers';

describe('ThemeToggleComponent', () => {
  let fixture: ComponentFixture<ThemeToggleComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ThemeToggleComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(ThemeToggleComponent);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should flip the resolved theme when toggled', () => {
    const theme = TestBed.inject(ThemeService);
    fixture.detectChanges(); // flush the initial apply() effect
    const before = theme.resolved();
    fixture.componentInstance.toggle();
    fixture.detectChanges(); // flush the effect triggered by the preference change
    expect(theme.resolved()).not.toBe(before);
  });
});
