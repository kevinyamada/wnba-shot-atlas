"""Create private reading extracts and a complete tabular source inventory."""
from pathlib import Path
import csv
import io
import json
import re
import zipfile
from collections import Counter
import argparse
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=Path,required=True)
    args=ap.parse_args()
    cache=HERE/"data"/"archive_review"
    audit=json.loads((HERE/"results"/"archive_audit.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(args.source) as source:
        for entry in audit["members"]:
            if entry["path"].endswith(".docx"):
                with zipfile.ZipFile(io.BytesIO(source.read(entry["path"]))) as doc:
                    root=ET.fromstring(doc.read("word/document.xml"))
                    ns="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                    paragraphs=["".join(t.text or "" for t in p.iter(ns+"t")) for p in root.iter(ns+"p")]
                    text="\n".join(paragraphs)
                    (cache/entry["extraction_file"]).write_text(text,encoding="utf-8")
                    entry["text_characters"]=len(text)
                    entry["field_instructions_excluded"]=True
    (HERE/"results"/"archive_audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    readings=[]
    words={}
    for entry in audit["members"]:
        name=entry.get("extraction_file")
        if not name:
            continue
        text=(cache/name).read_text(encoding="utf-8")
        cleaned=re.sub(r"PAGE \d+\s*","",text)
        matches=list(re.finditer(r"\ba\s*b\s*s\s*t\s*r\s*a\s*c\s*t\b",cleaned,re.I))
        abstract=next((m for m in matches if not re.search(r"\.{4,}",cleaned[m.end():m.end()+140])),None)
        abstract_text=cleaned[abstract.end():abstract.end()+4200] if abstract else cleaned[:4200]
        abstract_text=re.split(r"\b(?:keywords|key words|introduction)\b",abstract_text,flags=re.I)[0]
        headings=list(re.finditer(r"(?im)^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:conclusions?|discussion(?: and conclusions?)?|concluding remarks)\s*\n",cleaned))
        substantive=[m for m in headings if m.start()>len(cleaned)*.2]
        ending=cleaned[substantive[-1].start():substantive[-1].start()+4200] if substantive else cleaned[max(0,len(cleaned)-10000):max(0,len(cleaned)-6000)]
        methods=re.search(r"(?im)^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:methods|methodology|materials and methods|data and methods|data and methodology)\s*\n",cleaned)
        method_text=cleaned[methods.start():methods.start()+2200] if methods else ""
        topics={w:len(re.findall(re.escape(w),cleaned,re.I)) for w in ["shot","spatial","Gaussian","Bayesian","point process","prediction","validation","injury","role","entropy","network","expected points","causal"]}
        doi=list(dict.fromkeys(re.findall(r"10\.\d{4,9}/[^\s<>]+",cleaned)))[:8]
        readings.append({"file":entry["path"],"pages":entry.get("pages"),"text_characters":len(text),"opening":cleaned[:1500],
                         "abstract":abstract_text,"methods":method_text,"discussion_or_conclusion":ending,"dois":doi,"topic_mentions":topics})
        words[entry["path"]]=set(re.findall(r"[a-z]{3,}",cleaned.lower()))
    duplicates=[]
    names=list(words)
    for i,a in enumerate(names):
        for b in names[i+1:]:
            score=len(words[a]&words[b])/max(1,len(words[a]|words[b]))
            if score>.7:
                duplicates.append({"a":a,"b":b,"token_jaccard":score})
    (cache/"reading_brief.json").write_text(json.dumps({"readings":readings,"possible_duplicate_documents":duplicates},ensure_ascii=False,indent=2),encoding="utf-8")
    tables=[]
    with zipfile.ZipFile(args.source) as archive:
        for entry in archive.infolist():
            if entry.filename.endswith(".txt"):
                raw=archive.read(entry).decode("utf-8-sig",errors="replace")
                try:
                    dialect=csv.Sniffer().sniff(raw[:12000],delimiters=",;\t|")
                    rows=list(csv.reader(io.StringIO(raw),dialect))
                    tables.append({"file":entry.filename,"rows_including_headers":len(rows),"delimiter":dialect.delimiter,"field_counts":dict(Counter(map(len,rows))),"first_rows":rows[:3]})
                except csv.Error:
                    tables.append({"file":entry.filename,"lines":len(raw.splitlines()),"first_lines":raw.splitlines()[:3],"format":"unstructured text"})
            elif entry.filename.endswith(".csv") and "/Wehoop/" not in entry.filename:
                reader=csv.DictReader(io.StringIO(archive.read(entry).decode("utf-8-sig",errors="replace")))
                rows=list(reader)
                tables.append({"file":entry.filename,"columns":reader.fieldnames,"rows":len(rows),"first_rows":rows[:2]})
    (cache/"other_tables_review.json").write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Reviewed",len(readings),"documents and",len(tables),"additional tabular files")
    print("Possible duplicate papers:",json.dumps(duplicates,ensure_ascii=False))


if __name__=="__main__":
    main()
