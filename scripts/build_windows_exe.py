"""PyInstaller build automation script for compiling the EDC desktop agent on Windows.

Usage:
    python scripts/build_windows_exe.py [--clean] [--verify]

Output:
    dist/edc.exe (standalone single-file executable)
"""
import argparse
from pathlib import Path
import subprocess
import sys


def build_executable(clean: bool = True, verify: bool = True) -> int:
    """Execute PyInstaller build for Windows and verify output binary."""
    repo_root = Path(__file__).resolve().parent.parent
    packaging_dir = repo_root / "packaging" / "windows"
    spec_file = packaging_dir / "edc.spec"

    if not spec_file.exists():
        sys.stderr.write(f"[BUILD ERROR] Spec file not found at: {spec_file}\n")
        return 1

    dist_dir = repo_root / "dist"
    build_dir = repo_root / "build"
    output_exe = dist_dir / "edc.exe"

    sys.stdout.write("======================================================================\n")
    sys.stdout.write("  Building Employee Data Collector (EDC) Windows Standalone Binary\n")
    sys.stdout.write("======================================================================\n")
    sys.stdout.write(f"Repo Root: {repo_root}\n")
    sys.stdout.write(f"Spec File: {spec_file}\n")
    sys.stdout.write(f"Target:    {output_exe}\n\n")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec_file),
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
    ]

    if clean:
        cmd.append("--clean")
        cmd.append("-y")

    sys.stdout.write(f"Running: {' '.join(cmd)}\n\n")
    sys.stdout.flush()

    res = subprocess.run(cmd, cwd=str(repo_root))
    if res.returncode != 0:
        sys.stderr.write(f"[BUILD ERROR] PyInstaller build failed with exit code {res.returncode}\n")
        return res.returncode

    if not output_exe.exists():
        sys.stderr.write(f"[BUILD ERROR] Build finished but expected executable not found: {output_exe}\n")
        return 1

    size_mb = output_exe.stat().st_size / (1024 * 1024)
    sys.stdout.write(f"\n[BUILD SUCCESS] Successfully compiled: {output_exe} ({size_mb:.2f} MB)\n")

    if verify:
        sys.stdout.write("\n[VERIFICATION] Running smoke check: edc.exe --help ...\n")
        verify_res = subprocess.run(
            [str(output_exe), "--help"],
            capture_output=True,
            text=True,
        )
        if verify_res.returncode == 0 and "Employee Data Collector" in verify_res.stdout:
            sys.stdout.write("[VERIFICATION PASSED] edc.exe executed successfully and produced expected CLI output.\n")
        else:
            sys.stderr.write(
                f"[VERIFICATION WARNING] Smoke test returned code {verify_res.returncode}:\n"
                f"STDOUT:\n{verify_res.stdout}\nSTDERR:\n{verify_res.stderr}\n"
            )
            return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build EDC Windows standalone executable")
    parser.add_argument("--no-clean", dest="clean", action="store_false", default=True, help="Skip clean build directory")
    parser.add_argument("--no-verify", dest="verify", action="store_false", default=True, help="Skip smoke verification")
    args = parser.parse_args()

    return build_executable(clean=args.clean, verify=args.verify)


if __name__ == "__main__":
    sys.exit(main())
