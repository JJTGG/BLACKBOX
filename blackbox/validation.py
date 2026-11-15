from __future__ import annotations
import json
from dataclasses import dataclass
from .canonical import canonical_finding
@dataclass(frozen=True)
class EvidenceRef:
 evidence_id:str;relation:str;note:str;excerpt:str
class ContractError(ValueError):pass
class AuditRejected(ContractError):pass
def _records(records):return {str(r['evidence_id']):r for r in records}
def _refs(raw,records):
 indexed=_records(records);out=[]
 for item in raw:
  eid=str(item.get('evidence_id'));excerpt=str(item.get('excerpt',''))
  if eid not in indexed or item.get('relation') not in {'supports','contradicts'} or not item.get('note') or not excerpt or excerpt not in str(indexed[eid].get('content','')):raise ContractError('invalid evidence provenance or excerpt')
  out.append(EvidenceRef(eid,item['relation'],item['note'],excerpt))
 return out
def validate_finding(finding,records):
 if not finding.get('statement') or finding.get('confidence') not in {'unknown','low','medium','high'}:raise ContractError('invalid finding contract')
 refs=_refs(finding.get('evidence',[]),records)
 if finding.get('unsupported') and refs:raise ContractError('unsupported finding cannot contain evidence')
 if not refs and not finding.get('unsupported'):raise ContractError('finding must be explicitly supported or explicitly unsupported')
 result={**finding,'evidence':[r.__dict__ for r in refs]}
 if refs:result['semantic_support']='unverified'
 return result
class CommanderReconciler:
 def reconcile(self,messages,records):
  findings=[]
  for message in messages:
   for finding in message.get('output',{}).get('findings',[]):
    normalized=validate_finding(finding,records);findings.append({**normalized,'source_agent':message['agent'],'message_id':message['message_id']})
  relationships=[];groups={}
  for finding in findings:groups.setdefault(canonical_finding(finding),[]).append(finding)
  for group in groups.values():
   if len(group)>1:relationships.append({'type':'independent_corroboration' if len({x['source_agent'] for x in group})>1 else 'same_source_duplicate','findings':group})
  for i,left in enumerate(findings):
   for right in findings[i+1:]:
    if canonical_finding(left)==canonical_finding(right):continue
    lc,rc=left.get('claim',{}),right.get('claim',{});same=(lc.get('subject'),lc.get('predicate'))==(rc.get('subject'),rc.get('predicate')) and lc.get('subject') is not None
    if same and lc.get('time_interval')==rc.get('time_interval') and lc.get('value')!=rc.get('value'):relationships.append({'type':'direct_contradiction','findings':[left,right]})
    elif same and lc.get('time_interval')!=rc.get('time_interval'):relationships.append({'type':'compatible_distinct_time','findings':[left,right]})
    elif same:relationships.append({'type':'conflicting_interpretation','findings':[left,right]})
  for f in findings:
   if f.get('unsupported'):relationships.append({'type':'insufficient_evidence','findings':[f]})
  review={'direct_contradiction','conflicting_interpretation','insufficient_evidence'}
  return {'findings':findings,'relationships':relationships,'disagreements':[x for x in relationships if x['type'] in review],'requires_human_review':any(x['type'] in review for x in relationships),'contributors':sorted({x['source_agent'] for x in findings})}
class IndependentAuditor:
 def review(self,reconciliation,messages,records):
  authentic={(m['message_id'],m['agent'],canonical_finding(f)):f for m in messages for f in m.get('output',{}).get('findings',[])};accepted=[];rejected=[]
  for f in reconciliation.get('findings',[]):
   try:n=validate_finding(f,records);key=(f.get('message_id'),f.get('source_agent'),canonical_finding(n))
   except (ContractError,ValueError) as exc:rejected.append({'statement':f.get('statement',''),'reason':str(exc)});continue
   if key not in authentic:rejected.append({'statement':f.get('statement',''),'reason':'finding does not exactly match authentic specialist output'})
   else:accepted.append(f)
  return {'status':'rejected' if rejected else 'accepted','accepted':accepted,'rejected':rejected,'unsupported':[x['statement'] for x in reconciliation.get('findings',[]) if x not in accepted],'missing_evidence':[] if accepted else ['authentic specialist evidence']}
