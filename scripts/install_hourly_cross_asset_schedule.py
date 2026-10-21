"""Queue the frozen cross-asset follow-up after prospective evaluation completes."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    output = args.experiment.resolve()
    if not (output/'plan.json').exists():
        parser.error('Preregister an experiment first')
    label = f'com.coinsight.hourly-cross-asset.{output.name}'
    destination = Path.home()/'Library/LaunchAgents'/f'{label}.plist'
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = plistlib.dumps(dict(Label=label,
        ProgramArguments=[sys.executable, '-B', '-m', 'scripts.hourly_cross_asset', 'run', '--experiment', str(output)],
        WorkingDirectory=str(output/'frozen'), StartCalendarInterval={'Minute': 10}, RunAtLoad=True,
        EnvironmentVariables={'PYTHONPATH': str(output/'frozen'), 'PYTHONUNBUFFERED': '1'},
        StandardOutPath=str(output/'scheduler.stdout.log'), StandardErrorPath=str(output/'scheduler.stderr.log')))
    if destination.exists() and destination.read_bytes() != content:
        raise ValueError('Refusing to replace a different schedule')
    if not destination.exists():
        with destination.open('xb') as stream:
            stream.write(content)
    domain = f'gui/{os.getuid()}'
    probe = subprocess.run(['launchctl', 'print', f'{domain}/{label}'], capture_output=True)
    if probe.returncode:
        subprocess.run(['launchctl', 'bootstrap', domain, str(destination)], check=True)
    print(destination)


if __name__ == '__main__':
    main()
