import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { RepetitifsComponent } from './repetitifs.component';
import { commonTestProviders } from '../../testing/test-providers';

describe('RepetitifsComponent', () => {
  let fixture: ComponentFixture<RepetitifsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RepetitifsComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(RepetitifsComponent);
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
