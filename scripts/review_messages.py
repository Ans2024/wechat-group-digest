"""Read bounded, lossless batches for Codex; never generates an AI summary."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def load(directory):
    raw=(Path(directory)/'messages.json').read_bytes()
    data=json.loads(raw)
    return data,hashlib.sha256(raw).hexdigest()


def batches(data,budget):
    if not 2000 <= budget <= 16000:
        raise ValueError('budget 必须在 2000–16000 字符之间')
    chunks=[]
    for ordinal,message in enumerate(data['messages'],1):
        view={key:message[key] for key in ('id','time','sender','type','text','reference','links','card','transcript_source','parse_warning') if key in message}
        if message.get('parse_warning') or message.get('type','').startswith('未知类型'):
            view['raw_content']=message.get('raw_content','')
        serial=json.dumps(view,ensure_ascii=False)
        # Leave ample space for JSON escaping and wrapper fields.
        limit=max(300,(budget-800)//3)
        if len(serial)<=limit:
            chunks.append({'message_number':ordinal,'message':view})
        else:
            parts=[serial[i:i+limit] for i in range(0,len(serial),limit)]
            for i,fragment in enumerate(parts,1):
                chunks.append({'message_number':ordinal,'message_id':message['id'],'part':i,'parts':len(parts),'json_fragment':fragment})
    result=[];current=[];used=500
    for chunk in chunks:
        size=len(json.dumps(chunk,ensure_ascii=False))+2
        if size+used>budget and current:
            result.append(current);current=[];used=500
        current.append(chunk);used+=size
    if current:result.append(current)
    return result


def public_check(directory,data):
    directory=Path(directory);meta=data['metadata']
    secrets={meta.get('account',''),meta.get('group',{}).get('username',''),meta.get('group',{}).get('owner_id','')}
    secrets.update(m.get('sender_id','') for m in data['messages']);secrets.discard('')
    secrets.update(m['id'] for m in data['messages'])
    result={}
    for name in ('index.html','summary.md'):
        text=(directory/name).read_text(encoding='utf-8')
        # Report only counts, not the identifiers this check is intended to protect.
        count=sum(secret in text for secret in secrets)
        count+=bool(re.search(r'\bwxid_[\w-]+|\d+@chatroom',text))
        if count:
            raise ValueError(f'{name} 存在 {count} 处账号或内部消息标识匹配，需要清理后重新渲染')
        result[name]='account and internal message identifiers absent'
    manifest=json.loads((directory/'render_manifest.json').read_text(encoding='utf-8'))
    images=manifest.get('images',[])
    if not images:
        raise ValueError('没有 PNG 输出清单')
    for name in images:
        target=(directory/name).resolve()
        if target.parent!=directory.resolve() or not target.is_file() or target.stat().st_size==0:
            raise ValueError('PNG 清单路径无效或文件缺失')
    result.update(images=images,png_visual_review='仍需目视检查；文本扫描不等于 OCR 检查')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['inspect','batch','check-public'])
    parser.add_argument('directory')
    parser.add_argument('--index',type=int,default=1)
    parser.add_argument('--budget',type=int,default=6500)
    args=parser.parse_args();data,digest=load(args.directory)
    if args.command=='check-public':
        answer=public_check(args.directory,data)
    else:
        pieces=batches(data,args.budget);meta=data['metadata']
        answer={'input_sha256':digest,'message_count':len(data['messages']),'batch_count':len(pieces),'budget':args.budget}
        if args.command=='inspect':
            answer['scope']={k:meta.get(k) for k in ('group_name','start','end','timezone','speaker_count','synthetic')}
            answer['reading_note']='依次读取全部批次；长消息 json_fragment 按 part 顺序拼接，不遗漏任何部分。'
        else:
            if not 1<=args.index<=len(pieces):raise ValueError('批次索引越界；零消息时无需 batch')
            answer.update(batch=args.index,items=pieces[args.index-1])
    print(json.dumps(answer,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as exc:raise SystemExit(str(exc))
