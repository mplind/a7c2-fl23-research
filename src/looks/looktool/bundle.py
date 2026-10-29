"""Compose FL23, selected compiled looks and native sound into one write plan."""
import copy
import importlib.util
from pathlib import Path
import shutil
from . import lookfile, nativebuild, resources


def documents(options, destination=None):
    options = copy.deepcopy(options)
    resets=options.get('reset_slots',[])
    if not isinstance(resets,list) or any(type(s) is not int or s not in range(1,7) for s in resets) or len(set(resets))!=len(resets):
        raise ValueError('Choose distinct reset slots 1..6')
    selected, seen = [], set(resets)
    for row in options.get('looks', []):
        slot = row.get('slot')
        if type(slot) is not int or slot not in range(1, 7) or slot in seen:
            raise ValueError('Choose distinct custom slots 1..6')
        seen.add(slot)
        path = Path(row['path']).resolve()
        doc = lookfile.read(path)
        lookfile.writer_document(doc)
        name = row.get('name') or doc['name']
        if name != doc['name']:
            lookfile.validate(dict(doc, name=name))
        if destination is not None:
            target = Path(destination) / ('reference-slot-%d.a7look' % slot)
            shutil.copy2(path, target)
            path = target
        selected.append(dict(slot=slot, path=str(path), name=name, document=doc))
    options['looks'] = [{k: v for k, v in row.items() if k != 'document'} for row in selected]
    return options, selected


def plan(current, records, options, selected, *, build=None):
    """The one write plan of every option chosen, for `build`: a job passes the build Camera.read_programs
    identified, and nothing is identified again; a standalone or offline caller may leave it None, and the
    programs are identified once, when a chosen option's plan depends on the build (buildprofile.build_of)."""
    from . import buildprofile
    from .direct import plan as single
    if options.get('fl23', True) or options.get('reset_slots') or selected:
        build = buildprofile.build_of(current['appFw.so'], current['cpapp-b.bin'], build)
    target, working = dict(current), copy.deepcopy(records)
    wanted, names, labels = [{}, {}], {}, None

    def merge(next_target, fields):
        nonlocal target
        target = next_target
        for chip in (0, 1):
            wanted[chip].update(fields[chip])
            for key, value in fields[chip].items():
                working[chip][key] = working[chip][key]._replace(data=value)

    if options.get('fl23', True):
        a, b, _ = single(target, working, 'fl23_enable', build=build)
        merge(a, b)
    def titles(rename):
        nonlocal labels
        if rename is None:return
        if labels is not None and labels != rename[1]:
            raise ValueError('Selected looks require conflicting title layouts')
        labels=rename[1];names.update(rename[0])

    for slot in options.get('reset_slots',[]):
        a,b,rename=single(target,working,'slot_default',slot=slot,build=build)
        merge(a,b);titles(rename)
    for row in selected:
        a, b, rename = single(target, working, 'look_import', slot=row['slot'],
                              look=row['document'], name=row['name'], build=build)
        merge(a, b)
        titles(rename)
    # Append selected titles once, irrespective of how many slots are chosen.
    if names:
        for filename in resources_files():
            key = 'resources/' + filename
            parsed = resources.decode(current[key])
            target[key] = (resources.rename(current[key], names, labels)[0] if
                any(parsed['entries'].get(labels[s-1], {}).get('text') != title for s, title in names.items()) else current[key])
    spec = importlib.util.spec_from_file_location('bundle_sound_candidate', nativebuild.ROOT / 'src/shutter_sound/candidate.py')
    sound = importlib.util.module_from_spec(spec); spec.loader.exec_module(sound)
    ap, cp = target['appFw.so'], target['cpapp-b.bin']
    # An unchecked feature preserves its current state. Repair the exact legacy
    # enabled patch in this same install plan without enabling an off feature.
    if options.get('sound', True) or sound.is_legacy(cp):
        target.update(sound.patch(ap, cp))
    if options.get('vertical_persistent', False):
        from .verticalpersist import field
        wanted[0].update(field(target['appFw.so'], working, True))
    return target, wanted, (names, labels) if names else None


def resources_files():
    from .nameworker import filenames
    return filenames()
