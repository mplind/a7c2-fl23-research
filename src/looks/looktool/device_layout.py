"""Reviewed layouts, edited-byte checks, and independent custom tables.

Legacy jobs still record their complete source identities. First activation
checks its actual windows, and legacy code matching normalizes only reviewed
native FL23 updates. Desktop transactions use structural checks directly.

Every check and write is in the identified build's own addresses and bytes
(runtime_for). Functions given both programs identify the build from them
(buildprofile.identify) when no build is passed; the appFw.so-only checks
accept any supported build's bytes when none is passed.
"""
import hashlib,struct,json
from pathlib import Path
from . import buildprofile,firmware,six

CODE_SHA='5434cd40a746fef421fbe6825ebbdc1d41aa5304a686a162bb56378a6e94c4b5'  # Filled from the known complete v4 private fixture during build.

CONVERTER,CONVERTER_END=0x35287f0,0x3528874
TABLE_ADD=0x3528828  # every template's `add x0,x0,#table` (template offset 0x38)
PUBLIC_TABLE_ADD=bytes.fromhex('00f03d91')

def _candidates(build):
    """The builds an appFw.so-only check may match: `build`, or every supported build when None."""
    return (build,) if build is not None else buildprofile.BUILDS

def runtime():
    """runtime-v1.json as bundled: written for the public build. Use runtime_for(build) for another."""
    data=json.loads((Path(__file__).resolve().parents[1]/'assets/runtime-v1.json').read_text(encoding='utf-8'))
    if data['schema']!='a7c2-lut-runtime/1':raise ValueError('Unknown runtime patch schema')
    return data

def _retarget(template,build):
    """A public converter template with its look-table add re-encoded for `build`."""
    at=TABLE_ADD-CONVERTER
    if template[at:at+4]!=PUBLIC_TABLE_ADD:
        raise ValueError(f'Converter template has no public look-table add at {TABLE_ADD:#x}; no writes')
    return template[:at]+build.converter_add+template[at+4:]

def template_for(build,mask):
    """The converter template for slot `mask` on `build`: the bundled public template with the 4 bytes
    at template offset 0x38 (appFw.so 0x3528828) replaced by build.converter_add."""
    if type(mask) is not int or mask not in range(64):raise ValueError('Expected a six-slot bitmap')
    return _retarget(bytes.fromhex(runtime()['ap_templates'][mask]),build)

def runtime_for(build):
    """runtime() as `build` holds it: its own AP digests and CP code digest, its AP restore windows at
    its own addresses (the stock windows with its own stock bytes) and its converter templates.

    The bundled top-level values are the public build's; any other build has a "builds" entry. FL2/FL3's
    converter is self-contained, so the 'fl23' windows hold the same bytes in every build."""
    asset=runtime()
    own=asset.get('builds',{}).get(build.key)
    if own is None:
        own={spec['kind']+'_sha256':spec['sha256'] for spec in asset['ap_sources']}
        own['cp_code_sha256']=asset['cp_code_sha256']
    if own['stock_sha256']!=build.ap_sha256:raise ValueError('No custom-look runtime for '+build.key)
    sources=[]
    for spec in asset['ap_sources']:
        restore=[]
        for window in spec['restore']:
            at=buildprofile.translate(window['offset'],build);raw=bytes.fromhex(window['hex'])
            if spec['kind']=='stock':raw=buildprofile.stock(build,'appFw.so',at,len(raw))
            restore.append({'offset':at,'hex':raw.hex()})
        sources.append(dict(spec,sha256=own[spec['kind']+'_sha256'],restore=restore))
    return dict(asset,ap_templates=[_retarget(bytes.fromhex(t),build).hex() for t in asset['ap_templates']],
                ap_sources=sources,cp_code_sha256=own['cp_code_sha256'])

