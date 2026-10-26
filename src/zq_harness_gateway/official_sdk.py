"""Official SDK subprocess. Runs on the server; never accepts remote credentials."""
import json,os,sys
from datetime import datetime,timezone,date

ARITIES={'THS_HQ':(5,),'THS_BD':(3,),'THS_DS':(6,),'THS_RQ':(2,3),'THS_DR':(3,),
         'THS_EDB':(4,),'THS_DataStatistics':(0,),'THS_WC':(2,),'THS_ReportQuery':(3,)}

def request_for(name,args):
    if name=='fuyao_ifind_history':
        if date.fromisoformat(args['start_date'])>date.fromisoformat(args['end_date']):raise ValueError('INVALID_DATE_RANGE')
        return {'api':'THS_HQ','args':[args['codes'],args['indicators'],args.get('options','CPS:1'),args['start_date'],args['end_date']]}
    if name=='fuyao_ifind_basic':return {'api':'THS_BD','args':[args['codes'],args['indicators'],args['parameters']]}
    if name!='fuyao_ifind_query':raise ValueError('UNKNOWN_OFFICIAL_TOOL')
    return {'api':args['api'],'args':args['args']}

def code(value):
    if isinstance(value,int):return value
    if isinstance(value,dict):return value.get('errorcode',value.get('ErrorCode',-99999))
    return getattr(value,'errorcode',-99999)

def run(request,sdk=None):
    api=request['api'];args=request['args']
    if api not in ARITIES or len(args) not in ARITIES[api] or any(not isinstance(x,str) for x in args):
        return {'status':'invalid_arguments','errorcode':'INVALID_ARGUMENT_COUNT'}
    if not os.environ.get('IFIND_USERNAME') or not os.environ.get('IFIND_PASSWORD'):
        return {'status':'not_configured','errorcode':'SERVER_IFIND_CREDENTIALS_MISSING'}
    if sdk is None:
        from .sdk_native import ensure_native
        ensure_native()
        import iFinDPy as sdk
    login=code(sdk.THS_iFinDLogin(os.environ['IFIND_USERNAME'],os.environ['IFIND_PASSWORD']))
    if login not in (0,-201):return {'status':'login_failed','login_code':login}
    try:
        result=getattr(sdk,api)(*args)
        if isinstance(result,str):result=json.loads(result)
        error=code(result)
        data=result.get('data',result.get('tables')) if isinstance(result,dict) else getattr(result,'data',None)
        if hasattr(data,'to_json'):data=json.loads(data.to_json(orient='records',force_ascii=False,date_format='iso'))
        return {'status':'ok' if error==0 else 'query_failed','api':api,'args':args,'login_code':login,
                'errorcode':error,'data':data if error==0 else None,'queried_at':datetime.now(timezone.utc).isoformat()}
    finally:
        if login==0:sdk.THS_iFinDLogout()

if __name__=='__main__':
    # Keep native-library diagnostics, including any account identifiers, away
    # from application logs. Only the structured result goes to the parent.
    output=os.fdopen(os.dup(sys.stdout.fileno()),'w',encoding='utf-8')
    with open(os.devnull,'w') as null:
        os.dup2(null.fileno(),1);os.dup2(null.fileno(),2)
        try:result=run(json.load(sys.stdin))
        except ModuleNotFoundError as error:
            name=error.name if error.name in ('iFinDPy','iFinDAPI','pandas','numpy') else 'DEPENDENCY'
            result={'status':'failed','errorcode':'SDK_MODULE_MISSING_'+name}
        except OSError:result={'status':'failed','errorcode':'SDK_NATIVE_LOAD_FAILED'}
        except Exception:result={'status':'failed','errorcode':'SERVER_SDK_ERROR'}
        result['source']='official_ifind'
        output.write(json.dumps(result,ensure_ascii=False,allow_nan=False));output.flush()
