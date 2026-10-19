"""An offline research publication cannot clear the last failed quote update."""
import json
from pathlib import Path
from screener.__main__ import write_json


def preserve(previous_path='.history/latest-results.json',current_path='site/results.json'):
    previous_path,current_path=Path(previous_path),Path(current_path)
    if not previous_path.exists():return False
    previous=json.loads(previous_path.read_text())
    if previous.get('status')!='error':return False
    current=json.loads(current_path.read_text())
    errors=previous.get('errors')
    if not isinstance(errors,list) or not errors or not all(isinstance(e,str) for e in errors):
        errors=['最近一次官方行情更新失敗；本輪歷史研究未重新驗證最新行情']
    current.update(status='error',mode='research',active_strategy=None,active_model=None,candidates=[],strategies={},
                   errors=errors,source_error_at=previous.get('source_error_at') or previous.get('generated_at'),
                   message='最新行情更新錯誤尚未解除；離線研究不代表行情更新成功')
    current.setdefault('warnings',[]).append('本輪僅執行歷史研究；需成功更新官方行情後才能解除來源錯誤')
    write_json(current_path,current)
    write_json(current_path.with_name('active-performance.json'),{'status':'inactive','executed':False})
    return True


if __name__=='__main__':preserve()