def _ap_target(source,mask,build):
    asset=runtime();result=bytearray(source)
    result[CONVERTER:CONVERTER_END]=template_for(build,mask)
    result[0x1b5cd7c:0x1b5cd80]=bytes.fromhex(asset['title_branch'])
    table=build.look_table;result[table:table+buildprofile.LOOK_TABLE_BYTES]=bytes.fromhex(asset['map'])
    for i in range(6):
        if mask&(1<<i):struct.pack_into('<I',result,0x59896f0+i*0xb8,0x0200ab2c+i)
    return bytes(result)

def identify_ap(ap,*,build=None):
    """The custom-look identity of appFw.so `ap` by whole-file digest, on `build` or on any supported
    build when None."""
    digest=firmware.sha(ap)
    if digest==six.AP_SHA:return {'kind':'legacy-six','mask':63,'label_ids':list(__import__(__package__+'.resources',fromlist=['LABEL_IDS']).LABEL_IDS)}
    for candidate in _candidates(build):
        asset=runtime_for(candidate)
        for spec in asset['ap_sources']:
            if len(ap)!=spec['bytes']:continue
            restored=bytearray(ap)
            for window in spec['restore']:
                at=window['offset'];raw=bytes.fromhex(window['hex']);restored[at:at+len(raw)]=raw
            if firmware.sha(restored)!=spec['sha256']:continue
            if digest==spec['sha256']:return {'kind':spec['kind'],'mask':0,'label_ids':list(range(0x0200ab2c,0x0200ab32)),'first_install':True}
            # Masks are checked against a complete rebuilt AP, not merely ignored.
            template=ap[CONVERTER:CONVERTER_END].hex();templates=asset['ap_templates']
            if template not in templates:continue
            mask=templates.index(template)
            if _ap_target(bytes(restored),mask,candidate)==ap:return {'kind':spec['kind']+'-lut','mask':mask,'label_ids':list(range(0x0200ab2c,0x0200ab32))}
    raise ValueError('Unsupported AP identity; no firmware/settings writes performed')

def code_hash(cp):
    cp=normalize_fl23_native(cp)
    start=six.TABLE_FILE+8;end=six.TABLE_FILE+32+6*six.TABLE_BYTES
    if len(cp)<end:raise ValueError('Truncated CP program')
    h=hashlib.sha256();h.update(cp[:start]);h.update(bytes(end-start));h.update(cp[end:]);return h.hexdigest()

def fl23_native_windows():
    """Reviewed native FL23 fields that remain independent of custom slots."""
    root=Path(__file__).resolve().parents[3]
    folder=root/'src/camera_runtime/assets'
    if not folder.is_dir():folder=root/'src/fl23/assets'
    manifest=json.loads((folder/'patches.json').read_text(encoding='utf-8'))[1]['writes']
    stock=next(s for s in runtime()['cp_sources'] if s['kind']=='stock')
    result=[]
    for w in manifest:
        at=int(w['file_offset'],16)
        if at not in (0x138832,0x1100b80):continue
        old,new=bytes.fromhex(w['before_hex']),bytes.fromhex(w['after_hex'])
        legacy=bytearray(old)
        for patch in stock['windows']:
            pos=patch['offset'];raw=bytes.fromhex(patch['after'])
            a,b=max(at,pos),min(at+len(old),pos+len(raw))
            if a<b:legacy[a-at:b-at]=raw[a-pos:b-pos]
        result.append((at,old,new,bytes(legacy)))
    return result

def normalize_fl23_native(cp):
    result=None
    for at,old,new,legacy in fl23_native_windows():
        if cp[at:at+len(new)] in (new,*fl23_previous_values(at)) and cp[at:at+len(new)]!=legacy:
            if result is None:result=bytearray(cp)
            result[at:at+len(new)]=legacy
    return bytes(result) if result is not None else cp


