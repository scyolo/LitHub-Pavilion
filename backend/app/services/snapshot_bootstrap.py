"""One compressed, independently verified startup read for the static site."""
import gzip


def write_snapshot_bootstrap(directory, manifest):
    from app.services.snapshot import _atomic_write, _json_bytes, _load_entry,MAX_FILE_BYTES

    _load_entry(directory, manifest['catalog'], 'catalog')
    raw = (directory / manifest['catalog']['path']).read_bytes()
    value={'manifest':manifest,'catalog_text':raw.decode('utf-8')}
    import json
    catalog=json.loads(raw)
    if catalog.get('reader',{}).get('version')==10:
        from app.services.snapshot_reader import read_compressed_asset
        _,reader=read_compressed_asset(directory,catalog['reader']['index'])
        value['reader_text']=reader.decode('utf-8')
    content = _json_bytes(value)
    compressed=gzip.compress(content,mtime=0)
    if len(content)>MAX_FILE_BYTES or len(compressed)>MAX_FILE_BYTES:
        raise ValueError('Startup snapshot exceeds the transfer limit')
    _atomic_write(directory / 'bootstrap.json.gz', compressed)
