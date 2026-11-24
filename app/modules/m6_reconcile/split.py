from decimal import Decimal
from app.modules.m5_calculate.rules import allocate
from app.modules.m2_mapping.coerce import SENTINELS

CENT=Decimal('.01')

def _money(value):
    if value is None:return Decimal(0)
    if str(value).strip().upper() in SENTINELS:return Decimal(0)
    return Decimal(str(value))

def _text(value):
    return str(Decimal(value).quantize(CENT))

def _vouched(row):
    return str(row.get('voucher','')).strip().upper() not in SENTINELS

def split(state):
    # 裁决：退款按原缴费实收中个人:财政补贴的占比唯一分账，财政退回转入财政专户；
    # 凭证未到齐或依据缺失时整笔挂账为未分配余额，个人退款一并等待。
    entries=[];disbursements=[]
    totals={key:Decimal(0) for key in ('refund','personal','fiscal','unallocated')}
    for calc in state['calculations']:
        difference=Decimal(str(calc['difference']))
        if difference>=0:continue
        refund=-difference
        rows=[r for r in state['rows'] if r['policy_id']==calc['id']]
        personal_paid=sum((_money(r.get('paid_personal')) for r in rows),Decimal(0))
        subsidy_paid=sum((_money(r.get('paid_subsidy')) for r in rows),Decimal(0))
        basis=personal_paid+subsidy_paid
        vouchers_complete=all(_vouched(r) for r in rows if _money(r.get('paid_subsidy'))>0)
        if personal_paid<0 or subsidy_paid<0:status,reason='pending','缴费依据无效'
        elif basis<=0:status,reason='pending','缺缴费依据'
        elif subsidy_paid>0 and not vouchers_complete:status,reason='pending','凭证未到齐'
        else:status,reason='allocated',''
        if status=='allocated':
            personal,fiscal=allocate([refund*personal_paid/basis,refund*subsidy_paid/basis])
            unallocated=Decimal(0)
            for direction,account,amount in (('个人退款','投保人',personal),('财政退回','财政专户',fiscal)):
                if amount>0:disbursements.append({'id':calc['id']+'-'+direction,'policy':calc['id'],'direction':direction,'account':account,'amount':_text(amount)})
        else:
            personal=fiscal=Decimal(0);unallocated=refund
        totals['refund']+=refund;totals['personal']+=personal;totals['fiscal']+=fiscal;totals['unallocated']+=unallocated
        entries.append({'id':calc['id'],'line':calc['line'],'status':status,'reason':reason,
            'refund':_text(refund),'personal':_text(personal),'fiscal':_text(fiscal),'unallocated':_text(unallocated),
            'receipts':{'personal':_text(personal_paid),'subsidy':_text(subsidy_paid)},
            'receipts_matched':basis==Decimal(str(calc['paid'])),'vouchers_complete':vouchers_complete})
    summary={key:_text(value) for key,value in totals.items()}
    summary['balanced']=totals['personal']+totals['fiscal']+totals['unallocated']==totals['refund']
    summary['pending']=sum(1 for e in entries if e['status']=='pending')
    summary['allocated']=sum(1 for e in entries if e['status']=='allocated')
    summary['unit']='CNY'
    return {'policies':entries,'summary':summary,'disbursements':disbursements}