def fl23_previous_values(offset):
    """Known published native-field revisions, never full firmware admission."""
    path=Path(__file__).resolve().parents[3]/'src/camera_runtime/assets/fl23-native-history.json'
    if not path.is_file():return ()
    history=json.loads(path.read_text(encoding='utf-8'))
    if history.get('schema')!='a7c2-reviewed-fl23-native-history/1':raise ValueError('Unknown native FL23 migration data')
    if offset not in (0x138832,0x1100b80):return ()
    return tuple(bytes.fromhex(row['after_hex']) for row in history['windows'] if int(row['file_offset'],16)==offset)

def structural_ap(ap,*,build=None):
    """Recognize actual converter bytes/slot mask, without a file digest, on `build` or on any supported
    build when None."""
    template=ap[CONVERTER:CONVERTER_END].hex();assets=[runtime_for(b) for b in _candidates(build)]
    base='fl23' if ap[0x4b2ed19:0x4b2ed1b]==b'\x01\x01' else 'stock'
    labels=list(range(0x0200ab2c,0x0200ab32))
    for asset in assets:
        if template in asset['ap_templates']:
            return {'kind':base+'-lut','mask':asset['ap_templates'].index(template),'label_ids':labels}
    legacy=bytes.fromhex('e1000035002800511f1400718800005400e4031140000039c0035fd63f2c007188020054800000100048613840000039c0035fd600030201100f1112050d13141f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d51f2003d5')
    if ap[0x3528804:0x3528874]==legacy:
        from .resources import LABEL_IDS
        return {'kind':'legacy-six','mask':63,'label_ids':list(LABEL_IDS)}
    for asset in assets:
        spec=next(s for s in asset['ap_sources'] if s['kind']==base)
        converter=next(w for w in spec['restore'] if w['offset']==CONVERTER)
        raw=bytes.fromhex(converter['hex'])
        if ap[converter['offset']:converter['offset']+len(raw)]==raw:
            return {'kind':base,'mask':0,'label_ids':labels,'first_install':True}
    raise ValueError('Custom-slot converter bytes conflict; no writes')

def structural(ap,cp,*,build=None):
    build=buildprofile.build_of(ap,cp,build)
    identity=structural_ap(ap,build=build)
    from . import photoio
    photo=photoio.inspect(cp)
    if not identity.get('first_install'):
        if len(cp)<six.TABLE_FILE+32+6*six.TABLE_BYTES or struct.unpack_from('<2I',cp,six.TABLE_FILE)!=(six.MAGIC,six.VERSION):
            raise ValueError('Custom table header/size differs')
    return dict(identity,layout='full7-v4' if identity['kind']=='legacy-six' else 'standalone-v1',
                native_photo=photo)

def tables(cp):
    """Read native-grid payloads, without comparing source table digests."""
    if len(cp)<six.TABLE_FILE+32+6*six.TABLE_BYTES or struct.unpack_from('<2I',cp,six.TABLE_FILE)!=(six.MAGIC,six.VERSION):
        raise ValueError('Custom table header/size differs')
    return [cp[six.TABLE_FILE+32+i*six.TABLE_BYTES:six.TABLE_FILE+32+(i+1)*six.TABLE_BYTES] for i in range(6)]


def same_selected_programs(expected,actual,slot):
    """Post-reload only: permit later data updates to the other five slots.

    AP and every CP byte outside the explicit per-slot data remain exact.
    This never relaxes pre-write checks or immediate installation readback.
    """
    from . import photoio,photobuild,photobasis
    if actual['appFw.so']!=expected['appFw.so']:return False
    before,current=expected['cpapp-b.bin'],actual['cpapp-b.bin']
    if len(before)!=len(current):return False
    try:
        tables(before);tables(current)
        a,b=photoio.inspect(before),photoio.inspect(current)
    except (ValueError,struct.error):return False
    if (a is None)!=(b is None):return False
    result=bytearray(current)
    if a is not None:
        if (a['mask']^b['mask'])&(1<<(slot-1)):return False
        at=photobuild.DATA_FILE+8;result[at:at+4]=before[at:at+4]
    for other in range(1,7):
        if other==slot:continue
        for at,size in [(six.TABLE_FILE+8+(other-1)*4,4),
                        (six.TABLE_FILE+32+(other-1)*six.TABLE_BYTES,six.TABLE_BYTES)]:
            result[at:at+size]=before[at:at+size]
        if a is not None:
            at=photobuild.PARAMS_VA-photobuild.BASE+(other-1)*photobasis.STRIDE
            result[at:at+photobasis.STRIDE]=before[at:at+photobasis.STRIDE]
    return result==before

