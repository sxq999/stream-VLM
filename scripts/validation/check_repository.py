"""Check repository documentation links and documented script paths, offline."""
import argparse
import ast
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def check(root):
    documents = [root/'README.md', root/'scripts/README.md', root/'configs/README.md']
    documents += [p for p in (root/'docs').rglob('*') if p.suffix in ('.md','.html')]
    errors, checked = [], 0
    for path in list((root/'docs').rglob('*'))+list(root.iterdir()):
        if path.is_file() and path.suffix.lower() in ('.ppt','.pptx','.doc','.docx','.key'):
            errors.append(dict(file=path.relative_to(root).as_posix(),error='internal presentation material is outside the public project scope'))
    for path in documents:
        text = path.read_text(encoding='utf-8')
        if path.suffix=='.md':
            # Code snippets are not rendered Markdown links.
            prose=re.sub(r'```.*?```','',text,flags=re.S)
            targets=re.findall(r'!?\[[^\]\n]*\]\(([^\)\n]+)\)',prose)
        else:
            targets=re.findall(r'(?:href|src)=["\']([^"\']+)["\']',text)
        for target in targets:
            target=target.strip().strip('<>')
            parsed=urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:continue
            resolved=(path.parent/unquote(parsed.path)).resolve()
            checked+=1
            if not resolved.is_relative_to(root) or not resolved.exists():
                errors.append(dict(file=path.relative_to(root).as_posix(),target=target))
        if path.suffix=='.md':
            for script in re.findall(r'(?<![\w/])scripts/[\w/.-]+\.py',text):
                checked+=1
                if not (root/script).is_file():
                    errors.append(dict(file=path.relative_to(root).as_posix(),script=script))
    python_files=list((root/'scripts').rglob('*.py'))
    for path in python_files:
        try:ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
        except SyntaxError as exc:errors.append(dict(file=path.relative_to(root).as_posix(),error=str(exc)))
    return dict(status='pass' if not errors else 'failed',documents=len(documents),
                references_checked=checked,python_scripts_parsed=len(python_files),errors=errors)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    args=parser.parse_args();result=check(args.root.resolve())
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status']=='pass' else 1)
