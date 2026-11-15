"""Mesh refinement is included in the Data1 reference comparison stage."""
from data1_cpu import compare, DATA
import pandas as pd

if __name__ == "__main__":
    compare(pd.read_csv(DATA / "model_shots.csv.gz", dtype={"player_id":str,"team_id":str}))
