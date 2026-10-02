import {render,screen,fireEvent} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter,Link} from 'react-router-dom';
import {it,expect,vi,beforeEach} from 'vitest';
import SourceCoverage from './SourceCoverage.jsx';
import {loadCoverage,loadAssociations} from '../data/source-coverage.js';
vi.mock('../data/source-coverage.js',()=>({loadCoverage:vi.fn(),loadAssociations:vi.fn()}));
beforeEach(()=>{loadCoverage.mockResolvedValue({snapshot_revision:'a'.repeat(64),snapshot_papers:100,snapshot_generated_at:'2026-10-01T00:00:00Z',configured_sources:2,direct_sources:0,represented_sources:1,sources:[{abbr:'Eurographics',name:'Eurographics Conference',type:'conf',level:'B',primary_count:0,associated_count:1,primary_years:{},associated_years:{'2024':1},status:'journal_linked',associations:{path:'sample',count:1}},{abbr:'Pending',name:'Pending Conference',type:'conf',level:'A',primary_count:0,associated_count:0,primary_years:{},associated_years:{},status:'unresolved'}]});loadAssociations.mockResolvedValue({papers:[{id:10,title:'Verified geometry paper',canonical_venue:'CGF',publication_year:2024,event_year:2024,official_url:'https://doi.org/10.1111/cgf.1',evidence_url:'https://publisher.example/toc'}]});});
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});return render(<QueryClientProvider client={client}><MemoryRouter><Link to="/coverage?source=Pending">切换来源书签</Link><SourceCoverage/></MemoryRouter></QueryClientProvider>);}
it('separates pending and journal-linked sources and opens the evidence list on demand',async()=>{mount();expect(await screen.findByRole('heading',{name:'Eurographics'})).toBeInTheDocument();expect(loadAssociations).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'查看 Eurographics 的期刊发表关联'}));expect(await screen.findByText('Verified geometry paper')).toBeInTheDocument();expect(screen.getByText(/原始发表来源：CGF/)).toBeInTheDocument();expect(screen.getByRole('link',{name:'官网目录证据'})).toHaveAttribute('href','https://publisher.example/toc');fireEvent.change(screen.getByLabelText('覆盖状态'),{target:{value:'unresolved'}});expect(screen.getByRole('heading',{name:'Pending'})).toBeInTheDocument();expect(screen.queryByRole('heading',{name:'Eurographics'})).not.toBeInTheDocument();});
it('shows a retryable error rather than fabricating counts',async()=>{loadCoverage.mockRejectedValueOnce(new Error('清单不可用'));mount();expect(await screen.findByText('清单不可用')).toBeInTheDocument();});

it('keeps source filters synchronized when a bookmarked URL changes',async()=>{mount();await screen.findByRole('heading',{name:'Eurographics'});fireEvent.change(screen.getByLabelText('搜索覆盖来源'),{target:{value:'Eurographics'}});fireEvent.click(screen.getByRole('link',{name:'切换来源书签'}));expect(screen.getByLabelText('搜索覆盖来源')).toHaveValue('Pending');expect(screen.queryByRole('heading',{name:'Eurographics'})).not.toBeInTheDocument();});


it('can filter zero-record years without equating them to absent publications',async()=>{
 const current=await loadCoverage();
 const indexed={abbr:'CompleteYears',name:'Year Records',type:'conf',level:'A',primary_count:4,associated_count:0,primary_years:{'2023':1,'2024':1,'2025':1,'2026':1},associated_years:{},status:'indexed'};
 loadCoverage.mockResolvedValue({...current,sources:[...current.sources,indexed],configured_sources:3});
 mount();await screen.findByRole('heading',{name:'CompleteYears'});
 fireEvent.change(screen.getByLabelText('覆盖状态'),{target:{value:'year_gaps'}});
 expect(screen.queryByRole('heading',{name:'CompleteYears'})).not.toBeInTheDocument();
 expect(screen.getByRole('heading',{name:'Eurographics'})).toBeInTheDocument();
 expect(screen.getByText(/零记录年份不等于缺失论文/)).toBeInTheDocument();
});
