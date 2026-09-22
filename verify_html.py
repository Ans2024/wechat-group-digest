"""Offline file:// QA fallback when the in-app Browser runtime is unavailable."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

folder=Path(sys.argv[1]).resolve()
result=[]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    try:
        for width in (1280,390):
            page=browser.new_page(viewport={'width':width,'height':900},device_scale_factor=1)
            remote=[]
            page.on('request',lambda req:remote.append(req.url) if req.url.startswith(('http:','https:')) else None)
            page.goto((folder/'index.html').as_uri())
            page.evaluate('document.fonts.ready')
            assert page.locator('h1').count()==1
            assert page.locator('details[open]').count()==0
            overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not overflow
            details=page.locator('details')
            if details.count():
                details.first.locator('summary').click()
                assert details.first.get_attribute('open') is not None
            assert not remote
            page.screenshot(path=str(folder/f'html-{width}.png'),full_page=True)
            result.append({'width':width,'offline_file_open':True,'horizontal_overflow':overflow,'remote_requests':len(remote),'source_expand':True})
            page.close()
    finally:
        browser.close()
(folder/'html-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
