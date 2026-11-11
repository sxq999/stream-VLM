"""Read public metadata only; do not download weights or disclose credentials."""
import json
from pathlib import Path
import requests

out=Path("runs/model-source-preflight")
out.mkdir(parents=True,exist_ok=True)
session=requests.Session()
models=["Qwen/Qwen3-VL-8B-Instruct","Qwen/Qwen3.5-9B","OpenBMB/MiniCPM-o-4_5"]
results=[]
for name in models:
    item={"model":name}
    for service,url in [
        ("huggingface","https://huggingface.co/api/models/"+name),
        ("modelscope","https://modelscope.cn/api/v1/models/"+name+"/repo/files?Revision=master&Recursive=true")]:
        try:
            response=session.get(url,timeout=20)
            info={"http_status":response.status_code}
            if response.ok:
                data=response.json()
                (out/(name.replace("/","__")+"_"+service+".json")).write_text(json.dumps(data,indent=2),encoding="utf-8")
                info["metadata_saved"]=True
                if service=="huggingface":info["revision"]=data.get("sha")
            item[service]=info
        except Exception as exc:item[service]={"error_type":type(exc).__name__}
    results.append(item)
    print(json.dumps(item),flush=True)
(out/"summary.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
