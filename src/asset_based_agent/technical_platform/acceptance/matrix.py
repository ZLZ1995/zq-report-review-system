"""S14 完整验收矩阵：40 项验收与证据绑定。

状态：
- automated：本重构新增测试直接锁定（agent_rebuild/ 下）；
- legacy_automated：既有技术平台测试锁定（未改动的旧能力）；
- manual_environment：依赖本机 Office/WPS、真实 OA 站点、真实服务端或
  EXE 打包环境——本地灰度需人工执行，结果登记在验收报告中。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MatrixItem:
    number: int
    requirement: str
    status: str          # automated / legacy_automated / manual_environment
    evidence: tuple = ()  # 相对 tests/ 的测试文件路径
    note: str = ''


MATRIX = (
    MatrixItem(1, '“你好”正常回答且不调用 Skill', 'automated',
               ('technical_platform/agent_rebuild/acceptance/test_acceptance_matrix.py',)),
    MatrixItem(2, '“你能帮我做什么”基于当前 Resource Registry 回答', 'automated',
               ('technical_platform/agent_rebuild/acceptance/test_acceptance_matrix.py',)),
    MatrixItem(3, '失败 Turn 有 Entry、error code、request ID', 'automated',
               ('technical_platform/agent_rebuild/core/',)),
    MatrixItem(4, '同 lane 拒绝并发 Operation', 'automated',
               ('technical_platform/agent_rebuild/core/',)),
    MatrixItem(5, '不同 lane 可以并行', 'automated',
               ('technical_platform/agent_rebuild/core/',)),
    MatrixItem(6, '切换 Session 不串流式输出', 'automated',
               ('technical_platform/agent_rebuild/application/test_application_layer.py',)),
    MatrixItem(7, '打开 Session 不写数据库', 'automated',
               ('technical_platform/agent_rebuild/application/test_application_layer.py',)),
    MatrixItem(8, '旧 Session 可查看和继续', 'automated',
               ('technical_platform/agent_rebuild/sessions/',)),
    MatrixItem(9, '旧损坏 question 不阻止新任务', 'automated',
               ('technical_platform/agent_rebuild/characterization/',)),
    MatrixItem(10, '分支共享父链', 'automated',
               ('technical_platform/agent_rebuild/context/test_context_builder.py',)),
    MatrixItem(11, '分支不继承授权', 'automated',
               ('technical_platform/agent_rebuild/policies/',)),
    MatrixItem(12, '本轮新附件不混入历史附件', 'automated',
               ('technical_platform/agent_rebuild/context/',)),
    MatrixItem(13, '第二次补充附件可以继续原任务', 'automated',
               ('technical_platform/agent_rebuild/context/',)),
    MatrixItem(14, '.xls/.xlsx/.docx/.pdf 声明支持与实际支持一致', 'legacy_automated',
               ('technical_platform/test_store.py',)),
    MatrixItem(15, '模型能先分析资料再决定是否澄清', 'automated',
               ('technical_platform/agent_rebuild/shadow/test_shadow_mode.py',)),
    MatrixItem(16, 'Skill 自动选择', 'automated',
               ('technical_platform/agent_rebuild/shadow/test_shadow_mode.py',)),
    MatrixItem(17, '多 Skill 连续执行', 'automated',
               ('technical_platform/agent_rebuild/core/',)),
    MatrixItem(18, 'Skill 仅展示最终成果', 'automated',
               ('technical_platform/agent_rebuild/business_tools/test_business_tools.py',)),
    MatrixItem(19, '报告审核后主动询问是否批注', 'manual_environment', (),
               '模型行为验收，需真实模型流量（灰度期间人工核对）'),
    MatrixItem(20, '原件默认只读', 'automated',
               ('technical_platform/agent_rebuild/policies/',)),
    MatrixItem(21, 'Office 验收', 'manual_environment', (),
               '需要本机 Microsoft Office COM 环境'),
    MatrixItem(22, 'WPS 验收', 'manual_environment', (),
               '需要本机 WPS COM 环境'),
    MatrixItem(23, '浏览器访问外部网站', 'manual_environment', (),
               '工具层已锁定（S12）；真实站点访问需 QWebEngine 后端接线后人工核对'),
    MatrixItem(24, '浏览器三档权限', 'automated',
               ('technical_platform/agent_rebuild/browser/test_browser_tools.py',)),
    MatrixItem(25, 'OA 上传合成文件', 'manual_environment', (),
               '需要真实 OA 站点与 QWebEngine 后端'),
    MatrixItem(26, '凭据保存需独立同意', 'automated',
               ('technical_platform/agent_rebuild/browser/test_browser_tools.py',)),
    MatrixItem(27, 'access token 过期可恢复', 'automated',
               ('technical_platform/agent_rebuild/model_port/',)),
    MatrixItem(28, 'request ID 重试不重复计费', 'legacy_automated',
               ('report_review_server/test_agent_completion_stream.py',)),
    MatrixItem(29, '中止模型调用', 'automated',
               ('technical_platform/agent_rebuild/core/',)),
    MatrixItem(30, '中止 Skill', 'automated',
               ('technical_platform/agent_rebuild/business_tools/test_business_tools.py',)),
    MatrixItem(31, '外部副作用 unknown 对账', 'automated',
               ('technical_platform/agent_rebuild/browser/test_browser_tools.py',)),
    MatrixItem(32, '强杀客户端后恢复', 'automated',
               ('technical_platform/agent_rebuild/resources/test_kernel_resources.py',)),
    MatrixItem(33, '数据库迁移和回滚', 'automated',
               ('technical_platform/agent_rebuild/sessions/',)),
    MatrixItem(34, '本地更新不丢历史', 'legacy_automated',
               ('technical_platform/test_local_migrations.py',)),
    MatrixItem(35, '最终 EXE 冷启动', 'manual_environment', (),
               'PyInstaller 打包与冷启动验证属构建发布动作，未获授权；灰度期间以源码入口启动核对'),
    MatrixItem(36, '旧版数据目录升级', 'automated',
               ('technical_platform/agent_rebuild/sessions/',)),
    MatrixItem(37, '非系统盘业务数据规则保持', 'legacy_automated',
               ('technical_platform/test_local_migrations.py',)),
    MatrixItem(38, '所有模板哈希保持', 'legacy_automated',
               ('technical_platform/test_store.py',)),
    MatrixItem(39, '全量测试通过', 'automated',
               ('technical_platform/agent_rebuild/',)),
    MatrixItem(40, '诊断包不包含秘密', 'automated',
               ('technical_platform/agent_rebuild/shadow/test_shadow_mode.py',)),
)

STATUSES = frozenset({'automated', 'legacy_automated', 'manual_environment'})


def by_number(number):
    return next(item for item in MATRIX if item.number == number)
