"""Use the original ASGI application and its existing metered service."""
import os
from asset_based_agent.report_review_server.main import app
from .gateway import install_gateway

flag = os.environ.get('ZQ_HARNESS_GATEWAY_ENABLED', '0')
if flag not in ('0', '1'):
    raise RuntimeError('INVALID_GATEWAY_ENABLE_FLAG')
if flag == '1':
    install_gateway(app, app.state.review_job_service.metered)
