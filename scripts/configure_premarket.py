"""Keep the site on existing GitHub collection; ignore old external API settings."""
import json
from pathlib import Path


def main():
    Path('site/premarket-config.json').write_text(json.dumps({
        'mode':'github_actions','api_base_url':None,
        'deployment_status':'no_external_backend_required'},indent=2)+'\n')


if __name__=='__main__':main()
