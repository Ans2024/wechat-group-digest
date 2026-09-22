"""Reference-inspired navy header, metric strip and compact editorial cards."""
import html
import json
import re
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

NAVY='#172f49'
INK='#28445e'
MUTED='#75899e'
BG='#f1f5fb'
BLUE='#2863dc'

def public_filter(data):
    meta=data['metadata']
    secrets={meta.get('account',''),meta.get('group',{}).get('username',''),meta.get('group',{}).get('owner_id','')}
    secrets.update(m.get('sender_id','') for m in data['messages'])
    secrets.discard('')
    def clean(value):
        value=str(value)
        for secret in sorted(secrets,key=len,reverse=True):
            value=value.replace(secret,'[账号已隐藏]')
        value=re.sub(r'\b\d+@chatroom\b|\bwxid_[A-Za-z0-9_-]+\b','[账号已隐藏]',value)
        return value
    return clean

def render_report(directory):
    from .report import validate,item_text
    directory=Path(directory)
    data=json.loads((directory/'messages.json').read_text(encoding='utf-8'))
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    ids=validate(data,report); meta=data['metadata']; clean=public_filter(data)
    esc=lambda value:html.escape(clean(value),quote=True)
    numbers={m['id']:i for i,m in enumerate(data['messages'],1)}
    start,end=datetime.fromisoformat(meta['start']),datetime.fromisoformat(meta['end'])
    hours=(end-start).total_seconds()/3600
    title=f'这 {hours:g} 小时，群里聊了什么'
    if meta.get('synthetic'):title='虚构样例 · '+title
    eyebrow='群聊日报 / '+end.strftime('%Y.%m.%d')
    group=clean(meta['group_name'])
    period=start.strftime('%m.%d %H:%M')+' — '+end.strftime('%m.%d %H:%M')+' · UTC+08:00'
    media=sum((m.get('local_type',0)&0xffffffff) in (3,34,43,47,11000) for m in data['messages'])
    stats=[(str(meta['message_count']),'条消息'),(str(meta['speaker_count']),'位发言人'),(str(media),'条图片 / 音视频 / 表情')]
    blocks=[{'kind':'hero','eyebrow':eyebrow,'title':title,'group':group,'period':period}, {'kind':'stats','stats':stats}]
    parts=[f'<header><div class="wrap"><div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1><p>{esc(group)}</p><p class="period">{esc(period)}</p></div></header><main class="wrap">',
           '<div class="stats">'+''.join(f'<div><b>{n}</b><span>{label}</span></div>' for n,label in stats)+'</div>']
    md=['# '+title,group,period,' · '.join(n+' '+label for n,label in stats)]
    def refs(item):return '来源：消息 '+ '、'.join(str(numbers[mid]) for mid in item['message_ids'])
    def sources(item):
        text='<details><summary>'+esc(refs(item))+'</summary>'
        for evidence in item['evidence']:
            message=ids[evidence['message_id']]
            stamp=datetime.fromisoformat(message['time']).strftime('%m-%d %H:%M:%S')
            text+='<blockquote><p>'+esc(evidence['quote'])+'</p><small>'+esc(f"消息 {numbers[message['id']]} · {stamp} · {message['sender']}")+'</small>'
            for url in message.get('links',[]):
                if url.startswith(('https://','http://')) and clean(url)==url:
                    text+='<p><a rel="noreferrer" href="'+esc(url)+'">查看原链接</a></p>'
            text+='</blockquote>'
        return text+'</details>'
    for item in report['overview']:
        body=clean(item['text']);blocks.append({'kind':'intro','text':body})
        parts.append('<div class="intro"><p>'+esc(body)+'</p>'+sources(item)+'</div>')
        md.extend([body,refs(item)])
    sections=[('topics','主要讨论','white'),('todos','需要跟进的事','amber'),
              ('confirmed','已有回应与结论','green'),('unresolved','尚待明确','amber'),('other','其他交流','white')]
    for key,label,tone in sections:
        blocks.append({'kind':'heading','text':label});parts.append('<section><h2>'+label+'</h2>');md.append('## '+label)
        if not report[key]:
            text='本时段未出现明确分派的待办事项。' if key=='todos' else '本时段暂无明确记录。'
            blocks.append({'kind':'empty','text':text});parts.append('<p class="empty">'+text+'</p>');md.append(text)
        for index,item in enumerate(report[key],1):
            body=clean(item_text(item,key=='todos'))
            heading=clean(item.get('title',''))
            if not heading:
                first,sep,rest=body.partition('：')
                if sep and len(first)<=18:
                    heading,body=first,rest
                else:heading={'topics':'讨论记录','todos':'待跟进事项','confirmed':'成员回应','unresolved':'记录中的信息缺口','other':'交流补充'}[key]
            block={'kind':'card','title':heading,'text':body,'source':refs(item),'tone':tone}
            blocks.append(block)
            parts.append('<article class="card '+tone+'"><h3>'+esc(heading)+'</h3><p>'+esc(body)+'</p>'+sources(item)+'</article>')
            md.extend(['### '+heading,body,refs(item)])
        parts.append('</section>')
    notes=[f"统计窗口：{meta['start']} 至 {meta['end']}，包含起点，不包含终点。时区：Asia/Shanghai（UTC+08:00）。",
           f"完整读取本窗口 {meta['message_count']} 条本地消息，识别 {meta['speaker_count']} 位发言人。仅代表本机已同步记录，不代表该群完整历史。",
           '图片、视频、语音和表情未进行内容识别；总结仅依据可读取文本与卡片信息。来源序号按本次导出消息顺序编号。']
    if meta.get('synthetic'):notes.insert(0,'本报告使用虚构数据，仅用于测试排版与来源核对。')
    for warning in meta.get('warnings',[]):
        if '可能存在同步不足' in warning or '无可用消息' in warning:notes.append(clean(warning))
    footer='“'+group+'” · '+end.strftime('%Y.%m.%d')
    blocks.append({'kind':'heading','text':'数据范围与阅读口径','small':True})
    parts.append('<footer><h2>数据范围与阅读口径</h2>');md.append('## 数据范围与阅读口径')
    for note in notes:
        note=clean(note);blocks.append({'kind':'note','text':note});parts.append('<p>'+esc(note)+'</p>');md.append(note)
    blocks.append({'kind':'note','text':footer});parts.append('<p class="signature">'+esc(footer)+'</p></footer></main>')
    css='''*{box-sizing:border-box}body{margin:0;background:#f1f5fb;color:#28445e;font:16px/1.75 "Microsoft YaHei","PingFang SC",sans-serif}.wrap{max-width:1000px;margin:auto;padding:0 50px}header{background:#172f49;color:#fff;padding:32px 0 27px}.eyebrow{color:#94b9ed;font-size:13px;font-weight:700}h1{font-size:34px;line-height:1.45;margin:10px 0 8px;letter-spacing:.5px}header p{color:#c4d1df;margin:3px 0}.period{font-size:14px}main.wrap{padding-top:24px;padding-bottom:30px}.stats{display:grid;grid-template-columns:repeat(3,1fr);padding:12px 26px;background:white;border:1px solid #dce5ef;border-radius:10px;margin-bottom:22px}.stats b{display:block;font-size:30px;line-height:1.3;color:#2863dc}.stats span{font-size:13px;color:#75899e}.intro{font-weight:700;margin-bottom:20px}.intro p{margin:0 0 4px}h2{font-size:21px;line-height:1.5;margin:20px 0 12px}h3{font-size:18px;line-height:1.5;margin:0 0 11px}.card{background:white;border:1px solid #dce5ef;border-radius:10px;padding:18px 24px;margin-bottom:14px}.card.amber{background:#fff7e9;border-color:#f0dcc0}.card.green{background:#e8f2ee;border-color:#d6e6df}p{white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 10px}.card>p:last-of-type{margin-bottom:12px}summary{font-size:12px;color:#75899e;cursor:pointer;font-weight:400}blockquote{margin:12px 0 0;padding:12px;border-left:3px solid #91abc3;background:#f4f7fa;font-weight:400}blockquote p{font-size:14px}small{font-size:12px;color:#75899e;overflow-wrap:anywhere}a{color:#2863dc}.empty{font-size:14px;color:#75899e;margin:0 0 18px}footer{margin-top:28px;color:#75899e;font-size:12px}footer h2{font-size:16px;color:#28445e}footer p{margin-bottom:10px}.signature{margin-top:18px}@media(max-width:600px){.wrap{padding-left:22px;padding-right:22px}header{padding:25px 0}h1{font-size:27px}.stats{padding:12px 16px;gap:8px}.stats b{font-size:27px}.stats span{font-size:11px}.card{padding:16px 18px}h2{font-size:20px}h3{font-size:17px}body{font-size:15px}}'''
    document='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'"><title>'+esc(group+' · '+title)+'</title><style>'+css+'</style></head><body>'+''.join(parts)+'</body></html>'
    (directory/'index.html').write_text(document,encoding='utf-8')
    (directory/'summary.md').write_text('\n\n'.join(md),encoding='utf-8')
    images=draw_cards(blocks,directory)
    manifest={'images':images,'style':'navy-card-digest','public_account_ids':False,'source_labels':'1-based message order',
              'split_reason':'内容超过 12000 像素，按完整卡片或文字行编号分图，report.png 为第 1 张。' if len(images)>1 else None,
              'reviewed_count':len(report['reviewed_message_ids'])}
    (directory/'render_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    if len(images)>1:
        with (directory/'summary.md').open('a',encoding='utf-8') as f:f.write('\n\n'+manifest['split_reason']+'\n'+', '.join(images))
    return manifest

def draw_cards(blocks,directory,max_height=12000):
    width,pad=1080,54
    measure=ImageDraw.Draw(Image.new('RGB',(1,1)))
    def font(size,bold=False):return ImageFont.truetype('C:/Windows/Fonts/'+('msyhbd.ttc' if bold else 'msyh.ttc'),size)
    def lines(text,size=23,bold=False,available=972,color=INK):
        f=font(size,bold);out=[];lh=int(size*1.65)
        for paragraph in text.split('\n'):
            current=''
            for char in paragraph:
                if current and measure.textlength(current+char,font=f)>available:
                    out.append((current,f,color,lh));current=''
                current+=char
            out.append((current,f,color,lh))
        return out
    def height(rows):return sum(row[3] for row in rows)
    tiles=[]
    for block in blocks:
        kind=block['kind']
        if kind=='hero':
            rows=lines(block['eyebrow'],18,True,color='#94b9ed')+[('',font(8),INK,9)]+lines(block['title'],42,True,color='#ffffff')+[('',font(8),INK,9)]+lines(block['group'],22,color='#c4d1df')+lines(block['period'],20,color='#c4d1df')
            tiles.append({'kind':kind,'rows':rows,'height':height(rows)+60});continue
        if kind=='stats':tiles.append({'kind':kind,'stats':block['stats'],'height':140});continue
        if kind=='card':
            rows=lines(block['title'],25,True,available=916)+[('',font(8),INK,12)]+lines(block['text'],23,available=916)+[('',font(8),INK,14)]+lines(block['source'],17,available=916,color=MUTED)
            # Oversized cards split on full rows; ordinary cards remain intact across pages.
            chunks=[];chunk=[];used=0
            for row in rows:
                if used+row[3]>max_height-160 and chunk:chunks.append(chunk);chunk=[];used=0
                chunk.append(row);used+=row[3]
            if chunk:chunks.append(chunk)
            for chunk in chunks:tiles.append({'kind':kind,'rows':chunk,'height':height(chunk)+50+18,'tone':block['tone']})
        else:
            size=28 if kind=='heading' else 24 if kind=='intro' else 18 if kind=='note' else 21
            if block.get('small'):size=22
            rows=lines(block['text'],size,kind in ('intro','heading'),color=MUTED if kind in ('note','empty') else INK)
            tiles.append({'kind':kind,'rows':rows,'height':height(rows)+(26 if kind=='heading' else 16)})
    pages=[];current=[];used=40
    for i,tile in enumerate(tiles):
        # Keep each section heading with its first card when possible.
        required=tile['height']
        if tile['kind']=='heading' and i+1<len(tiles):required+=tiles[i+1]['height']
        if current and used+required>max_height:pages.append(current);current=[];used=40
        current.append(tile);used+=tile['height']
    if current:pages.append(current)
    names=[]
    for page_number,page in enumerate(pages,1):
        total=sum(t['height'] for t in page)+40
        im=Image.new('RGB',(width,total),BG);draw=ImageDraw.Draw(im);y=0
        for tile in page:
            kind=tile['kind'];h=tile['height'];x=pad;ty=y
            if kind=='hero':draw.rectangle((0,y,width,y+h),fill=NAVY);ty+=30
            elif kind=='stats':
                draw.rounded_rectangle((pad,y+26,width-pad,y+h-10),radius=12,fill='#ffffff',outline='#dce5ef',width=2)
                for i,(value,label) in enumerate(tile['stats']):
                    sx=pad+30+i*(width-2*pad-30)//3
                    draw.text((sx,y+36),value,font=font(38,True),fill=BLUE,anchor='lt')
                    draw.text((sx,y+89),label,font=font(17),fill=MUTED,anchor='lt')
                y+=h;continue
            elif kind=='card':
                fill,border={'white':('#ffffff','#dce5ef'),'amber':('#fff7e9','#f0dcc0'),'green':('#e8f2ee','#d6e6df')}[tile['tone']]
                draw.rounded_rectangle((pad,y,width-pad,y+h-18),radius=12,fill=fill,outline=border,width=2);x+=28;ty+=23
            elif kind=='heading':ty+=10
            for text,f,color,lh in tile.get('rows',[]):draw.text((x,ty),text,font=f,fill=color,anchor='lt');ty+=lh
            y+=h
        if len(pages)>1:draw.text((pad,total-30),f'{page_number} / {len(pages)}',font=font(16),fill=MUTED,anchor='lt')
        name='report.png' if page_number==1 else f'report-{page_number:02}.png'
        im.save(directory/name);names.append(name)
    return names
