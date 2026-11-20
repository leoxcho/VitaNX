"""Summarize an existing execution.json without rebuilding or launching a game."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vitanx.diagnostics import summarize
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('execution',type=Path)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    result=json.dumps(summarize(json.loads(a.execution.read_text())),indent=2)+'\n'
    if a.output:
        with a.output.open('x') as stream:stream.write(result)
    else:print(result,end='')
