"""Direct files for frequent terms avoid downloading unrelated hash neighbors."""
import json


def direct_token_assets(directory,search,emit):
    from app.services.snapshot import _json_bytes,MAX_FILE_BYTES
    from app.services.snapshot_reader import read_compressed_asset
    counts={}
    for entries in search['terms'].values():
        for entry in entries:
            _,raw=read_compressed_asset(directory,entry)
            for group in json.loads(raw):counts[group[0]]=counts.get(group[0],0)+len(group[1])
    eligible={token for token in sorted(counts,key=lambda token:(-counts[token],token))[:64]
              if counts[token]>=10000 and len(token)<=32}
    direct={}
    for section,prefix in [('terms','search'),('metadata','matchrank'),('hints','cardhint')]:
        table=search[section] if section=='terms' else search[section]['terms']
        for parts in table.values():
            groups=[]
            for part in parts:
                _,raw=read_compressed_asset(directory,part);groups.extend(json.loads(raw))
            if section=='hints':
                shared={row[0]:row for group in groups if group[0]=='$cards' for row in group[1]}
                values=[(group[0],[shared[pid] for pid in group[1]]) for group in groups if group[0]!='$cards']
            else:
                values=[(group[0],group) for group in groups]
            collected={}
            for token,value in values:collected.setdefault(token,[]).append(value)
            for token,values in collected.items():
                if section=='terms':
                    if token not in eligible:continue
                    # A small universal high-frequency tier bounds duplicate
                    # assets; all other terms use their complete hash buckets.
                    direct.setdefault(token,{})
                elif token not in direct:continue
                if section=='hints':values=[[token,[row for group in values for row in group]]]
                packed=[];rows=[];size=2
                for group in values:
                    added=len(_json_bytes(group))+1
                    if size+added>MAX_FILE_BYTES and rows:
                        packed.append(emit(prefix,_json_bytes(rows),len(rows)));rows=[];size=2
                    if added+2>MAX_FILE_BYTES:
                        raise ValueError('Direct token group exceeds asset limit')
                    rows.append(group);size+=added
                if rows:packed.append(emit(prefix,_json_bytes(rows),len(rows)))
                direct[token][section]=packed
    return direct
