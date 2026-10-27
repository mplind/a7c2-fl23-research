"""Standalone offline look compilation adapter used by any frontend."""
import contextlib
from pathlib import Path
import signal
import tempfile
import threading

HALD_SUFFIXES = ('.tif', '.tiff')


@contextlib.contextmanager
def stop_cleanly():
    """While compiling, turn the Stop button's SIGTERM into SystemExit so temporary files are removed."""
    if threading.current_thread() is not threading.main_thread():
        yield  # signal handlers can only be installed from the main thread
        return
    def stop(signum, frame):
        raise SystemExit('Stopped')
    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run(args):
    from looktool.compilelook import main
    source, report = Path(args['source']), None
    with stop_cleanly(), tempfile.TemporaryDirectory(prefix='a7c2-hald-') as temporary:
        if source.suffix.lower() in HALD_SUFFIXES:
            # An identity HALD exported from an editor: its pixels are the look on ST sRGB.
            from looktool import hald
            cube = Path(temporary) / (source.stem + '.cube')
            report = hald.convert(source, cube, title=args.get('name'))
            source = cube
        # The name is typed by the user: '--name=' keeps one starting with '-' from reading as an option.
        argv = [str(source), '--name=' + args['name'], '--output', args['output'],
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
