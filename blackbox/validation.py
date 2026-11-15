from __future__ import annotations
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str; relation: str; note: str; excerpt: str
class ContractError(ValueError): pass
class AuditRejected(ContractError): pass

def _records(records): return {str(r['evidence_id']):r for r in records}
def _refs(raw,records):
    indexed=_records(records); result=[]
    for item in raw:
        eid=str(item.get('evidence_id')); excerpt=str(item.get('excerpt',''))
        if eid not in indexed or item.get('relation') not in {'supports','contradicts'} or not item.get('note') or not excerpt or excerpt not in str(indexed[eid].get('content','')): raise ContractError('invalid evidence provenance or excerpt')
        result.append(EvidenceRef(eid,item['relation'],item['note'],excerpt))
    return result

def validate_finding(finding,records):
    if not finding.get('statement') or finding.get('confidence') not in {'unknown','low','medium','high'}: raise ContractError('invalid finding contract')
    refs=_refs(finding.get('evidence',[]),records)
    if finding.get('unsupported') and refs: raise ContractError('unsupported finding cannot contain evidence')
    if not refs and not finding.get('unsupported'): raise ContractError('finding must be explicitly supported or explicitly unsupported')
    result={**finding,'evidence':[r.__dict__ for r in refs]}
    if refs: result['semantic_support']='unverified'
    return result

def claim_view(finding):
    reserved={'source_agent','message_id'}
    return {k:v for k,v in finding.items() if k not in reserved}
def canonical_claim(finding): return json.dumps(claim_view(finding),sort_keys=True,separators=(',',':'))

class CommanderReconciler:
    def reconcile(self,messages,records):
        findings=[]
        for message in messages:
            for finding in message.get('output',{}).get('findings',[]): findings.append({**validate_finding(finding,records),'source_agent':message['agent'],'message_id':message['message_id']})
        relationships=[]; grouped={}
        for finding in findings: grouped.setdefault(canonical_claim(finding),[]).append(finding)
        for group in grouped.values():
            if len(group)>1: relationships.append({'type':'independent_corroboration' if len({x['source_agent'] for x in group})>1 else 'same_source_duplicate','findings':group})
        for i,left in enumerate(findings):
            for right in findings[i+1:]:
                if canonical_claim(left)==canonical_claim(right): continue
                lc,rc=left.get('claim',{}),right.get('claim',{})
                same_identity=(lc.get('subject'),lc.get('predicate'))==(rc.get('subject'),rc.get('predicate')) and lc.get('subject') is not None
                same_time=lc.get('time_interval')==rc.get('time_interval')
                if same_identity and same_time and lc.get('value')!=rc.get('value'):
                    relationships.append({'type':'direct_contradiction','findings':[left,right]})
                elif same_identity and not same_time:
                    relationships.append({'type':'compatible_distinct_time','findings':[left,right]})
                elif same_identity:
                    relationships.append({'type':'conflicting_interpretation','findings':[left,right]})
        for finding in findings:
            if finding.get('unsupported'): relationships.append({'type':'insufficient_evidence','findings':[finding]})
        review={'direct_contradiction','conflicting_interpretation','insufficient_evidence'}
        return {'findings':findings,'relationships':relationships,'disagreements':[x for x in relationships if x['type'] in review],'requires_human_review':any(x['type'] in review for x in relationships),'contributors':sorted({x['source_agent'] for x in findings})}

class IndependentAuditor:
    def review(self,reconciliation,messages,records):
        authentic={(m['message_id'],m['agent'],canonical_claim(f)):f for m in messages for f in m.get('output',{}).get('findings',[])}; accepted=[]; rejected=[]
        for finding in reconciliation.get('findings',[]):
            try: normalized=validate_finding(finding,records); key=(finding.get('message_id'),finding.get('source_agent'),canonical_claim(normalized))
            except ContractError as exc: rejected.append({'statement':finding.get('statement',''),'reason':str(exc)}); continue
            if key not in authentic: rejected.append({'statement':finding.get('statement',''),'reason':'finding does not exactly match authentic specialist output'})
            else: accepted.append(finding)
        return {'status':'rejected' if rejected else 'accepted','accepted':accepted,'rejected':rejected,'unsupported':[x['statement'] for x in reconciliation.get('findings',[]) if x not in accepted],'missing_evidence':[] if accepted else ['authentic specialist evidence']}
