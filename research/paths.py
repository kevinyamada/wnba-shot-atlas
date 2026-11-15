from pathlib import Path
HERE=Path(__file__).resolve().parent
SITE=HERE.parent
DATA=HERE/'data'/'data1'
RESULTS=HERE/'results'/'data1'
DATA.mkdir(parents=True,exist_ok=True)
RESULTS.mkdir(parents=True,exist_ok=True)
