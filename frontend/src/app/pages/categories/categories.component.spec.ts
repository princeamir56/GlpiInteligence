import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { CategoriesComponent } from './categories.component';
import { commonTestProviders } from '../../testing/test-providers';

describe('CategoriesComponent', () => {
  let fixture: ComponentFixture<CategoriesComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CategoriesComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(CategoriesComponent);
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
