import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_build_includes_office_modules_used_by_bundled_scripts(monkeypatch):
    script = Path(__file__).resolve().parents[2] / 'scripts/build_technical_platform.py'
    spec = importlib.util.spec_from_file_location('build_platform_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module, 'builtin_data_arguments', lambda _: [])
    monkeypatch.setattr(module.subprocess, 'run', lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0))
    assert module.main() == 0
    assert len(calls) == 3
    args = calls[0]
    imports = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == '--hidden-import']
    assert 'win32com.client' in imports
    assert 'pythoncom' in imports
    for module in (
        'asset_based_agent.technical_platform.feedback_service',
        'asset_based_agent.technical_platform.material_analysis',
        'asset_based_agent.technical_platform.material_resume',
        'asset_based_agent.technical_platform.memory_contracts',
        'asset_based_agent.technical_platform.memory_retrieval',
        'asset_based_agent.technical_platform.memory_service',
        'asset_based_agent.technical_platform.platform_queries',
        'asset_based_agent.technical_platform.review_issues',
        'asset_based_agent.technical_platform.skill_improvement',
        'asset_based_agent.technical_platform.turn_router',
        'asset_based_agent.technical_platform.ui.memory_panel',
    ):
        assert module in imports
    resources = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == '--add-data']
    assert any('builtin_contracts' in item for item in resources)
    tool_commands = calls[1:]
    names = {
        command[command.index('--name') + 1]: command
        for command in tool_commands
    }
    assert set(names) == {'ZQ技术平台更新器', 'ZQ技术平台启动器'}
    assert all('--onefile' in command for command in tool_commands)
    assert names['ZQ技术平台更新器'][-1].endswith('run_client_updater.py')
    assert names['ZQ技术平台启动器'][-1].endswith('run_client_launcher.py')
