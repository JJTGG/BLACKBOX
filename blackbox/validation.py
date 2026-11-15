from __future__ import annotations
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class EvidenceRef:
    evidence_id:str; relation:str; note:str
class ContractError(ValueError): pass
class AuditRejected(ContractError): pass

def _refs(raw,evidence_ids):
    result=[]
    for item in raw:
        if item.get('evidence_id') not in evidence_ids or item.get('relation') not in {'supports','contradicts'} or not item.get('note'): raise ContractError('invalid evidence reference')
        result.append(EvidenceRef(item['evidence_id'],item['relation'],item['note']))
    return result

def validate_finding(finding,evidence_ids):
    if not finding.get('statement') or finding.get('confidence') not in {'unknown','low','medium','high'}: raise ContractError('invalid finding contract')
    refs=_refs(finding.get('evidence',[]),evidence_ids)
    if finding.get('unsupported') and refs: raise ContractError('unsupported finding cannot contain evidence')
    if not refs and not finding.get('unsupported'): raise ContractError('finding must be explicitly supported or explicitly unsupported')
    return {**finding,'evidence':[r.__dict__ for r in refs]}

def claim_view(finding):
    return {'kind':finding.get('kind'),'statement':finding.get('statement'),'confidence':finding.get('confidence'),'unsupported':bool(finding.get('unsupported')),'evidence':finding.get('evidence',[]),'contradicting_evidence_status':finding.get('contradicting_evidence_status')}

def canonical_claim(finding): return json.dumps(claim_view(finding),sort_keys=True,separators=(',',':'))

class CommanderReconciler:
    def reconcile(self,messages,evidence_ids):
        findings=[]
        for message in messages:
            for finding in message.get('output',{}).get('findings',[]):
                findings.append({**validate_finding(finding,evidence_ids),'source_agent':message['agent'],'message_id':message['message_id']})
        classes=[]; grouped={}
        for finding in findings: grouped.setdefault(canonical_claim(finding),[]).append(finding)
        for group in grouped.values():
            if len(group)>1: classes.append({'type':'independent_corroboration' if len({g['source_agent'] for g in group})>1 else 'duplicate','findings':group})
        for i,left in enumerate(findings):
            for right in findings[i+1:]:
                if canonical_claim(left)==canonical_claim(right): continue
                lwords=set(left['statement'].lower().split()); rwords=set(right['statement'].lower().split())
                opposing=(('not' in lwords)!=('not' in rwords)) and bool(lwords&rwords)
                contradictory=any(a['evidence_id']==b['evidence_id'] and a['relation']!=b['relation'] for a in left['evidence'] for b in right['evidence'])
                if opposing or contradictory: classes.append({'type':'direct_contradiction','findings':[left,right]})
                elif lwords&rwords: classes.append({'type':'compatible_or_conflicting_interpretation','findings':[left,right]})
        for finding in findings:
            if finding.get('unsupported'): classes.append({'type':'insufficient_evidence','findings':[finding]})
        disagreement_types={'direct_contradiction','compatible_or_conflicting_interpretation','insufficient_evidence'}
        return {'findings':findings,'relationships':classes,'disagreements':[c for c in classes if c['type'] in disagreement_types],'requires_human_review':any(c['type'] in disagreement_types for c in classes),'contributors':sorted({f['source_agent'] for f in findings})}

class IndependentAuditor:
    def review(self,reconciliation,messages,evidence_ids):
        authentic={(message['message_id'],message['agent'],canonical_claim(finding)):finding for message in messages for finding in message.get('output',{}).get('findings',[])}
        accepted=[]; rejected=[]
        for finding in reconciliation.get('findings',[]):
            try: normalized=validate_finding(finding,evidence_ids); key=(finding.get('message_id'),finding.get('source_agent'),canonical_claim(normalized))
            except ContractError as exc: rejected.append({'statement':finding.get('statement',''),'reason':str(exc)}); continue
            if key not in authentic: rejected.append({'statement':finding.get('statement',''),'reason':'finding does not exactly match authentic specialist output'})
            else: accepted.append(finding)
        return {'status':'rejected' if rejected else 'accepted','accepted':accepted,'rejected':rejected,'unsupported':[f['statement'] for f in reconciliation.get('findings',[]) if f not in accepted],'missing_evidence':[] if accepted else ['authentic specialist evidence']}
