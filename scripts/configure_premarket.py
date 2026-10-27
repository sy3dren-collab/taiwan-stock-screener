"""Use a public Worker URL, never embed a deployment token in the website."""
import json,os
from pathlib import Path
from urllib.parse import urlparse


def main():
    value=os.environ.get('MARKET_BRIEF_API','').strip()
    if not value:return
    u=urlparse(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
        raise ValueError('MARKET_BRIEF_API 需為不含金鑰、路徑與參數的 HTTPS 來源網址')
    Path('site/premarket-config.json').write_text(json.dumps({'api_base_url':value.rstrip('/'),
        'deployment_status':'configured_requires_live_verification'},indent=2)+'\n')


if __name__=='__main__':main()
