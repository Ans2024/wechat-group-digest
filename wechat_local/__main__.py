import argparse
import json
from datetime import datetime
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description='本地微信群记录导出、Codex 会话总结、离线报告渲染')
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('accounts')
    exp = sub.add_parser('export')
    exp.add_argument('--group'); exp.add_argument('--group-id'); exp.add_argument('--account')
    exp.add_argument('--hours',type=int,choices=[24,48,72],default=24)
    exp.add_argument('--start'); exp.add_argument('--end'); exp.add_argument('--output')
    ren=sub.add_parser('render'); ren.add_argument('directory')
    demo=sub.add_parser('demo'); demo.add_argument('--output',default=None)
    args=parser.parse_args()
    if args.command=='accounts':
        from .storage import discover
        print(json.dumps([str(p) for p in discover()],ensure_ascii=False,indent=2))
    elif args.command=='export':
        from .export import export
        if not args.group:
            args.group=input('请输入完整群名：').strip()
        if not args.group:
            parser.error('必须提供完整群名')
        output=args.output or 'outputs/'+datetime.now().strftime('%Y%m%d-%H%M%S')
        export(args.group,output,args.account,args.group_id,args.hours,args.start,args.end)
        print('已完成消息导出，等待当前 Codex 会话完整阅读并生成 report.json：'+str(Path(output).resolve()))
    elif args.command=='render':
        from .report import render
        print(json.dumps(render(args.directory),ensure_ascii=False))
    else:
        from .demo import demo
        output=args.output or 'outputs/demo-'+datetime.now().strftime('%Y%m%d-%H%M%S')
        demo(output)
        print(str(Path(output).resolve()))

if __name__=='__main__':
    try:
        main()
    except (ValueError,RuntimeError,OSError) as exc:
        raise SystemExit(str(exc))
