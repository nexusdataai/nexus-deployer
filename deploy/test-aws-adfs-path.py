#!/usr/bin/env python3
"""Test script to find aws-adfs executable."""
import os
import sys
import shutil
import site

print("=" * 60)
print("  AWS-ADFS Path Detection Test")
print("=" * 60)
print()

print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")
print()

# Location 1: Same directory as Python executable
venv_scripts = os.path.dirname(sys.executable)
if sys.platform == 'win32':
    candidate1 = os.path.join(venv_scripts, 'aws-adfs.exe')
else:
    candidate1 = os.path.join(venv_scripts, 'aws-adfs')

print(f"Location 1 (venv): {candidate1}")
print(f"  Exists: {os.path.exists(candidate1)}")
print()

# Location 2: User's local Scripts directory
if sys.platform == 'win32':
    user_site = site.getusersitepackages()
    print(f"User site-packages: {user_site}")
    if user_site:
        user_scripts = os.path.join(os.path.dirname(user_site), 'Scripts', 'aws-adfs.exe')
        print(f"Location 2 (user scripts): {user_scripts}")
        print(f"  Exists: {os.path.exists(user_scripts)}")
        print()

# Location 3: System PATH
aws_adfs_path = shutil.which('aws-adfs')
print(f"Location 3 (PATH): {aws_adfs_path}")
print()

# Determine which one to use
aws_adfs_exe = None
if os.path.exists(candidate1):
    aws_adfs_exe = candidate1
    print(f"✓ Using: {aws_adfs_exe}")
elif sys.platform == 'win32' and user_site:
    user_scripts = os.path.join(os.path.dirname(user_site), 'Scripts', 'aws-adfs.exe')
    if os.path.exists(user_scripts):
        aws_adfs_exe = user_scripts
        print(f"✓ Using: {aws_adfs_exe}")
elif aws_adfs_path:
    aws_adfs_exe = aws_adfs_path
    print(f"✓ Using: {aws_adfs_exe}")
else:
    print("✗ aws-adfs not found in any location")
    print()
    print("Install with: pip install aws-adfs")

print()
print("=" * 60)
