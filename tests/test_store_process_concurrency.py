import multiprocessing, os, tempfile
from blackbox.core import Store

def _audit_process(path, index):
 s=Store(path);s.audit('BBX-P',f'process-{index}','process.event','accepted',metadata={'index':index});s.db.close()

def test_default_store_reopens_and_preserves_audit_chain():
 fd,path=tempfile.mkstemp();os.close(fd)
 try:
  s=Store(path);s.create_incident('BBX-P','process','durable','ops');s.db.close();r=Store(path);assert r.db.execute("SELECT COUNT(*) FROM incidents WHERE incident_id='BBX-P'").fetchone()[0]==1;assert r.verify_audit_chain();r.db.close()
 finally:os.unlink(path)

def test_independent_process_audit_writes_survive_reopen():
 fd,path=tempfile.mkstemp();os.close(fd)
 try:
  s=Store(path);s.create_incident('BBX-MP','mp','durable','ops');s.db.close();procs=[multiprocessing.Process(target=_audit_process,args=(path,i)) for i in range(4)]
  for p in procs:p.start()
  for p in procs:p.join()
  assert all(p.exitcode==0 for p in procs)
  r=Store(path);assert r.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='process.event'").fetchone()[0]==4;assert r.verify_audit_chain();r.db.close()
 finally:os.unlink(path)
