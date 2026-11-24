from app.modules.m7_archive.export_out import checksum

def execute(state):
    allocation=state.get('allocation',{})
    state['archive']={'sha256':checksum(state),
        'evidence_count':len(state.get('calculations',[]))+len(state['quarantine'])+len(allocation.get('policies',[]))+len(allocation.get('disbursements',[])),
        'ready':state.get('reconcile',{}).get('balanced',False)}
    return state
