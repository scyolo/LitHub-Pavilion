import { describe,it,expect } from 'vitest';
import { validateCoverage,validateAssociations,loadAssociations } from './source-coverage.js';
const hash='a'.repeat(64);
const source={abbr:'EG',name:'Eurographics',type:'conf',level:'B',primary_count:0,associated_count:1,primary_years:{},associated_years:{'2024':1},status:'journal_linked',associations:{path:'coverage/associations-'+hash+'.json',sha256:hash,count:1}};
export const fixture=()=>({version:1,generated_at:'2026-10-01T00:00:00Z',snapshot_generated_at:'2026-10-01T00:00:00Z',snapshot_revision:hash,snapshot_papers:1,configured_sources:1,direct_sources:0,represented_sources:1,full_coverage_verified:false,sources:[structuredClone(source)]});
it('preserves separate canonical and associated source counts',()=>{expect(validateCoverage(fixture()).sources[0].associated_count).toBe(1);});
it('rejects fabricated coverage totals and unsafe descriptors',()=>{let v=fixture();v.represented_sources=2;expect(()=>validateCoverage(v)).toThrow();v=fixture();v.sources[0].associations.path='../private';expect(()=>validateCoverage(v)).toThrow();});
it('rejects unsafe official links and revision mismatch',()=>{const data={version:1,venue:'EG',snapshot_revision:hash,papers:[{id:1,title:'Geometry',doi:'10.1111/cgf.1',canonical_venue:'CGF',publication_year:2024,event_year:2024,official_url:'javascript:alert(1)',evidence_url:'https://publisher.example/toc'}]};expect(()=>validateAssociations(data,source,hash)).toThrow();data.papers[0].official_url='https://doi.org/10.1111/cgf.1';expect(validateAssociations(data,source,hash).papers).toHaveLength(1);expect(()=>validateAssociations(data,source,'b'.repeat(64))).toThrow();});
it('checks a descriptor hash before using remote association data',async()=>{await expect(loadAssociations(source,hash,undefined,async()=>new Response('{}'))).rejects.toThrow();});

it('rejects unsafe optional evidence-note links',()=>{const v=fixture();v.sources[0].note='Source history';v.sources[0].evidence_url='javascript:bad()';expect(()=>validateCoverage(v)).toThrow();});
