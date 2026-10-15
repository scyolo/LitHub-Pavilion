import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import PaperCard from './PaperCard.jsx';

afterEach(cleanup);
const paper = { id: 1, title: 'Paper with multiple resources', venue: 'ICML', level: 'A', year: 2025, venue_confirmed: true, official_url: 'https://proceedings.mlr.press/v1/paper.html', oa_url: 'https://arxiv.org/abs/2501.00001' };

it('shows distinct official and open access resources together', () => {
  render(<MemoryRouter><PaperCard paper={paper} /></MemoryRouter>);
  const resources = screen.getAllByRole('link').filter((link) => link.target === '_blank');
  expect(resources.map((link) => link.href)).toEqual([paper.official_url, paper.oa_url]);
});

it('does not duplicate the same official and open access resource', () => {
  render(<MemoryRouter><PaperCard paper={{ ...paper, oa_url: paper.official_url }} /></MemoryRouter>);
  expect(screen.getAllByRole('link').filter((link) => link.target === '_blank')).toHaveLength(1);
});

it('always offers a clearly labelled discovery route when no direct paper URL is known', () => {
  render(<MemoryRouter><PaperCard paper={{ ...paper, official_url: null, oa_url: null, title: 'A & B: "Exact title"' }} /></MemoryRouter>);
  const link = screen.getByRole('link', { name: /查找原文/ });
  expect(new URL(link.href).searchParams.get('q')).toBe('"A & B: "Exact title""');
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  expect(screen.queryByText('开放获取')).not.toBeInTheDocument();
});
