from decimal import Decimal
import pytest
from app import store
from app.workflow import run,load
from app.modules.m7_archive.export_out import bundle
from app.errors import DomainError

@pytest.fixture
def sub():return run(load('subsidy.csv'),{})

def _entry(state,pid):return {p['id']:p for p in state['allocation']['policies']}[pid]

def test_proportional_split_exact(sub):
    e=_entry(sub,'S001')
    assert (e['personal'],e['fiscal'],e['unallocated'],e['status'])==('552.00','368.00','0.00','allocated')

def test_cent_tail_goes_to_largest_fraction(sub):
    e=_entry(sub,'S004')
    assert (e['refund'],e['personal'],e['fiscal'])==('415.89','249.53','166.36')

def test_no_subsidy_all_personal(sub):
    e=_entry(sub,'S003')
    assert (e['personal'],e['fiscal'])==('368.00','0.00') and e['vouchers_complete'] is True

def test_voucher_missing_blocks_personal(sub):
    e=_entry(sub,'S002')
    assert e['status']=='pending' and e['reason']=='凭证未到齐'
    assert (e['personal'],e['fiscal'],e['unallocated'])==('0.00','0.00','920.00')

def test_conservation_per_policy(sub):
    for p in sub['allocation']['policies']:
        assert Decimal(p['personal'])+Decimal(p['fiscal'])+Decimal(p['unallocated'])==Decimal(p['refund'])

def test_difference_equals_two_refund_types_plus_unallocated(sub):
    s=sub['allocation']['summary']
    assert Decimal(s['personal'])+Decimal(s['fiscal'])+Decimal(s['unallocated'])==Decimal(s['refund'])
    refunds=sum(-Decimal(c['difference']) for c in sub['calculations'] if Decimal(c['difference'])<0)
    assert Decimal(s['refund'])==refunds and s['balanced'] is True

def test_recalculation_same_version_stable(sub):
    again=run(load('subsidy.csv'),{})
    assert again['run_id']==sub['run_id'] and again['allocation']==sub['allocation']

def test_rerun_no_new_disbursement(sub,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    store.save(sub['run_id'],sub);store.save(sub['run_id'],run(load('subsidy.csv'),{}))
    kept=store.get(sub['run_id'])
    assert len(store.history())==1 and kept['allocation']['disbursements']==sub['allocation']['disbursements']

def test_disbursement_accounts(sub):
    d={(x['id'],x['account'],x['amount']) for x in sub['allocation']['disbursements']}
    assert ('S001-财政退回','财政专户','368.00') in d and ('S001-个人退款','投保人','552.00') in d
    assert all(x['policy']!='S002' for x in sub['allocation']['disbursements'])

def test_saved_basis_cannot_be_overwritten(sub,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    store.save(sub['run_id'],sub)
    tampered=dict(sub);tampered['allocation']=dict(sub['allocation']);tampered['allocation']['summary']=dict(sub['allocation']['summary'],personal='0.00')
    store.save(sub['run_id'],tampered)
    assert store.get(sub['run_id'])['allocation']['summary']['personal']=='1169.53'

def test_subsidy_basis_conflict_isolated_not_overwritten():
    text=('id,policy_id,version,kind,effective,start,end,annual_premium,paid,ref,cover,paid_personal,paid_subsidy,voucher\n'
        'A1,PA,1,issue,2026-01-01,2026-01-01,2027-01-01,3650,3650,,基础险,2190,1460,CZ1\n'
        'A1,PA,1,issue,2026-01-01,2026-01-01,2027-01-01,3650,3650,,基础险,3000,650,CZ1\n')
    s=run(text.encode(),{})
    assert [q['code'] for q in s['quarantine']]==['CONFLICT','CONFLICT'] and not s['calculations']

def test_version_switch_failure_keeps_old_batch(client):
    kept=client.post('/api/runs',json={'sample':'subsidy.csv'}).get_json()
    conflict=('id,policy_id,version,kind,effective,start,end,annual_premium,paid,ref,cover\n'
        'T1,PT,1,issue,2026-01-01,2026-01-01,2027-01-01,3650,3650,,基础险\n'
        'T2,PT,2,change,2026-07-01,2026-01-01,2027-01-01,7300,0,,基础险\n'
        'T3,PT,2,change,2026-07-01,2026-01-01,2027-01-01,5475,0,,基础险\n')
    r=client.post('/api/runs',json={'csv':conflict})
    assert r.status_code==422 and r.get_json()['code']=='VERSION'
    ids=[h['id'] for h in client.get('/api/runs').get_json()]
    assert kept['run_id'] in ids and len(ids)==2
    assert client.get('/api/archive/'+kept['run_id']+'/export.csv').status_code==200

def test_export_shows_split_and_unallocated(sub):
    import csv,io,json
    rows=list(csv.reader(io.StringIO(bundle(sub).lstrip('﻿'))))
    kinds=[r[0] for r in rows]
    assert kinds.count('分账')==4 and kinds.count('拨付')==5
    recon=json.loads(next(r[5] for r in rows if r[0]=='对账'))['allocation']
    assert (recon['personal'],recon['fiscal'],recon['unallocated'])==('1169.53','534.36','920.00')
    assert '财政专户' in bundle(sub) and '凭证未到齐' in bundle(sub)

def test_reconcile_page_shows_three_amounts(client):
    client.post('/api/runs',json={'sample':'subsidy.csv'})
    page=client.get('/m6_reconcile').data.decode()
    assert '个人退款' in page and '财政退回' in page and '未分配余额' in page and '920.00' in page and '待凭证' in page

def test_archive_page_shows_three_amounts(client):
    client.post('/api/runs',json={'sample':'subsidy.csv'})
    page=client.get('/m7_archive').data.decode()
    assert '个人退款' in page and '财政退回' in page and '未分配余额' in page and '534.36' in page

def test_legacy_samples_have_no_refund_split():
    for sample in ('dirty.csv','clean.csv','legacy.csv'):
        s=run(load(sample),{})['allocation']['summary']
        assert s['refund']=='0.00' and s['unallocated']=='0.00' and s['balanced'] is True
