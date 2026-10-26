"""Durable shared-account queue. Lease loss never silently repeats a paid query."""
import hashlib,json,secrets,time,uuid
from contextlib import contextmanager
from sqlalchemy import MetaData,Table,Column,String,Text,Float,Integer,select,insert,update,func

metadata=MetaData()
INLINE_BYTES=1_000_000
MAX_RESULT_BYTES=64*1024*1024
slots=Table('zq_finance_slots',metadata,Column('id',Integer,primary_key=True),Column('last_seen',Float))
jobs=Table('zq_finance_jobs',metadata,
    Column('id',String(32),primary_key=True),Column('owner',String(128),nullable=False),
    Column('request_key',String(64),nullable=False,unique=True),Column('fingerprint',String(64),nullable=False),
    Column('tool',String(128),nullable=False),Column('arguments',Text,nullable=False),
    Column('status',String(32),nullable=False),Column('created',Float,nullable=False),
    Column('node',String(128)),Column('lease_hash',String(64)),Column('expires',Float),Column('result',Text))
class JobError(Exception):pass
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def encoded(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False)

class JobQueue:
    def __init__(self,engine,cipher):self.engine=engine;self.cipher=cipher
    def protect(self,owner,identifier,field,value):
        return self.cipher.encrypt(value,purpose=encoded(['finance-job',owner,identifier,field]))
    def reveal(self,row,field):
        value=row[field]
        if not value:return None
        return self.cipher.decrypt(value,purpose=encoded(['finance-job',row['owner'],row['id'],field]))
    def sweep(self,now=None):
        now=time.time() if now is None else now
        with self.transaction() as c:
            return c.execute(update(jobs).where(jobs.c.created<now-86400,jobs.c.status!='expired').values(
                status='expired',arguments='',result=None,lease_hash=None,expires=None)).rowcount
    def health(self,now=None):
        now=time.time() if now is None else now
        with self.engine.connect() as c:last_seen=c.scalar(select(slots.c.last_seen).where(slots.c.id==1))
        return {'source':'official_ifind','configured':True,'node_online':last_seen is not None and 0<=now-last_seen<90,
                'node_last_seen':last_seen,'live_access_verified':False,'status':'ok'}
    def migrate(self):
        metadata.create_all(self.engine)
        with self.engine.begin() as c:
            if c.execute(select(slots.c.id)).first() is None:c.execute(insert(slots).values(id=1))
    @contextmanager
    def transaction(self):
        with self.engine.connect() as c:
            # Standalone SQLite tests use explicit writer locking. Existing gateway
            # engines may already install BEGIN IMMEDIATE via their begin event.
            if self.engine.dialect.name=='sqlite' and not getattr(self.engine,'_zq_serialized_transactions',False):
                c.exec_driver_sql('BEGIN IMMEDIATE')
                try:yield c;c.commit()
                except BaseException:c.rollback();raise
            else:
                with c.begin():
                    c.execute(select(slots.c.id).where(slots.c.id==1).with_for_update()).first()
                    yield c
    def public(self,row):
        body=self.reveal(row,'result');large=bool(body and len(body.encode())>INLINE_BYTES)
        return {'id':row['id'],'tool':row['tool'],'arguments':json.loads(self.reveal(row,'arguments') or '{}'),
                'status':row['status'],'result':json.loads(body) if body and not large else None,
                'artifact':{'id':row['id'],'bytes':len(body.encode()),'sha256':digest(body)} if large else None}
    def download(self,owner,identifier):
        with self.engine.connect() as c:
            row=c.execute(select(jobs).where(jobs.c.id==identifier,jobs.c.owner==owner)).mappings().first()
            if not row or not row['result'] or row['status'] not in ('succeeded','failed','timed_out'):raise JobError('NOT_FOUND')
            return self.reveal(row,'result')
    def submit(self,owner,request_id,tool,arguments):
        from asset_based_agent.finance_data import validate,OFFICIAL
        if not owner or len(owner)>128 or not request_id or len(request_id)>128:raise JobError('INVALID_IDENTITY')
        if tool not in OFFICIAL or tool=='fuyao_ifind_status':raise JobError('NOT_OFFICIAL_QUERY')
        validate(tool,arguments)
        args=encoded(arguments)
        if len(args.encode())>32000:raise JobError('ARGUMENTS_TOO_LARGE')
        key=digest(encoded([owner,request_id]));fingerprint=digest(encoded([tool,arguments]))
        with self.transaction() as c:
            old=c.execute(select(jobs).where(jobs.c.request_key==key)).mappings().first()
            if old:
                if old['fingerprint']!=fingerprint:raise JobError('IDEMPOTENCY_CONFLICT')
                return self.public(old)
            count=c.scalar(select(func.count()).select_from(jobs).where(jobs.c.status.in_(['queued','running','cancel_requested'])))
            if count>=100:raise JobError('QUEUE_FULL')
            identifier=uuid.uuid4().hex
            c.execute(insert(jobs).values(id=identifier,owner=owner,request_key=key,fingerprint=fingerprint,
                tool=tool,arguments=self.protect(owner,identifier,'arguments',args),status='queued',created=time.time()))
            return self.public(c.execute(select(jobs).where(jobs.c.id==identifier)).mappings().one())
    def get(self,owner,identifier):
        with self.engine.connect() as c:
            row=c.execute(select(jobs).where(jobs.c.id==identifier,jobs.c.owner==owner)).mappings().first()
            if not row:raise JobError('NOT_FOUND')
            return self.public(row)
    def cancel(self,owner,identifier):
        with self.transaction() as c:
            row=c.execute(select(jobs).where(jobs.c.id==identifier,jobs.c.owner==owner)).mappings().first()
            if not row:raise JobError('NOT_FOUND')
            status={'queued':'cancelled','running':'cancel_requested'}.get(row['status'],row['status'])
            c.execute(update(jobs).where(jobs.c.id==identifier).values(status=status))
        return self.get(owner,identifier)
    def claim(self,node,now=None):
        now=time.time() if now is None else now
        with self.transaction() as c:
            c.execute(update(slots).where(slots.c.id==1).values(last_seen=now))
            c.execute(update(jobs).where(jobs.c.status.in_(['running','cancel_requested']),jobs.c.expires<now).values(status='interrupted'))
            active=c.execute(select(jobs.c.id).where(jobs.c.status.in_(['running','cancel_requested']))).first()
            if active:return None
            row=c.execute(select(jobs).where(jobs.c.status=='queued').order_by(jobs.c.created,jobs.c.id).limit(1)).mappings().first()
            if not row:return None
            lease=secrets.token_urlsafe(32)
            c.execute(update(jobs).where(jobs.c.id==row['id']).values(status='running',node=node,lease_hash=digest(lease),expires=now+90))
            return {'id':row['id'],'tool':row['tool'],'arguments':json.loads(self.reveal(row,'arguments')),'lease':lease,'lease_seconds':90}
    def heartbeat(self,node,identifier,lease):
        now=time.time()
        with self.transaction() as c:
            row=self._leased(c,node,identifier,lease,now)
            c.execute(update(slots).where(slots.c.id==1).values(last_seen=now))
            c.execute(update(jobs).where(jobs.c.id==identifier).values(expires=now+90))
            return {'status':row['status']}
    def _leased(self,c,node,identifier,lease,now):
        row=c.execute(select(jobs).where(jobs.c.id==identifier,jobs.c.node==node)).mappings().first()
        if not row or row['status'] not in ('running','cancel_requested') or row['expires']<now or not secrets.compare_digest(row['lease_hash'],digest(lease)):
            raise JobError('STALE_LEASE')
        return row
    def finish(self,node,identifier,lease,result,now=None):
        now=time.time() if now is None else now
        if not isinstance(result,dict):raise JobError('INVALID_RESULT')
        body=encoded(result)
        if len(body.encode())>MAX_RESULT_BYTES:raise JobError('RESULT_TOO_LARGE')
        with self.transaction() as c:
            previous=c.execute(select(jobs).where(jobs.c.id==identifier,jobs.c.node==node)).mappings().first()
            if previous and previous['status'] in ('succeeded','failed','timed_out','cancelled') and secrets.compare_digest(previous['lease_hash'] or '',digest(lease)):
                if previous['status']=='cancelled' or self.reveal(previous,'result')==body:return {'id':identifier,'status':previous['status']}
                raise JobError('RESULT_CONFLICT')
            row=self._leased(c,node,identifier,lease,now)
            status='succeeded' if result.get('status')=='ok' else 'timed_out' if result.get('status')=='timeout' else 'failed'
            if row['status']=='cancel_requested':status='cancelled';body=None
            c.execute(update(jobs).where(jobs.c.id==identifier).values(status=status,result=self.protect(row['owner'],identifier,'result',body) if body else None))
            return {'id':identifier,'status':status}
