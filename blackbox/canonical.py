from __future__ import annotations
import json
TRANSPORT_FIELDS=frozenset({'source_agent','message_id'})
NORMALIZED_FIELDS=frozenset({'semantic_support'})
REQUIRED_FIELDS=frozenset({'kind','statement','confidence','evidence','unsupported'})
def canonical_finding(finding):
 unknown=set(finding)-REQUIRED_FIELDS-TRANSPORT_FIELDS-NORMALIZED_FIELDS-{'claim','contradicting_evidence_status'}
 if unknown:raise ValueError(f'unrecognized finding fields: {sorted(unknown)}')
 value={key:finding.get(key) for key in sorted(REQUIRED_FIELDS|{'claim','contradicting_evidence_status'}) if key in finding};return json.dumps(value,sort_keys=True,separators=(',',':'))
