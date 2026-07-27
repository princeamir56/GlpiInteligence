import { TestBed } from '@angular/core/testing';
import { ScatterChartComponent } from './scatter-chart.component';
import { commonTestProviders } from '../../../testing/test-providers';

describe('ScatterChartComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ScatterChartComponent],
      providers: [commonTestProviders],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(ScatterChartComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
  });
});
