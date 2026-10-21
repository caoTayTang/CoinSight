"""Install an hourly macOS user LaunchAgent for a frozen prospective study."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    study = args.study.resolve()
    if not (study/'plan.json').exists():
        parser.error('Initialize a study first')
    label = f'com.coinsight.hourly-future.{study.name}'
    destination = Path.home()/'Library/LaunchAgents'/f'{label}.plist'
    destination.parent.mkdir(parents=True, exist_ok=True)
    config = dict(Label=label,
        ProgramArguments=[sys.executable, '-B', '-m', 'scripts.hourly_future', 'tick', '--study', str(study)],
        WorkingDirectory=str(study/'frozen'), StartCalendarInterval={'Minute': 1}, RunAtLoad=True,
        EnvironmentVariables={'PYTHONPATH': str(study/'frozen'), 'PYTHONUNBUFFERED': '1'},
        StandardOutPath=str(study/'scheduler.stdout.log'), StandardErrorPath=str(study/'scheduler.stderr.log'))
    content = plistlib.dumps(config)
    if destination.exists() and destination.read_bytes() != content:
        raise ValueError(f'Refusing to replace a different schedule: {destination}')
    if not destination.exists():
        with destination.open('xb') as stream:
            stream.write(content)
    domain = f'gui/{os.getuid()}'
    probe = subprocess.run(['launchctl', 'print', f'{domain}/{label}'], capture_output=True)
    if probe.returncode:
        subprocess.run(['launchctl', 'bootstrap', domain, str(destination)], check=True)
    print(destination)
    print(f'launchctl print {domain}/{label}')
    print(f'Uninstall: launchctl bootout {domain} {destination}')


if __name__ == '__main__':
    main()
