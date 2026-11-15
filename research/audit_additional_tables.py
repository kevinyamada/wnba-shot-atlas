"""Check every supporting table's grain and internal identities in the supplied ZIP."""
from pathlib import Path
import argparse
import csv
import io
import json
import re
import zipfile
from collections import Counter
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);args=p.parse_args()
    findings=[]
    with zipfile.ZipFile(args.source) as z:
        for name in z.namelist():
            if name.endswith(".txt"):
                text=z.read(name).decode("utf-8-sig",errors="replace")
                rows=list(csv.reader(io.StringIO(text)))
                header=rows[0];data=rows[1:]
                check={"file":name,"data_rows":len(data),"columns":len(header),"duplicate_header_names":[k for k,n in Counter(header).items() if n>1],
                       "all_rows_have_expected_fields":all(len(r)==len(header) for r in data),"unit":"per 100 possessions; games and minutes are separate counting fields"}
                counts={"fg_components_differ_by_more_than_rounding":0,"fg_rate_outside_0_1":0,"three_rate_outside_0_1":0,"blank_fg_rate_when_attempts_zero":0}
                for r in data:
                    d=dict(zip(header,r))
                    try:
                        fg,two,three=map(float,[d["FG"],d["2P"],d["3P"]])
                        counts["fg_components_differ_by_more_than_rounding"]+=abs(fg-two-three)>.151
                        for field,target in [("FG%","fg_rate_outside_0_1"),("3P%","three_rate_outside_0_1")]:
                            if d[field]:counts[target]+=not 0<=float(d[field])<=1
                        counts["blank_fg_rate_when_attempts_zero"]+=not d["FG%"] and float(d["FGA"])==0
                    except (ValueError,KeyError):
                        counts["non_numeric_or_repeated_header_rows"]=counts.get("non_numeric_or_repeated_header_rows",0)+1
                check.update(counts)
                check["modelling_use"]="Excluded from pre-shot features: season-end grain, duplicate headers and player-stint rows require explicit handling. Past box scores provide ID-based prior features instead."
                findings.append(check)
            elif name.endswith(".csv") and "/Wehoop/" not in name:
                d=pd.read_csv(z.open(name),low_memory=False)
                check={"file":name,"rows":len(d),"columns":list(d.columns),"exact_duplicate_rows":int(d.duplicated().sum()),"missing_by_column":d.isna().sum().astype(int).to_dict()}
                if "All-Time Regular" in name:
                    w,l,g=(pd.to_numeric(d[c]) for c in ["Wins","Losses","Games"])
                    check["wins_plus_losses_equal_games"]=bool(w.add(l).eq(g).all())
                    check["win_percent_matches_counts"]=bool(np.allclose(100*w/g,pd.to_numeric(d["Win Percentage"]),atol=.0001))
                    check["asof_date_explicit_in_columns"]=any(re.search("date|as.?of",c,re.I) for c in d)
                    check["modelling_use"]="Historical franchise context only; cumulative records have no shot-level availability timestamp."
                if "Salary" in name:
                    for c in ["season","salary_year","stats_year","year"]:
                        if c in d:check[c+"_counts"]=d[c].value_counts(dropna=False).astype(int).to_dict()
                    if "salary_year" in d and "season" in d:
                        check["salary_year_differs_from_stats_season"]=int(pd.to_numeric(d.salary_year,errors="coerce").ne(pd.to_numeric(d.season,errors="coerce")).sum())
                    if "salary_year" in d and "stats_year" in d:
                        check["salary_year_differs_from_stats_year"]=int(pd.to_numeric(d.salary_year,errors="coerce").ne(pd.to_numeric(d.stats_year,errors="coerce")).sum())
                    check["modelling_use"]="Excluded: contract/salary seasons and full-season performance are different grains and no verified pre-shot contract snapshot is supplied."
                if "Consensus Link" in d:
                    check["distinct_nonmissing_dois"]=int(d.DOI.dropna().str.lower().nunique())
                    check["duplicate_nonmissing_dois"]=int(d.DOI.dropna().str.lower().duplicated().sum())
                    check["study_years"]=d.Year.value_counts(dropna=False).astype(int).to_dict()
                    check["modelling_use"]="Literature-search metadata, not shot observations or independent validation datasets."
                findings.append(check)
        demo_name=next(n for n in z.namelist() if n.endswith("/wnba_player_demographics.csv"))
        d=pd.read_csv(z.open(demo_name),low_memory=False)
        findings.append({"file":demo_name,"rows":len(d),"duplicate_person_ids":int(d.PERSON_ID.duplicated().sum()),"missing_person_ids":int(d.PERSON_ID.isna().sum()),
                         "position_counts":d.POSITION.value_counts(dropna=False).astype(int).to_dict(),
                         "modelling_use":"NBA PERSON_ID demographic records are not automatically joined to ESPN athlete IDs. Protected and medical characteristics are not features in this shooting study."})
    result={"only_source":args.source.name,"table_checks":findings,
            "dictionary_note":"Five sheets provide a mixed-source variable catalogue, not a definitive event schema. Some 3PA definitions say points attempted; the supplied box-score counts and scoring identities establish attempts versus points.",
            "point_in_time_rule":"Only 2022-2024 ID-matched game box counts and completed earlier eligible 2025 games supply player-history features."}
    out=HERE/"results"/"data1"/"supporting_tables_audit.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print("SUPPORTING_TABLES_AUDIT_COMPLETE",len(findings),"tables")
    for item in findings:
        print(json.dumps({k:v for k,v in item.items() if k in ["file","rows","data_rows","exact_duplicate_rows","wins_plus_losses_equal_games","win_percent_matches_counts","salary_year_differs_from_stats_season","salary_year_differs_from_stats_year","distinct_nonmissing_dois","duplicate_nonmissing_dois","duplicate_person_ids"]},ensure_ascii=False))


if __name__=="__main__":main()
