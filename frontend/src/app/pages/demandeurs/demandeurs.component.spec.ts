import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { DemandeursComponent } from './demandeurs.component';
import { commonTestProviders } from '../../testing/test-providers';

describe('DemandeursComponent', () => {
  let fixture: ComponentFixture<DemandeursComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DemandeursComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(DemandeursComponent);
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
