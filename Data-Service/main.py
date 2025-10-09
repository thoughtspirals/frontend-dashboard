#!/usr/bin/env python3
"""
Main entry point for the DataService application.
"""
import sys
import os

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dataservice.server import main

if __name__ == "__main__":
    main()
