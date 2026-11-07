"""Inspect the installed Isaac files without starting a GPU application."""
import ast
import json
from pathlib import Path

root = Path('/isaac-sim')
report = {'install_root': str(root), 'version_files': {}, 'extensions': {}, 'api_details': {}}
for name in ('VERSION', 'version.txt'):
    path = root / name
    if path.exists():
        report['version_files'][name] = path.read_text().strip()

patterns = (
    'isaacsim.core.utils*', 'isaacsim.core.experimental.utils*',
    'isaacsim.sensors.*camera*', 'isaacsim.robot.policy.examples*',
    'omni.replicator.core*', 'omni.kit.viewport.utility*',
)
for pattern in patterns:
    for folder in root.glob('exts*'):
        for extension in folder.glob(pattern):
            modules = {}
            for source in extension.rglob('*.py'):
                if source.name not in ('stage.py', 'prims.py', 'semantics.py',
                                       'camera.py', 'orchestrator.py', 'capture.py', 'utility.py') \
                        and not any(name in str(source).lower() for name in ('quadruped', 'spot', 'anymal')):
                    continue
                tree = ast.parse(source.read_text())
                definitions = []
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        definitions.append(node.name)
                        if node.name in ('step', 'run', 'add_labels', 'capture_viewport_to_file'):
                            report['api_details'][str(source.relative_to(root)) + ':' + node.name] = (
                                ast.unparse(node).splitlines()[0] + '\n' + (ast.get_docstring(node) or '')[:1800])
                modules[str(source.relative_to(extension))] = definitions
            report['extensions'][extension.name] = modules
report['streaming_experience_exists'] = (root / 'apps/isaacsim.exp.full.streaming.kit').exists()
report['python_launcher_exists'] = (root / 'python.sh').exists()
print(json.dumps(report, indent=2))
