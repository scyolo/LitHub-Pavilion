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

it('includes official affiliations when a linked source is chosen and exposes the scope control', async () => {
  api.dashboard.mockResolvedValue({directions: [], annual: [], configured_venues: 1,
    venues: [{abbr: 'VIS', name: 'Visualization', paper_count: 0, associated_paper_count: 12}]});
  show();
  fireEvent.click(await screen.findByRole('button', {name: /^VIS/}));
  await waitFor(() => expect(api.papers).toHaveBeenCalledWith(expect.objectContaining({venue: 'VIS', include_associated: '1'}), expect.anything()));
  expect(screen.getByRole('checkbox', {name: '包含官方期刊发表关联'})).toBeChecked();
  expect(screen.getByText(/关联论文按期刊发表年份筛选/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: /^全部来源/}));
  await waitFor(() => expect(api.papers.mock.calls.at(-1)[0]).not.toHaveProperty('include_associated'));
});

it('shows a verified accepted paper without calling it a published result or an empty search', async () => {
  api.search.mockResolvedValue({total: 0, items: [], page: 1, size: 20,
    accepted_items: [{reference_id: 'accepted-example', title: 'Future LLM Serving', venue: 'ATC', year: 2026,
      level: 'A', authors: ['Ada Lee'], official_url: 'https://example.org/accepted', preprint_url: null}]});
  show('/papers?q=Future+LLM+Serving');
  expect(await screen.findByRole('link', {name: 'Future LLM Serving'})).toHaveAttribute('href', 'https://example.org/accepted');
  expect(screen.getByText('官方已录用 · 出版待核验')).toBeInTheDocument();
  expect(screen.getByText(/上方录用记录不计入正式论文总数/)).toBeInTheDocument();
  expect(screen.queryByText('清除所有筛选')).not.toBeInTheDocument();
});
