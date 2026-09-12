"""
Main entry point for Buy or Wait challenge at repository root.
Runs the complete financial decision pipeline and generates output.csv and usage_report.md.
"""
import sys
import os

# Add code directory to path
code_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'code')
sys.path.insert(0, code_dir)

from main import main

if __name__ == '__main__':
    main()
