import { TestBed } from '@angular/core/testing';
import { TabScaffoldComponent } from './tab-scaffold.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('TabScaffoldComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TabScaffoldComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(TabScaffoldComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should render the title and show the error state when error=true', () => {
    const fixture = TestBed.createComponent(TabScaffoldComponent);
    fixture.componentInstance.title = 'Demandeurs';
    fixture.componentInstance.error = true;
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('h1')?.textContent).toContain('Demandeurs');
    expect(el.querySelector('.state')).toBeTruthy();
  });
});
