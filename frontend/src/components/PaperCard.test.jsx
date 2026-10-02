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
