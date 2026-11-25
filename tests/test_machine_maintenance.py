# SPDX-License-Identifier: GPL-3.0-only
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows maintenance service")
def test_machine_update_transaction(tmp_path):
    source = Path(__file__).resolve().parents[1]
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    tester = tmp_path / "machine-tests.exe"
    subprocess.run([
        str(compiler), "/nologo", "/define:CADENCE_STORE_TEST", "/platform:x64", f"/out:{tester}",
        "/r:System.Core.dll", "/r:System.IO.Compression.dll", "/r:System.Web.Extensions.dll",
        "/r:Microsoft.CSharp.dll", str(source / "maintenance/MachineStore.cs"),
        str(source / "maintenance/ReleaseSource.cs"), str(source / "maintenance/tests/MachineStoreTests.cs"),
    ], check=True)
    subprocess.run([str(tester), str(tmp_path)], check=True, timeout=90)
