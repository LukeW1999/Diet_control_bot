#!/usr/bin/env python3
"""Weekly cleanup: delete old media files and trim conversation log."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from utils.cleanup import run_all

result = run_all()
print(
    f"Cleanup done — "
    f"images:{result['images_deleted']} "
    f"docs:{result['docs_deleted']} "
    f"log_lines:{result['log_lines_removed']} "
    f"feed_files:{result['feed_files_removed']}"
)
