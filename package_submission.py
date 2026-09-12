"""
Packaging script: Build the submission code.zip for HackerRank Orchestrate.
Ensures code.zip contains all runnable solution code, configuration, README,
and evaluation/usage_report.md without logging secrets or unnecessary cache files.
"""
import os
import zipfile
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ZIP = os.path.join(REPO_ROOT, 'code.zip')

# Items to include in code.zip
INCLUDED_FILES = [
    'run.py',
    'requirements.txt',
    'README.md',
    '.env.example',
]

INCLUDED_DIRS = [
    'code',
]

# Patterns to exclude from the zip
EXCLUDE_PATTERNS = [
    '__pycache__',
    '.pytest_cache',
    '*.pyc',
    '*.pyo',
    '*.pyd',
    '.git',
    '.DS_Store',
    'Thumbs.db',
    'log.txt',
    '.env',
]

def should_exclude(rel_path):
    parts = rel_path.replace('\\', '/').split('/')
    for part in parts:
        for pat in EXCLUDE_PATTERNS:
            if pat.startswith('*') and part.endswith(pat[1:]):
                return True
            if part == pat:
                return True
    return False

def build_zip():
    print(f"Building submission zip: {OUTPUT_ZIP}")
    with zipfile.ZipFile(OUTPUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add root files
        for fname in INCLUDED_FILES:
            fpath = os.path.join(REPO_ROOT, fname)
            if os.path.exists(fpath):
                zf.write(fpath, arcname=fname)
                print(f"  Added file: {fname}")
            else:
                print(f"  WARNING: missing {fname}")

        # Add code directory
        for dirname in INCLUDED_DIRS:
            dirpath = os.path.join(REPO_ROOT, dirname)
            if not os.path.exists(dirpath):
                continue
            for root, dirs, files in os.walk(dirpath):
                for f in files:
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, REPO_ROOT)
                    if not should_exclude(rel_path):
                        zf.write(full_path, arcname=rel_path)

    # Verify contents
    print("\nVerifying code.zip contents:")
    has_usage_report = False
    with zipfile.ZipFile(OUTPUT_ZIP, 'r') as zf:
        namelist = zf.namelist()
        print(f"  Total files in archive: {len(namelist)}")
        for name in namelist:
            if 'usage_report.md' in name:
                has_usage_report = True
                print(f"  Found required report: {name}")

    if not has_usage_report:
        print("  ERROR: evaluation/usage_report.md NOT found in code.zip!")
        sys.exit(1)
    else:
        print("  Verification SUCCESSFUL! code.zip is ready for submission.")

if __name__ == '__main__':
    build_zip()
