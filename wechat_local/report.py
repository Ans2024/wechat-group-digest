import html
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SECTIONS = [('overview','概览'),('topics','主要话题与讨论结论'),('todos','待办事项'),('confirmed','已解决或已确认事项'),('unresolved','尚未解决的问题'),('other','其他信息')]

def validate(data, report):
    messages = data['messages']
    ids = {m['id']:m for m in messages}
    if len(ids) != len(messages) or data['metadata']['message_count'] != len(messages):
        raise ValueError('消息标识或统计错误')
    if data['metadata']['speaker_count'] != len({m['sender_id'] for m in messages if m['sender_id']}):
        raise ValueError('发言人数不一致')
    reviewed = report.get('reviewed_message_ids',[])
    if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(ids):
        raise ValueError('总结必须声明已读完本次全部消息，reviewed_message_ids 不完整')
    for key,_ in SECTIONS:
        if not isinstance(report.get(key),list):
            raise ValueError('报告缺少数组字段 '+key)
        for item in report[key]:
            if not isinstance(item.get('text'),str) or not item['text'].strip():
                raise ValueError('总结条目缺少 text')
            refs = item.get('message_ids',[])
            if not refs or not set(refs).issubset(ids):
                raise ValueError('总结引用不存在或没有引用消息')
            evidence = item.get('evidence',[])
            if {e.get('message_id') for e in evidence} != set(refs):
                raise ValueError('每个消息引用均须提供原文摘录')
            for e in evidence:
                message = ids[e['message_id']]
                source = message['text']+'\n'+json.dumps(message.get('reference'),ensure_ascii=False)
                if not e.get('quote') or e['quote'] not in source:
                    raise ValueError('来源摘录不是该消息原文')
            if key == 'todos' and any(not item.get(field) for field in ('owner','deadline','status')):
                raise ValueError('待办缺少负责人、时间要求或状态；无明确值请写未明确')
    # Existence and literal evidence can be checked mechanically; entailment needs human/model review.
    return ids

def item_text(item, todo=False):
    text = item['text']
    if todo:
        text += f"\n负责人：{item['owner']}；时间要求：{item['deadline']}；状态：{item['status']}"
    return text

def render(directory):
    from .styled import render_report
    return render_report(directory)


def draw_png(blocks,directory,max_height=12000):
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    if not font_path.exists():
        raise RuntimeError('未找到微软雅黑字体；请配置经过验证的中文字体')
    width,pad = 1080,64
    measure = ImageDraw.Draw(Image.new('RGB',(1,1)))
    lines = []
    for text,size,color in blocks:
        font = ImageFont.truetype(str(font_path),size)
        height = sum(font.getmetrics())+10
        for paragraph in text.split('\n'):
            current = ''
            for char in paragraph:
                if current and measure.textlength(current+char,font=font) > width-2*pad:
                    lines.append((current,font,color,height)); current = ''
                current += char
            lines.append((current,font,color,height))
        lines.append(('',font,color,18))
    pages,current,used = [],[],pad*2+44
    for line in lines:
        if current and used+line[3]>max_height:
            pages.append(current); current=[]; used=pad*2+44
        current.append(line); used+=line[3]
    if current:
        pages.append(current)
    names=[]
    for i,page in enumerate(pages,1):
        height = sum(line[3] for line in page)+pad*2+44
        im = Image.new('RGB',(width,height),'#fbfcf8')
        draw = ImageDraw.Draw(im)
        draw.rectangle((0,0,width,10),fill='#286f59')
        y=pad
        for text,font,color,lh in page:
            draw.text((pad,y),text,font=font,fill=color,anchor='lt'); y+=lh
        draw.text((pad,height-pad),f'本地聊天总结  ·  {i}/{len(pages)}',font=ImageFont.truetype(str(font_path),18),fill='#77897d')
        name = 'report.png' if i==1 else f'report-{i:02}.png'
        im.save(directory/name)
        names.append(name)
    return names
