#!/usr/bin/env python3
"""Weekly: generate hermes_feed/YYYY-WNN.json for the just-completed week."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from utils.hermes_feed import generate_weekly_feed

# weeks_back=1 → last week (this runs on Monday morning)
path = generate_weekly_feed(weeks_back=1)
print(f"Hermes feed generated: {path}")
