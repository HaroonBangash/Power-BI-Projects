
"""
scale_dataset.py
Creates larger copies of starter fact tables for Power BI performance testing.

Usage:
    python scale_dataset.py --input fact_gl.csv --output fact_gl_5m.csv --rows 5000000

The script samples starter rows, assigns new synthetic primary keys where a likely
ID column exists, and rewrites date columns across the same historical window.
This is for load/performance/incremental-refresh practice, not for statistical research.
"""
import argparse, csv, random
from datetime import datetime, timedelta

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--rows", type=int, required=True)
    args=p.parse_args()

    with open(args.input, newline="", encoding="utf-8") as f:
        r=csv.reader(f)
        header=next(r)
        starter=list(r)

    id_idx=0
    date_idxs=[i for i,h in enumerate(header) if "Date" in h or h in ("Month","WeekStart","SnapshotDate")]
    with open(args.output,"w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(header)
        for i in range(1,args.rows+1):
            row=random.choice(starter).copy()
            if header[id_idx].lower().endswith("id"):
                prefix=''.join([c for c in row[id_idx] if c.isalpha()]) or "ID"
                row[id_idx]=f"{prefix}{i:09d}"
            for j in date_idxs:
                try:
                    d=datetime.strptime(row[j],"%Y-%m-%d")
                    d=d+timedelta(days=random.randint(-120,120))
                    row[j]=d.strftime("%Y-%m-%d")
                except:
                    pass
            w.writerow(row)

if __name__=="__main__":
    main()
