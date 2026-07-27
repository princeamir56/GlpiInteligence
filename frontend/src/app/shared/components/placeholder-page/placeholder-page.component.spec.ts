import { TestBed } from '@angular/core/testing';
import { PlaceholderPageComponent } from './placeholder-page.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('PlaceholderPageComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PlaceholderPageComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(PlaceholderPageComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });
});
