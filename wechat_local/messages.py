import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import zstandard

TZ = timezone(timedelta(hours=8), 'Asia/Shanghai')
TYPES = {1:'文本',3:'图片',34:'语音',43:'视频',47:'表情',48:'位置',49:'卡片',50:'通话',10000:'系统消息',11000:'表情'}

def redact_media_secrets(value):
    # Preserve message text, but never export media decryption/authentication material.
    value = re.sub(r'(?i)(\b(?:[\w]*aeskey|authkey|tpauthkey|filekey)\s*=\s*)([\"\x27])(.*?)\2',
                   lambda m:m[1]+m[2]+'[REDACTED]'+m[2],value)
    value = re.sub(r'(?is)(<([\w]*(?:aeskey|authkey|filekey))\b[^>]*>).*?(</\2>)',r'\1[REDACTED]\3',value)
    value = re.sub(r'(?i)([?&](?:amp;)?(?:filekey|authkey|aeskey)=)[^&\s\"<>]+',r'\1[REDACTED]',value)
    return value

def window(hours=24, start=None, end=None):
    def parse(value):
        date = datetime.fromisoformat(value)
        return date.replace(tzinfo=TZ) if date.tzinfo is None else date.astimezone(TZ)
    stop = parse(end) if end else datetime.now(TZ).replace(microsecond=0)
    begin = parse(start) if start else stop-timedelta(hours=hours)
    if begin >= stop:
        raise ValueError('起点必须早于终点')
    return begin, stop

def parse_body(raw, kind, compression=0):
    if isinstance(raw, bytes):
        if compression == 4 or raw.startswith(b'\x28\xb5\x2f\xfd'):
            raw = zstandard.ZstdDecompressor().decompress(raw, max_output_size=64*1024*1024)
        raw = raw.decode('utf-8', errors='strict')
    raw = raw or ''
    prefix = ''
    match = re.match(r'^([^\s<>:]{1,128}):\n', raw)
    if match:
        prefix, raw = match[1], raw[match.end():]
    base = kind & 0xffffffff
    result = {'type':TYPES.get(base, f'未知类型 {base}'), 'text':raw if base in (1,10000) else '',
              'raw_content':redact_media_secrets(raw), 'sender_prefix':prefix, 'links':[], 'reference':None}
    if base == 1:
        result['links'] = re.findall(r'https?://[^\s<>]+', raw)
        return result
    if not raw.lstrip().startswith('<'):
        result['text'] = result['text'] or '['+result['type']+'：未解析内容]'
        return result
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        result['parse_warning'] = '拒绝含实体声明的 XML'
        return result
    try:
        root = ET.fromstring(raw)
        app = root.find('.//appmsg') if root.tag != 'appmsg' else root
        if base == 49 and app is not None:
            fields = {name:app.findtext(name, '') for name in ('title','des','url','type')}
            result['card'] = fields
            result['text'] = '\n'.join(v for v in (fields['title'],fields['des']) if v)
            if fields['url'].startswith(('https://','http://')):
                result['links'].append(fields['url'])
            if fields['type'] == '6':
                result['type'] = '文件'
                result['card']['file_extension'] = app.findtext('appattach/fileext','')
            ref = app.find('refermsg')
            if ref is not None:
                result['reference'] = {tag:ref.findtext(tag,'') for tag in ('svrid','type','fromusr','displayname','content','createtime')}
        elif base == 34:
            transcript = root.find('.//voicetrans')
            if transcript is not None and transcript.attrib.get('transtext'):
                result['text'] = transcript.attrib['transtext']
                result['transcript_source'] = '本地消息 XML voicetrans.transtext'
    except ET.ParseError:
        result['parse_warning'] = 'XML 格式无法解析，保留原文供核对'
    if not result['text']:
        result['text'] = '['+result['type']+'：未解析内容]'
    return result

def deduplicate(messages):
    unique = {}
    removed = 0
    for message in messages:
        sid = message['server_id']
        key = ('server',sid) if sid and sid != '0' else ('local',message['source']['db'],message['source']['table'],message['source']['local_id'])
        if key in unique:
            old = unique[key]
            if any(old[k] != message[k] for k in ('timestamp','sender_id','raw_content','local_type')):
                raise ValueError('同一消息标识出现冲突，不能静默去重')
            old['duplicates'].append(message['source'])
            removed += 1
        else:
            message['duplicates'] = []
            unique[key] = message
    return sorted(unique.values(), key=lambda m:(m['timestamp'],m.get('sort_seq',0),m['id'])), removed

def message_id(group_id, db, local_id, server_id):
    identity = f'{group_id}:server:{server_id}' if server_id and server_id != '0' else f'{group_id}:{db}:{local_id}'
    return 'm-'+hashlib.sha256(identity.encode()).hexdigest()[:20]
