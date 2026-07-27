import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { TechniciensComponent } from './techniciens.component';
import { commonTestProviders } from '../../testing/test-providers';

describe('TechniciensComponent', () => {
  let fixture: ComponentFixture<TechniciensComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TechniciensComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(TechniciensComponent);
    fixture.detectChanges();
  });

  afterEach(() => {
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock.match(() => true).forEach((r) => r.flush([]));
    httpMock.verify();
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });
});
