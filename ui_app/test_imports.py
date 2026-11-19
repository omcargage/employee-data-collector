import sys
import time

print("Step 1: Basic imports...", flush=True)
t0 = time.time()
import numpy as np
print(f"  numpy OK ({time.time()-t0:.1f}s)", flush=True)

import pandas as pd
print(f"  pandas OK ({time.time()-t0:.1f}s)", flush=True)

print("Step 2: torch...", flush=True)
import torch
print(f"  torch OK ({time.time()-t0:.1f}s)", flush=True)

print("Step 3: fastapi...", flush=True)
import fastapi
print(f"  fastapi OK ({time.time()-t0:.1f}s)", flush=True)

print("Step 4: edc_agent.ml...", flush=True)
from edc_agent.ml import CORE_NUMERICAL_FEATURES, INT_TO_STATUS, PersonalBaselineTransformer
print(f"  edc_agent.ml OK ({time.time()-t0:.1f}s), features={len(CORE_NUMERICAL_FEATURES)}", flush=True)

print("Step 5: WorkSenseBurnoutPredictor...", flush=True)
from edc_agent.ml import WorkSenseBurnoutPredictor, WorkSenseTemporalNN
print(f"  predictor OK ({time.time()-t0:.1f}s)", flush=True)

print("Step 6: self_report...", flush=True)
from edc_agent.privacy.self_report import BAT12_QUESTIONS, BAT12Summary, compute_bat12_scores
print(f"  self_report OK ({time.time()-t0:.1f}s)", flush=True)

print("Step 7: database...", flush=True)
from edc_agent.storage.database import Database
print(f"  database OK ({time.time()-t0:.1f}s)", flush=True)

print("ALL IMPORTS SUCCEEDED", flush=True)
