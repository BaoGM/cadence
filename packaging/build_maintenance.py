# SPDX-License-Identifier: GPL-3.0-only
import argparse
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def build_maintenance(output, test_key=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    csc = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    source = ROOT / 'maintenance'
    key = Path(test_key).resolve() if test_key else ROOT / 'assets/update-key.txt'
    service_options = [
        '/r:System.ServiceProcess.dll', '/r:System.Core.dll',
        '/r:System.IO.Compression.dll', '/r:System.Web.Extensions.dll',
        f'/resource:{key},Cadence.Machine.UpdateKey',
    ]
    if test_key:
        if key == (ROOT / 'assets/update-key.txt').resolve():
            raise ValueError('A test service requires a separate fixture key')
        service_options.append('/define:CADENCE_TEST_SERVICE')
    setup_options = ['/r:System.ServiceProcess.dll', '/r:System.Windows.Forms.dll', '/r:System.Web.Extensions.dll',
                     f'/win32manifest:{source / "setup.manifest"}', f'/win32icon:{ROOT / "assets/cadence.ico"}']
    targets = [
        ('CadenceMaintenance', 'winexe', service_options,
         [source / name for name in ('Program.cs', 'MachineStore.cs', 'ReleaseSource.cs')]),
        ('CadenceRestart', 'winexe', ['/r:System.Runtime.Serialization.dll'],
         [ROOT / 'packaging/maintenance/CadenceRestart.cs']),
        ('CadenceMaintenanceRemove', 'winexe', setup_options, [source / 'Setup.cs']),
        ('CadenceMaintenanceSetup', 'winexe',
         [*setup_options, *[f'/resource:{output / name},Cadence.Setup.{name}'
                            for name in ('CadenceMaintenance.exe', 'CadenceRestart.exe', 'CadenceMaintenanceRemove.exe')]],
         [source / 'Setup.cs']),
    ]
    for name, target_type, options, sources in targets:
        subprocess.run([str(csc), '/nologo', '/optimize+', '/platform:x64', f'/target:{target_type}',
                        f'/out:{output / (name + ".exe")}', *options, *map(str,sources)], check=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--test-key', type=Path)
    args = parser.parse_args()
    build_maintenance(args.output, args.test_key)
