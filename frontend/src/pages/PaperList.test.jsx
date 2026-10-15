import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import PaperList from './PaperList.jsx';
import { api } from '../api.js';

vi.mock('../api.js', () => ({ api: { isSnapshot: true, dashboard: vi.fn(), papers: vi.fn(), search: vi.fn() } }));
const venues = Array.from({ length: 200 }, (_, i) => ({ abbr: `V${String(i).padStart(3, '0')}`, name: `Venue ${i}`, paper_count: 1 }));
beforeEach(() => {
  api.dashboard.mockResolvedValue({ directions: [], annual: [], venues, configured_venues: venues.length });
  api.papers.mockResolvedValue({ total: 0, items: [], page: 1, size: 20 });
});
function show(url = '/papers') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter initialEntries={[url]}><QueryClientProvider client={client}><PaperList /></QueryClientProvider></MemoryRouter>);
}

it('bounds first-page venue DOM while keeping the complete directory reachable', async () => {
  show();
  await screen.findByRole('button', { name: /^V000/ });
  const list = document.querySelector('.venue-filter-options');
  expect(within(list).getAllByRole('button')).toHaveLength(41);
  while (screen.queryByRole('button', { name: /继续显示来源/ })) fireEvent.click(screen.getByRole('button', { name: /继续显示来源/ }));
  expect(within(list).getAllByRole('button')).toHaveLength(201);
});

it('searches all sources rather than only the displayed preview', async () => {
  show(); await screen.findByRole('button', { name: /^V000/ });
  fireEvent.change(screen.getByRole('textbox', { name: '会议 / 期刊' }), { target: { value: 'V199' } });
  expect(await screen.findByRole('button', { name: /^V199/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^V000/ })).not.toBeInTheDocument();
});

it('keeps a selected source visible even when it lies outside the initial preview', async () => {
  show('/papers?venue=V199');
  expect(await screen.findByRole('button', { name: /^V199/ })).toHaveClass('selected');
  await waitFor(() => expect(within(document.querySelector('.venue-filter-options')).getAllByRole('button')).toHaveLength(42));
});
