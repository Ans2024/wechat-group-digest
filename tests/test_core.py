import copy
import hashlib
import hmac
import json
import shutil
import sqlite3
import struct
import unittest
import uuid
from pathlib import Path
from Crypto.Cipher import AES
import zstandard
from wechat_local.crypto import PAGE, checksum, committed_frames, decrypt_page, mac_key
from wechat_local.messages import window,parse_body,deduplicate
from wechat_local.export import select_group
from wechat_local.report import validate,draw_png
from PIL import Image

class CoreTests(unittest.TestCase):
    def test_time_boundaries(self):
        start,end=window(start='2026-09-19T10:00:00+08:00',end='2026-09-20T10:00:00+08:00')
        db=sqlite3.connect(':memory:')
        db.execute('create table messages(ts real)')
        db.executemany('insert into messages values(?)',[(start.timestamp()-1,),(start.timestamp(),),(end.timestamp()-1,),(end.timestamp(),)])
        self.assertEqual(db.execute('select count(*) from messages where ts>=? and ts<?',(start.timestamp(),end.timestamp())).fetchone()[0],2)
        db.close()
        self.assertEqual((end-start).total_seconds(),86400)
        with self.assertRaises(ValueError):window(start=end.isoformat(),end=start.isoformat())

    def test_group_exact_and_ambiguity(self):
        db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
        db.executescript('create table contact(username,nick_name,remark);create table chat_room(id,username,owner);create table chatroom_member(room_id,member_id);')
        db.executemany('insert into contact values(?,?,?)',[('1@chatroom','完整群',''),('2@chatroom','完整群',''),('3@chatroom','完整群二','')])
        with self.assertRaises(ValueError):select_group(db,'完整群')
        self.assertEqual(select_group(db,'完整群','2@chatroom')['username'],'2@chatroom')
        with self.assertRaises(ValueError):select_group(db,'完整')
        db.close()

    def test_zstd_reference_and_media(self):
        raw='用户:\n中文正文'
        self.assertEqual(parse_body(zstandard.ZstdCompressor().compress(raw.encode()),1,4)['text'],'中文正文')
        self.assertEqual(parse_body('<msg><img/></msg>',3)['text'],'[图片：未解析内容]')
        value=parse_body('<msg><appmsg><title>答复</title><refermsg><svrid>99</svrid><content>原文</content></refermsg></appmsg></msg>',49)
        self.assertEqual(value['reference']['svrid'],'99')
        self.assertEqual(parse_body('<msg><voicetrans transtext="已有转写"/></msg>',34)['transcript_source'],'本地消息 XML voicetrans.transtext')

    def test_media_keys_redacted(self):
        value=parse_body('<msg><img aeskey="secret" cdnthumbaeskey="secret2"/><cdnthumbaeskey>secret3</cdnthumbaeskey></msg>',3)
        self.assertNotIn('secret',value['raw_content'])

    def test_key_cleanup_on_failure(self):
        from unittest.mock import patch
        from wechat_local.windows import find_keys
        captured=[]
        def fail(paths,found):
            key=bytearray(b'synthetic key material');captured.append(key);found[b'salt']=key
            raise KeyboardInterrupt()
        with patch('wechat_local.windows._scan_keys',side_effect=fail):
            with self.assertRaises(KeyboardInterrupt):find_keys([])
        self.assertFalse(any(captured[0]))

    def test_dedup_identity_not_content(self):
        m={'id':'1','server_id':'100','source':{'db':'a','table':'t','local_id':1},'timestamp':1,'sender_id':'a','raw_content':'收到','local_type':1}
        dup=copy.deepcopy(m); dup['source']['db']='b'
        other=copy.deepcopy(m); other['id']='2';other['server_id']='101'
        rows,count=deduplicate([m,dup,other]);self.assertEqual((len(rows),count),(2,1))
        dup['raw_content']='同意'
        with self.assertRaises(ValueError):deduplicate([m,dup])

    def test_authenticated_pages(self):
        key=bytes(range(32));salt=bytes(range(16));iv=bytes(reversed(range(16)))
        for number in (1,2,37):
            start=16 if number==1 else 0
            plain=b'P'*(PAGE-80-start)
            encrypted=AES.new(key,AES.MODE_CBC,iv).encrypt(plain)
            tail=hmac.digest(mac_key(key,salt),encrypted+iv+struct.pack('<I',number),'sha512')
            page=(salt if number==1 else b'')+encrypted+iv+tail
            self.assertEqual(decrypt_page(page,number,key,salt)[start:-80],plain)
            corrupt=bytearray(page);corrupt[55]^=1
            with self.assertRaises(ValueError):decrypt_page(corrupt,number,key,salt)

    def test_wal_commit_checksum_stale_tail(self):
        header=struct.pack('>6I',0x377f0682,3007000,PAGE,0,17,23)
        state=checksum(header,'<');wal=header+struct.pack('>II',*state)
        for number,commit,fill in [(1,0,1),(2,2,2),(1,0,3)]:
            head=struct.pack('>4I',number,commit,17,23);data=bytes([fill])*PAGE
            state=checksum(head[:8]+data,'<',state)
            wal+=head+struct.pack('>II',*state)+data
        pages,size,audit=committed_frames(wal)
        self.assertEqual((size,audit['committed_frames'],audit['uncommitted_frames']),(2,2,1))
        self.assertEqual(pages[1][0],1)
        stale=struct.pack('>6I',1,1,99,99,0,0)+bytes(PAGE)
        self.assertEqual(committed_frames(wal+stale)[0],pages)
        bad=bytearray(wal);bad[200]^=1
        with self.assertRaises(ValueError):committed_frames(bad)

    def test_real_sqlite_generated_wal(self):
        # Independent WAL producer (SQLite itself), not just fixtures using our checksum.
        root=Path('.tmp')/('wal-test-'+uuid.uuid4().hex);root.mkdir(parents=True)
        conn=None
        try:
            path=root/'synthetic.sqlite'
            conn=sqlite3.connect(path)
            conn.execute('PRAGMA page_size=4096')
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA wal_autocheckpoint=0')
            conn.execute('CREATE TABLE sample(body TEXT)')
            conn.execute('INSERT INTO sample VALUES(?)',('仅为虚构测试',));conn.commit()
            frames,count,audit=committed_frames(Path(str(path)+'-wal').read_bytes())
            self.assertGreater(audit['committed_frames'],0)
            reconstructed=bytearray(path.read_bytes())
            reconstructed.extend(bytes(max(0,count*PAGE-len(reconstructed))))
            for n,page in frames.items():reconstructed[(n-1)*PAGE:n*PAGE]=page
            reconstructed[18:20]=b'\1\1'
            check=sqlite3.connect(':memory:')
            try:
                check.deserialize(reconstructed)
                self.assertEqual(check.execute('SELECT body FROM sample').fetchone()[0],'仅为虚构测试')
            finally:check.close()
        finally:
            if conn:conn.close()
            shutil.rmtree(root)

    def test_html_source_escaping(self):
        from wechat_local.report import render
        root=Path('.tmp')/('html-test-'+uuid.uuid4().hex);root.mkdir(parents=True)
        try:
            source=Path('outputs/demo-validation')
            data=json.loads((source/'messages.json').read_text(encoding='utf-8'))
            report=json.loads((source/'report.json').read_text(encoding='utf-8'))
            data['messages'][6]['sender']='<img src=x onerror=alert(1)>'
            report['other'].append({'text':'转义检查','message_ids':['demo-7'],'evidence':[{'message_id':'demo-7','quote':data['messages'][6]['text']}]})
            (root/'messages.json').write_text(json.dumps(data),encoding='utf-8')
            (root/'report.json').write_text(json.dumps(report),encoding='utf-8')
            render(root)
            html=(root/'index.html').read_text(encoding='utf-8')
            self.assertNotIn('<script',html);self.assertNotIn('<img src=x',html)
            self.assertIn('&lt;script&gt;',html);self.assertIn('&lt;img src=x',html)
        finally:shutil.rmtree(root)

    def test_references_and_complete_review(self):
        root=Path('outputs/demo-validation')
        data=json.loads((root/'messages.json').read_text(encoding='utf-8'))
        report=json.loads((root/'report.json').read_text(encoding='utf-8'))
        validate(data,report)
        bad=copy.deepcopy(report);bad['reviewed_message_ids'].pop()
        with self.assertRaises(ValueError):validate(data,bad)
        bad=copy.deepcopy(report);bad['overview'][0]['evidence'][0]['quote']='伪造结论'
        with self.assertRaises(ValueError):validate(data,bad)
        html=(root/'index.html').read_text(encoding='utf-8')
        self.assertNotIn('<script',html);self.assertIn('&lt;离线样例&gt;',html)
        self.assertNotIn('<details open',html)

    def test_png_splits_without_lost_lines(self):
        root=Path('.tmp')/('png-test-'+uuid.uuid4().hex);root.mkdir(parents=True)
        try:
            names=draw_png([('中文长图内容核对。'*20,24,'#000000')]*20,root,max_height=1500)
            self.assertGreater(len(names),1)
            for name in names:
                with Image.open(root/name) as image:
                    self.assertLessEqual(image.height,1500)
                    self.assertEqual(image.width,1080)
        finally:
            shutil.rmtree(root)

if __name__=='__main__':unittest.main()