def identify(ap,cp,*,build=None):
    from . import photoio
    build=buildprofile.build_of(ap,cp,build)
    if photoio.present(cp):return structural(ap,cp,build=build)
    a=identify_ap(ap,build=build);c=firmware.sha(cp);asset=runtime_for(build)
    if a['kind']=='legacy-six':
        if code_hash(cp)!=CODE_SHA:raise ValueError('Unsupported legacy CP code identity')
        six.read_tables(cp)
    elif a.get('first_install'):
        spec=next((s for s in asset['cp_sources'] if s['kind']==a['kind']),None)
        if spec is None or len(cp)!=spec['bytes']:raise ValueError('First import needs matching A7C II 2.01 program extents')
        # FL23 curve improvements change its full CP digest. Admission uses
        # the identified AP and every actual CP window we will replace.
        for w in spec['windows']:
            at=w['offset'];old=bytes.fromhex(w['before'])
            if cp[at:at+len(old)]!=old:raise ValueError('First-import CP window conflicts at '+hex(at))
    else:
        if code_hash(cp)!=asset['cp_code_sha256']:raise ValueError('Unsupported standalone CP code identity')
        six.read_tables(cp)
    return dict(a,layout='full7-v4' if a['kind']=='legacy-six' else 'standalone-v1',AP=firmware.sha(ap),CP=c,
        physical_first_install_tested=False if a['kind']!='legacy-six' else None)

def replace(ap,cp,replacements,*,hash_checks=True,native_photo=None,native_bank=None,transitions=True,build=None):
    build=buildprofile.build_of(ap,cp,build)
    identify_current=identify if hash_checks else structural
    identity=identify_current(ap,cp,build=build)
    if not replacements or any(type(s) is not int or s not in range(1,7) for s in replacements):raise ValueError('Select custom slots 1..6')
    result=bytearray(cp);spans=[];ap_result=ap;ap_spans=[]
    if identity.get('first_install'):
        spec=next(s for s in runtime()['cp_sources'] if s['kind']==identity['kind'])
        for w in spec['windows']:
            at=w['offset'];old,new=bytes.fromhex(w['before']),bytes.fromhex(w['after'])
            if cp[at:at+len(old)]!=old:raise ValueError('Bootstrap source window differs')
            result[at:at+len(new)]=new
        # The final code/layout check below also permits the reviewed updated
        # native FL23 curves. Do not reject them with the old full-file digest.
    if identity['kind']!='legacy-six':
        source=bytearray(ap)
        spec=next(s for s in runtime_for(build)['ap_sources'] if identity['kind'].startswith(s['kind']))
        for w in spec['restore']:
            raw=bytes.fromhex(w['hex']);source[w['offset']:w['offset']+len(raw)]=raw
        mask=identity['mask']|sum(1<<(s-1) for s in replacements)
        ap_result=_ap_target(bytes(source),mask,build)
        ap_spans=[(w['offset'],len(bytes.fromhex(w['hex']))) for w in spec['restore']]
    for slot,raw in sorted(replacements.items()):
        six.decode(raw);at=six.TABLE_FILE+32+(slot-1)*six.TABLE_BYTES;check=six.TABLE_FILE+8+(slot-1)*4
        result[at:at+six.TABLE_BYTES]=raw;struct.pack_into('<I',result,check,six.fnv(raw));spans.extend([(at,six.TABLE_BYTES),(check,4)])
    if identity.get('first_install') and transitions:
        # Derive disjoint bounded windows including bootstrap and user data.
        # Only the transitions use them: this byte loop over the CP is slow.
        spans=[];start=None;last=None
        for at,(a,b) in enumerate(zip(cp,result)):
            if a!=b:
                if start is None:start=at
                elif at-last>16 or at-start>=4096:spans.append((start,last-start+1));start=at
                last=at
        if start is not None:spans.append((start,last-start+1))
    from . import photoio
    stages={slot:(native_photo or {}).get(slot) for slot in replacements}
    if photoio.present(cp) or any(value is not None for value in stages.values()):
        result=photoio.update(bytes(result),stages,native_bank,allocation_proved=True)
        from .checkpointworker import differences
        spans=[(at,len(old)) for at,old,_ in differences(cp,result)]
    after={'appFw.so':ap_result,'cpapp-b.bin':bytes(result)};before={'appFw.so':ap,'cpapp-b.bin':cp}
    identify_current(after['appFw.so'],after['cpapp-b.bin'],build=build)
    if not transitions:return None,None,after
    regions={'appFw.so':ap_spans,'cpapp-b.bin':spans}
    f=firmware.transition(before,after,regions)
    r=firmware.transition(after,before,regions)
    if firmware.apply(after,r,hash_checks=hash_checks)!=before:raise ValueError('Complete table inverse differs')
    return f,r,after

