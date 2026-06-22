#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
import yaml
from datetime import datetime, timezone

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

from main import run_live
run_live(cfg, 'v_oliver_kell')
