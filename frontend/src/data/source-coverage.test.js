import { describe,it,expect } from 'vitest';
import { validateCoverage,validateAssociations,loadAssociations,zeroYearChecks } from './source-coverage.js';
const hash='a'.repeat(64);
const source={abbr:'EG',name:'Eurographics',type:'conf',level:'B',primary_count:0,associated_count:1,primary_years:{},associated_years:{'2024':1},status:'journal_linked',associations:{path:'coverage/associations-'+hash+'.json',sha256:hash,count:1}};
export const fixture=()=>({version:1,generated_at:'2026-10-01T00:00:00Z',snapshot_generated_at:'2026-10-01T00:00:00Z',snapshot_revision:hash,snapshot_papers:1,configured_sources:1,direct_sources:0,represented_sources:1,full_coverage_verified:false,sources:[structuredClone(source)]});
it('preserves separate canonical and associated source counts',()=>{expect(validateCoverage(fixture()).sources[0].associated_count).toBe(1);});
it('rejects fabricated coverage totals and unsafe descriptors',()=>{let v=fixture();v.represented_sources=2;expect(()=>validateCoverage(v)).toThrow();v=fixture();v.sources[0].associations.path='../private';expect(()=>validateCoverage(v)).toThrow();});
it('rejects unsafe official links and revision mismatch',()=>{const data={version:1,venue:'EG',snapshot_revision:hash,papers:[{id:1,title:'Geometry',doi:'10.1111/cgf.1',canonical_venue:'CGF',publication_year:2024,event_year:2024,official_url:'javascript:alert(1)',evidence_url:'https://publisher.example/toc'}]};expect(()=>validateAssociations(data,source,hash)).toThrow();data.papers[0].official_url='https://doi.org/10.1111/cgf.1';expect(validateAssociations(data,source,hash).papers).toHaveLength(1);expect(()=>validateAssociations(data,source,'b'.repeat(64))).toThrow();});
it('checks a descriptor hash before using remote association data',async()=>{await expect(loadAssociations(source,hash,undefined,async()=>new Response('{}'))).rejects.toThrow();});

it('rejects unsafe optional evidence-note links',()=>{const v=fixture();v.sources[0].note='Source history';v.sources[0].evidence_url='javascript:bad()';expect(()=>validateCoverage(v)).toThrow();});

function withYearEvidence(){
 const v=fixture();
 v.sources[0].year_checks={
  '2023':{status:'not_scheduled',note:'Official calendar.',checked_at:'2026-10-21',evidence_url:'https://publisher.example/calendar'},
  '2025':{status:'unverified',note:'No verified explanation.'},
  '2026':{status:'unverified',note:'No verified explanation.'},
 };
 v.zero_source_year_units=3;
 v.zero_year_status_counts={not_scheduled:1,unverified:2};
 return v;
}
it('counts explained zeros and keeps legacy manifests usable',()=>{
 expect(Object.keys(zeroYearChecks(fixture().sources[0]))).toEqual(['2023','2025','2026']);
 expect(validateCoverage(withYearEvidence()).zero_source_year_units).toBe(3);
});
it.each([
 v=>{v.zero_source_year_units=2;},
 v=>{v.zero_year_status_counts.unverified=1;},
 v=>{delete v.sources[0].year_checks['2025'];},
 v=>{v.sources[0].year_checks['2024']=v.sources[0].year_checks['2023'];},
 v=>{v.sources[0].year_checks['2023'].status='complete';},
 v=>{v.sources[0].year_checks['2023'].checked_at='2026-02-30';},
 v=>{v.sources[0].year_checks['2023'].evidence_url='javascript:bad()';},
 v=>{v.sources[0].year_checks['2023'].canonical_venue='Outside';},
])('rejects misleading or unsafe year evidence',change=>{
 const v=withYearEvidence();change(v);expect(()=>validateCoverage(v)).toThrow();
});