def before_first_table(ap,cp,slot,*,hash_checks=True,build=None):
    """Dormant canonical data for a slot that originally used native looks."""
    identity=(identify if hash_checks else structural)(ap,cp,build=build)
    read_tables=six.read_tables if hash_checks else tables
    if not identity.get('first_install'):return read_tables(cp)[slot-1]
    result=bytearray(cp)
    spec=next(s for s in runtime()['cp_sources'] if s['kind']==identity['kind'])
    for w in spec['windows']:
        raw=bytes.fromhex(w['after']);result[w['offset']:w['offset']+len(raw)]=raw
    return read_tables(bytes(result))[slot-1]

def deactivate(ap,cp,slot,raw,*,hash_checks=True,native_bank=None,transitions=True,build=None):
    """Restore one native custom slot, retaining other LUTs and current FL23.

    Mask zero leaves the shared CP runtime dormant. The independent recovery
    tool removes shared programs when the owner wants a full rollback.
    """
    build=buildprofile.build_of(ap,cp,build)
    identify_current=identify if hash_checks else structural
    identity=identify_current(ap,cp,build=build)
    if identity['kind']=='legacy-six':raise ValueError('First-activation undo requires the standalone slot layout')
    spec=next(s for s in runtime_for(build)['ap_sources'] if identity['kind'].startswith(s['kind']))
    base=bytearray(ap)
    for w in spec['restore']:
        value=bytes.fromhex(w['hex']);base[w['offset']:w['offset']+len(value)]=value
    after_ap=_ap_target(bytes(base),identity['mask']&~(1<<(slot-1)),build)
    six.decode(raw);result=bytearray(cp)
    at=six.TABLE_FILE+32+(slot-1)*six.TABLE_BYTES;check=six.TABLE_FILE+8+(slot-1)*4
    result[at:at+six.TABLE_BYTES]=raw;struct.pack_into('<I',result,check,six.fnv(raw))
    from . import photoio
    result=photoio.update(bytes(result),{slot:None},native_bank)
    before={'appFw.so':ap,'cpapp-b.bin':cp};after={'appFw.so':after_ap,'cpapp-b.bin':bytes(result)}
    if not transitions:
        identify_current(after_ap,bytes(result),build=build)
        return None,None,after
    from .checkpointworker import differences
    regions={'appFw.so':[(w['offset'],len(bytes.fromhex(w['hex']))) for w in spec['restore']],
        'cpapp-b.bin':[(offset,len(old)) for offset,old,_ in differences(cp,result)]}
    forward,reverse=firmware.transition(before,after,regions),firmware.transition(after,before,regions)
    identify_current(after_ap,after['cpapp-b.bin'],build=build)
    return forward,reverse,after
