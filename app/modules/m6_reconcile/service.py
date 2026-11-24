from app.modules.m6_reconcile.compare import balance
from app.modules.m6_reconcile.split import split

def execute(state):
    state['allocation']=split(state);state['reconcile']=balance(state);return state
