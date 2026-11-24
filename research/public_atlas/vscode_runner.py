"""Run atlas steps inside a VS Code terminal so they can be watched there.

Start it once in VS Code with the task "WNBA public: runner", or with
    py -3.13 research/public_atlas/vscode_runner.py
While it is running, any step sent with --send appears in that terminal.
Without a running runner, --send runs the step directly and still writes its log.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOX = ROOT / 'research/data/public_wnba/runner'
BEAT = BOX / 'heartbeat'
STEP = re.compile(r'^[a-z_]+\.py$')


def run(step, extra, log):
    assert STEP.match(step) and (HERE / step).is_file(), f'{step} is not an atlas step'
    command = [sys.executable, '-u', str(HERE / step), *extra]
    with log.open('w', encoding='utf-8') as file:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        for line in process.stdout:
            print(line, end='', flush=True)
            file.write(line)
        return process.wait()


def serve():
    BOX.mkdir(parents=True, exist_ok=True)
    print('Runner ready. Steps sent from Claude will appear here. Press Ctrl+C to stop.', flush=True)
    while True:
        BEAT.write_text(str(time.time()))
        for request in sorted(BOX.glob('*.request')):
            step, *extra = request.read_text(encoding='utf-8').split()
            request.unlink()
            print(f'\n=== {step} {" ".join(extra)}', flush=True)
            code = run(step, extra, BOX / f'{request.stem}.log')
            (BOX / f'{request.stem}.done').write_text(str(code))
            print(f'=== {step} finished with exit code {code}', flush=True)
        time.sleep(1)


def send(step, extra):
    BOX.mkdir(parents=True, exist_ok=True)
    name = f'{Path(step).stem}_{int(time.time())}'
    log = BOX / f'{name}.log'
    alive = BEAT.exists() and time.time() - float(BEAT.read_text() or 0) < 10
    if not alive:
        print('No runner in VS Code, so the step runs here.', flush=True)
        return run(step, extra, log)
    (BOX / f'{name}.request').write_text(' '.join([step, *extra]), encoding='utf-8')
    done = BOX / f'{name}.done'
    while not done.exists():
        time.sleep(1)
    print(''.join(log.read_text(encoding='utf-8').splitlines(keepends=True)[-15:]), end='')
    return int(done.read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', nargs='+', metavar=('STEP', 'ARG'), help='run one step, for example --send shooters.py')
    args = parser.parse_args()
    sys.exit(send(args.send[0], args.send[1:]) if args.send else serve())
