"""Standalone offline look compilation adapter used by any frontend."""
from pathlib import Path
import tempfile

HALD_SUFFIXES = ('.tif', '.tiff')


def run(args):
    from looktool.compilelook import main
    source, report = Path(args['source']), None
    with tempfile.TemporaryDirectory(prefix='a7c2-hald-') as temporary:
        if source.suffix.lower() in HALD_SUFFIXES:
            # An identity HALD exported from an editor: its pixels are the look on ST sRGB.
            from looktool import hald
            cube = Path(temporary) / (source.stem + '.cube')
            report = hald.convert(source, cube, title=args.get('name'))
            source = cube
        argv = [str(source), '--name', args['name'], '--output', args['output'],
                '--calibration', args['model'], '--passes', str(args.get('passes', 3)),
                '--extra-colors',str(args.get('extra_colors',256))]
        if args.get('evaluations') is not None:
            argv += ['--evaluations', str(args['evaluations'])]
        if source.suffix.lower() == '.cube':
            argv += ['--input-space', args.get('input_space', 'sony-st-srgb')]
            if args.get('bridge'):
                argv += ['--bridge', args['bridge']]
        code = main(argv)
    if code:
        raise RuntimeError('A7Look conversion did not complete')
    result = {'output': args['output'], 'exit_code': code}
    if report is not None:
        result['hald'] = report
    return result
