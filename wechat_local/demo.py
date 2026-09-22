import json
from datetime import datetime
from pathlib import Path
from .messages import parse_body, TZ
from .export import write_messages
from .report import render

def demo(output):
    bodies=[('甲','建议周五发布，还需要测试。',1),('乙','收到，我今天检查导出功能。',1),
            ('乙','导出功能已测试通过。',1),('甲','确定周五发布，具体时间另议。',1),
            ('丙','<msg><appmsg><title>说明文档 &amp; 样例</title><type>5</type><url>https://example.org/doc</url></appmsg></msg>',49),
            ('丙','<msg><img/></msg>',3),('甲','<script>alert("测试")</script> 昵称和正文都应转义。',1),
            ('乙','<msg><appmsg><title>我来核对</title><type>57</type><refermsg><svrid>1</svrid><content>建议周五发布，还需要测试。</content><displayname>甲</displayname></refermsg></appmsg></msg>',49)]
    messages=[]
    for i,(sender,body,kind) in enumerate(bodies,1):
        date=datetime(2026,9,19,10,i,tzinfo=TZ)
        messages.append(dict(parse_body(body,kind),id=f'demo-{i}',time=date.isoformat(),timestamp=date.timestamp(),
                             sender=sender,sender_id='user-'+sender,server_id=str(i),local_type=kind,
                             source={'db':'synthetic.db','table':'synthetic','local_id':i},duplicates=[]))
    meta={'group_name':'项目讨论群 <离线样例>','start':'2026-09-19T00:00:00+08:00','end':'2026-09-20T00:00:00+08:00',
          'timezone':'Asia/Shanghai (UTC+08:00)','message_count':8,'speaker_count':3,'synthetic':True,
          'warnings':['本报告所有人物、消息和结论均为虚构测试数据，不代表真实微信读取成功。']}
    write_messages(output,meta,messages)
    def item(text,*indexes):
        return {'text':text,'message_ids':[f'demo-{i}' for i in indexes],
                'evidence':[{'message_id':f'demo-{i}','quote':messages[i-1]['text']} for i in indexes]}
    report={'reviewed_message_ids':[m['id'] for m in messages],
            'overview':[item('群内讨论发布安排与导出测试，发布日已确定，具体时间仍待明确。',3,4)],
            'topics':[item('周五发布从建议转为明确安排。',1,4)],
            'todos':[dict(item('明确周五发布的具体时间。',4),owner='未明确',deadline='未明确',status='待明确')],
            'confirmed':[item('乙报告导出功能测试通过；这是群内报告，未作外部独立验证。',3)],
            'unresolved':[item('具体发布时间未确定。',4)],
            'other':[item('分享了说明文档链接；图片内容未解析。',5,6)]}
    (Path(output)/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return render(output)
