import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DataTableComponent } from './data-table.component';
import { TableColumn } from './data-table.model';
import { commonTestProviders } from '../../../testing/test-providers';

describe('DataTableComponent', () => {
  let fixture: ComponentFixture<DataTableComponent>;
  const columns: TableColumn[] = [
    { key: 'name', label: 'Nom', sortable: true },
    { key: 'total', label: 'Total', type: 'number', sortable: true },
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DataTableComponent],
      providers: [commonTestProviders],
    }).compileComponents();
    fixture = TestBed.createComponent(DataTableComponent);
    fixture.componentInstance.columns = columns;
    fixture.componentInstance.rows = [
      { name: 'Alice', total: 10 },
      { name: 'Bob', total: 3 },
    ];
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should filter rows by the search term', () => {
    const cmp = fixture.componentInstance;
    expect(cmp.filtered().length).toBe(2);
    cmp.search.set('ali');
    expect(cmp.filtered().length).toBe(1);
    expect(cmp.filtered()[0]['name']).toBe('Alice');
  });

  it('should sort ascending then descending on a column', () => {
    const cmp = fixture.componentInstance;
    cmp.sortBy(columns[1]);
    expect(cmp.filtered()[0]['total']).toBe(3);
    cmp.sortBy(columns[1]);
    expect(cmp.filtered()[0]['total']).toBe(10);
  });
});
